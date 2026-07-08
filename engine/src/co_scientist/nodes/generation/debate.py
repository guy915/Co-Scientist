"""Debate generation strategy - generate hypotheses through adversarial debates.

Each debate runs multiple turns between experts to generate a single hypothesis.
Multiple debates can run in parallel.
"""

import asyncio
import logging
from typing import Any

from co_scientist.nodes.generation.citations import (
    hypothesis_from_llm_output,
    ReferenceIndex,
)
from co_scientist.constants import (
    DEBATE_FINAL_TURN_MAX_TOKENS_CAP,
    DEBATE_FINAL_TURN_TOKENS_PER_HYPOTHESIS,
    DEBATE_MAX_TURNS,
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    scaled_max_tokens,
)
from co_scientist.exceptions import GenerationError
from co_scientist.llm import call_llm, call_llm_json
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.prompts import get_debate_generation_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Angles cycled through parallel debates (via debate_id modulo the list
# length in _debate_diversity_instruction) so concurrent debates on the
# same research goal explore different facets instead of converging on
# the same obvious hypothesis.
_DEBATE_DIVERSITY_ANGLES = [
    "a direct causal molecular or mechanistic intervention",
    "an upstream regulatory or control-system mechanism",
    "a downstream measurable phenotype or functional assay",
    "a cross-pathway interaction that could explain an unexpected effect",
    "a temporal or state-dependent mechanism that changes across conditions",
    "a translational experiment or intervention with practical constraints",
    "a falsification-focused hypothesis with a discriminating negative control",
    "a high-novelty mechanism that challenges the dominant explanation",
]


def _debate_diversity_instruction(debate_id: int | None,
                                  total_debates: int) -> str | None:
    """Return a debate-specific angle for parallel hypothesis diversity."""
    # A single, non-parallel debate has no sibling to diverge from, so no
    # diversity nudge is needed.
    if debate_id is None or total_debates <= 1:
        return None
    angle = _DEBATE_DIVERSITY_ANGLES[debate_id % len(_DEBATE_DIVERSITY_ANGLES)]
    return (
        f"Parallel debate {debate_id + 1} of {total_debates}: focus this "
        f"debate on {angle}. Produce a final hypothesis that is meaningfully "
        "different from what other parallel debates would generate; do not "
        "collapse to the most generic or obvious mechanism unless it uniquely "
        "fits this assigned angle.")


def _append_diversity_instruction(preferences: str | None,
                                  instruction: str | None) -> str | None:
    """Append the parallel-debate diversity instruction to preferences."""
    # Augments, rather than replaces, any user-supplied preferences so both
    # constraints are honored together in the generation prompt.
    if not instruction:
        return preferences
    if preferences:
        return f"{preferences}\n\n{instruction}"
    return instruction


async def _run_single_debate(
    state: WorkflowState,
    debate_id: int | None = None,
    total_debates: int = 1,
    num_turns: int = DEBATE_MAX_TURNS,
    articles_with_reasoning: str | None = None,
    reference_index: ReferenceIndex | None = None,
) -> tuple[Hypothesis, str]:
    """Generate a single hypothesis using multi-turn debate strategy.

    Args:
        state: current workflow state
        debate_id: id for this debate (used for tracking and identification)
        total_debates: total number of parallel debates in this batch
        num_turns: number of debate turns to run (default from constants)
        articles_with_reasoning: optional literature review context for debate
        reference_index: citation key → source mapping for structured citations

    Returns:
        Tuple of (single generated Hypothesis object, debate transcript string)
    """
    # Callers may omit reference_index (e.g. the debate-only path in
    # coordinator.py), so fall back to an empty index; citation resolution
    # then simply yields no citation_map entries.
    ref_idx = reference_index or ReferenceIndex(text="", sources={})
    count = 1  # each debate generates exactly 1 hypothesis
    debate_label = f"debate {debate_id}" if debate_id is not None else "debate"

    supervisor_guidance = state.get("supervisor_guidance")
    meta_review = state.get("meta_review")
    diversity_instruction = _debate_diversity_instruction(
        debate_id, total_debates)
    preferences = _append_diversity_instruction(state.get("preferences"),
                                                diversity_instruction)
    attributes = state.get("attributes")

    transcript = ""

    # Earlier turns produce free-form adversarial dialogue that accumulates
    # into transcript, giving each subsequent turn's prompt the full debate
    # history so far. Only the final turn is constrained to structured JSON
    # output that becomes the resulting Hypothesis.
    for turn in range(1, num_turns + 1):
        is_final = turn == num_turns

        prompt, schema = get_debate_generation_prompt(
            research_goal=state["research_goal"],
            hypotheses_count=count,
            transcript=transcript,
            supervisor_guidance=supervisor_guidance,
            preferences=preferences,
            attributes=attributes,
            is_final_turn=is_final,
            articles_with_reasoning=articles_with_reasoning,
            articles=state.get("articles"),
            tool_registry=state.get("tool_registry"),
            reference_list=ref_idx.text,
            meta_review=meta_review,
            run_setup_guidance=state.get("run_setup_guidance"),
            run_focus_guidance=state.get("run_focus_guidance"),
        )

        if is_final:
            # count is always 1 here (one hypothesis per debate), so this
            # evaluates to a fixed budget (base + one per_item increment)
            # rather than truly scaling with batch size, unlike other
            # scaled_max_tokens call sites that pass a variable count.
            final_max_tokens = scaled_max_tokens(
                EXTENDED_MAX_TOKENS,
                count,
                per_item=DEBATE_FINAL_TURN_TOKENS_PER_HYPOTHESIS,
                cap=DEBATE_FINAL_TURN_MAX_TOKENS_CAP,
            )

            response = await call_llm_json(
                prompt=prompt,
                model_name=state["model_name"],
                max_tokens=final_max_tokens,
                temperature=HIGH_TEMPERATURE,
                json_schema=schema,
                # Generation is stochastic and diversity-critical: never cache
                # it, so parallel debates and re-runs stay diverse regardless of
                # cache state.
                use_cache=False,
                run_id=state.get("run_id"),
                prompt_name=f"generate_debate_{debate_id}_final",
                prompt_metadata={
                    "debate_id": debate_id,
                    "turn": turn,
                    "has_literature": articles_with_reasoning is not None,
                    "reference_keys": list(ref_idx.sources.keys()),
                    "prompt_length_chars": len(prompt),
                },
            )

            # The schema wraps a single hypothesis in a list to keep the
            # response shape consistent with other generation paths' schemas
            # (e.g. batch tool-based generation), even though a debate only
            # ever produces one.
            hypotheses_data = response.get("hypotheses", [])
            if not hypotheses_data:
                raise GenerationError(
                    f"{debate_label} failed to generate hypothesis")

            hyp_data = hypotheses_data[0]

            # Shared constructor (also used by the literature_tools validate
            # phase) resolves citation keys against ref_idx.sources and
            # stamps debate_id so downstream tournament/ranking can trace a
            # hypothesis back to the debate that produced it.
            hypothesis = hypothesis_from_llm_output(
                hyp_data,
                ref_idx.sources,
                GenerationMethod.DEBATE,
                debate_id=debate_id,
            )

            return hypothesis, transcript
        else:
            # Intermediate turns are unconstrained free text (no JSON
            # schema) - this is where the adversarial back-and-forth
            # dialogue that gets folded into transcript actually happens.
            response_text = await call_llm(
                prompt=prompt,
                model_name=state["model_name"],
                max_tokens=EXTENDED_MAX_TOKENS,
                temperature=HIGH_TEMPERATURE,
                use_cache=False,  # keep debate turns fresh too
            )

            transcript += f"\n\nTurn {turn}:\n{response_text}"

    # Unreachable under normal DEBATE_MAX_TURNS configuration, since the
    # loop always hits is_final on its last iteration; this guards against
    # a misconfigured num_turns <= 0.
    raise GenerationError(f"{debate_label} ended without final turn")


async def generate_with_debate(
    state: WorkflowState,
    count: int,
    articles_with_reasoning: str | None = None,
    reference_index: ReferenceIndex | None = None,
) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
    """Generate hypotheses using parallel debate strategy.

    Each debate generates 1 hypothesis through multi-turn expert discussion

    Args:
        state: current workflow state
        count: number of debates to run (= number of hypotheses to generate)
        articles_with_reasoning: optional literature review context for debates
        reference_index: citation key → source mapping for structured citations

    Returns:
        tuple of (debate_hypotheses, debate_transcripts)
    """
    # coordinator.py may allocate 0 hypotheses to this path (e.g. condition
    # (a)/(c) giving 0 to debate-only); skip the gather/log overhead entirely
    # rather than running it with an empty task list.
    if count == 0:
        return [], []

    logger.info("Running %s parallel debates", count)

    # debate_id=i doubles as both a diversity-angle selector (see
    # _debate_diversity_instruction) and a stable identifier for pairing
    # each resulting hypothesis back to its transcript below.
    debate_tasks = [
        _run_single_debate(
            state,
            debate_id=i,
            total_debates=count,
            articles_with_reasoning=articles_with_reasoning,
            reference_index=reference_index,
        ) for i in range(count)
    ]

    debate_results = await asyncio.gather(*debate_tasks)

    debate_hypotheses = [hyp for hyp, _ in debate_results]
    # Shape matches the debate_transcripts entries expected in
    # WorkflowState: {debate_id, transcript, hypothesis_text}.
    debate_transcripts = [{
        "debate_id": i,
        "transcript": transcript,
        "hypothesis_text": debate_hypotheses[i].text
    } for i, (_, transcript) in enumerate(debate_results)]

    logger.info("Generated %s hypotheses from debates", len(debate_hypotheses))
    return debate_hypotheses, debate_transcripts

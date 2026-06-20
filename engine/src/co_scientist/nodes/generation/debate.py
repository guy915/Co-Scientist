"""Debate generation strategy - generate hypotheses through adversarial debates.

Each debate runs multiple turns between experts to generate a single hypothesis.
Multiple debates can run in parallel.
"""

import asyncio
import logging
from typing import Any

from co_scientist.nodes.generation.citations import (
    ReferenceIndex,
    resolve_citation_keys,
)
from co_scientist.constants import (
    DEBATE_MAX_TURNS,
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    INITIAL_ELO_RATING,
)
from co_scientist.exceptions import GenerationError
from co_scientist.llm import call_llm, call_llm_json
from co_scientist.models import Article, GenerationMethod, Hypothesis
from co_scientist.prompts import (
    get_debate_generation_prompt,
    save_prompt_to_disk,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

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
    if debate_id is None or total_debates <= 1:
        return None
    angle = _DEBATE_DIVERSITY_ANGLES[debate_id %
                                     len(_DEBATE_DIVERSITY_ANGLES)]
    return (
        f"Parallel debate {debate_id + 1} of {total_debates}: focus this "
        f"debate on {angle}. Produce a final hypothesis that is meaningfully "
        "different from what other parallel debates would generate; do not "
        "collapse to the most generic or obvious mechanism unless it uniquely "
        "fits this assigned angle.")


def _append_diversity_instruction(preferences: str | None,
                                  instruction: str | None) -> str | None:
    """Append the parallel-debate diversity instruction to preferences."""
    if not instruction:
        return preferences
    if preferences:
        return f"{preferences}\n\n{instruction}"
    return instruction


def _match_papers_to_grounding(
    articles: list[Article],
    literature_grounding: str | None,
) -> list[dict[str, str]]:
    """Match lit review articles against a hypothesis's literature_grounding.

    Uses author last name + year matching against citation patterns like
    "(Roepert et al., 2020; Erba et al., 2021)" in the grounding text.

    Returns empty list if no grounding text or no matches.
    """
    from co_scientist.nodes.generation.papers import articles_to_candidates, filter_papers_by_grounding  # pylint: disable=import-outside-toplevel

    candidates = articles_to_candidates(articles)
    return filter_papers_by_grounding(candidates, literature_grounding)


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
    ref_idx = reference_index or ReferenceIndex(text="", sources={})
    count = 1  # each debate generates exactly 1 hypothesis
    debate_label = f"debate {debate_id}" if debate_id is not None else "debate"

    supervisor_guidance = state.get("supervisor_guidance")
    diversity_instruction = _debate_diversity_instruction(
        debate_id, total_debates)
    preferences = _append_diversity_instruction(state.get("preferences"),
                                                diversity_instruction)
    attributes = state.get("attributes")

    transcript = ""

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
        )

        if is_final:
            save_prompt_to_disk(
                run_id=state.get("run_id", "unknown"),
                prompt_name=f"generate_debate_{debate_id}_final",
                content=prompt,
                metadata={
                    "debate_id": debate_id,
                    "turn": turn,
                    "has_literature": articles_with_reasoning is not None,
                    "reference_keys": list(ref_idx.sources.keys()),
                    "prompt_length_chars": len(prompt),
                },
            )
            scaled_max_tokens = min(EXTENDED_MAX_TOKENS + 4000, 20000)

            response = await call_llm_json(
                prompt=prompt,
                model_name=state["model_name"],
                max_tokens=scaled_max_tokens,
                temperature=HIGH_TEMPERATURE,
                json_schema=schema,
            )

            hypotheses_data = response.get("hypotheses", [])
            if not hypotheses_data:
                raise GenerationError(
                    f"{debate_label} failed to generate hypothesis")

            hyp_data = hypotheses_data[0]

            hypothesis_text = hyp_data.get("hypothesis") or hyp_data.get(
                "text", "")
            explanation = hyp_data.get("explanation")
            literature_grounding = hyp_data.get("literature_grounding")
            experiment = hyp_data.get("experiment")

            citation_map = resolve_citation_keys(literature_grounding,
                                                 ref_idx.sources)

            hypothesis = Hypothesis(
                text=hypothesis_text,
                explanation=explanation,
                literature_grounding=literature_grounding,
                experiment=experiment,
                score=0.0,
                elo_rating=INITIAL_ELO_RATING,
                generation_method=GenerationMethod.DEBATE,
                debate_id=debate_id,
                citation_map=citation_map,
            )

            return hypothesis, transcript
        else:
            response_text = await call_llm(
                prompt=prompt,
                model_name=state["model_name"],
                max_tokens=EXTENDED_MAX_TOKENS,
                temperature=HIGH_TEMPERATURE,
            )

            transcript += f"\n\nTurn {turn}:\n{response_text}"

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
    if count == 0:
        return [], []

    logger.info("Running %s parallel debates", count)

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
    debate_transcripts = [{
        "debate_id": i,
        "transcript": transcript,
        "hypothesis_text": debate_hypotheses[i].text
    } for i, (_, transcript) in enumerate(debate_results)]

    logger.info("Generated %s hypotheses from debates", len(debate_hypotheses))
    return debate_hypotheses, debate_transcripts

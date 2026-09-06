"""Debate generation strategy - generate hypotheses through adversarial debates.

Each debate runs multiple turns between experts to generate a single hypothesis.
Multiple debates can run in parallel.

Diversity and final-turn budget helpers live in the sibling module
debate_support.py; the LLM seams (call_llm and call_llm_json) stay here so
tests can monkeypatch them on this namespace. All helper names are re-exported
here for compatibility.
"""

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from co_scientist.agents.generation.citations import (
    ReferenceIndex,
    hypothesis_from_llm_output,
)
from co_scientist.agents.generation.debate_support import (
    _DEBATE_DIVERSITY_ANGLES as _DEBATE_DIVERSITY_ANGLES,
)
from co_scientist.agents.generation.debate_support import (
    DebateBatchPosition as DebateBatchPosition,
)
from co_scientist.agents.generation.debate_support import (
    _append_diversity_instruction as _append_diversity_instruction,
)
from co_scientist.agents.generation.debate_support import (
    _debate_converged as _debate_converged,
)
from co_scientist.agents.generation.debate_support import (
    _debate_diversity_instruction as _debate_diversity_instruction,
)
from co_scientist.agents.generation.debate_support import (
    _debate_final_turn_max_tokens as _debate_final_turn_max_tokens,
)
from co_scientist.agents.generation.debate_support import (
    _final_turn_prompt_metadata as _final_turn_prompt_metadata,
)
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
)
from co_scientist.exceptions import GenerationError
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm,
    call_llm_json,
)
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.prompts import (
    DebatePromptRequest,
    PromptRunContext,
    get_debate_generation_prompt,
)
from co_scientist.prompts.generation_debate import (
    _DEBATE_MAX_DISCUSSION_TURNS,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def _call_final_debate_turn(
    state: WorkflowState,
    ctx: "_DebateContext",
    turn: int,
    prompt: str,
    schema: Any,
) -> dict[str, Any]:
    """Call the LLM for a debate's final structured-output turn.

    Args:
        state: current workflow state
        ctx: per-debate context shared by every turn of this debate
        turn: 1-based index of this (final) turn
        prompt: the final-turn prompt built from the transcript so far
        schema: JSON schema constraining the final turn's output

    Returns:
        Parsed JSON response containing the "hypotheses" list.
    """
    final_max_tokens = _debate_final_turn_max_tokens(ctx.count)

    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=state["model_name"],
            max_tokens=final_max_tokens,
            temperature=HIGH_TEMPERATURE,
            json_schema=schema,
        ),
        options=LLMCallOptions(
            use_cache=False,
            run_id=state.get("run_id"),
            prompt_name=f"generate_debate_{ctx.debate_id}_final",
            prompt_metadata=_final_turn_prompt_metadata(
                ctx.debate_id,
                turn,
                ctx.articles_with_reasoning,
                ctx.ref_idx,
                prompt,
            ),
        ),
    )


def _first_debate_hypothesis_data(
    response: dict[str, Any], debate_label: str
) -> dict[str, Any]:
    """Extract the single hypothesis dict from a debate final-turn response.

    The schema wraps a single hypothesis in a list to keep the response
    shape consistent with other generation paths' schemas (e.g. batch
    tool-based generation), even though a debate only ever produces one.

    Raises:
        GenerationError: if the final turn produced no hypothesis.
    """
    hypotheses_data: list[dict[str, Any]] = response.get("hypotheses", [])
    if not hypotheses_data:
        raise GenerationError(f"{debate_label} failed to generate hypothesis")
    return hypotheses_data[0]


async def _run_final_debate_turn(
    state: WorkflowState,
    ctx: "_DebateContext",
    turn: int,
    prompt: str,
    schema: Any,
) -> Hypothesis:
    """Run the final debate turn and build the resulting Hypothesis.

    The final turn is constrained to structured JSON output (unlike earlier
    free-form turns), which this parses into a single Hypothesis.

    Args:
        state: current workflow state
        ctx: per-debate context shared by every turn of this debate
        turn: 1-based index of this (final) turn
        prompt: the final-turn prompt built from the transcript so far
        schema: JSON schema constraining the final turn's output

    Returns:
        The Hypothesis built from the final turn's structured output.

    Raises:
        GenerationError: if the final turn produced no hypothesis.
    """
    response = await _call_final_debate_turn(state, ctx, turn, prompt, schema)
    hyp_data = _first_debate_hypothesis_data(response, ctx.debate_label)

    # Shared constructor (also used by the literature_tools validate phase)
    # resolves citation keys against ref_idx.sources and stamps debate_id so
    # downstream tournament/ranking can trace a hypothesis back to the
    # debate that produced it.
    return hypothesis_from_llm_output(
        hyp_data,
        ctx.ref_idx.sources,
        GenerationMethod.DEBATE,
        debate_id=ctx.debate_id,
    )


def _build_debate_turn_prompt(
    state: WorkflowState,
    ctx: "_DebateContext",
    transcript: str,
    is_final: bool,
) -> tuple[str, Any]:
    """Build the prompt/schema for one debate turn.

    Thin wrapper around get_debate_generation_prompt that isolates its long
    keyword-argument list from the turn loop in _run_debate_turns. is_final
    selects the structured-output final turn vs. an earlier free-form turn.

    Args:
        state: current workflow state
        ctx: per-debate context shared by every turn of this debate
        transcript: the debate transcript accumulated so far
        is_final: whether this is the structured-output final turn

    Returns:
        The (prompt, schema) pair for this turn.
    """
    return get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal=state["research_goal"],
            transcript=transcript,
            preferences=ctx.preferences,
            attributes=ctx.attributes,
            user_hypotheses=state.get("starting_hypotheses"),
            criteria=ctx.criteria,
            is_final_turn=is_final,
            articles_with_reasoning=ctx.articles_with_reasoning,
            articles=state.get("articles"),
            reference_list=ctx.ref_idx.text,
            context=PromptRunContext(
                supervisor_guidance=ctx.supervisor_guidance,
                meta_review=ctx.meta_review,
                tool_registry=state.get("tool_registry"),
                run_setup_guidance=state.get("run_setup_guidance"),
                run_focus_guidance=state.get("run_focus_guidance"),
            ),
        )
    )


async def _run_intermediate_debate_turn(
    state: WorkflowState, prompt: str
) -> str:
    """Run one non-final debate turn and return its free-form response text.

    Args:
        state: current workflow state
        prompt: intermediate-turn prompt built from the transcript so far

    Returns:
        The raw response text to fold into the debate transcript.
    """
    # Intermediate turns are unconstrained free text (no JSON schema) - this
    # is where the adversarial back-and-forth dialogue that gets folded into
    # transcript actually happens.
    return await call_llm(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=state["model_name"],
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=HIGH_TEMPERATURE,
        ),
        options=LLMCallOptions(
            use_cache=False,
        ),
    )


@dataclass
class _DebateContext:
    """Per-debate values that stay constant across all turns of one debate."""

    ref_idx: ReferenceIndex
    debate_id: int | None
    debate_label: str
    supervisor_guidance: Any
    meta_review: Any
    preferences: str | None
    attributes: Any
    articles_with_reasoning: str | None
    criteria: list[str] | None = None
    count: int = 1  # each debate generates exactly 1 hypothesis


def _build_debate_context(
    state: WorkflowState,
    debate_id: int | None,
    total_debates: int,
    articles_with_reasoning: str | None,
    reference_index: ReferenceIndex | None,
) -> _DebateContext:
    """Resolve the per-debate context shared by every turn of one debate.

    Args:
        state: current workflow state
        debate_id: id for this debate (used for tracking and identification)
        total_debates: total number of parallel debates in this batch
        articles_with_reasoning: optional literature review context for the
            debate
        reference_index: citation key → source mapping for structured
            citations; callers may omit it (e.g. the debate-only path in
            coordinator.py), which falls back to an empty index so citation
            resolution simply yields no citation_map entries.

    Returns:
        The resolved _DebateContext for this debate.
    """
    diversity_instruction = _debate_diversity_instruction(
        debate_id, total_debates
    )
    return _DebateContext(
        ref_idx=reference_index or ReferenceIndex(text="", sources={}),
        debate_id=debate_id,
        debate_label=(
            f"debate {debate_id}" if debate_id is not None else "debate"
        ),
        supervisor_guidance=state.get("supervisor_guidance"),
        meta_review=state.get("meta_review"),
        preferences=_append_diversity_instruction(
            state.get("preferences"), diversity_instruction
        ),
        attributes=state.get("attributes"),
        articles_with_reasoning=articles_with_reasoning,
        criteria=state.get("criteria"),
    )


async def _run_debate_turns(
    state: WorkflowState,
    ctx: _DebateContext,
) -> tuple[Hypothesis, str, int]:
    """Run one debate's discussion turns, then its synthesis turn.

    The panel debates for up to ``_DEBATE_MAX_DISCUSSION_TURNS`` free-form
    turns -- the paper's envelope is typically 3-5 conversational turns,
    never more than 10 -- and stops as soon as a turn declares consensus
    with the HYPOTHESIS termination token (see ``_debate_converged``).
    The schema-constrained synthesis turn always runs afterwards, so a
    panel that never agrees still yields a hypothesis; it simply spends
    the whole envelope arguing. Each turn's prompt carries the full
    transcript accumulated so far.

    Returns:
        Tuple of (hypothesis, transcript, llm_call_count), where
        llm_call_count is every real completion this debate spent: one per
        discussion turn plus the final synthesis turn (finding L3 -- debate
        generation previously reported no llm_calls at all).
    """
    transcript = ""
    turns_run = 0
    for turn in range(1, _DEBATE_MAX_DISCUSSION_TURNS + 1):
        prompt, _ = _build_debate_turn_prompt(
            state, ctx, transcript, is_final=False
        )
        response_text = await _run_intermediate_debate_turn(state, prompt)
        transcript += f"\n\nTurn {turn}:\n{response_text}"
        turns_run = turn
        if _debate_converged(response_text):
            logger.info(
                "%s declared consensus after turn %s", ctx.debate_label, turn
            )
            break

    prompt, schema = _build_debate_turn_prompt(
        state, ctx, transcript, is_final=True
    )
    hypothesis = await _run_final_debate_turn(
        state, ctx, turns_run + 1, prompt, schema
    )
    # turns_run discussion turns plus the one final synthesis turn.
    return hypothesis, transcript, turns_run + 1


def _unpack_debate_results(
    debate_results: list[tuple[Hypothesis, str, int]],
) -> tuple[list[Hypothesis], list[dict[str, Any]], int]:
    """Split gathered (hypothesis, transcript, calls) triples into lists.

    Args:
        debate_results: per-debate (hypothesis, transcript, llm_call_count)
            triples, in the same order they were passed to asyncio.gather.

    Returns:
        Tuple of (debate_hypotheses, debate_transcripts, llm_call_count),
        where each transcript entry has the shape expected in
        WorkflowState: {debate_id, transcript, hypothesis_text}, and
        llm_call_count sums every debate's real completions.
    """
    debate_hypotheses = [hyp for hyp, _, _ in debate_results]
    debate_transcripts = [
        {
            # The id stamped on the hypothesis is the debate's own
            # (its index within the whole parallel batch), which differs
            # from the enumerate position when a durable task runs one
            # debate of a larger fan-out; fall back to the position only
            # for a hypothesis that carries no debate id at all.
            "debate_id": (
                debate_hypotheses[i].debate_id
                if debate_hypotheses[i].debate_id is not None
                else i
            ),
            "transcript": transcript,
            "hypothesis_text": debate_hypotheses[i].text,
        }
        for i, (_, transcript, _) in enumerate(debate_results)
    ]
    llm_call_count = sum(calls for _, _, calls in debate_results)
    return debate_hypotheses, debate_transcripts, llm_call_count


def _build_debate_tasks(
    state: WorkflowState,
    count: int,
    articles_with_reasoning: str | None,
    reference_index: ReferenceIndex | None,
    batch_position: DebateBatchPosition,
) -> list[Coroutine[Any, Any, tuple[Hypothesis, str, int]]]:
    """Build one debate-turn-loop coroutine per debate in this batch.

    debate_id=debate_index+i doubles as both a diversity-angle selector
    (see _debate_diversity_instruction) and a stable identifier for
    pairing each resulting hypothesis back to its transcript in
    _unpack_debate_results.
    """
    return [
        _run_debate_turns(
            state,
            _build_debate_context(
                state,
                batch_position.debate_index + i,
                batch_position.total_debates,
                articles_with_reasoning,
                reference_index,
            ),
        )
        for i in range(count)
    ]


async def generate_with_debate(
    state: WorkflowState,
    count: int,
    articles_with_reasoning: str | None = None,
    reference_index: ReferenceIndex | None = None,
    batch_position: DebateBatchPosition | None = None,
) -> tuple[list[Hypothesis], list[dict[str, Any]], int]:
    """Generate hypotheses using parallel debate strategy.

    Each debate generates 1 hypothesis through multi-turn expert discussion

    Args:
        state: current workflow state
        count: number of debates to run (= number of hypotheses to generate)
        articles_with_reasoning: optional literature review context for debates
        reference_index: citation key → source mapping for structured citations
        batch_position: this call's position within a larger parallel
            batch (default: this call IS the whole batch, ids 0..count-1).
            The durable path runs each debate as its own task and passes
            the task's index plus the family's batch total so every task
            angles its debate distinctly (finding E14).

    Returns:
        Tuple of (debate_hypotheses, debate_transcripts, llm_call_count) --
        llm_call_count is every real completion spent across every debate
        in this batch (finding L3).
    """
    # coordinator.py may allocate 0 hypotheses to this path (e.g. condition
    # (a)/(c) giving 0 to debate-only); skip the gather/log overhead entirely
    # rather than running it with an empty task list.
    if count == 0:
        return [], [], 0

    logger.info("Running %s parallel debates", count)

    if batch_position is None:
        position = DebateBatchPosition(0, count)
    else:
        position = DebateBatchPosition(
            max(0, batch_position.debate_index),
            max(
                batch_position.total_debates,
                batch_position.debate_index + count,
            ),
        )
    debate_tasks = _build_debate_tasks(
        state,
        count,
        articles_with_reasoning,
        reference_index,
        position,
    )
    debate_results = await asyncio.gather(*debate_tasks)
    debate_hypotheses, debate_transcripts, llm_call_count = (
        _unpack_debate_results(debate_results)
    )

    logger.info("Generated %s hypotheses from debates", len(debate_hypotheses))
    return debate_hypotheses, debate_transcripts, llm_call_count

"""Literature-grounded observation review and hypothesis feedback."""

import asyncio
import dataclasses
import logging
from collections.abc import Coroutine
from typing import Any

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
    PROGRESS_REFLECTION_COMPLETE,
    PROGRESS_REFLECTION_START,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
    indexed_prompt_name,
)
from co_scientist.models import Hypothesis, phase_message
from co_scientist.progress import emit_progress
from co_scientist.prompts import PromptRunContext, get_reflection_prompt
from co_scientist.schemas.review import (
    REFLECTION_MAX_POSITIVE_OBSERVATIONS,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


_STRENGTHS_HEADER = "Confirmed strengths (positive observations):"


def clean_positive_observations(raw: Any) -> list[str]:
    """Normalize a review's positive observations, bounded and deduped.

    Args:
        raw: The raw ``positive_observations`` value from a review
            payload (may be absent, malformed, or hold blank entries).

    Returns:
        Cleaned strengths, at most REFLECTION_MAX_POSITIVE_OBSERVATIONS.
    """
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:REFLECTION_MAX_POSITIVE_OBSERVATIONS]


def _format_confirmed_strengths(positives: list[str]) -> str:
    """Render confirmed strengths as a bulleted note block."""
    if not positives:
        return ""
    lines = [_STRENGTHS_HEADER]
    lines.extend(f"- {item}" for item in positives)
    return "\n".join(lines)


def apply_observation_result(
    hypothesis: Hypothesis, result: dict[str, Any] | None
) -> None:
    """Fold one observation-review result onto its hypothesis.

    Sets reflection_notes to the reasoning, then the confirmed strengths
    the review recorded (K8), then the "Classification: <value>" suffix
    agents/ranking/ranking_debate_turns.py parses back out of the notes;
    stores the structured verdict under enrichments["observation"],
    which carries the strengths only when there are any, keeping
    no-finding records byte-identical to the pre-K8 shape.

    Args:
        hypothesis: Hypothesis the observation review judged (mutated).
        result: Observation-review payload, or None when the analysis
            failed; the failure note keeps the classification suffix the
            ranking parser relies on.
    """
    if result is None:
        hypothesis.reflection_notes = (
            "Analysis failed\n\nClassification: neutral"
        )
        return

    classification = str(result.get("classification", "neutral"))
    reasoning = str(result.get("reasoning", ""))
    positives = clean_positive_observations(result.get("positive_observations"))

    notes = reasoning
    strengths = _format_confirmed_strengths(positives)
    if strengths:
        notes = f"{notes}\n\n{strengths}" if notes else strengths
    hypothesis.reflection_notes = f"{notes}\n\nClassification: {classification}"

    observation: dict[str, Any] = {
        "classification": classification,
        "reasoning": reasoning,
    }
    if positives:
        observation["positive_observations"] = positives
    hypothesis.enrichments["observation"] = observation


def store_indra_enrichment(
    hypothesis: Hypothesis, result: dict[str, Any]
) -> None:
    """Merge INDRA evidence items from an observation result, if any.

    Knowledge-graph evidence rides in enrichments["indra_evidence"]
    (yaml-driven, only present for biomedical configs), separate from
    the observation verdict itself.
    """
    enrichment_items = result.get("indra_enrichment_items", [])
    if enrichment_items:
        hypothesis.enrichments["indra_evidence"] = enrichment_items


@dataclasses.dataclass(frozen=True)
class _ReflectionContext:
    """Batch-invariant context shared by every per-hypothesis reflection."""

    articles_with_reasoning: str
    model_name: str
    run_id: str | None = None
    tool_registry: Any | None = None
    meta_review: dict[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class _ReflectionCall:
    """A prepared reflection prompt plus its pre-fetched INDRA evidence."""

    prompt: str
    schema: dict[str, Any] | None
    indra_data: dict[str, Any]


async def observe_hypothesis(
    state: WorkflowState,
    hypothesis: Hypothesis,
    *,
    hypothesis_index: int = 1,
    total_count: int = 1,
) -> dict[str, Any] | None:
    """Observe one idea with engine-owned literature and prompt context."""
    context = _ReflectionContext(
        articles_with_reasoning=state.get("articles_with_reasoning") or "",
        model_name=state["model_name"],
        run_id=state.get("run_id"),
        tool_registry=state.get("tool_registry"),
        meta_review=state.get("meta_review"),
    )
    return await analyze_single_hypothesis(
        hypothesis, hypothesis_index, total_count, context
    )


async def analyze_single_hypothesis(
    hypothesis: Hypothesis,
    hypothesis_index: int,
    total_count: int,
    context: _ReflectionContext,
) -> dict[str, Any] | None:
    """Analyze a single hypothesis against literature observations.

    Args:
        hypothesis: hypothesis to analyze
        hypothesis_index: index for logging (1-based)
        total_count: total hypotheses count for logging
        context: batch-invariant context (literature, model, run id, tool
            registry, meta-review)

    Returns:
        dict with classification and reasoning, or None if failed
    """
    logger.debug(
        "\n→ analyzing hypothesis %s/%s", hypothesis_index, total_count
    )
    call = await _prepare_reflection_call(hypothesis, context, hypothesis_index)
    return await _run_reflection_llm_or_none(
        call, context, hypothesis_index, total_count
    )


async def _run_reflection_llm_or_none(
    call: _ReflectionCall,
    context: _ReflectionContext,
    hypothesis_index: int,
    total_count: int,
) -> dict[str, Any] | None:
    """Calls the reflection LLM, isolating any failure to this hypothesis.

    Returns None instead of raising, so the asyncio.gather in
    reflection_node still completes for every other hypothesis in the batch.
    """
    try:
        response = await _call_reflection_llm(call, context, hypothesis_index)
        return _format_reflection_result(
            response, call.indra_data, hypothesis_index
        )
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as e:
        logger.error(
            "Reflection failed for hypothesis %s: %s", hypothesis_index, e
        )
        return None


async def _prepare_reflection_call(
    hypothesis: Hypothesis,
    context: _ReflectionContext,
    hypothesis_index: int,
) -> _ReflectionCall:
    """Fetches INDRA evidence and builds the reflection prompt for one idea."""
    # Pre-fetch INDRA evidence for this hypothesis (non-critical, skip on
    # failure)
    indra_data = await _fetch_indra_for_hypothesis(
        hypothesis.text,
        context.tool_registry,
        hypothesis_index,
    )
    # Get reflection prompt (uses formatted text for LLM context)
    prompt, schema = get_reflection_prompt(
        articles_with_reasoning=context.articles_with_reasoning,
        hypothesis_text=hypothesis.text,
        indra_evidence=indra_data.get("prompt_text", ""),
        context=PromptRunContext(
            meta_review=context.meta_review,
            tool_registry=context.tool_registry,
        ),
    )
    return _ReflectionCall(prompt=prompt, schema=schema, indra_data=indra_data)


async def _call_reflection_llm(
    call: _ReflectionCall,
    context: _ReflectionContext,
    hypothesis_index: int,
) -> dict[str, Any]:
    return await call_llm_json(
        prompt=call.prompt,
        spec=CompletionSpec(
            model_name=context.model_name,
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=LOW_TEMPERATURE,
            json_schema=call.schema,
        ),
        options=LLMCallOptions(
            run_id=context.run_id,
            prompt_name=indexed_prompt_name("reflection", hypothesis_index),
        ),
    )


def _format_reflection_result(
    response: dict[str, Any],
    indra_data: dict[str, Any],
    hypothesis_index: int,
) -> dict[str, Any]:
    """Formats an LLM reflection response into the node's result shape.

    indra_enrichment_items rides alongside the classification so the caller
    can merge it into hypothesis.enrichments separately from the
    reflection_notes text.

    Args:
        response: raw LLM JSON response from the reflection call.
        indra_data: pre-fetched INDRA evidence for this hypothesis.
        hypothesis_index: Index for logging (1-based).

    Returns:
        Dict with classification, reasoning, positive_observations, and
        indra_enrichment_items.
    """
    # Default to "neutral"/empty if the LLM response omits a field, since
    # json_schema validation may still let optional keys through.
    classification = response.get("classification", "neutral")
    reasoning = response.get("reasoning", "")

    logger.debug(
        "hypothesis %s classification: %s", hypothesis_index, classification
    )

    return {
        "classification": classification,
        "reasoning": reasoning,
        # Optional schema field (audit K8): absent until the review
        # records confirmed strengths.
        "positive_observations": response.get("positive_observations", []),
        "indra_enrichment_items": indra_data.get("enrichment_items", []),
    }


async def reflection_node(state: WorkflowState) -> dict[str, Any]:
    """Analyze each hypothesis against literature observations.

    this node:
    1. for each generated hypothesis, calls the llm with reflection prompt
    2. analyzes if hypothesis provides novel causal explanation
    3. classifies as: already explained, other explanations more likely,
       missing piece, neutral, or disproved
    4. stores reflection metadata on each hypothesis

    Args:
        state: current workflow state

    Returns:
        dictionary with updated state fields
    """
    logger.debug("\n=== reflection node ===")
    logger.info("Analyzing hypotheses against literature observations")

    # Reflection compares hypotheses against literature review output, so it
    # depends on the (MCP-gated) literature_review node having run and
    # succeeded. If that node was skipped or failed, this node is a no-op
    # and hypotheses proceed to review with no reflection_notes set.
    inputs = _extract_reflection_inputs(state)
    if inputs is None:
        return {}
    articles_with_reasoning, hypotheses = inputs

    logger.debug("analyzing %s hypotheses against literature", len(hypotheses))

    await _run_reflection_phase(state, hypotheses, articles_with_reasoning)

    logger.info(
        "Completed reflection analysis for %s hypotheses", len(hypotheses)
    )

    return _build_reflection_result(hypotheses)


async def _run_reflection_phase(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    articles_with_reasoning: str,
) -> None:
    """Runs reflection analysis for every hypothesis and applies results.

    Emits progress before and after the analysis; emit_progress is a no-op
    unless a progress_callback was wired into state (the app layer uses it
    to stream SSE updates to the UI). Mutates hypotheses in place.

    Args:
        state: current workflow state.
        hypotheses: hypotheses to analyze; mutated in place.
        articles_with_reasoning: literature review context shared by all
            tasks.
    """
    await emit_progress(
        state,
        "reflection_start",
        f"Analyzing {len(hypotheses)} hypotheses against literature...",
        PROGRESS_REFLECTION_START,
        hypotheses_count=len(hypotheses),
    )

    logger.info("Running %s reflection analyses in parallel", len(hypotheses))
    analysis_results = await _run_reflection_analysis(
        state, hypotheses, articles_with_reasoning
    )

    _apply_reflection_results(hypotheses, analysis_results)

    await emit_progress(
        state,
        "reflection_complete",
        "Reflection analysis complete",
        PROGRESS_REFLECTION_COMPLETE,
        hypotheses_count=len(hypotheses),
    )


async def _run_reflection_analysis(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    articles_with_reasoning: str,
) -> list[dict[str, Any] | None]:
    """Runs reflection analysis for every hypothesis concurrently.

    asyncio.gather preserves input order, so the caller can zip hypotheses
    against the returned results by position even though the tasks ran
    concurrently.

    Args:
        state: current workflow state.
        hypotheses: hypotheses to analyze.
        articles_with_reasoning: literature review context shared by all
            tasks.

    Returns:
        Per-hypothesis result dicts, in the same order as hypotheses.
    """
    analysis_tasks = _build_analysis_tasks(
        state, hypotheses, articles_with_reasoning
    )
    return await asyncio.gather(*analysis_tasks)


def _build_reflection_result(hypotheses: list[Hypothesis]) -> dict[str, Any]:
    """Assembles the reflection_node return dict.

    hypotheses is the same list of objects fetched from state, mutated in
    place by _apply_reflection_results; returning it back through the
    "hypotheses" key hits the deduplicate_hypotheses reducer (state package)
    with 100% text overlap, so it is treated as a same-set replacement
    rather than an addition.

    Args:
        hypotheses: hypotheses with reflection results applied.

    Returns:
        Dict with updated state fields (hypotheses, messages).
    """
    return {
        "hypotheses": hypotheses,
        "messages": phase_message(
            "reflection",
            f"completed reflection analysis for {len(hypotheses)} hypotheses",
        ),
    }


def _extract_reflection_inputs(
    state: WorkflowState,
) -> tuple[str, list[Hypothesis]] | None:
    """Pulls the literature and hypotheses reflection needs out of state.

    Args:
        state: current workflow state.

    Returns:
        Tuple of (articles_with_reasoning, hypotheses), or None if either
        is missing, in which case the caller should no-op.
    """
    articles_with_reasoning = state.get("articles_with_reasoning")
    if not articles_with_reasoning:
        logger.warning(
            "No articles_with_reasoning in state, skipping reflection"
        )
        return None

    hypotheses = state.get("hypotheses", [])
    if not hypotheses:
        logger.warning("No hypotheses in state, skipping reflection")
        return None

    return articles_with_reasoning, hypotheses


def _build_analysis_tasks(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    articles_with_reasoning: str,
) -> list[Coroutine[Any, Any, dict[str, Any] | None]]:
    """Builds the per-hypothesis reflection coroutines to run concurrently.

    tool_registry/meta_review are threaded through to every task below as
    shared, read-only context. In the current graph wiring, "reflection" is
    reached only once, from "generate", before the iteration cycle produces
    a meta_review, so meta_review is effectively always empty here; evolved
    hypotheses re-enter "review" directly and never pass back through
    reflection. No semaphore caps concurrency here (unlike the ranking and
    deep_verification nodes), so one LLM call fires per hypothesis at once.

    Args:
        state: current workflow state.
        hypotheses: hypotheses to analyze.
        articles_with_reasoning: literature review context shared by all
            tasks.

    Returns:
        List of analyze_single_hypothesis coroutines, one per hypothesis.
    """
    return [
        observe_hypothesis(
            state,
            hyp,
            hypothesis_index=i + 1,
            total_count=len(hypotheses),
        )
        for i, hyp in enumerate(hypotheses)
    ]


def _apply_reflection_results(
    hypotheses: list[Hypothesis],
    analysis_results: list[dict[str, Any] | None],
) -> None:
    """Applies per-hypothesis reflection results onto their hypotheses.

    Mutates each hypothesis in place through the shared observation-
    feedback seam (which folds the critique and the confirmed strengths
    into reflection_notes, keeping the "Classification: <value>" suffix
    agents/ranking/ranking_debate_turns.py parses back out) and merges INDRA
    enrichment items when present.

    Args:
        hypotheses: hypotheses analyzed, in the same order as
            analysis_results.
        analysis_results: per-hypothesis result dicts from
            analyze_single_hypothesis, or None where analysis failed.
    """
    for hypothesis, result in zip(hypotheses, analysis_results, strict=True):
        apply_observation_result(hypothesis, result)
        if result:
            store_indra_enrichment(hypothesis, result)


async def _fetch_indra_for_hypothesis(
    hypothesis_text: str,
    tool_registry: Any | None,
    hypothesis_index: int,
) -> dict[str, Any]:
    """Pre-fetch INDRA knowledge graph evidence for a hypothesis.

    Non-critical: returns empty dict on any failure so reflection
    proceeds without INDRA data if the MCP server or tools are unavailable.

    Returns dict with "prompt_text" (str) and "enrichment_items" (list).
    """
    empty: dict[str, Any] = {"prompt_text": "", "enrichment_items": []}
    try:
        # Imported locally (not at module scope) so this call site's own
        # try/except is what handles a broken/missing optional dependency,
        # rather than failing at reflection.py import time.
        from co_scientist.agents.reflection.reflection_helpers import (
            fetch_indra_evidence,
        )

        result = await fetch_indra_evidence(
            hypothesis_text=hypothesis_text,
            tool_registry=tool_registry,
            max_statements=5,
        )
        prompt_text = result.get("prompt_text", "")
        if prompt_text:
            logger.debug(
                "hypothesis %s: fetched INDRA evidence (%s chars, %s items)",
                hypothesis_index,
                len(prompt_text),
                len(result.get("enrichment_items", [])),
            )
        return result
    except Exception as e:
        logger.debug(
            "hypothesis %s: INDRA fetch skipped: %s", hypothesis_index, e
        )
        return empty

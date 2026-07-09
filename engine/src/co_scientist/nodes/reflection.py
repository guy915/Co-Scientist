"""Reflection node - analyzes hypotheses against literature observations."""
# pylint: disable=inconsistent-quotes

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
    PROGRESS_REFLECTION_COMPLETE,
    PROGRESS_REFLECTION_START,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import Hypothesis, phase_message
from co_scientist.nodes.progress import emit_progress
from co_scientist.prompts import get_reflection_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def analyze_single_hypothesis(
    hypothesis: Hypothesis,
    articles_with_reasoning: str,
    model_name: str,
    hypothesis_index: int,
    total_count: int,
    run_id: str | None = None,
    tool_registry: Any | None = None,
    meta_review: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Analyze a single hypothesis against literature observations.

    Args:
        hypothesis: hypothesis to analyze
        articles_with_reasoning: literature review context
        model_name: llm model to use
        hypothesis_index: index for logging (1-based)
        total_count: total hypotheses count for logging
        run_id: optional run ID for saving prompts
        tool_registry: optional ToolRegistry for dynamic tool instructions
        meta_review: optional cross-iteration meta-review feedback

    Returns:
        dict with classification and reasoning, or None if failed
    """
    logger.debug(
        "\n→ analyzing hypothesis %s/%s", hypothesis_index, total_count
    )

    # Pre-fetch INDRA evidence for this hypothesis (non-critical, skip on
    # failure)
    indra_data = await _fetch_indra_for_hypothesis(
        hypothesis.text,
        tool_registry,
        hypothesis_index,
    )

    # Get reflection prompt (uses formatted text for LLM context)
    prompt, schema = get_reflection_prompt(
        articles_with_reasoning=articles_with_reasoning,
        hypothesis_text=hypothesis.text,
        meta_review=meta_review,
        tool_registry=tool_registry,
        indra_evidence=indra_data.get("prompt_text", ""),
    )

    try:
        response = await _call_reflection_llm(
            prompt, schema, model_name, run_id, hypothesis_index, total_count
        )
        return _format_reflection_result(response, indra_data, hypothesis_index)
    except Exception as e:  # pylint: disable=broad-exception-caught
        # Isolate this hypothesis's failure: return None instead of
        # raising, so the asyncio.gather in reflection_node still
        # completes for every other hypothesis in the batch.
        logger.error(
            "Reflection failed for hypothesis %s: %s", hypothesis_index, e
        )
        return None


async def _call_reflection_llm(
    prompt: str,
    schema: dict[str, Any] | None,
    model_name: str,
    run_id: str | None,
    hypothesis_index: int,
    total_count: int,
) -> dict[str, Any]:
    """Calls the LLM with the reflection prompt for one hypothesis.

    Args:
        prompt: Rendered reflection prompt.
        schema: JSON schema the response must conform to.
        model_name: LLM model to use.
        run_id: Optional run ID for saving prompts.
        hypothesis_index: Index for logging (1-based).
        total_count: Total hypotheses count for logging.

    Returns:
        The raw LLM JSON response.
    """
    return await call_llm_json(
        prompt=prompt,
        model_name=model_name,
        max_tokens=EXTENDED_MAX_TOKENS,
        temperature=LOW_TEMPERATURE,
        json_schema=schema,
        run_id=run_id,
        prompt_name=f"reflection_{hypothesis_index}",
        prompt_metadata={
            "hypothesis_index": hypothesis_index,
            "total_count": total_count,
            "prompt_length_chars": len(prompt),
        },
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
        Dict with classification, reasoning, and indra_enrichment_items.
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
    "hypotheses" key hits the deduplicate_hypotheses reducer (state.py)
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
    tool_registry = state.get("tool_registry")
    meta_review = state.get("meta_review")
    return [
        analyze_single_hypothesis(
            hypothesis=hyp,
            articles_with_reasoning=articles_with_reasoning,
            model_name=state["model_name"],
            hypothesis_index=i + 1,
            total_count=len(hypotheses),
            run_id=state.get("run_id"),
            tool_registry=tool_registry,
            meta_review=meta_review,
        )
        for i, hyp in enumerate(hypotheses)
    ]


def _apply_reflection_results(
    hypotheses: list[Hypothesis],
    analysis_results: list[dict[str, Any] | None],
) -> None:
    """Applies per-hypothesis reflection results onto their hypotheses.

    Mutates each hypothesis in place: sets reflection_notes (including the
    "Classification: <value>" suffix that nodes/ranking.py later parses back
    out of reflection_notes to show reflection context in tournament
    matchup prompts) and, when present, merges INDRA enrichment items.

    Args:
        hypotheses: hypotheses analyzed, in the same order as
            analysis_results.
        analysis_results: per-hypothesis result dicts from
            analyze_single_hypothesis, or None where analysis failed.
    """
    for hypothesis, result in zip(hypotheses, analysis_results, strict=True):
        if result:
            classification = result.get("classification", "neutral")
            reasoning = result.get("reasoning", "")
            hypothesis.reflection_notes = (
                f"{reasoning}\n\nClassification: {classification}"
            )
            # Store knowledge graph evidence in enrichments (yaml-driven,
            # only present for biomedical configs)
            enrichment_items = result.get("indra_enrichment_items", [])
            if enrichment_items:
                hypothesis.enrichments["indra_evidence"] = enrichment_items
        else:
            # Keep the same "Classification: neutral" suffix even on
            # failure so the ranking.py parser above never breaks.
            hypothesis.reflection_notes = (
                "Analysis failed\n\nClassification: neutral"
            )


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
        from co_scientist.nodes.reflection_helpers import (
            fetch_indra_evidence,  # pylint: disable=import-outside-toplevel
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
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.debug(
            "hypothesis %s: INDRA fetch skipped: %s", hypothesis_index, e
        )
        return empty

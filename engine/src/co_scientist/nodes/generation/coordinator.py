"""Generation coordinator - orchestrates all generation strategies.

All generation paths output hypotheses with explanation, literature_grounding,
and experiment fields.
When no literature is available, literature_grounding contains an explicit
warning message.
"""
# pylint: disable=inconsistent-quotes

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from collections.abc import Coroutine

from co_scientist.constants import (
    PROGRESS_GENERATE_START,
    PROGRESS_GENERATE_COMPLETE,
    LITERATURE_REVIEW_FAILED,
)
from co_scientist.exceptions import GenerationError
from co_scientist.mcp_client import get_mcp_client
from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState
from co_scientist.nodes.generation.citations import (
    ReferenceIndex,
    build_reference_index,
)
from co_scientist.nodes.generation.debate import generate_with_debate
from co_scientist.nodes.generation.literature_tools import generate_with_tools

logger = logging.getLogger(__name__)


@dataclass
class GenerationCounts:
    """Encapsulates hypothesis count allocation across generation methods."""

    tools_count: int
    debate_with_lit_count: int
    debate_only_count: int
    is_dev_isolation: bool = False
    is_degraded_mode: bool = False


@dataclass
class GenerationResults:
    """Encapsulates results from parallel generation execution."""

    tools_hypotheses: list[Hypothesis]
    debate_with_lit_hypotheses: list[Hypothesis]
    debate_only_hypotheses: list[Hypothesis]
    debate_transcripts: list[dict[str, Any]]


# Helper functions


def _check_literature_availability(articles_with_reasoning: str | None,
                                   mcp_available: bool) -> bool:
    """Determine if literature review is available and valid."""
    return (articles_with_reasoning is not None and
            articles_with_reasoning != LITERATURE_REVIEW_FAILED and
            mcp_available)


def _determine_generation_counts(state: WorkflowState, total_count: int,
                                 has_literature: bool,
                                 enable_tool_calling: bool) -> GenerationCounts:
    """Determine how many hypotheses to generate with each method."""
    if state.get("dev_test_lit_tools_isolation", False):
        return GenerationCounts(
            tools_count=total_count,
            debate_with_lit_count=0,
            debate_only_count=0,
            is_dev_isolation=True,
        )

    # Condition (a)
    if has_literature and enable_tool_calling:
        # Split 50/50, but ensure we don't exceed total_count
        tools_count = max(1, total_count // 2)
        debate_with_lit_count = total_count - tools_count
        # If total_count=1, tools_count=1, debate_with_lit_count=0
        # in this case, adjust to just use tools
        if debate_with_lit_count == 0:
            tools_count = total_count
        return GenerationCounts(
            tools_count=tools_count,
            debate_with_lit_count=debate_with_lit_count,
            debate_only_count=0,
        )

    # Condition (c)
    if has_literature and not enable_tool_calling:
        return GenerationCounts(
            tools_count=0,
            debate_with_lit_count=total_count,
            debate_only_count=0,
        )

    # Condition (b)
    return GenerationCounts(
        tools_count=0,
        debate_with_lit_count=0,
        debate_only_count=total_count,
        is_degraded_mode=True,
    )


def _log_generation_strategy(counts: GenerationCounts,
                             total_count: int) -> None:
    """Log which generation strategy is being used."""
    if counts.is_dev_isolation:
        logger.info("Dev isolation mode: allocating all hypotheses"
                    " to lit tools generation (no debate)")
        return

    if counts.tools_count > 0 and counts.debate_with_lit_count > 0:
        logger.info(
            "Condition (a): Generating %s hypotheses with literature review "
            "(%s tool-based + %s debate-with-literature)", total_count,
            counts.tools_count, counts.debate_with_lit_count)
    elif counts.debate_with_lit_count > 0:
        logger.info(
            "Condition (c): Generating %s hypotheses with"
            " debate-with-literature", total_count)
    elif counts.is_degraded_mode:
        logger.warning("=" * 80)
        logger.warning("No literature review tools available")
        logger.warning("Generating hypotheses from model latent knowledge only")
        logger.warning("=" * 80)


async def _emit_start_progress(state: WorkflowState, counts: GenerationCounts,
                               total_count: int) -> None:
    """Emit progress callback for generation start."""
    progress_callback = state.get("progress_callback")
    if not progress_callback:
        return

    if counts.is_dev_isolation:
        await progress_callback(
            "generation_start",
            {
                "message": (f"Generating {total_count} hypotheses with lit"
                            " tools only (dev isolation mode)..."),
                "progress": PROGRESS_GENERATE_START,
                "dev_isolation_mode": True,
            },
        )
    elif counts.tools_count > 0 and counts.debate_with_lit_count > 0:
        await progress_callback(
            "generation_start",
            {
                "message": (f"Generating {total_count} hypotheses"
                            f" ({counts.tools_count} tool-based"
                            f" + {counts.debate_with_lit_count}"
                            " debate-with-literature)..."),
                "progress": PROGRESS_GENERATE_START,
            },
        )
    elif counts.debate_with_lit_count > 0:
        await progress_callback(
            "generation_start",
            {
                "message": (f"Generating {total_count} hypotheses with"
                            " debate-with-literature..."),
                "progress": PROGRESS_GENERATE_START,
            },
        )
    elif counts.is_degraded_mode:
        await progress_callback(
            "generation_start",
            {
                "message": (f"Generating {counts.debate_only_count} hypotheses"
                            " without literature review..."),
                "progress": PROGRESS_GENERATE_START,
                "literature_review_available": False,
                "degraded_mode": True,
            },
        )


async def _execute_generation_tasks(
    state: WorkflowState,
    counts: GenerationCounts,
    articles_with_reasoning: str | None,
    reference_index: ReferenceIndex,
) -> GenerationResults:
    """Execute parallel generation tasks and return results."""
    tools_hypotheses: list[Hypothesis] = []
    debate_with_lit_hypotheses: list[Hypothesis] = []
    debate_only_hypotheses: list[Hypothesis] = []
    debate_transcripts: list[dict[str, Any]] = []

    # Collect tasks to run in parallel
    tasks: list[tuple[str, Coroutine[Any, Any, Any]]] = []

    if counts.tools_count > 0:
        logger.info("Running tool-based generation for %s hypotheses",
                    counts.tools_count)
        tasks.append(("tools",
                      generate_with_tools(state, counts.tools_count,
                                          reference_index)))

    if counts.debate_with_lit_count > 0:
        logger.info("Running debate-with-literature for %s hypotheses",
                    counts.debate_with_lit_count)
        tasks.append((
            "debate_lit",
            generate_with_debate(
                state=state,
                count=counts.debate_with_lit_count,
                articles_with_reasoning=articles_with_reasoning,
                reference_index=reference_index,
            ),
        ))

    if counts.debate_only_count > 0:
        logger.info("Running debate-only for %s hypotheses",
                    counts.debate_only_count)
        tasks.append((
            "debate_only",
            generate_with_debate(
                state=state,
                count=counts.debate_only_count,
                articles_with_reasoning=None,  # explicitly no literature
                reference_index=ReferenceIndex(text="", sources={}),
            ),
        ))

    # Run all tasks in parallel
    results = await asyncio.gather(*[task for _, task in tasks])

    # Unpack results
    for i, (task_type, _) in enumerate(tasks):
        if task_type == "tools":
            tools_hypotheses = results[i]
        elif task_type == "debate_lit":
            debate_with_lit_hypotheses, transcripts = results[i]
            debate_transcripts.extend(transcripts)
        elif task_type == "debate_only":
            debate_only_hypotheses, transcripts = results[i]
            debate_transcripts.extend(transcripts)

    return GenerationResults(
        tools_hypotheses=tools_hypotheses,
        debate_with_lit_hypotheses=debate_with_lit_hypotheses,
        debate_only_hypotheses=debate_only_hypotheses,
        debate_transcripts=debate_transcripts,
    )


def _apply_degraded_mode_fallback(hypotheses: list[Hypothesis]) -> None:
    """Set explicit literature_grounding message for hypotheses without
    literature review.
    """
    for hyp in hypotheses:
        # Always overwrite in non-lit-mcp mode to prevent hallucinated citations
        hyp.literature_grounding = (
            "No literature review available. This hypothesis is based"
            " on the model's latent knowledge and has not been"
            " validated against current research literature."
            " Novelty and scientific validity should be independently"
            " verified.")


def _log_generation_summary(results: GenerationResults) -> None:
    """Log summary of generated hypotheses."""
    total = (len(results.tools_hypotheses) +
             len(results.debate_with_lit_hypotheses) +
             len(results.debate_only_hypotheses))
    logger.info(
        "Generated %s total hypotheses (%s tool-based,"
        " %s debate-with-lit, %s debate-only)", total,
        len(results.tools_hypotheses), len(results.debate_with_lit_hypotheses),
        len(results.debate_only_hypotheses))

    if results.tools_hypotheses:
        logger.debug("tool-based generation_methods: %s", [
            h.generation_method.value if h.generation_method else None
            for h in results.tools_hypotheses
        ])
    if results.debate_with_lit_hypotheses:
        logger.debug("debate-with-Lit generation_methods: %s", [
            h.generation_method.value if h.generation_method else None
            for h in results.debate_with_lit_hypotheses
        ])
    if results.debate_only_hypotheses:
        logger.debug("debate-only generation_methods: %s", [
            h.generation_method.value if h.generation_method else None
            for h in results.debate_only_hypotheses
        ])


def _build_summary_message_parts(results: GenerationResults,
                                 counts: GenerationCounts) -> list[str]:
    """Build message parts for summary output."""
    parts = []
    if counts.tools_count > 0:
        parts.append(f"{len(results.tools_hypotheses)} tool-based")
    if counts.debate_with_lit_count > 0:
        parts.append(
            f"{len(results.debate_with_lit_hypotheses)} debate-with-literature")
    if counts.debate_only_count > 0:
        suffix = ""
        parts.append(
            f"{len(results.debate_only_hypotheses)} debate-only{suffix}")
    return parts


async def _emit_complete_progress(state: WorkflowState,
                                  results: GenerationResults,
                                  counts: GenerationCounts) -> None:
    """Emit progress callback for generation complete."""
    progress_callback = state.get("progress_callback")
    if not progress_callback:
        return

    parts = _build_summary_message_parts(results, counts)
    all_hypotheses = (results.tools_hypotheses +
                      results.debate_with_lit_hypotheses +
                      results.debate_only_hypotheses)

    message = f"Generated {len(all_hypotheses)} hypotheses ({', '.join(parts)})"

    await progress_callback(
        "generation_complete",
        {
            "message": message,
            "progress": PROGRESS_GENERATE_COMPLETE,
            "hypotheses_count": len(all_hypotheses),
        },
    )


# Enrichment


async def _enrich_hypotheses(
    hypotheses: list[Hypothesis],
    state: WorkflowState,
) -> None:
    """Run post-generation enrichment tools and attach results to hypotheses.

    Reads enrichment configs from the tool registry. For each config, calls
    the specified tool with each hypothesis's input_field value and stores
    the result in hypothesis.enrichments[output_key].
    """
    tool_registry = state.get("tool_registry")
    if not tool_registry:
        return

    enrichment_configs = tool_registry.get_enrichment_configs()
    if not enrichment_configs:
        return

    mcp_client = await get_mcp_client(tool_registry=tool_registry)

    for enrichment in enrichment_configs:
        tool_config = tool_registry.get_tool(enrichment.tool)
        if not tool_config:
            logger.warning("enrichment tool '%s' not found in registry",
                           enrichment.tool)
            continue

        output_key = enrichment.output_key or enrichment.tool
        logger.info("running enrichment '%s' via %s for %s hypotheses",
                    output_key, tool_config.mcp_tool_name, len(hypotheses))

        for hyp in hypotheses:
            input_value = getattr(hyp, enrichment.input_field, hyp.text)
            try:
                result = await mcp_client.call_tool(
                    tool_config.mcp_tool_name,
                    topic=input_value,
                    max_results=enrichment.max_results,
                )
                parsed = json.loads(result) if isinstance(result,
                                                          str) else result
                # Extract nested array via results_path (e.g., "results" for
                # NvdSearchResponse)
                if enrichment.results_path and isinstance(parsed, dict):
                    parsed = parsed.get(enrichment.results_path, parsed)
                hyp.enrichments[output_key] = parsed
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("enrichment '%s' failed for hypothesis: %s",
                               output_key, e)
                hyp.enrichments[output_key] = {"error": str(e)}


# Main coordinator function


async def generate_hypotheses(state: WorkflowState) -> dict[str, Any]:
    """Coordinate hypothesis generation using appropriate strategies.

    Implements 3-condition strategy:
    - Condition (a): lit review + tools → 50% tool-based + 50% debate-with-lit
    - Condition (b): no lit review → 100% debate-only
    - Condition (c): lit review but no tools → 100% debate-with-lit

    Args:
        state: current workflow state

    Returns:
        dict with hypotheses, debate_transcripts, metrics, and message
    """
    logger.info("Starting hypothesis generation")

    supervisor_guidance = state.get("supervisor_guidance")
    articles_with_reasoning = state.get("articles_with_reasoning")
    mcp_available = bool(state.get("mcp_available", False))
    enable_tool_calling = bool(
        state.get("enable_tool_calling_generation", False))
    total_count = state["initial_hypotheses_count"]

    if not supervisor_guidance:
        raise GenerationError(
            "No supervisor_guidance in state for node=generation")

    has_literature = _check_literature_availability(articles_with_reasoning,
                                                    mcp_available)
    counts = _determine_generation_counts(state, total_count, has_literature,
                                          enable_tool_calling)

    reference_index = build_reference_index(
        articles=state.get("articles"),
        context_enrichment_sources=state.get("context_enrichment_sources"),
    )
    if not reference_index.is_empty():
        logger.info(
            "Built reference index: %s paper(s), %s KG source(s)",
            sum(1 for k in reference_index.sources if k.startswith('P')),
            sum(1 for k in reference_index.sources if k.startswith('KG')))

    _log_generation_strategy(counts, total_count)
    await _emit_start_progress(state, counts, total_count)

    try:
        results = await _execute_generation_tasks(state, counts,
                                                  articles_with_reasoning,
                                                  reference_index)

        if counts.is_degraded_mode:
            _apply_degraded_mode_fallback(results.debate_only_hypotheses)

        _log_generation_summary(results)
        await _emit_complete_progress(state, results, counts)

        all_hypotheses = (results.tools_hypotheses +
                          results.debate_with_lit_hypotheses +
                          results.debate_only_hypotheses)

        # Run post-generation enrichments (e.g., NVD CVE lookup)
        await _enrich_hypotheses(all_hypotheses, state)

        parts = _build_summary_message_parts(results, counts)
        message_content = (f"Generated {len(all_hypotheses)} hypotheses"
                           f" ({', '.join(parts)})")

        return {
            "hypotheses": all_hypotheses,
            "debate_transcripts": results.debate_transcripts,
            "hypothesis_count": len(all_hypotheses),
            "message": message_content,
        }

    except Exception as e:
        logger.error("Generation failed: %s", e)
        raise

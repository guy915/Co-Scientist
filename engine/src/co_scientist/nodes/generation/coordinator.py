"""Generation coordinator - orchestrates all generation strategies.

All generation paths output hypotheses with explanation, literature_grounding,
and experiment fields.
When no literature is available, literature_grounding contains an explicit
warning message.
"""
# pylint: disable=inconsistent-quotes

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from collections.abc import Coroutine

from co_scientist.config.schema import EnrichmentConfig, ToolConfig
from co_scientist.constants import (
    PROGRESS_GENERATE_START,
    PROGRESS_GENERATE_COMPLETE,
    LITERATURE_REVIEW_FAILED,
    MAX_CONCURRENT_LLM_CALLS,
)
from co_scientist.exceptions import GenerationError
from co_scientist.mcp_client import get_mcp_client
from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState
from co_scientist.tools.response_parser import parse_mcp_result
from co_scientist.nodes.generation.citations import (
    ReferenceIndex,
    build_reference_index,
)
from co_scientist.nodes.generation.debate import generate_with_debate
from co_scientist.nodes.generation.literature_tools import generate_with_tools
from co_scientist.nodes.progress import emit_progress

logger = logging.getLogger(__name__)


# Bundles the three-way count split (and the two special-mode flags) so the
# helper functions below can pass one object around instead of five loose
# parameters.
@dataclass
class GenerationCounts:
    """Encapsulates hypothesis count allocation across generation methods."""

    tools_count: int  # hypotheses via tool-based draft/validate flow
    debate_with_lit_count: int  # hypotheses via debate, with lit context
    debate_only_count: int  # hypotheses via debate, no literature at all
    is_dev_isolation: bool = False  # dev/test: force tools-only allocation
    is_degraded_mode: bool = False  # no literature review was available


@dataclass
class GenerationResults:
    """Encapsulates results from parallel generation execution."""

    tools_hypotheses: list[Hypothesis]
    debate_with_lit_hypotheses: list[Hypothesis]
    debate_only_hypotheses: list[Hypothesis]
    # One entry per debate run (both debate_with_lit and debate_only feed
    # this); tool-based generation has no transcript equivalent.
    debate_transcripts: list[dict[str, Any]]

    @property
    def all_hypotheses(self) -> list[Hypothesis]:
        """All generated hypotheses across every strategy, in method order."""
        return (self.tools_hypotheses + self.debate_with_lit_hypotheses +
                self.debate_only_hypotheses)


# Helper functions


def _check_literature_availability(articles_with_reasoning: str | None,
                                   mcp_available: bool) -> bool:
    """Determine if literature review is available and valid."""
    # articles_with_reasoning is None before the literature review node has
    # run; it is set to the LITERATURE_REVIEW_FAILED sentinel when that node
    # ran but errored out. mcp_available must also be true here so we do not
    # try to run tool-based generation against a lit review summary that was
    # produced without live MCP tool access.
    return (articles_with_reasoning is not None and
            articles_with_reasoning != LITERATURE_REVIEW_FAILED and
            mcp_available)


def _determine_generation_counts(state: WorkflowState, total_count: int,
                                 has_literature: bool,
                                 enable_tool_calling: bool) -> GenerationCounts:
    """Determine how many hypotheses to generate with each method."""
    # Dev/test escape hatch: route everything through the tool-based path in
    # isolation so its behavior can be exercised without debate generation
    # mixed in. Takes priority over the normal 3-condition strategy below.
    if state.get("dev_test_lit_tools_isolation", False):
        return GenerationCounts(
            tools_count=total_count,
            debate_with_lit_count=0,
            debate_only_count=0,
            is_dev_isolation=True,
        )

    # Condition (a): literature review succeeded and tool calling is enabled
    # for generation - split the workload between the two literature-aware
    # strategies so results benefit from both a tool-driven read/validate
    # loop and a debate that has the same literature context.
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

    # Condition (c): literature review succeeded but tool calling is off for
    # generation (e.g. model/config does not support it) - fall back to
    # debate-with-literature for the full count.
    if has_literature and not enable_tool_calling:
        return GenerationCounts(
            tools_count=0,
            debate_with_lit_count=total_count,
            debate_only_count=0,
        )

    # Condition (b): no usable literature review at all - degrade to debate
    # generation from the model's latent knowledge only. Flagged so callers
    # can attach an explicit "no literature" warning to every hypothesis.
    return GenerationCounts(
        tools_count=0,
        debate_with_lit_count=0,
        debate_only_count=total_count,
        is_degraded_mode=True,
    )


def _log_generation_strategy(counts: GenerationCounts,
                             total_count: int) -> None:
    """Log which generation strategy is being used."""
    # Mirrors the branch order of _determine_generation_counts so the log
    # line always names the condition that actually produced these counts.
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
    # Builds a human-readable message plus optional extra payload fields for
    # the SSE progress event; branch order again follows the same conditions
    # as _determine_generation_counts.
    extra: dict[str, Any] = {}
    if counts.is_dev_isolation:
        message = (f"Generating {total_count} hypotheses with lit"
                   " tools only (dev isolation mode)...")
        extra = {"dev_isolation_mode": True}
    elif counts.tools_count > 0 and counts.debate_with_lit_count > 0:
        message = (f"Generating {total_count} hypotheses"
                   f" ({counts.tools_count} tool-based"
                   f" + {counts.debate_with_lit_count}"
                   " debate-with-literature)...")
    elif counts.debate_with_lit_count > 0:
        message = (f"Generating {total_count} hypotheses with"
                   " debate-with-literature...")
    elif counts.is_degraded_mode:
        message = (f"Generating {counts.debate_only_count} hypotheses"
                   " without literature review...")
        extra = {
            "literature_review_available": False,
            "degraded_mode": True,
        }
    else:
        return

    await emit_progress(state, "generation_start", message,
                        PROGRESS_GENERATE_START, **extra)


def _unpack_generation_results(
    tasks: list[tuple[str, Coroutine[Any, Any, Any]]],
    results: list[Any],
) -> GenerationResults:
    """Route gathered task results back into their per-strategy buckets.

    Args:
        tasks: the (task_type, coroutine) pairs passed to asyncio.gather, in
            the same order as results (task_type distinguishes the tools
            path's plain hypothesis list from the two debate paths'
            (hypotheses, transcripts) tuples).
        results: asyncio.gather's return value for those tasks.

    Returns:
        GenerationResults with each strategy's hypotheses/transcripts routed
        to the right field.
    """
    tools_hypotheses: list[Hypothesis] = []
    debate_with_lit_hypotheses: list[Hypothesis] = []
    debate_only_hypotheses: list[Hypothesis] = []
    debate_transcripts: list[dict[str, Any]] = []

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


async def _execute_generation_tasks(
    state: WorkflowState,
    counts: GenerationCounts,
    articles_with_reasoning: str | None,
    reference_index: ReferenceIndex,
) -> GenerationResults:
    """Execute parallel generation tasks and return results."""
    # Collect tasks to run in parallel. Each entry pairs a tag with its
    # coroutine so results can be routed back to the right bucket after
    # asyncio.gather() returns them in call order (order is not otherwise
    # recoverable once the coroutines are unpacked into gather()).
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
                # Passed explicitly rather than omitted, so degraded-mode
                # debates never accidentally pick up literature context from
                # a caller-supplied default.
                articles_with_reasoning=None,  # explicitly no literature
                reference_index=ReferenceIndex(text="", sources={}),
            ),
        ))

    # Run all tasks in parallel; gather preserves the order tasks were
    # appended in, which is what the index-based unpack in
    # _unpack_generation_results relies on.
    results = await asyncio.gather(*[task for _, task in tasks])

    return _unpack_generation_results(tasks, results)


def _apply_degraded_mode_fallback(hypotheses: list[Hypothesis]) -> None:
    """Set explicit literature_grounding message for hypotheses without
    literature review.
    """
    for hyp in hypotheses:
        # Always overwrite in non-lit-mcp mode to prevent hallucinated
        # citations: even if the model produced its own literature_grounding
        # text (it was told not to have literature), replace it so the
        # user-facing field never implies grounding that does not exist.
        hyp.literature_grounding = (
            "No literature review available. This hypothesis is based"
            " on the model's latent knowledge and has not been"
            " validated against current research literature."
            " Novelty and scientific validity should be independently"
            " verified.")


def _log_generation_summary(results: GenerationResults) -> None:
    """Log summary of generated hypotheses."""
    total = len(results.all_hypotheses)
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
        parts.append(f"{len(results.debate_only_hypotheses)} debate-only")
    return parts


async def _emit_complete_progress(state: WorkflowState,
                                  results: GenerationResults,
                                  counts: GenerationCounts) -> str:
    """Emit progress callback for generation complete.

    Returns:
        The human-readable generation summary message that was emitted.
    """
    parts = _build_summary_message_parts(results, counts)
    all_hypotheses = results.all_hypotheses

    message = f"Generated {len(all_hypotheses)} hypotheses ({', '.join(parts)})"

    await emit_progress(state,
                        "generation_complete",
                        message,
                        PROGRESS_GENERATE_COMPLETE,
                        hypotheses_count=len(all_hypotheses))
    return message


# Enrichment


async def _enrich_one_hypothesis(
    hyp: Hypothesis,
    enrichment: EnrichmentConfig,
    tool_config: ToolConfig,
    output_key: str,
    mcp_client: Any,
    semaphore: asyncio.Semaphore,
) -> None:
    """Run one enrichment tool call for one hypothesis, best-effort.

    Args:
        hyp: the hypothesis to enrich; the result is stored on
            hyp.enrichments[output_key].
        enrichment: the enrichment config (input field, tool, result shape).
        tool_config: the resolved tool config for enrichment.tool.
        output_key: key under which the result is stored on
            hyp.enrichments.
        mcp_client: MCP client used to call the enrichment tool.
        semaphore: shared concurrency limiter across all enrichment calls.
    """
    # input_field selects which hypothesis attribute to query with (e.g. its
    # explanation instead of its text); falls back to text.
    input_value = getattr(hyp, enrichment.input_field, hyp.text)
    try:
        async with semaphore:
            result = await mcp_client.call_tool(
                tool_config.mcp_tool_name,
                topic=input_value,
                max_results=enrichment.max_results,
            )
        parsed = parse_mcp_result(result)
        # Extract nested array via results_path (e.g., "results" for
        # NvdSearchResponse)
        if enrichment.results_path and isinstance(parsed, dict):
            parsed = parsed.get(enrichment.results_path, parsed)
        hyp.enrichments[output_key] = parsed
    except Exception as e:  # pylint: disable=broad-exception-caught
        # Enrichment is supplementary, not load-bearing: a failure here must
        # not fail hypothesis generation, so it is recorded on the
        # hypothesis instead of being raised.
        logger.warning("enrichment '%s' failed for hypothesis: %s", output_key,
                       e)
        hyp.enrichments[output_key] = {"error": str(e)}


async def _enrich_hypotheses(
    hypotheses: list[Hypothesis],
    state: WorkflowState,
) -> None:
    """Run post-generation enrichment tools and attach results to hypotheses.

    Reads enrichment configs from the tool registry. For each config, calls
    the specified tool with each hypothesis's input_field value and stores
    the result in hypothesis.enrichments[output_key].
    """
    # No-op unless the domain's tool config declares enrichment tools (e.g.
    # a CVE lookup for a cyber domain) - most domains have none configured.
    tool_registry = state.get("tool_registry")
    if not tool_registry:
        return

    enrichment_configs = tool_registry.get_enrichment_configs()
    if not enrichment_configs:
        return

    mcp_client = await get_mcp_client(tool_registry=tool_registry)
    # Reuse the same concurrency cap as LLM calls even though these are tool
    # calls, not LLM calls - it is a reasonable shared limit on outstanding
    # MCP requests and avoids adding a second constant for the same purpose.
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    for enrichment in enrichment_configs:
        tool_config = tool_registry.get_tool(enrichment.tool)
        if not tool_config:
            logger.warning("enrichment tool '%s' not found in registry",
                           enrichment.tool)
            continue

        output_key = enrichment.output_key or enrichment.tool
        logger.info("running enrichment '%s' via %s for %s hypotheses",
                    output_key, tool_config.mcp_tool_name, len(hypotheses))

        # Fan out one call per hypothesis for this enrichment config; the
        # semaphore inside _enrich_one_hypothesis bounds actual concurrency.
        await asyncio.gather(*(_enrich_one_hypothesis(
            hyp, enrichment, tool_config, output_key, mcp_client, semaphore)
                               for hyp in hypotheses))


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

    # supervisor_guidance drives prompt assembly in every downstream
    # generation path, so its absence is treated as a hard precondition
    # failure rather than something to silently work around.
    if not supervisor_guidance:
        raise GenerationError(
            "No supervisor_guidance in state for node=generation")

    has_literature = _check_literature_availability(articles_with_reasoning,
                                                    mcp_available)
    counts = _determine_generation_counts(state, total_count, has_literature,
                                          enable_tool_calling)

    # Built once up front and threaded through every strategy below so all
    # hypotheses generated in this call share one [C*] citation-key
    # namespace, regardless of which method produced them.
    reference_index = build_reference_index(
        articles=state.get("articles"),
        context_enrichment_sources=state.get("context_enrichment_sources"),
    )
    if not reference_index.is_empty():
        # Keys are uniformly "C<n>"; the paper/KG split lives in each
        # source's "type" field (see build_reference_index).
        logger.info(
            "Built reference index: %s paper(s), %s KG source(s)",
            sum(1 for s in reference_index.sources.values()
                if s.get("type") == "paper"),
            sum(1 for s in reference_index.sources.values()
                if s.get("type") == "knowledge_graph"))

    _log_generation_strategy(counts, total_count)
    await _emit_start_progress(state, counts, total_count)

    try:
        results = await _execute_generation_tasks(state, counts,
                                                  articles_with_reasoning,
                                                  reference_index)

        # Only debate_only_hypotheses need the fallback message: tools_ and
        # debate_with_lit_hypotheses are only populated when has_literature
        # was true, so is_degraded_mode and those lists are mutually
        # exclusive by construction.
        if counts.is_degraded_mode:
            _apply_degraded_mode_fallback(results.debate_only_hypotheses)

        _log_generation_summary(results)
        message_content = await _emit_complete_progress(state, results, counts)

        all_hypotheses = results.all_hypotheses

        # Run post-generation enrichments (e.g., NVD CVE lookup)
        await _enrich_hypotheses(all_hypotheses, state)

        return {
            "hypotheses": all_hypotheses,
            "debate_transcripts": results.debate_transcripts,
            "hypothesis_count": len(all_hypotheses),
            "message": message_content,
        }

    except Exception as e:
        # Log with full context here (this is the top-level entry point),
        # then re-raise so the caller (generate_node) treats generation
        # failure as a hard error rather than a partial/degraded result.
        logger.error("Generation failed: %s", e)
        raise

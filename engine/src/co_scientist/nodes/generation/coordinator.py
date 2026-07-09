"""Generation coordinator - orchestrates all generation strategies.

All generation paths output hypotheses with explanation, literature_grounding,
and experiment fields.
When no literature is available, literature_grounding contains an explicit
warning message.
"""
# pylint: disable=inconsistent-quotes

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from co_scientist.config.schema import EnrichmentConfig, ToolConfig
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    MAX_CONCURRENT_LLM_CALLS,
    PROGRESS_GENERATE_COMPLETE,
    PROGRESS_GENERATE_START,
)
from co_scientist.exceptions import GenerationError
from co_scientist.mcp_client import get_mcp_client
from co_scientist.models import Hypothesis
from co_scientist.nodes.generation.citations import (
    ReferenceIndex,
    build_reference_index,
)
from co_scientist.nodes.generation.debate import generate_with_debate
from co_scientist.nodes.generation.literature_tools import generate_with_tools
from co_scientist.nodes.progress import emit_progress
from co_scientist.state import WorkflowState
from co_scientist.tools.response_parser import parse_mcp_result

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
        return (
            self.tools_hypotheses
            + self.debate_with_lit_hypotheses
            + self.debate_only_hypotheses
        )


# Helper functions


def _check_literature_availability(
    articles_with_reasoning: str | None, mcp_available: bool
) -> bool:
    """Determine if literature review is available and valid."""
    # articles_with_reasoning is None before the literature review node has
    # run; it is set to the LITERATURE_REVIEW_FAILED sentinel when that node
    # ran but errored out. mcp_available must also be true here so we do not
    # try to run tool-based generation against a lit review summary that was
    # produced without live MCP tool access.
    return (
        articles_with_reasoning is not None
        and articles_with_reasoning != LITERATURE_REVIEW_FAILED
        and mcp_available
    )


def _classify_generation_strategy(
    state: WorkflowState, has_literature: bool, enable_tool_calling: bool
) -> str:
    """Classify which of the 3-condition generation strategies applies.

    Mirrors the precondition order that _determine_generation_counts,
    _log_generation_strategy, and _emit_start_progress all key off of, so
    each of those stays a plain per-label dispatch.

    Returns:
        One of "dev_isolation", "lit_and_tools" (condition a), "lit_only"
        (condition c), or "no_lit" (condition b).
    """
    # Dev/test escape hatch: route everything through the tool-based path in
    # isolation so its behavior can be exercised without debate generation
    # mixed in. Takes priority over the normal 3-condition strategy below.
    if state.get("dev_test_lit_tools_isolation", False):
        return "dev_isolation"

    # Condition (a): literature review succeeded and tool calling is enabled
    # for generation - split the workload between the two literature-aware
    # strategies so results benefit from both a tool-driven read/validate
    # loop and a debate that has the same literature context.
    if has_literature and enable_tool_calling:
        return "lit_and_tools"

    # Condition (c): literature review succeeded but tool calling is off for
    # generation (e.g. model/config does not support it) - fall back to
    # debate-with-literature for the full count.
    if has_literature:
        return "lit_only"

    # Condition (b): no usable literature review at all - degrade to debate
    # generation from the model's latent knowledge only.
    return "no_lit"


def _split_tools_and_debate_counts(total_count: int) -> tuple[int, int]:
    """Split total_count 50/50 between tools and debate-with-literature.

    Args:
        total_count: total hypotheses to allocate across the two methods.

    Returns:
        Tuple of (tools_count, debate_with_lit_count). If the 50/50 split
        would leave debate_with_lit_count at zero (total_count=1), the full
        count is routed to tools instead.
    """
    tools_count = max(1, total_count // 2)
    debate_with_lit_count = total_count - tools_count
    if debate_with_lit_count == 0:
        tools_count = total_count
    return tools_count, debate_with_lit_count


def _determine_generation_counts(
    state: WorkflowState,
    total_count: int,
    has_literature: bool,
    enable_tool_calling: bool,
) -> GenerationCounts:
    """Determine how many hypotheses to generate with each method."""
    strategy = _classify_generation_strategy(
        state, has_literature, enable_tool_calling
    )

    if strategy == "dev_isolation":
        return GenerationCounts(
            tools_count=total_count,
            debate_with_lit_count=0,
            debate_only_count=0,
            is_dev_isolation=True,
        )

    if strategy == "lit_and_tools":
        tools_count, debate_with_lit_count = _split_tools_and_debate_counts(
            total_count
        )
        return GenerationCounts(
            tools_count=tools_count,
            debate_with_lit_count=debate_with_lit_count,
            debate_only_count=0,
        )

    if strategy == "lit_only":
        return GenerationCounts(
            tools_count=0,
            debate_with_lit_count=total_count,
            debate_only_count=0,
        )

    # strategy == "no_lit". Flagged so callers can attach an explicit "no
    # literature" warning to every hypothesis.
    return GenerationCounts(
        tools_count=0,
        debate_with_lit_count=0,
        debate_only_count=total_count,
        is_degraded_mode=True,
    )


def _generation_log_case(counts: GenerationCounts) -> str:
    """Classify a resolved GenerationCounts for the log + start-progress steps.

    Shared by _log_generation_strategy and _emit_start_progress so both key
    off the same case label instead of repeating the same count comparisons.
    Derived from the actual counts (not the pre-count strategy) because a
    total_count=1 run of the "lit_and_tools" strategy collapses to
    tools-only, which - like the original if/elif chain - intentionally logs
    and emits nothing (case "none").

    Returns:
        One of "dev_isolation", "mixed" (both tools and debate-with-lit),
        "lit_only" (debate-with-lit alone), "degraded", or "none".
    """
    if counts.is_dev_isolation:
        return "dev_isolation"
    if counts.debate_with_lit_count > 0:
        return "mixed" if counts.tools_count > 0 else "lit_only"
    if counts.is_degraded_mode:
        return "degraded"
    return "none"


def _log_generation_strategy(
    counts: GenerationCounts, total_count: int
) -> None:
    """Log which generation strategy is being used."""
    case = _generation_log_case(counts)
    if case == "dev_isolation":
        logger.info(
            "Dev isolation mode: allocating all hypotheses"
            " to lit tools generation (no debate)"
        )
    elif case == "mixed":
        logger.info(
            "Condition (a): Generating %s hypotheses with literature review "
            "(%s tool-based + %s debate-with-literature)",
            total_count,
            counts.tools_count,
            counts.debate_with_lit_count,
        )
    elif case == "lit_only":
        logger.info(
            "Condition (c): Generating %s hypotheses with"
            " debate-with-literature",
            total_count,
        )
    elif case == "degraded":
        logger.warning("=" * 80)
        logger.warning("No literature review tools available")
        logger.warning("Generating hypotheses from model latent knowledge only")
        logger.warning("=" * 80)


def _start_progress_message(
    case: str, counts: GenerationCounts, total_count: int
) -> tuple[str, dict[str, Any]]:
    """Build the generation-start progress message/extra-payload for a case."""
    if case == "dev_isolation":
        return (
            f"Generating {total_count} hypotheses with lit"
            " tools only (dev isolation mode)...",
            {"dev_isolation_mode": True},
        )
    if case == "mixed":
        return (
            f"Generating {total_count} hypotheses"
            f" ({counts.tools_count} tool-based"
            f" + {counts.debate_with_lit_count}"
            " debate-with-literature)...",
            {},
        )
    if case == "lit_only":
        return (
            f"Generating {total_count} hypotheses with"
            " debate-with-literature...",
            {},
        )
    # case == "degraded"
    return (
        f"Generating {counts.debate_only_count} hypotheses"
        " without literature review...",
        {
            "literature_review_available": False,
            "degraded_mode": True,
        },
    )


async def _emit_start_progress(
    state: WorkflowState, counts: GenerationCounts, total_count: int
) -> None:
    """Emit progress callback for generation start."""
    case = _generation_log_case(counts)
    if case == "none":
        return
    message, extra = _start_progress_message(case, counts, total_count)
    await emit_progress(
        state, "generation_start", message, PROGRESS_GENERATE_START, **extra
    )


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


def _build_generation_tasks(
    state: WorkflowState,
    counts: GenerationCounts,
    articles_with_reasoning: str | None,
    reference_index: ReferenceIndex,
) -> list[tuple[str, Coroutine[Any, Any, Any]]]:
    """Build the (task_type, coroutine) pairs for each enabled strategy.

    Args:
        state: current workflow state
        counts: per-strategy hypothesis counts from
            _determine_generation_counts.
        articles_with_reasoning: optional literature review context.
        reference_index: citation key → source mapping shared across
            strategies.

    Returns:
        Task list in the order they should be passed to asyncio.gather.
    """
    # Collect tasks to run in parallel. Each entry pairs a tag with its
    # coroutine so results can be routed back to the right bucket after
    # asyncio.gather() returns them in call order (order is not otherwise
    # recoverable once the coroutines are unpacked into gather()).
    tasks: list[tuple[str, Coroutine[Any, Any, Any]]] = []

    if counts.tools_count > 0:
        logger.info(
            "Running tool-based generation for %s hypotheses",
            counts.tools_count,
        )
        tasks.append(
            (
                "tools",
                generate_with_tools(state, counts.tools_count, reference_index),
            )
        )

    if counts.debate_with_lit_count > 0:
        logger.info(
            "Running debate-with-literature for %s hypotheses",
            counts.debate_with_lit_count,
        )
        tasks.append(
            (
                "debate_lit",
                generate_with_debate(
                    state=state,
                    count=counts.debate_with_lit_count,
                    articles_with_reasoning=articles_with_reasoning,
                    reference_index=reference_index,
                ),
            )
        )

    if counts.debate_only_count > 0:
        logger.info(
            "Running debate-only for %s hypotheses", counts.debate_only_count
        )
        tasks.append(
            (
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
            )
        )

    return tasks


async def _execute_generation_tasks(
    state: WorkflowState,
    counts: GenerationCounts,
    articles_with_reasoning: str | None,
    reference_index: ReferenceIndex,
) -> GenerationResults:
    """Execute parallel generation tasks and return results."""
    tasks = _build_generation_tasks(
        state, counts, articles_with_reasoning, reference_index
    )

    # Run all tasks in parallel; gather preserves the order tasks were
    # appended in, which is what the index-based unpack in
    # _unpack_generation_results relies on.
    results = await asyncio.gather(*[task for _, task in tasks])

    return _unpack_generation_results(tasks, results)


def _apply_degraded_mode_fallback(hypotheses: list[Hypothesis]) -> None:
    """Sets a fallback literature_grounding message in degraded mode.

    Applies to every hypothesis generated without a literature review.
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
            " verified."
        )


def _log_bucket_methods(label: str, hypotheses: list[Hypothesis]) -> None:
    """Log the generation_method of every hypothesis in one bucket.

    No-op when the bucket is empty.

    Args:
        label: name of the bucket, used as the log line prefix.
        hypotheses: hypotheses in this bucket.
    """
    if not hypotheses:
        return
    logger.debug(
        "%s generation_methods: %s",
        label,
        [
            h.generation_method.value if h.generation_method else None
            for h in hypotheses
        ],
    )


def _log_generation_summary(results: GenerationResults) -> None:
    """Log summary of generated hypotheses."""
    total = len(results.all_hypotheses)
    logger.info(
        "Generated %s total hypotheses (%s tool-based,"
        " %s debate-with-lit, %s debate-only)",
        total,
        len(results.tools_hypotheses),
        len(results.debate_with_lit_hypotheses),
        len(results.debate_only_hypotheses),
    )

    _log_bucket_methods("tool-based", results.tools_hypotheses)
    _log_bucket_methods("debate-with-Lit", results.debate_with_lit_hypotheses)
    _log_bucket_methods("debate-only", results.debate_only_hypotheses)


def _build_summary_message_parts(
    results: GenerationResults, counts: GenerationCounts
) -> list[str]:
    """Build message parts for summary output."""
    parts = []
    if counts.tools_count > 0:
        parts.append(f"{len(results.tools_hypotheses)} tool-based")
    if counts.debate_with_lit_count > 0:
        parts.append(
            f"{len(results.debate_with_lit_hypotheses)} debate-with-literature"
        )
    if counts.debate_only_count > 0:
        parts.append(f"{len(results.debate_only_hypotheses)} debate-only")
    return parts


async def _emit_complete_progress(
    state: WorkflowState, results: GenerationResults, counts: GenerationCounts
) -> str:
    """Emit progress callback for generation complete.

    Returns:
        The human-readable generation summary message that was emitted.
    """
    parts = _build_summary_message_parts(results, counts)
    all_hypotheses = results.all_hypotheses

    message = f"Generated {len(all_hypotheses)} hypotheses ({', '.join(parts)})"

    await emit_progress(
        state,
        "generation_complete",
        message,
        PROGRESS_GENERATE_COMPLETE,
        hypotheses_count=len(all_hypotheses),
    )
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
        logger.warning(
            "enrichment '%s' failed for hypothesis: %s", output_key, e
        )
        hyp.enrichments[output_key] = {"error": str(e)}


async def _run_one_enrichment(
    enrichment: EnrichmentConfig,
    tool_registry: Any,
    hypotheses: list[Hypothesis],
    mcp_client: Any,
    semaphore: asyncio.Semaphore,
) -> None:
    """Resolve one enrichment config's tool and fan out calls per hypothesis.

    No-op (with a warning) when the config's tool is not found in the
    registry.
    """
    tool_config = tool_registry.get_tool(enrichment.tool)
    if not tool_config:
        logger.warning(
            "enrichment tool '%s' not found in registry", enrichment.tool
        )
        return

    output_key = enrichment.output_key or enrichment.tool
    logger.info(
        "running enrichment '%s' via %s for %s hypotheses",
        output_key,
        tool_config.mcp_tool_name,
        len(hypotheses),
    )

    # Fan out one call per hypothesis for this enrichment config; the
    # semaphore inside _enrich_one_hypothesis bounds actual concurrency.
    await asyncio.gather(
        *(
            _enrich_one_hypothesis(
                hyp, enrichment, tool_config, output_key, mcp_client, semaphore
            )
            for hyp in hypotheses
        )
    )


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
        await _run_one_enrichment(
            enrichment, tool_registry, hypotheses, mcp_client, semaphore
        )


# Main coordinator function


def _count_sources_by_type(
    reference_index: ReferenceIndex, source_type: str
) -> int:
    """Count reference-index sources whose "type" field matches source_type."""
    return sum(
        1
        for s in reference_index.sources.values()
        if s.get("type") == source_type
    )


def _log_reference_index_summary(reference_index: ReferenceIndex) -> None:
    """Log a paper/KG-source breakdown of a non-empty reference index."""
    if reference_index.is_empty():
        return
    # Keys are uniformly "C<n>"; the paper/KG split lives in each source's
    # "type" field (see build_reference_index).
    logger.info(
        "Built reference index: %s paper(s), %s KG source(s)",
        _count_sources_by_type(reference_index, "paper"),
        _count_sources_by_type(reference_index, "knowledge_graph"),
    )


async def _prepare_generation(
    state: WorkflowState,
) -> tuple[GenerationCounts, ReferenceIndex, str | None]:
    """Validate preconditions and resolve strategy, counts, and references.

    Also logs the resolved strategy and emits the generation-start progress
    callback, since both key off the counts computed here.

    Args:
        state: current workflow state

    Returns:
        Tuple of (counts, reference_index, articles_with_reasoning).

    Raises:
        GenerationError: if supervisor_guidance is missing from state.
    """
    supervisor_guidance = state.get("supervisor_guidance")
    articles_with_reasoning = state.get("articles_with_reasoning")
    mcp_available = bool(state.get("mcp_available", False))
    enable_tool_calling = bool(
        state.get("enable_tool_calling_generation", False)
    )
    total_count = state["initial_hypotheses_count"]

    # supervisor_guidance drives prompt assembly in every downstream
    # generation path, so its absence is treated as a hard precondition
    # failure rather than something to silently work around.
    if not supervisor_guidance:
        raise GenerationError(
            "No supervisor_guidance in state for node=generation"
        )

    has_literature = _check_literature_availability(
        articles_with_reasoning, mcp_available
    )
    counts = _determine_generation_counts(
        state, total_count, has_literature, enable_tool_calling
    )

    # Built once up front and threaded through every strategy below so all
    # hypotheses generated in this call share one [C*] citation-key
    # namespace, regardless of which method produced them.
    reference_index = build_reference_index(
        articles=state.get("articles"),
        context_enrichment_sources=state.get("context_enrichment_sources"),
    )
    _log_reference_index_summary(reference_index)

    _log_generation_strategy(counts, total_count)
    await _emit_start_progress(state, counts, total_count)

    return counts, reference_index, articles_with_reasoning


async def _finalize_generation(
    state: WorkflowState,
    counts: GenerationCounts,
    results: GenerationResults,
) -> dict[str, Any]:
    """Apply the degraded-mode fallback, enrich, and build the result dict.

    Args:
        state: current workflow state
        counts: per-strategy counts from _determine_generation_counts
        results: gathered generation results from _execute_generation_tasks

    Returns:
        dict with hypotheses, debate_transcripts, hypothesis_count, message.
    """
    # Only debate_only_hypotheses need the fallback message: tools_ and
    # debate_with_lit_hypotheses are only populated when has_literature was
    # true, so is_degraded_mode and those lists are mutually exclusive by
    # construction.
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

    (
        counts,
        reference_index,
        articles_with_reasoning,
    ) = await _prepare_generation(state)

    try:
        results = await _execute_generation_tasks(
            state, counts, articles_with_reasoning, reference_index
        )
        return await _finalize_generation(state, counts, results)

    except Exception as e:
        # Log with full context here (this is the top-level entry point),
        # then re-raise so the caller (generate_node) treats generation
        # failure as a hard error rather than a partial/degraded result.
        logger.error("Generation failed: %s", e)
        raise

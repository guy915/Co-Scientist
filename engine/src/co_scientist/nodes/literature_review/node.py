"""Literature review node orchestrator.

Orchestrates a multi-phase literature review process:
1. Generate search queries (MCP tool or LLM)
2. Collect papers from configured sources
3. Discover PDF links (for sources returning landing pages)
4. Fetch content (for sources without fulltext)
5. Analyze each paper for gaps/limitations
6. Synthesize findings into articles_with_reasoning
"""
# pylint: disable=inconsistent-quotes

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, cast

from co_scientist.constants import (
    corpus_slug,
    LITERATURE_REVIEW_PAPERS_COUNT,
    LITERATURE_REVIEW_PAPERS_COUNT_DEV,
    LITERATURE_REVIEW_FAILED,
)
from co_scientist.cache import get_node_cache, NodeCache
from co_scientist.config.registry import parse_bool_env
from co_scientist.mcp_client import (
    get_mcp_client,
    check_literature_source_available,
    MCPToolClient,
)
from co_scientist.models import Article
from co_scientist.state import WorkflowState

from co_scientist.nodes.progress import emit_progress
from co_scientist.nodes.literature_review.helpers import (
    SearchConfig,
    extract_source_name,
    build_articles_from_metadata,
    count_papers_with_fulltext,
    make_failure_result,
    make_success_result,
)
from co_scientist.nodes.literature_review.queries import (
    _phase1_generate_queries,)
from co_scientist.nodes.literature_review.search import (
    _phase2_collect_papers_multi_source,
    _phase2_collect_papers_single_source,
)
from co_scientist.nodes.literature_review.content import (
    _phase2_4_discover_pdf_links,
    _phase2_5_fetch_content,
)
from co_scientist.nodes.literature_review.enrichment import (
    _phase2_6_fetch_context_enrichment,
    _format_kg_section_with_keys,
)
from co_scientist.nodes.literature_review.analysis import _phase3_analyze_papers
from co_scientist.nodes.literature_review.synthesis import _phase4_synthesize

logger = logging.getLogger(__name__)


def _describe_exc(exc: BaseException) -> str:
    """Describe an exception by type and message for diagnostic logging.

    Unwraps ``ExceptionGroup`` (raised by the anyio task groups inside the MCP
    transport) down to its first leaf so the root cause - e.g. a connection
    error versus a validation error - is visible instead of the opaque group
    wrapper.

    Args:
        exc: The caught exception.

    Returns:
        A "TypeName: message" string describing the underlying cause.
    """
    current: BaseException = exc
    # ExceptionGroup (Python 3.11+) exposes an ``exceptions`` tuple; descend to
    # the first leaf so the real cause surfaces instead of the group wrapper.
    while getattr(current, "exceptions", None):
        current = current.exceptions[0]  # type: ignore[attr-defined]
    message = str(current).strip()
    return (f"{type(current).__name__}: {message}"
            if message else type(current).__name__)


# =============================================================================
# Configuration setup
# =============================================================================


def _resolve_papers_to_read_count(state: WorkflowState) -> tuple[int, bool]:
    """Resolve the papers-to-read budget and dev-mode status for this run.

    Dev mode uses a far smaller paper budget for fast iteration; a per-run
    override in state takes priority over the default when not in dev mode.

    Returns:
        A (papers_to_read_count, is_dev_mode) tuple.
    """
    is_dev_mode = parse_bool_env(os.getenv("COSCIENTIST_DEV_MODE", "false"))
    run_papers_count = state.get("literature_review_papers_count")
    papers_to_read_count = (LITERATURE_REVIEW_PAPERS_COUNT_DEV if is_dev_mode
                            else int(run_papers_count or
                                     LITERATURE_REVIEW_PAPERS_COUNT))
    return papers_to_read_count, is_dev_mode


def _get_search_config(state: WorkflowState) -> SearchConfig:
    """Extract search configuration from state and tool registry."""
    tool_registry = state.get("tool_registry")
    workflow = tool_registry.get_workflow(
        "literature_review") if tool_registry else None
    # config.is_multi_source is the branch point used throughout this file to
    # pick between the multi-source and single-source Phase 2 code paths.
    is_multi_source = bool(workflow and workflow.is_multi_source())

    # Defaults for backwards compatibility
    # If there is no tool registry (or no configured workflow), fall back to
    # the legacy hardcoded PubMed tool so the node still works without a
    # YAML tools config.
    search_tool_name = "pubmed_search_with_fulltext"
    source_name = "pubmed"
    search_tool_config = None

    if is_multi_source and workflow is not None:
        enabled_sources = workflow.get_enabled_search_sources()
        source_names = [s.tool for s in enabled_sources]
        logger.info("Multi-source mode: %s sources configured: %s",
                    len(enabled_sources), source_names)
    elif tool_registry and workflow and workflow.primary_search:
        search_tool_config = tool_registry.get_tool(workflow.primary_search)
        if search_tool_config:
            search_tool_name = search_tool_config.mcp_tool_name
            source_name = extract_source_name(search_tool_config)
            logger.info("Single-source mode: %s (source: %s)", search_tool_name,
                        source_name)

    papers_to_read_count, is_dev_mode = _resolve_papers_to_read_count(state)

    return SearchConfig(
        tool_registry=tool_registry,
        workflow=workflow,
        is_multi_source=is_multi_source,
        search_tool_name=search_tool_name,
        search_tool_config=search_tool_config,
        source_name=source_name,
        papers_to_read_count=papers_to_read_count,
        is_dev_mode=is_dev_mode,
    )


# =============================================================================
# Result and diagnostics helpers
#
# Each helper below covers one self-contained step of literature_review_node
# (a diagnostic side effect or an early-exit result), factored out purely to
# keep the orchestrator's phase sequence readable.
# =============================================================================


async def _emit_empty_search_diagnostics(
    state: WorkflowState,
    queries: list[str],
    search_errors: list[str],
) -> None:
    """Log and report progress when Phase 2 collected zero papers.

    Distinguishes a genuinely empty search from one where every call
    errored: both otherwise surface as zero articles with no trace of the
    cause.
    """
    if search_errors:
        logger.error(
            "Literature review found no papers: %s of %s search call(s) "
            "errored: %s", len(search_errors), len(queries),
            "; ".join(search_errors[:5]))
        await emit_progress(state,
                            "literature_review_error",
                            "Literature search failed (no papers retrieved)",
                            0.2,
                            queries_count=len(queries),
                            search_errors_count=len(search_errors),
                            search_error_sample=search_errors[:5])
    else:
        logger.warning(
            "Literature review found no papers: all %s query/queries "
            "returned zero results (no errors)", len(queries))
        await emit_progress(state,
                            "literature_review_empty",
                            "Literature search returned no results",
                            0.2,
                            queries_count=len(queries),
                            search_errors_count=0)


async def _handle_no_papers_found(
    state: WorkflowState,
    queries: list[str],
) -> dict[str, Any]:
    """Build the failure result when Phase 2 collected zero papers."""
    logger.warning("No papers collected")
    await emit_progress(state, "literature_review_complete",
                        "Literature review completed (no papers found)", 0.2)
    return make_failure_result("no papers found", queries=queries)


async def _handle_no_fulltext_available(
    state: WorkflowState,
    all_paper_metadata: dict[str, dict[str, Any]],
    queries: list[str],
    source_name: str,
) -> dict[str, Any]:
    """Build the failure result when no collected paper has usable content.

    Papers were found but none have any usable content (fulltext or
    abstract fallback) for Phase 3 analysis. Still returns the collected
    metadata as `articles` (used_in_analysis defaults True in
    build_article_from_metadata) so callers retain the paper list even
    though the review itself failed.
    """
    logger.error("No papers have fulltexts available - cannot perform analysis")
    n = len(all_paper_metadata)
    await emit_progress(
        state,
        "literature_review_complete",
        f"Literature review failed ({n} papers found but none"
        " have fulltexts)",
        0.2,
    )
    articles = build_articles_from_metadata(all_paper_metadata, source_name)
    return make_failure_result(
        f"{n} papers found but none have fulltexts for analysis",
        queries=queries,
        articles=articles,
    )


def _log_sample_papers(all_paper_metadata: dict[str, dict[str, Any]]) -> None:
    """Debug-log a small sample of collected papers before Phase 3 analysis."""
    for paper_id, meta in list(all_paper_metadata.items())[:3]:
        has_ft = bool(
            meta.get("pmc_full_text_id") or meta.get("fulltext") or
            meta.get("pdf_url"))
        logger.debug("Paper %s: title='%s...' has_fulltext=%s", paper_id,
                     meta.get('title', '')[:60], has_ft)


def _append_kg_evidence_section(
    synthesis: str,
    articles: list[Article],
    context_enrichment_sources: list[dict[str, Any]],
) -> str:
    """Append knowledge graph evidence with [C*] keys to the synthesis text.

    Keys start after the analyzed papers so they match what
    build_reference_index will assign at generation time, giving the
    generation LLM explicit handles to cite.
    """
    if not context_enrichment_sources or synthesis == LITERATURE_REVIEW_FAILED:
        return synthesis

    # used_paper_count must match the number of [C*] keys
    # build_reference_index will assign to papers at generation time, so the
    # KG section's keys start immediately after them.
    used_paper_count = sum(
        1 for a in articles if getattr(a, "used_in_analysis", False))
    kg_section = _format_kg_section_with_keys(context_enrichment_sources,
                                              used_paper_count)
    if not kg_section:
        return synthesis

    logger.info("Appended %s KG source(s) with [C%s...] keys to synthesis",
                len(context_enrichment_sources), used_paper_count + 1)
    return synthesis + kg_section


# =============================================================================
# Phase orchestration helpers
#
# Each helper below wraps one self-contained step of literature_review_node's
# phase sequence (a cache/availability gate, or a parallel phase dispatch),
# factored out purely to keep the orchestrator's phase sequence readable.
# =============================================================================


async def _check_cache(
    state: WorkflowState,
    node_cache: NodeCache,
    cache_params: dict[str, Any],
    force_cache: bool,
) -> dict[str, Any] | None:
    """Return the cached literature review result, if any.

    Keyed only on research_goal, so identical goals across runs reuse the
    full literature review output (queries, articles, and synthesis) instead
    of re-running every phase.

    Returns:
        The cached result dict on a cache hit, else None.
    """
    cached = node_cache.get("literature_review",
                            force=force_cache,
                            **cache_params)
    if cached is None:
        return None

    logger.info("Literature review cache hit")
    await emit_progress(state,
                        "literature_review_complete",
                        "Literature review completed (cached)",
                        0.2,
                        cached=True)
    return cached


async def _check_source_available(
    state: WorkflowState,
    config: SearchConfig,
) -> dict[str, Any] | None:
    """Verify the configured literature MCP source is reachable.

    Fails fast (before spending any LLM calls on query generation) if the
    configured literature MCP tool is unreachable.

    Returns:
        A failure result dict if unavailable, else None to continue.
    """
    source_available = await check_literature_source_available(
        tool_registry=config.tool_registry)
    if source_available:
        return None

    logger.error("Literature source MCP service unavailable")
    await emit_progress(state, "literature_review_error",
                        "Literature review failed (source unavailable)", 0.2)
    return make_failure_result("literature source service unavailable")


async def _phase2_collect_papers(
    queries: list[str],
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
    search_errors: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Phase 2: collect papers from configured sources.

    Dispatches to the multi-source or single-source collection path based on
    config.is_multi_source. The slug ties this run's searches to the shared
    on-disk corpus so a warm-started corpus from a prior run/tool-based
    generation phase is reused rather than re-downloaded.
    """
    slug = corpus_slug(state["research_goal"])

    if config.is_multi_source:
        return await _phase2_collect_papers_multi_source(
            queries, slug, state, config, mcp_client, search_errors)
    return await _phase2_collect_papers_single_source(queries, slug, state,
                                                      config, mcp_client,
                                                      search_errors)


async def _fetch_content_and_enrichment(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    config: SearchConfig,
    mcp_client: MCPToolClient,
    state: WorkflowState,
) -> tuple[str, list[dict[str, Any]]]:
    """Phase 2.5 + 2.6: fetch content and context enrichment in parallel.

    These two phases are independent of each other (content fetching acts on
    already-collected papers; enrichment queries external KG tools using
    entities from the research goal), so running them concurrently shaves
    wall-clock time off the node.

    Returns:
        (background_context, context_enrichment_sources) from Phase 2.6.
    """
    content_task = _phase2_5_fetch_content(all_paper_metadata, paper_source_map,
                                           config, mcp_client, state)
    enrichment_task = _phase2_6_fetch_context_enrichment(
        state, config, mcp_client)
    _, enrichment_result = await asyncio.gather(content_task, enrichment_task)
    return cast(tuple[str, list[dict[str, Any]]], enrichment_result)


def _build_and_cache_result(
    synthesis: str,
    queries: list[str],
    articles: list[Article],
    context_enrichment_sources: list[dict[str, Any]],
    node_cache: NodeCache,
    cache_params: dict[str, Any],
    force_cache: bool,
) -> dict[str, Any]:
    """Build the success result dict and populate the node cache with it.

    make_success_result always reports "success" even when synthesis is the
    LITERATURE_REVIEW_FAILED sentinel (that case only reaches here via the
    paper_analyses-empty branch, which still returns a normal-looking result
    dict rather than an early failure return) - downstream nodes rely on
    checking articles_with_reasoning for the sentinel rather than a
    top-level status field.

    Cached under the same force_cache flag used for the lookup, so a
    dev-isolation run that missed the cache still populates it for the next
    call.
    """
    result = make_success_result(synthesis, queries, articles)
    if context_enrichment_sources:
        result["context_enrichment_sources"] = context_enrichment_sources
    node_cache.set("literature_review",
                   result,
                   force=force_cache,
                   **cache_params)
    return result


@dataclass
class _CollectionResult:
    """Bundled output of Phases 2 through 2.6 for the orchestrator.

    Attributes:
        all_paper_metadata: Collected paper metadata keyed by paper ID.
        paper_source_map: Maps paper ID to the source name it came from.
        search_errors: Error strings from any failed search calls.
        background_context: Context-enrichment text for Phase 4 synthesis.
        context_enrichment_sources: Raw KG source dicts for citation keys.
        with_fulltext: Count of papers that have usable fulltext.
        without_fulltext: Count of papers missing usable fulltext.
    """
    all_paper_metadata: dict[str, dict[str, Any]]
    paper_source_map: dict[str, str]
    search_errors: list[str]
    background_context: str
    context_enrichment_sources: list[dict[str, Any]]
    with_fulltext: int
    without_fulltext: int


def _initialize_review(
    state: WorkflowState,
) -> tuple[SearchConfig, NodeCache, dict[str, Any], bool]:
    """Resolves search config and cache lookup parameters for this run.

    Returns:
        A (config, node_cache, cache_params, force_cache) tuple.
    """
    config = _get_search_config(state)
    logger.info("Literature review config: dev_mode=%s, papers=%s",
                config.is_dev_mode, config.papers_to_read_count)

    node_cache = get_node_cache()
    cache_params = {"research_goal": state["research_goal"]}
    # dev_test_lit_tools_isolation forces cache use even when the global
    # cache is disabled, so a developer iterating on the downstream
    # lit-tools generation phase can skip re-running this expensive node
    # every time.
    force_cache = bool(state.get("dev_test_lit_tools_isolation", False))
    if force_cache:
        logger.info("Dev isolation mode: forcing literature review cache")

    return config, node_cache, cache_params, force_cache


async def _collect_and_enrich_papers(
    queries: list[str],
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> _CollectionResult:
    """Phases 2 through 2.6: collect, discover PDFs, fetch content/enrichment.

    Returns:
        A _CollectionResult bundling the collected papers and fulltext
        counts.
    """
    search_errors: list[str] = []
    all_paper_metadata, paper_source_map = await _phase2_collect_papers(
        queries, state, config, mcp_client, search_errors)

    if not all_paper_metadata:
        await _emit_empty_search_diagnostics(state, queries, search_errors)

    # Phase 2.4: discover PDF links. Mutates all_paper_metadata in place
    # (no-op when no pdf_discovery_tool is configured for any source).
    await _phase2_4_discover_pdf_links(all_paper_metadata, paper_source_map,
                                       config, mcp_client)

    # Phase 2.5 + 2.6: fetch content and context enrichment in parallel
    background_context, context_enrichment_sources = (
        await _fetch_content_and_enrichment(all_paper_metadata,
                                            paper_source_map, config,
                                            mcp_client, state))

    with_fulltext, without_fulltext = count_papers_with_fulltext(
        all_paper_metadata)
    logger.info("Collected %s papers (%s with fulltext)",
                len(all_paper_metadata), with_fulltext)
    if without_fulltext > 0:
        logger.warning("%s papers do not have fulltexts available",
                       without_fulltext)

    return _CollectionResult(
        all_paper_metadata=all_paper_metadata,
        paper_source_map=paper_source_map,
        search_errors=search_errors,
        background_context=background_context,
        context_enrichment_sources=context_enrichment_sources,
        with_fulltext=with_fulltext,
        without_fulltext=without_fulltext,
    )


async def _handle_collection_edge_cases(
    state: WorkflowState,
    collected: _CollectionResult,
    queries: list[str],
    config: SearchConfig,
) -> dict[str, Any] | None:
    """Builds an early failure result if collection yielded nothing usable.

    Zero papers collected is a hard failure (nothing to analyze or
    synthesize from); zero papers with fulltext is also a hard failure for
    Phase 3 analysis, though still surfaced with the collected metadata.

    Returns:
        A failure result dict if either edge case applies, else None to
        continue to analysis.
    """
    if len(collected.all_paper_metadata) == 0:
        return await _handle_no_papers_found(state, queries)

    if collected.with_fulltext == 0:
        return await _handle_no_fulltext_available(state,
                                                   collected.all_paper_metadata,
                                                   queries, config.source_name)

    return None


async def _analyze_and_synthesize(
    all_paper_metadata: dict[str, dict[str, Any]],
    state: WorkflowState,
    background_context: str,
) -> str:
    """Phase 3 + 4: analyze papers for gaps/limitations, then synthesize.

    Guards against calling the synthesis LLM with an empty analyses list
    (redundant with _phase4_synthesize's own check, but avoids the
    call/log noise entirely when Phase 3 produced nothing).

    Returns:
        The synthesis text, or the LITERATURE_REVIEW_FAILED sentinel if
        Phase 3 produced no analyses.
    """
    paper_analyses = await _phase3_analyze_papers(all_paper_metadata, state)
    if not paper_analyses:
        return LITERATURE_REVIEW_FAILED
    return await _phase4_synthesize(paper_analyses, state, background_context)


def _finalize_synthesis_and_articles(
    synthesis: str,
    all_paper_metadata: dict[str, dict[str, Any]],
    context_enrichment_sources: list[dict[str, Any]],
    source_name: str,
) -> tuple[str, list[Article]]:
    """Phase 5: builds article objects and appends KG evidence to synthesis.

    Built from all_paper_metadata (not just the analyzed subset) so
    `articles` in the returned state includes every collected paper,
    whether or not it had content for Phase 3 analysis. KG evidence keys
    are appended aligned to the reference index (see
    _append_kg_evidence_section for why the keys line up).

    Returns:
        The (synthesis, articles) pair to return from the node.
    """
    logger.info("Phase 5: creating article objects")
    articles = build_articles_from_metadata(all_paper_metadata, source_name)
    logger.info("Created %s article objects", len(articles))

    synthesis = _append_kg_evidence_section(synthesis, articles,
                                            context_enrichment_sources)
    return synthesis, articles


async def _emit_and_log_completion(
    state: WorkflowState,
    queries: list[str],
    articles: list[Article],
    search_errors: list[str],
    synthesis: str,
) -> None:
    """Emits the completion progress event and logs the final summary."""
    await emit_progress(
        state,
        "literature_review_complete",
        "Literature review completed",
        0.2,
        queries_count=len(queries),
        articles_count=len(articles),
        search_errors_count=len(search_errors),
    )

    logger.info(
        "Literature review complete: %s articles from %s queries,"
        " %s char synthesis", len(articles), len(queries), len(synthesis))


# =============================================================================
# Main node function
# =============================================================================


async def literature_review_node(state: WorkflowState) -> dict[str, Any]:
    """Conducts literature review using configured MCP tools with LLM analysis.

    Orchestrates the following phases:
    1. Generate search queries (MCP tool or LLM)
    2. Collect papers from configured sources
    3. Discover PDF links (for sources returning landing pages)
    4. Fetch content (for sources without fulltext)
    5. Analyze each paper for gaps/limitations
    6. Synthesize findings into articles_with_reasoning
    """
    logger.info("Starting literature review node")

    config, node_cache, cache_params, force_cache = _initialize_review(state)

    cached = await _check_cache(state, node_cache, cache_params, force_cache)
    if cached is not None:
        return cached

    unavailable_result = await _check_source_available(state, config)
    if unavailable_result is not None:
        return unavailable_result

    await emit_progress(state, "literature_review_start",
                        "Conducting literature review...", 0.1)

    mcp_client = await get_mcp_client(tool_registry=config.tool_registry)

    # Phase 1: generate queries
    queries = await _phase1_generate_queries(state, config, mcp_client)

    # Phases 2-2.6: collect papers, discover PDFs, fetch content/enrichment
    collected = await _collect_and_enrich_papers(queries, state, config,
                                                 mcp_client)

    edge_case_result = await _handle_collection_edge_cases(
        state, collected, queries, config)
    if edge_case_result is not None:
        return edge_case_result

    _log_sample_papers(collected.all_paper_metadata)

    # Phase 3 + 4: analyze papers, then synthesize
    synthesis = await _analyze_and_synthesize(collected.all_paper_metadata,
                                              state,
                                              collected.background_context)

    # Phase 5: create articles and append KG evidence
    synthesis, articles = _finalize_synthesis_and_articles(
        synthesis, collected.all_paper_metadata,
        collected.context_enrichment_sources, config.source_name)

    await _emit_and_log_completion(state, queries, articles,
                                   collected.search_errors, synthesis)

    return _build_and_cache_result(synthesis, queries, articles,
                                   collected.context_enrichment_sources,
                                   node_cache, cache_params, force_cache)

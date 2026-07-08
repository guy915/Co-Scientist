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
from typing import Any

from co_scientist.constants import (
    corpus_slug,
    LITERATURE_REVIEW_PAPERS_COUNT,
    LITERATURE_REVIEW_PAPERS_COUNT_DEV,
    LITERATURE_REVIEW_FAILED,
)
from co_scientist.cache import get_node_cache
from co_scientist.config.registry import parse_bool_env
from co_scientist.mcp_client import (
    get_mcp_client,
    check_literature_source_available,
)
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

    # Dev mode detection
    # Dev mode uses a far smaller paper budget for fast iteration; a
    # per-run override in state takes priority over the default when not in
    # dev mode.
    is_dev_mode = parse_bool_env(os.getenv("COSCIENTIST_DEV_MODE", "false"))
    run_papers_count = state.get("literature_review_papers_count")
    papers_to_read_count = (LITERATURE_REVIEW_PAPERS_COUNT_DEV if is_dev_mode
                            else int(run_papers_count or
                                     LITERATURE_REVIEW_PAPERS_COUNT))

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

    # Setup configuration
    config = _get_search_config(state)
    logger.info("Literature review config: dev_mode=%s, papers=%s",
                config.is_dev_mode, config.papers_to_read_count)

    # Check cache
    # Keyed only on research_goal, so identical goals across runs reuse the
    # full literature review output (queries, articles, and synthesis)
    # instead of re-running every phase below.
    node_cache = get_node_cache()
    cache_params = {"research_goal": state["research_goal"]}
    # dev_test_lit_tools_isolation forces cache use even when the global
    # cache is disabled, so a developer iterating on the downstream
    # lit-tools generation phase can skip re-running this expensive node
    # every time.
    force_cache = bool(state.get("dev_test_lit_tools_isolation", False))

    if force_cache:
        logger.info("Dev isolation mode: forcing literature review cache")

    cached = node_cache.get("literature_review",
                            force=force_cache,
                            **cache_params)
    if cached is not None:
        logger.info("Literature review cache hit")
        await emit_progress(state,
                            "literature_review_complete",
                            "Literature review completed (cached)",
                            0.2,
                            cached=True)
        return cached

    # Check source availability
    # Fails fast (before spending any LLM calls on query generation) if the
    # configured literature MCP tool is unreachable.
    source_available = await check_literature_source_available(
        tool_registry=config.tool_registry)
    if not source_available:
        logger.error("Literature source MCP service unavailable")
        await emit_progress(state, "literature_review_error",
                            "Literature review failed (source unavailable)",
                            0.2)
        return make_failure_result("literature source service unavailable")

    await emit_progress(state, "literature_review_start",
                        "Conducting literature review...", 0.1)

    # Initialize MCP client
    mcp_client = await get_mcp_client(tool_registry=config.tool_registry)

    # Phase 1: generate queries
    queries = await _phase1_generate_queries(state, config, mcp_client)

    # Phase 2: collect papers
    # slug ties this run's searches to the shared on-disk corpus (see
    # corpus_slug docstring) so a warm-started corpus from a prior run/
    # tool-based generation phase is reused rather than re-downloaded.
    slug = corpus_slug(state["research_goal"])

    search_errors: list[str] = []
    if config.is_multi_source:
        all_paper_metadata, paper_source_map = (
            await _phase2_collect_papers_multi_source(queries, slug, state,
                                                      config, mcp_client,
                                                      search_errors))
    else:
        all_paper_metadata, paper_source_map = (
            await _phase2_collect_papers_single_source(queries, slug, state,
                                                       config, mcp_client,
                                                       search_errors))

    # Distinguish a genuinely empty search from one where every call errored:
    # both otherwise surface as zero articles with no trace of the cause.
    if not all_paper_metadata:
        if search_errors:
            logger.error(
                "Literature review found no papers: %s of %s search call(s) "
                "errored: %s", len(search_errors), len(queries),
                "; ".join(search_errors[:5]))
            await emit_progress(
                state,
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

    # Phase 2.4: discover PDF links
    # Mutates all_paper_metadata in place (no-op when no pdf_discovery_tool
    # is configured for any source).
    await _phase2_4_discover_pdf_links(all_paper_metadata, paper_source_map,
                                       config, mcp_client)

    # Phase 2.5 + 2.6: fetch content and context enrichment in parallel
    # These two phases are independent of each other (content fetching acts
    # on already-collected papers; enrichment queries external KG tools
    # using entities from the research goal), so running them concurrently
    # shaves wall-clock time off the node.
    content_task = _phase2_5_fetch_content(all_paper_metadata, paper_source_map,
                                           config, mcp_client, state)
    enrichment_task = _phase2_6_fetch_context_enrichment(
        state, config, mcp_client)
    _, enrichment_result = await asyncio.gather(content_task, enrichment_task)
    background_context, context_enrichment_sources = enrichment_result

    # Check fulltext availability
    with_fulltext, without_fulltext = count_papers_with_fulltext(
        all_paper_metadata)
    logger.info("Collected %s papers (%s with fulltext)",
                len(all_paper_metadata), with_fulltext)

    if without_fulltext > 0:
        logger.warning("%s papers do not have fulltexts available",
                       without_fulltext)

    # Handle edge cases
    # Zero papers collected is a hard failure (nothing to analyze or
    # synthesize from).
    if len(all_paper_metadata) == 0:
        logger.warning("No papers collected")
        await emit_progress(state, "literature_review_complete",
                            "Literature review completed (no papers found)",
                            0.2)
        return make_failure_result("no papers found", queries=queries)

    # Papers were found but none have any usable content (fulltext or
    # abstract fallback) for Phase 3 analysis. Still return the collected
    # metadata as `articles` (used_in_analysis defaults True in
    # build_article_from_metadata) so callers retain the paper list even
    # though the review itself failed.
    if with_fulltext == 0:
        logger.error(
            "No papers have fulltexts available - cannot perform analysis")
        n = len(all_paper_metadata)
        await emit_progress(
            state,
            "literature_review_complete",
            f"Literature review failed ({n} papers found but none"
            " have fulltexts)",
            0.2,
        )
        articles = build_articles_from_metadata(all_paper_metadata,
                                                config.source_name)
        return make_failure_result(
            f"{n} papers found but none have fulltexts for analysis",
            queries=queries,
            articles=articles,
        )

    # Log sample papers for debugging
    for paper_id, meta in list(all_paper_metadata.items())[:3]:
        has_ft = bool(
            meta.get("pmc_full_text_id") or meta.get("fulltext") or
            meta.get("pdf_url"))
        logger.debug("Paper %s: title='%s...' has_fulltext=%s", paper_id,
                     meta.get('title', '')[:60], has_ft)

    # Phase 3: analyze papers
    paper_analyses = await _phase3_analyze_papers(all_paper_metadata, state)

    # Phase 4: synthesize
    # Guards against calling the synthesis LLM with an empty analyses list
    # (redundant with _phase4_synthesize's own check, but avoids the
    # call/log noise entirely when Phase 3 produced nothing).
    if paper_analyses:
        synthesis = await _phase4_synthesize(paper_analyses, state,
                                             background_context)
    else:
        synthesis = LITERATURE_REVIEW_FAILED

    # Phase 5: create articles
    # Built from all_paper_metadata (not just the analyzed subset) so
    # `articles` in the returned state includes every collected paper,
    # whether or not it had content for Phase 3 analysis.
    logger.info("Phase 5: creating article objects")
    articles = build_articles_from_metadata(all_paper_metadata,
                                            config.source_name)
    logger.info("Created %s article objects", len(articles))

    # Append knowledge graph evidence with [C*] keys aligned to the reference
    # index. keys start after the analyzed papers so they match what
    # build_reference_index will assign at generation time — giving the
    # generation LLM explicit handles to cite.
    if context_enrichment_sources and synthesis != LITERATURE_REVIEW_FAILED:
        # used_paper_count must match the number of [C*] keys
        # build_reference_index will assign to papers at generation time, so
        # the KG section's keys start immediately after them.
        used_paper_count = sum(
            1 for a in articles if getattr(a, "used_in_analysis", False))
        kg_section = _format_kg_section_with_keys(context_enrichment_sources,
                                                  used_paper_count)
        if kg_section:
            synthesis = synthesis + kg_section
            logger.info(
                "Appended %s KG source(s) with [C%s...] keys to synthesis",
                len(context_enrichment_sources), used_paper_count + 1)

    # Emit completion
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

    # Build and cache result
    # make_success_result always reports "success" even when synthesis is
    # the LITERATURE_REVIEW_FAILED sentinel (that case only reaches here via
    # the paper_analyses-empty branch above, which still returns a
    # normal-looking result dict rather than an early failure return) --
    # downstream nodes rely on checking articles_with_reasoning for the
    # sentinel rather than a top-level status field.
    result = make_success_result(synthesis, queries, articles)
    if context_enrichment_sources:
        result["context_enrichment_sources"] = context_enrichment_sources
    # Cached under the same force_cache flag used for the lookup above, so
    # a dev-isolation run that missed the cache still populates it for the
    # next call.
    node_cache.set("literature_review",
                   result,
                   force=force_cache,
                   **cache_params)

    return result

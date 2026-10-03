"""Phase 2: literature review paper collection.

Runs the generated queries against the configured search source(s) and merges
the results. Supports both the multi-source path (several sources searched in
parallel, deduped and provenance-tagged) and the legacy single-source path
(one tool, papers budget distributed across queries).

Both paths issue their individual queries through ``search_query``; what
lives here is the fan-out across sources and queries and the reduction of
what they return to the run's evidence budget.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from co_scientist.constants import corpus_slug
from co_scientist.evidence.relevance import (
    apply_semantic_relevance,
)
from co_scientist.evidence.search_fusion import (
    select_within_budget,
)
from co_scientist.evidence.search_query import (
    _search_single_query as _search_single_query,
)
from co_scientist.evidence.search_query import (
    _search_source_for_query as _search_source_for_query,
)
from co_scientist.evidence.search_query import (
    _SearchRunContext as _SearchRunContext,
)
from co_scientist.evidence.search_support import (
    SearchConfig,
    extract_source_name,
    merge_search_results,
)
from co_scientist.mcp_client import MCPToolClient, campaign_serves_tool
from co_scientist.state import WorkflowState


async def collect_papers(
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
    ctx = _SearchRunContext(
        slug=corpus_slug(state["research_goal"]),
        run_id=state["run_id"],
        mcp_client=mcp_client,
        errors=search_errors,
    )

    if config.is_multi_source:
        return await _phase2_collect_papers_multi_source(queries, config, ctx)
    return await _phase2_collect_papers_single_source(queries, config, ctx)


# Query execution lives in search_query; this module owns fan-out and
# reduction across queries and sources.

if TYPE_CHECKING:
    from co_scientist.config import SearchSourceConfig, ToolConfig, ToolRegistry

logger = logging.getLogger(__name__)


async def _run_single_source_queries(
    queries: list[str],
    ctx: _SearchRunContext,
    tool_config: "ToolConfig",
    src_name: str,
    papers_per_query: int,
) -> dict[str, dict[str, Any]]:
    """Runs every query against one source concurrently and merges results.

    A source's queries are independent round-trips to the same tool, so
    awaiting them one at a time made the source cost the sum of its queries
    when it need only cost the slowest. Phase 2 sits on the run's serial
    spine, and the caller only parallelizes *across* sources, so that sum
    was paid in full on every literature review.

    Query generation asks for 2-4 queries, which bounds this at four calls
    in flight per source -- comfortably inside the indexes' rate limits and
    not worth a semaphore.

    Results are merged in query order rather than completion order:
    ``asyncio.gather`` returns in input order, so a paper found by several
    queries keeps the same winning metadata it had when the loop was
    sequential, and selection downstream stays deterministic.
    """
    per_query = await asyncio.gather(
        *(
            _search_source_for_query(
                query, ctx, tool_config, src_name, papers_per_query
            )
            for query in queries
        )
    )
    source_results: dict[str, dict[str, Any]] = {}
    for normalized in per_query:
        source_results.update(normalized)
    return source_results


async def _search_single_source(
    source_config: "SearchSourceConfig",
    queries: list[str],
    ctx: _SearchRunContext,
    tool_registry: "ToolRegistry",
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Search a single source with all queries."""
    tool_config = tool_registry.get_tool(source_config.tool)
    if not tool_config:
        logger.warning(
            "Tool config not found for source: %s", source_config.tool
        )
        return (source_config.tool, {})

    src_name = extract_source_name(tool_config)
    papers_per_query = source_config.papers_per_query
    logger.info(
        "Searching %s (%s): %s papers/query",
        src_name,
        tool_config.mcp_tool_name,
        papers_per_query,
    )

    source_results = await _run_single_source_queries(
        queries, ctx, tool_config, src_name, papers_per_query
    )

    logger.info("Source %s: collected %s papers", src_name, len(source_results))
    return (source_config.tool, source_results)


async def _search_all_sources(
    enabled_sources: list["SearchSourceConfig"],
    queries: list[str],
    ctx: _SearchRunContext,
    tool_registry: "ToolRegistry",
) -> list[tuple[str, dict[str, dict[str, Any]]]]:
    """Searches all enabled sources in parallel.

    Each _search_single_source call also runs its own queries concurrently,
    so overall latency is bounded by the single slowest query anywhere
    rather than by any source's query count.

    Args:
        enabled_sources: Search sources enabled by the workflow config.
        queries: Queries to run against every source.
        ctx: Run-scoped search inputs (slug, run id, client, errors).
        tool_registry: Registry used to resolve each source's tool config.

    Returns:
        Per-source (tool_name, results) pairs, in enabled_sources order.
    """
    tasks = [
        _search_single_source(source, queries, ctx, tool_registry)
        for source in enabled_sources
    ]
    return await asyncio.gather(*tasks)


async def _apply_semantic_relevance_if_enabled(
    ranked: dict[str, dict[str, Any]],
    config: SearchConfig,
) -> dict[str, dict[str, Any]]:
    """Re-rank by model-judged relevance when this search has earned it.

    The pass spends one LLM call per candidate, so it belongs to searches
    that run once for the whole run rather than once per hypothesis; see
    ``SearchConfig.semantic_relevance_enabled`` for why probe retrieval
    opts out. Skipping leaves the pool in its lexical order rather than
    dropping anything, so the caller's budget still selects the same
    number of papers.
    """
    if not config.semantic_relevance_enabled:
        return ranked
    return await apply_semantic_relevance(
        ranked,
        config.research_goal,
        config.model_name,
        config.papers_to_read_count,
    )


async def _merge_and_budget_multi_source(
    source_results: list[tuple[str, dict[str, dict[str, Any]]]],
    enabled_sources: list["SearchSourceConfig"],
    config: SearchConfig,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Merges per-source results and trims the merged set to the budget.

    Optionally dedupes by title (config-driven via
    deduplicate_across_sources) and builds paper_source_map so later phases
    know which source's tool config applies to each paper. A bounded
    semantic relevance pass re-ranks the merged pool (see
    ``relevance.apply_semantic_relevance``) before select_within_budget's
    reserved-slots selection runs on it, so a reserved source's own
    best-by-hybrid-score candidates seat first, not merely its
    best-by-citation ones.
    """
    assert config.workflow is not None
    all_paper_metadata, paper_source_map = merge_search_results(
        source_results,
        deduplicate=config.workflow.deduplicate_across_sources,
    )
    all_paper_metadata = await _apply_semantic_relevance_if_enabled(
        all_paper_metadata, config
    )
    selected_ids = select_within_budget(
        all_paper_metadata,
        paper_source_map,
        enabled_sources,
        config.papers_to_read_count,
    )
    all_paper_metadata = {
        paper_id: all_paper_metadata[paper_id] for paper_id in selected_ids
    }
    paper_source_map = {
        paper_id: paper_source_map[paper_id]
        for paper_id in selected_ids
        if paper_id in paper_source_map
    }
    return all_paper_metadata, paper_source_map


def _campaign_admitted_sources(
    sources: list["SearchSourceConfig"], tool_registry: "ToolRegistry"
) -> list["SearchSourceConfig"]:
    """Drop the sources whose tool the campaign MCP policy refuses.

    The registry is built before the campaign scope is known, so a source
    such as web search stays enabled there. Every call to it is then
    refused by the policy, which is a fixed answer, not a transient one.
    Skipping it here saves the calls and keeps the refusals out of the
    run's error log.

    Args:
        sources: The workflow's enabled search sources.
        tool_registry: Registry used to resolve each source's MCP tool.

    Returns:
        The sources the current scope may search, in their original order.
    """
    admitted = []
    for source in sources:
        tool = tool_registry.get_tool(source.tool)
        if tool is not None and not campaign_serves_tool(tool.mcp_tool_name):
            logger.info(
                "Skipping search source %s: not served under campaign policy",
                source.tool,
            )
            continue
        admitted.append(source)
    return admitted


async def _phase2_collect_papers_multi_source(
    queries: list[str],
    config: SearchConfig,
    ctx: _SearchRunContext,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Phase 2 (multi-source): Collect papers from all sources in parallel."""
    # Multi-source mode guarantees a configured workflow/tool registry; the
    # registry already reconciled source flags with tool flags at load time
    # (ToolRegistry._apply_disabled_tools), so enabled sources are exactly
    # the sources whose tools are live.
    assert config.workflow is not None and config.tool_registry is not None
    enabled_sources = _campaign_admitted_sources(
        config.workflow.get_enabled_search_sources(), config.tool_registry
    )
    logger.info(
        "Phase 2: collecting papers from %s sources", len(enabled_sources)
    )

    source_results = await _search_all_sources(
        enabled_sources, queries, ctx, config.tool_registry
    )

    all_paper_metadata, paper_source_map = await _merge_and_budget_multi_source(
        source_results, enabled_sources, config
    )

    logger.info(
        "Multi-source search complete: %s unique papers from %s sources",
        len(all_paper_metadata),
        len(enabled_sources),
    )

    return all_paper_metadata, paper_source_map


async def _search_all_queries(
    queries: list[str],
    papers_per_query: int,
    ctx: _SearchRunContext,
    config: SearchConfig,
) -> list[dict[str, dict[str, Any]]]:
    """Searches all queries against the single configured source in parallel.

    Unlike multi-source mode, there is only one tool/source involved here so
    no per-source serialization is needed. Every query asks for the same
    budget: this path over-fetches deliberately (see the caller) rather than
    dividing one budget across the queries. Returns each query's results, in
    query order.
    """
    tasks = [
        _search_single_query(query, i + 1, papers_per_query, ctx, config)
        for i, query in enumerate(queries)
    ]
    return await asyncio.gather(*tasks)


async def _combine_and_cap_single_source_results(
    search_results: list[dict[str, dict[str, Any]]],
    config: SearchConfig,
) -> dict[str, dict[str, Any]]:
    """Merges per-query results, dedupes/ranks, and caps to the read count.

    The semantic relevance pass runs before capping (see
    ``relevance.apply_semantic_relevance``), so the papers kept are the
    best by hybrid score, not merely the best by lexical heuristic.
    """
    combined: dict[str, dict[str, Any]] = {}
    for result_data in search_results:
        combined.update(result_data)
    ranked, _ = merge_search_results(
        [(config.search_tool_name, combined)], deduplicate=True
    )
    ranked = await _apply_semantic_relevance_if_enabled(ranked, config)
    return dict(list(ranked.items())[: config.papers_to_read_count])


async def _phase2_collect_papers_single_source(
    queries: list[str],
    config: SearchConfig,
    ctx: _SearchRunContext,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Phase 2 (single-source): Collect papers with legacy distribution."""
    logger.info("Phase 2: collecting papers with %s", config.search_tool_name)

    logger.info(
        "Over-fetching %s papers per query for a %s-paper unique corpus",
        config.papers_to_read_count,
        config.papers_to_read_count,
    )

    # Query expansion commonly returns the same high-ranking publications for
    # several queries. Request the full target from each query, then dedupe,
    # rank, and cap globally so the configured evidence count represents
    # unique sources rather than raw search hits.
    search_results = await _search_all_queries(
        queries, config.papers_to_read_count, ctx, config
    )

    all_paper_metadata = await _combine_and_cap_single_source_results(
        search_results, config
    )
    return all_paper_metadata, {}

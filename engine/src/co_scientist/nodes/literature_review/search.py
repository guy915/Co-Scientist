"""Phase 2: literature review paper collection.

Runs the generated queries against the configured search source(s) and merges
the results. Supports both the multi-source path (several sources searched in
parallel, deduped and provenance-tagged) and the legacy single-source path
(one tool, papers budget distributed across queries).
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.constants import LITERATURE_REVIEW_RECENCY_YEARS
from co_scientist.mcp_client import MCPToolClient
from co_scientist.nodes.literature_review.helpers import (
    SearchConfig,
    extract_source_name,
    merge_search_results,
    normalize_search_response,
)
from co_scientist.state import WorkflowState
from co_scientist.tools.response_parser import parse_mcp_result

if TYPE_CHECKING:
    from co_scientist.config import SearchSourceConfig, ToolConfig, ToolRegistry

logger = logging.getLogger(__name__)


def _build_query_tool_params(
    query: str,
    slug: str,
    run_id: str,
    max_papers: int,
    tool_config: Optional["ToolConfig"],
) -> dict[str, Any]:
    """Build tool-call params for a search query in the tool's own shape.

    canonical_params uses the shared cross-source parameter names;
    tool_config.map_parameters() translates them into a specific tool's own
    argument names/shapes per its YAML config. Falls back to the canonical
    names unmapped when no tool_config is available (the legacy/no-registry
    single-source path).
    """
    canonical_params = {
        "query": query,
        "slug": slug,
        "max_papers": max_papers,
        "recency_years": LITERATURE_REVIEW_RECENCY_YEARS,
        "run_id": run_id,
    }
    if not tool_config:
        return canonical_params
    tool_params = tool_config.map_parameters(canonical_params)
    return {k: v for k, v in tool_params.items() if v is not None}


def _tag_source_name(
    normalized: dict[str, dict[str, Any]],
    src_name: str,
) -> dict[str, dict[str, Any]]:
    """Tag every result with the source that produced it, in place.

    Lets downstream phases (PDF discovery, content fetching) look up the
    right per-source tool config for each paper via paper_source_map.
    """
    for _, meta in normalized.items():
        if isinstance(meta, dict):
            meta["_source_name"] = src_name
    return normalized


async def _search_source_for_query(
    query: str,
    slug: str,
    run_id: str,
    tool_config: "ToolConfig",
    src_name: str,
    papers_per_query: int,
    mcp_client: MCPToolClient,
    errors: list[str] | None,
) -> dict[str, dict[str, Any]]:
    """Search one source for a single query; returns normalized results.

    Scoped to the per-source query loop in `_search_single_source`: a
    failed query is swallowed here (not raised) so other queries/sources
    still complete; the caller aggregates errors to distinguish "zero
    results" from "search broke".
    """
    # Imported locally to avoid a module-level import cycle: node.py owns
    # _describe_exc and imports this module at load time.
    from co_scientist.nodes.literature_review.node import (
        _describe_exc,
    )

    try:
        tool_params = _build_query_tool_params(
            query, slug, run_id, papers_per_query, tool_config
        )
        result = await mcp_client.call_tool(
            tool_config.mcp_tool_name, **tool_params
        )
        result_data = parse_mcp_result(result)
        normalized = normalize_search_response(result_data, tool_config)
        return _tag_source_name(normalized, src_name)

    except Exception as e:
        # A failed query for this source is swallowed here (not raised) so
        # other queries/sources still complete; the caller aggregates
        # errors to distinguish "zero results" from "search broke".
        detail = _describe_exc(e)
        logger.error("Query failed for %s: %s", src_name, detail)
        if errors is not None:
            errors.append(f"{src_name}: {detail}")
        return {}


async def _search_single_source(
    source_config: "SearchSourceConfig",
    queries: list[str],
    slug: str,
    run_id: str,
    tool_registry: "ToolRegistry",
    mcp_client: MCPToolClient,
    errors: list[str] | None = None,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Search a single source with all queries."""
    tool_config = tool_registry.get_tool(source_config.tool)
    if not tool_config:
        logger.warning(
            "Tool config not found for source: %s", source_config.tool
        )
        return (source_config.tool, {})

    mcp_tool_name = tool_config.mcp_tool_name
    src_name = extract_source_name(tool_config)
    papers_per_query = source_config.papers_per_query

    logger.info(
        "Searching %s (%s): %s papers/query",
        src_name,
        mcp_tool_name,
        papers_per_query,
    )

    # Queries run sequentially (not gathered) within a single source, so
    # this source's total time is proportional to its query count; the
    # caller instead parallelizes across sources.
    source_results = {}
    for query in queries:
        normalized = await _search_source_for_query(
            query,
            slug,
            run_id,
            tool_config,
            src_name,
            papers_per_query,
            mcp_client,
            errors,
        )
        source_results.update(normalized)

    logger.info("Source %s: collected %s papers", src_name, len(source_results))
    return (source_config.tool, source_results)


async def _search_single_query(
    query: str,
    index: int,
    papers_count: int,
    slug: str,
    run_id: str,
    search_tool_name: str,
    search_tool_config: Optional["ToolConfig"],
    mcp_client: MCPToolClient,
    errors: list[str] | None = None,
) -> tuple[int, dict[str, dict[str, Any]]]:
    """Search single query (for single-source mode)."""
    # Imported locally to avoid a module-level import cycle: node.py owns
    # _describe_exc and imports this module at load time.
    from co_scientist.nodes.literature_review.node import (
        _describe_exc,
    )

    logger.debug(
        "Searching query %s (%s papers): %s...", index, papers_count, query[:80]
    )

    try:
        tool_params = _build_query_tool_params(
            query, slug, run_id, papers_count, search_tool_config
        )
        result = await mcp_client.call_tool(search_tool_name, **tool_params)
        result_data = parse_mcp_result(result)
        normalized = normalize_search_response(result_data, search_tool_config)

        logger.debug("Query %s: found %s papers", index, len(normalized))
        return (index, normalized)

    except Exception as e:
        # Errors are recorded per-query index (not raised) so
        # asyncio.gather in the caller still completes for the other
        # queries; the aggregated errors list drives the "search broke" vs
        # "search found nothing" distinction in the main node function.
        detail = _describe_exc(e)
        logger.error(
            "Query %s (%s) failed: %s", index, search_tool_name, detail
        )
        if errors is not None:
            errors.append(f"query {index}: {detail}")
        return (index, {})


async def _search_all_sources(
    enabled_sources: list["SearchSourceConfig"],
    queries: list[str],
    slug: str,
    run_id: str,
    tool_registry: "ToolRegistry",
    mcp_client: MCPToolClient,
    errors: list[str] | None,
) -> list[tuple[str, dict[str, dict[str, Any]]]]:
    """Searches all enabled sources in parallel.

    Each _search_single_source call runs its own queries sequentially, so
    overall latency is bounded by the slowest source rather than the sum of
    all sources' query times.

    Args:
        enabled_sources: Search sources enabled by the workflow config.
        queries: Queries to run against every source.
        slug: Corpus slug shared across this run's searches.
        run_id: Current workflow run id.
        tool_registry: Registry used to resolve each source's tool config.
        mcp_client: Client used to call each source's search tool.
        errors: Shared list that failed queries append error strings to.

    Returns:
        Per-source (tool_name, results) pairs, in enabled_sources order.
    """
    tasks = [
        _search_single_source(
            source,
            queries,
            slug,
            run_id,
            tool_registry,
            mcp_client,
            errors,
        )
        for source in enabled_sources
    ]
    return await asyncio.gather(*tasks)


async def _phase2_collect_papers_multi_source(
    queries: list[str],
    slug: str,
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
    errors: list[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Phase 2 (multi-source): Collect papers from all sources in parallel."""
    # Multi-source mode guarantees a configured workflow and tool registry.
    assert config.workflow is not None
    assert config.tool_registry is not None
    enabled_sources = config.workflow.get_enabled_search_sources()
    logger.info(
        "Phase 2: collecting papers from %s sources", len(enabled_sources)
    )

    source_results = await _search_all_sources(
        enabled_sources,
        queries,
        slug,
        state["run_id"],
        config.tool_registry,
        mcp_client,
        errors,
    )

    # Merge results
    # Optionally dedupes by title (config-driven via
    # deduplicate_across_sources) and builds paper_source_map so later
    # phases know which source's tool config applies to each paper.
    all_paper_metadata, paper_source_map = merge_search_results(
        source_results,
        deduplicate=config.workflow.deduplicate_across_sources,
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
    remainder: int,
    slug: str,
    run_id: str,
    config: SearchConfig,
    mcp_client: MCPToolClient,
    errors: list[str] | None,
) -> list[tuple[int, dict[str, dict[str, Any]]]]:
    """Searches all queries against the single configured source in parallel.

    Unlike multi-source mode, there is only one tool/source involved here so
    no per-source serialization is needed.

    Args:
        queries: Queries to run.
        papers_per_query: Base per-query papers budget.
        remainder: Extra papers handed to the first `remainder` queries.
        slug: Corpus slug shared across this run's searches.
        run_id: Current workflow run id.
        config: Search config providing the single-source tool name/config.
        mcp_client: Client used to call the search tool.
        errors: Shared list that failed queries append error strings to.

    Returns:
        Per-query (index, results) pairs, in query order.
    """
    tasks = [
        _search_single_query(
            query,
            i + 1,
            papers_per_query + (1 if i < remainder else 0),
            slug,
            run_id,
            config.search_tool_name,
            config.search_tool_config,
            mcp_client,
            errors,
        )
        for i, query in enumerate(queries)
    ]
    return await asyncio.gather(*tasks)


async def _phase2_collect_papers_single_source(
    queries: list[str],
    slug: str,
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
    errors: list[str] | None = None,
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
        queries,
        config.papers_to_read_count,
        0,
        slug,
        state["run_id"],
        config,
        mcp_client,
        errors,
    )

    combined: dict[str, dict[str, Any]] = {}
    for _, result_data in search_results:
        combined.update(result_data)
    ranked, _ = merge_search_results(
        [(config.search_tool_name, combined)], deduplicate=True
    )
    all_paper_metadata = dict(
        list(ranked.items())[: config.papers_to_read_count]
    )

    return all_paper_metadata, {}

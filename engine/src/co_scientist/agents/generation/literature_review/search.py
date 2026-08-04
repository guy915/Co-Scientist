"""Phase 2: literature review paper collection.

Runs the generated queries against the configured search source(s) and merges
the results. Supports both the multi-source path (several sources searched in
parallel, deduped and provenance-tagged) and the legacy single-source path
(one tool, papers budget distributed across queries).
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.agents.generation.literature_review.helpers import (
    SearchConfig,
    extract_source_name,
    merge_search_results,
    normalize_search_response,
    select_within_budget,
)
from co_scientist.agents.generation.literature_review.outcomes import (
    _describe_exc,
)
from co_scientist.agents.generation.literature_review.query_broadening import (
    broadened_queries,
)

# The transient-failure retry moved to a sibling module; every name is
# re-exported so this module's namespace (which callers and tests patch
# against) keeps resolving.
from co_scientist.agents.generation.literature_review.search_retry import (
    _SEARCH_ATTEMPTS as _SEARCH_ATTEMPTS,
)
from co_scientist.agents.generation.literature_review.search_retry import (
    _call_search_tool as _call_search_tool,
)
from co_scientist.agents.generation.literature_review.search_retry import (
    _search_retry_delay as _search_retry_delay,
)
from co_scientist.constants import LITERATURE_REVIEW_RECENCY_YEARS
from co_scientist.mcp_client import MCPToolClient

if TYPE_CHECKING:
    from co_scientist.config import SearchSourceConfig, ToolConfig, ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SearchRunContext:
    """Run-scoped inputs shared by every Phase 2 search call.

    Attributes:
        slug: Corpus slug shared across this run's searches.
        run_id: Current workflow run id.
        mcp_client: Client used to call each source's search tool.
        errors: Shared list that failed queries append error strings to.
    """

    slug: str
    run_id: str
    mcp_client: MCPToolClient
    errors: list[str] | None = None


@dataclass(frozen=True)
class _QueryTarget:
    """The one search tool a query runs against, and how to label it.

    Both Phase 2 paths search a single tool per call and differ only in what
    that tool is and how a failure against it is named, so bundling the
    difference here is what lets them share one search body.

    Attributes:
        tool_name: MCP tool name to invoke.
        tool_config: Tool config used to map parameters and normalize the
            response, or None on the no-registry fallback path.
        label: Names this target in logs and in the ctx.errors entry a failed
            search appends: the source name in multi-source mode, the query
            index where the single-source path has nothing else to go on.
        max_papers: Papers to request from this call.
    """

    tool_name: str
    tool_config: Optional["ToolConfig"]
    label: str
    max_papers: int


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


async def _search_target_for_query(
    query: str,
    ctx: _SearchRunContext,
    target: _QueryTarget,
) -> dict[str, dict[str, Any]]:
    """Search one target for a single query; returns normalized results.

    The shared body of both Phase 2 paths. A failed query is swallowed here
    (not raised) so other queries and sources still complete; the caller
    aggregates ctx.errors to distinguish "zero results" from "search broke".

    A query that comes back empty is retried in progressively broader form
    (see ``query_broadening``). Back ends AND every term, so an over-specific
    query returns nothing and is indistinguishable downstream from a topic
    with no literature -- which is how runs ended up assessing their claims
    against a pool that never covered them. Broadening stops at the first
    form that returns anything; an errored query is not broadened, since the
    query was not what failed.
    """
    for attempt_query in broadened_queries(query):
        normalized = await _attempt_query(attempt_query, ctx, target)
        if normalized is None:
            return {}
        if normalized:
            if attempt_query != query:
                logger.info(
                    "Broadened %s from %r to %r after no results",
                    target.label,
                    query,
                    attempt_query,
                )
            return normalized
    return {}


async def _attempt_query(
    query: str,
    ctx: _SearchRunContext,
    target: _QueryTarget,
) -> dict[str, dict[str, Any]] | None:
    """Run one query against one target, once.

    Returns:
        The normalized results (possibly empty), or None when the search
        itself failed -- which the caller must not treat as "no results",
        since retrying a broader form would fail the same way.
    """
    try:
        tool_params = _build_query_tool_params(
            query, ctx.slug, ctx.run_id, target.max_papers, target.tool_config
        )
        result_data = await _call_search_tool(
            ctx.mcp_client,
            target.tool_name,
            tool_params,
        )
        return normalize_search_response(result_data, target.tool_config)
    except Exception as e:
        # A failed query is swallowed here (not raised) so the other queries
        # and sources still complete; the caller aggregates errors to
        # distinguish "zero results" from "search broke".
        detail = _describe_exc(e)
        logger.error("Search failed for %s: %s", target.label, detail)
        if ctx.errors is not None:
            ctx.errors.append(f"{target.label}: {detail}")
        return None


async def _search_source_for_query(
    query: str,
    ctx: _SearchRunContext,
    tool_config: "ToolConfig",
    src_name: str,
    papers_per_query: int,
) -> dict[str, dict[str, Any]]:
    """Search one multi-source source for a query, tagging its results.

    Scoped to the per-source query loop in `_run_single_source_queries`.
    """
    target = _QueryTarget(
        tool_name=tool_config.mcp_tool_name,
        tool_config=tool_config,
        label=src_name,
        max_papers=papers_per_query,
    )
    normalized = await _search_target_for_query(query, ctx, target)
    return _tag_source_name(normalized, src_name)


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


async def _search_single_query(
    query: str,
    index: int,
    papers_count: int,
    ctx: _SearchRunContext,
    config: SearchConfig,
) -> tuple[int, dict[str, dict[str, Any]]]:
    """Search single query (for single-source mode).

    Runs the same broadening ladder as the multi-source path: nothing about
    an over-constrained query is multi-source-specific, and a lone source has
    no sibling to make up for what it misses. The shipped single-source
    configs (``examples/arxiv_only.yaml``, ``examples/google_scholar.yaml``)
    put every query here.

    Errors are recorded per-query index (not raised) so asyncio.gather in the
    caller still completes for the other queries; the aggregated errors list
    drives the "search broke" vs "search found nothing" distinction in the
    main node function.
    """
    logger.debug(
        "Searching query %s (%s papers): %s...", index, papers_count, query[:80]
    )
    target = _QueryTarget(
        tool_name=config.search_tool_name,
        tool_config=config.search_tool_config,
        label=f"query {index}",
        max_papers=papers_count,
    )

    normalized = await _search_target_for_query(query, ctx, target)

    logger.debug("Query %s: found %s papers", index, len(normalized))
    return (index, normalized)


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


def _merge_and_budget_multi_source(
    source_results: list[tuple[str, dict[str, dict[str, Any]]]],
    enabled_sources: list["SearchSourceConfig"],
    config: SearchConfig,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Merges per-source results and trims the merged set to the budget.

    Optionally dedupes by title (config-driven via
    deduplicate_across_sources) and builds paper_source_map so later phases
    know which source's tool config applies to each paper, then applies
    select_within_budget's reserved-slots selection.
    """
    assert config.workflow is not None
    all_paper_metadata, paper_source_map = merge_search_results(
        source_results,
        deduplicate=config.workflow.deduplicate_across_sources,
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
    enabled_sources = config.workflow.get_enabled_search_sources()
    logger.info(
        "Phase 2: collecting papers from %s sources", len(enabled_sources)
    )

    source_results = await _search_all_sources(
        enabled_sources, queries, ctx, config.tool_registry
    )

    all_paper_metadata, paper_source_map = _merge_and_budget_multi_source(
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
    remainder: int,
    ctx: _SearchRunContext,
    config: SearchConfig,
) -> list[tuple[int, dict[str, dict[str, Any]]]]:
    """Searches all queries against the single configured source in parallel.

    Unlike multi-source mode, there is only one tool/source involved here so
    no per-source serialization is needed. The first `remainder` queries get
    one extra paper on top of papers_per_query. Returns per-query (index,
    results) pairs, in query order.
    """
    tasks = [
        _search_single_query(
            query,
            i + 1,
            papers_per_query + (1 if i < remainder else 0),
            ctx,
            config,
        )
        for i, query in enumerate(queries)
    ]
    return await asyncio.gather(*tasks)


def _combine_and_cap_single_source_results(
    search_results: list[tuple[int, dict[str, dict[str, Any]]]],
    config: SearchConfig,
) -> dict[str, dict[str, Any]]:
    """Merges per-query results, dedupes/ranks, and caps to the read count."""
    combined: dict[str, dict[str, Any]] = {}
    for _, result_data in search_results:
        combined.update(result_data)
    ranked, _ = merge_search_results(
        [(config.search_tool_name, combined)], deduplicate=True
    )
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
        queries, config.papers_to_read_count, 0, ctx, config
    )

    all_paper_metadata = _combine_and_cap_single_source_results(
        search_results, config
    )
    return all_paper_metadata, {}

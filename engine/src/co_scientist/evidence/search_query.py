"""Phase 2: running one literature query against one search target.

The shared body of both Phase 2 paths -- build the target tool's parameters,
call it through the transient-failure retry, normalize the response, tag its
provenance, and broaden a query that comes back empty. Both paths enter
through this module (``_search_source_for_query`` per source,
``_search_single_query`` per query), which is what keeps the broadening
ladder on both of them.

The queries themselves are generated in Phase 1 (``queries.py``); fanning
these calls out across sources and queries, and reducing what they return to
the run's evidence budget, is ``search.py``, which re-exports every name here
so the module namespace callers and tests patch against keeps resolving.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.constants import LITERATURE_REVIEW_RECENCY_YEARS
from co_scientist.evidence.errors import (
    describe_exception,
)
from co_scientist.evidence.query_broadening import (
    broadened_queries,
)
from co_scientist.evidence.search_retry import (
    _call_search_tool,
)
from co_scientist.evidence.search_support import (
    SearchConfig,
    normalize_search_response,
)
from co_scientist.mcp_client import MCPToolClient

if TYPE_CHECKING:
    from co_scientist.config import ToolConfig

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
        detail = describe_exception(e)
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


async def _search_single_query(
    query: str,
    index: int,
    papers_count: int,
    ctx: _SearchRunContext,
    config: SearchConfig,
) -> dict[str, dict[str, Any]]:
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
    return normalized

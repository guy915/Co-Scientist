"""Phase 2: running one literature query against one search target.

The shared body of both Phase 2 paths -- build the target tool's parameters,
call it through the transient-failure retry, normalize the response, tag its
provenance, and broaden a query that comes back empty. Both paths enter
through this module (``_search_source_for_query`` per source,
``_search_single_query`` per query), which is what keeps the broadening
ladder on both of them.

The queries themselves are generated in Phase 1 (``queries.py``); fanning
these calls out across sources and queries, and reducing what they return to
the run's evidence budget, is ``search.py``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.tools import ToolException

from co_scientist.backoff import jittered_backoff_seconds
from co_scientist.constants import LITERATURE_REVIEW_RECENCY_YEARS
from co_scientist.evidence.retrieval_support import (
    describe_exception,
)
from co_scientist.evidence.search_support import (
    SearchConfig,
    normalize_search_response,
)
from co_scientist.mcp_client import CampaignToolUnavailableError, MCPToolClient
from co_scientist.tools.response_parser import parse_mcp_result

# Two terms still name a topic ("mifepristone glioblastoma"); one term is a
# subject heading that would swamp the budget with unrelated papers.
_MIN_QUERY_TERMS = 2


def broadened_queries(query: str) -> list[str]:
    """Return progressively broader forms of ``query``, narrowest first.

    Halving rather than dropping one term at a time keeps the ladder to at
    most two extra calls on the run's serial spine while still reaching the
    productive range: the nine-term query above returns nothing until its
    fifth term is dropped, and one-at-a-time would have spent five calls
    discovering that.

    Terms are dropped from the end because query formulation appends
    qualifiers -- mechanism and setting come first, hedges and endpoints
    last -- so a prefix stays on topic while a suffix is what over-constrains
    it.

    Args:
        query: The keyword query as formulated, terms separated by spaces.

    Returns:
        The query followed by any broader forms, each strictly shorter than
        the last. A query already at or below the floor yields just itself.
    """
    terms = query.split()
    if len(terms) <= _MIN_QUERY_TERMS:
        return [query]

    ladder = [query]
    for count in ((len(terms) + 1) // 2, _MIN_QUERY_TERMS):
        broader = " ".join(terms[:count])
        if count < len(terms) and broader not in ladder:
            ladder.append(broader)
    return ladder


if TYPE_CHECKING:
    from co_scientist.config import ToolConfig

logger = logging.getLogger(__name__)


# FastMCP's tool manager formats an unmasked tool-execution exception as
# "Error calling tool '<name>': <detail>" and returns that text as the
# tool's own result content (fastmcp.tools.tool_manager.ToolManager.
# call_tool) rather than raising a transport error -- so it arrives here as
# an ordinary (non-JSON) string result. Retrying it re-asks the same
# rejected query and fails identically every time (this is what produced
# the "JSONDecodeError: Expecting value" warnings for a wildcard query
# OpenAlex's API had already refused with HTTP 400): the tool answered, it
# just answered with an error, so this is classified as permanent for the
# query rather than transient.
_TOOL_ERROR_ENVELOPE_RE = re.compile(r"^Error calling tool '[^']*':")

# A search source fails transiently for reasons that take seconds to clear --
# NCBI throttling a burst of concurrent queries, an MCP session reconnecting,
# an upstream index returning a status page. One retry a quarter-second later
# is not a budget against any of them; it re-asks while the cause is still in
# force and then drops the whole query, which is how a run reached its claim
# gate with a pool that never covered the topic.
#
# The waits are jittered on the shared schedule (see
# backoff.jittered_backoff_seconds); the numbers below are this path's own,
# sized for causes that clear in well under a second.
_SEARCH_ATTEMPTS = 4
_SEARCH_RETRY_BASE_DELAY_SECONDS = 0.5
_SEARCH_RETRY_MAX_DELAY_SECONDS = 8.0


def _is_tool_reported_error(payload: Any) -> bool:
    """True when payload is the MCP server's own tool-execution error text.

    Args:
        payload: A raw (pre-decode) tool call result.

    Returns:
        Whether payload is a string carrying the "Error calling tool
        '<name>': ..." envelope (see module docstring).
    """
    return isinstance(payload, str) and bool(
        _TOOL_ERROR_ENVELOPE_RE.match(payload.strip())
    )


def _decode_search_result(result: Any) -> Any:
    """Preserve reported source errors instead of manufacturing zero hits."""
    if _is_tool_reported_error(result):
        raise ToolException(result)
    return parse_mcp_result(result)


def _search_retry_delay(attempt: int) -> float:
    """Jittered exponential backoff before search attempt ``attempt`` + 1.

    Capped, unlike the LLM retry: the whole point of retrying here is to
    outlast a cause measured in seconds, so a wait that kept doubling would
    cost the run more than the source it is waiting on.
    """
    return jittered_backoff_seconds(
        attempt,
        base_seconds=_SEARCH_RETRY_BASE_DELAY_SECONDS,
        max_seconds=_SEARCH_RETRY_MAX_DELAY_SECONDS,
    )


async def _call_search_tool(
    mcp_client: MCPToolClient,
    tool_name: str,
    tool_params: dict[str, Any],
) -> Any:
    """Call and decode one search result with a bounded transient retry.

    MCP transports can return a non-JSON status body while a server session
    is reconnecting or an upstream index is rate-limiting. Retrying the
    complete tool invocation avoids silently discarding an otherwise healthy
    evidence source. The final exception remains visible to the caller so
    existing per-source diagnostics still record hard failures.

    Args:
        mcp_client: Initialized MCP client containing the search tool.
        tool_name: MCP search tool name.
        tool_params: Source-specific invocation arguments.

    Returns:
        Decoded search response.

    Raises:
        Exception: The final call or decoding failure after retries.
    """
    for attempt in range(1, _SEARCH_ATTEMPTS + 1):
        try:
            result = await mcp_client.call_tool(tool_name, **tool_params)
            return _decode_search_result(result)
        except (ToolException, CampaignToolUnavailableError):
            # A tool-reported error or a policy refusal answers the same way
            # on every attempt, so retrying only repeats it.
            raise
        except Exception as exc:
            if attempt == _SEARCH_ATTEMPTS:
                raise
            delay = _search_retry_delay(attempt)
            logger.warning(
                "Search call to %s failed transiently (%s); retrying in "
                "%.1fs (attempt %s of %s)",
                tool_name,
                describe_exception(exc),
                delay,
                attempt,
                _SEARCH_ATTEMPTS,
            )
            await asyncio.sleep(delay)

    raise AssertionError("search retry loop exited without a result")


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
    tool_config: ToolConfig | None
    label: str
    max_papers: int


def _build_query_tool_params(
    query: str,
    slug: str,
    run_id: str,
    max_papers: int,
    tool_config: ToolConfig | None,
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
    tool_config: ToolConfig,
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

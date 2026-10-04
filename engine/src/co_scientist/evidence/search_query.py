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

# One-term broadening swamps the evidence budget with unrelated papers.
_MIN_QUERY_TERMS = 2


def broadened_queries(query: str) -> list[str]:
    """Retain mechanism/setting prefixes; trailing qualifiers overconstrain.
    Halving bounds calls while keeping the topic anchor."""
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


# FastMCP returns tool-execution exceptions as ordinary text results;
# re-asking a rejected query will not fix that permanent failure.
_TOOL_ERROR_ENVELOPE_RE = re.compile(r"^Error calling tool '[^']*':")


_SEARCH_ATTEMPTS = 4
_SEARCH_RETRY_BASE_DELAY_SECONDS = 0.5
_SEARCH_RETRY_MAX_DELAY_SECONDS = 8.0


def _is_tool_reported_error(payload: Any) -> bool:
    return isinstance(payload, str) and bool(
        _TOOL_ERROR_ENVELOPE_RE.match(payload.strip())
    )


def _decode_search_result(result: Any) -> Any:
    if _is_tool_reported_error(result):
        raise ToolException(result)
    return parse_mcp_result(result)


def _search_retry_delay(attempt: int) -> float:
    """Transient throttling/session failures need time to clear, but unbounded
    backoff would cost more than the source it waits on."""
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
    """MCP reconnections and source throttling can return non-JSON bodies;
    retry while retaining the final error for diagnostics."""
    for attempt in range(1, _SEARCH_ATTEMPTS + 1):
        try:
            result = await mcp_client.call_tool(tool_name, **tool_params)
            return _decode_search_result(result)
        # Tool errors and policy refusals repeat identically; do not retry them.
        except (ToolException, CampaignToolUnavailableError):
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
    slug: str
    run_id: str
    mcp_client: MCPToolClient
    errors: list[str] | None = None


@dataclass(frozen=True)
class _QueryTarget:
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
    for _, meta in normalized.items():
        if isinstance(meta, dict):
            meta["_source_name"] = src_name
    return normalized


async def _search_target_for_query(
    query: str,
    ctx: _SearchRunContext,
    target: _QueryTarget,
) -> dict[str, dict[str, Any]]:
    """Empty results may reflect an overconstrained query; broaden until a hit.
    Failed retrieval is not an empty result and must not trigger broadening."""
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
    """One query failure must not abort siblings; record it so broken
    retrieval stays distinguishable from zero hits."""
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

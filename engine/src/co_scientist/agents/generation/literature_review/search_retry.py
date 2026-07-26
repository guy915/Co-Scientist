"""Transient-failure retry around a single literature search tool call.

Split from ``search.py``, which re-exports every name here so the module
namespace callers and tests patch against keeps resolving.
"""

import asyncio
import logging
import random
from typing import Any

from co_scientist.agents.generation.literature_review.outcomes import (
    _describe_exc,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import parse_mcp_result

logger = logging.getLogger(__name__)

# A search source fails transiently for reasons that take seconds to clear --
# NCBI throttling a burst of concurrent queries, an MCP session reconnecting,
# an upstream index returning a status page. One retry a quarter-second later
# is not a budget against any of them; it re-asks while the cause is still in
# force and then drops the whole query, which is how a run reached its claim
# gate with a pool that never covered the topic.
#
# Jittered, like the throttled-LLM backoff: a run fires many queries at once,
# and a fixed schedule releases every throttled caller simultaneously,
# reproducing the burst that caused the throttling.
_SEARCH_ATTEMPTS = 4
_SEARCH_RETRY_BASE_DELAY_SECONDS = 0.5
_SEARCH_RETRY_MAX_DELAY_SECONDS = 8.0


def _search_retry_delay(attempt: int) -> float:
    """Jittered exponential backoff before search attempt ``attempt`` + 1."""
    ceiling = min(
        _SEARCH_RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1),
        _SEARCH_RETRY_MAX_DELAY_SECONDS,
    )
    return random.uniform(ceiling / 2, ceiling)


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
            return parse_mcp_result(result)
        except Exception as exc:
            if attempt == _SEARCH_ATTEMPTS:
                raise
            delay = _search_retry_delay(attempt)
            logger.warning(
                "Search call to %s failed transiently (%s); retrying in "
                "%.1fs (attempt %s of %s)",
                tool_name,
                _describe_exc(exc),
                delay,
                attempt,
                _SEARCH_ATTEMPTS,
            )
            await asyncio.sleep(delay)

    raise AssertionError("search retry loop exited without a result")

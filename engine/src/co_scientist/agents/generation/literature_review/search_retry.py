"""Transient-failure retry around a single literature search tool call.

Split from ``search.py``, which re-exports every name here so the module
namespace callers and tests patch against keeps resolving.
"""

import asyncio
import logging
import re
from typing import Any

from co_scientist.agents.generation.literature_review.outcomes import (
    _describe_exc,
)
from co_scientist.backoff import jittered_backoff_seconds
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import parse_mcp_result

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
            if _is_tool_reported_error(result):
                logger.warning(
                    "Search call to %s failed permanently (tool-reported "
                    "error, not retrying): %s",
                    tool_name,
                    result,
                )
                return {}
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

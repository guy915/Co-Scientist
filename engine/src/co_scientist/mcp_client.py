"""MCP (Model Context Protocol) client for interacting with MCP servers.

This module provides utilities for connecting to MCP servers and accessing
their tools for use with LiteLLM agents.

Supports both single-server (legacy) and multi-server configurations.

This module keeps the availability probes (``check_mcp_available`` and
friends — callers such as ``generator/availability.py`` and tests resolve
them here) and the process-wide client singleton. The ``MCPToolClient``
class and its per-tool-call timeout helpers live in ``mcp_client_session``;
the connection helpers and availability-probe helpers live in
``mcp_client_helpers`` and ``mcp_client_availability``. All are re-exported
here so callers keep importing from ``co_scientist.mcp_client``.
"""

import logging
from typing import TYPE_CHECKING, Optional

from co_scientist.mcp_client_availability import (
    _has_any_tools,
    _log_mcp_test_start,
    _log_mcp_unavailable,
    _probe_literature_source_availability,
    _resolve_availability_check_tool,
)
from co_scientist.mcp_client_availability import (
    _interpret_availability_result as _interpret_availability_result,
)
from co_scientist.mcp_client_availability import (
    _short_circuit_availability as _short_circuit_availability,
)
from co_scientist.mcp_client_helpers import (
    DEFAULT_MCP_SERVER_URL as DEFAULT_MCP_SERVER_URL,
)
from co_scientist.mcp_client_helpers import (
    _ensure_tools_initialized as _ensure_tools_initialized,
)
from co_scientist.mcp_client_helpers import (
    _filter_tools_by_whitelist as _filter_tools_by_whitelist,
)
from co_scientist.mcp_client_helpers import (
    _is_wrapped_text_result as _is_wrapped_text_result,
)
from co_scientist.mcp_client_helpers import (
    _resolve_server_configs as _resolve_server_configs,
)
from co_scientist.mcp_client_helpers import (
    _resolve_server_url,
)
from co_scientist.mcp_client_helpers import (
    _truncate_for_log as _truncate_for_log,
)
from co_scientist.mcp_client_helpers import (
    _unwrap_tool_result as _unwrap_tool_result,
)
from co_scientist.mcp_client_session import (
    DEFAULT_MCP_TOOL_TIMEOUT_SECONDS as DEFAULT_MCP_TOOL_TIMEOUT_SECONDS,
)
from co_scientist.mcp_client_session import (
    MCP_TOOL_TIMEOUT_ENV as MCP_TOOL_TIMEOUT_ENV,
)
from co_scientist.mcp_client_session import (
    MCPToolClient as MCPToolClient,
)
from co_scientist.mcp_client_session import (
    _ainvoke_within_timeout as _ainvoke_within_timeout,
)
from co_scientist.mcp_client_session import (
    mcp_tool_timeout_seconds as mcp_tool_timeout_seconds,
)

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


# Process-wide singleton, shared across nodes so they reuse one MCP session
# instead of each opening a fresh connection to every configured server.
# Global client instance
_global_client: MCPToolClient | None = None


async def _probe_literature_source(
    server_url: str | None,
    tool_registry: Optional["ToolRegistry"],
    check_tool_name: str | None,
    skip_availability_check: bool,
) -> bool:
    """Probes literature source availability via a throwaway MCP client.

    Args:
        server_url: URL of the MCP server (legacy).
        tool_registry: Optional ToolRegistry for config-driven tool lookup.
        check_tool_name: Availability-check tool name, or None to skip.
        skip_availability_check: Whether the server responding is enough,
            without a tool-specific check.

    Returns:
        True if the literature source is available, else False.
    """
    try:
        # One throwaway client serves both probes below. Deliberately not
        # the cached global client: a down server must not poison state.
        mcp_client = MCPToolClient(
            server_url=server_url, tool_registry=tool_registry
        )
        await mcp_client.initialize()
        return await _probe_literature_source_availability(
            mcp_client, check_tool_name, skip_availability_check
        )
    except Exception as e:
        # Deliberately broad: any MCP hiccup (connection refused, timeout,
        # malformed tool schema) degrades to "unavailable" here rather than
        # raising, so callers (e.g. HypothesisGenerator._prepare_generation)
        # can fall back to LLM-only mode instead of aborting the run.
        logger.warning(
            "error checking literature source availability: %s: %s",
            type(e).__name__,
            e,
        )
        logger.debug("full traceback: %s", e, exc_info=True)
        return False


async def check_literature_source_available(
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
) -> bool:
    """Check if the literature source is available via MCP server.

    Queries the configured availability check tool (e.g.,
    check_pubmed_available)
    to verify the literature source is accessible.

    If no availability check tool is configured (availability_check: null in
    YAML),
    assumes the source is available as long as MCP server responds.

    Args:
        server_url: URL of the MCP server (legacy). If None, reads from
            MCP_SERVER_URL
        tool_registry: Optional ToolRegistry for config-driven tool lookup

    Returns:
        True if literature source is available via MCP server, False otherwise
    """
    check_tool_name, skip_availability_check = _resolve_availability_check_tool(
        tool_registry
    )

    if server_url is None and tool_registry is None:
        server_url = _resolve_server_url()

    return await _probe_literature_source(
        server_url, tool_registry, check_tool_name, skip_availability_check
    )


async def check_tool_available(
    tool_name: str,
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
) -> bool:
    """Check whether the MCP server advertises a specific tool.

    Some tools are registered conditionally by the server (``search_web``
    only appears when a provider API key is configured), so asking the
    server what it exposes is the only honest way to tell whether a
    capability is usable.

    Args:
        tool_name: MCP tool name to look for, e.g. "search_web".
        server_url: URL of the MCP server (legacy).
        tool_registry: Optional ToolRegistry for multi-server configs.

    Returns:
        True if the server responded and lists that tool, False otherwise.
    """
    if server_url is None and tool_registry is None:
        server_url = _resolve_server_url()

    try:
        test_client = MCPToolClient(
            server_url=server_url, tool_registry=tool_registry
        )
        await test_client.initialize()
        return test_client.has_tool(tool_name)
    except Exception as e:
        # Broad catch to False, matching the other probes here: this result
        # only gates whether a capability is offered, and an unreachable
        # server must degrade to "not available" rather than raise.
        logger.debug("tool availability check failed for %s: %s", tool_name, e)
        return False


async def check_mcp_available(
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
) -> bool:
    """Check if MCP server is available and responding.

    Args:
        server_url: URL of the MCP server (legacy)
        tool_registry: Optional ToolRegistry for multi-server configs

    Returns:
        True if MCP server is available and responding, False otherwise
    """
    if server_url is None and tool_registry is None:
        server_url = _resolve_server_url()

    try:
        _log_mcp_test_start(tool_registry, server_url)

        test_client = MCPToolClient(
            server_url=server_url, tool_registry=tool_registry
        )
        await test_client.initialize()

        # Check if we got any tools
        tools_dict = test_client._tools_dict
        return _has_any_tools(tools_dict)

    except Exception as e:
        # Same broad-catch-to-False fallback as
        # check_literature_source_available: an unreachable server here must
        # not raise, since this result gates whether the literature_review
        # node is added to the graph at all (see generator.py).
        _log_mcp_unavailable(tool_registry, server_url, e)
        return False


async def get_mcp_client(
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
    force_new: bool = False,
) -> MCPToolClient:
    """Get or create the global MCP client instance.

    Args:
        server_url: URL of the MCP server (legacy)
        tool_registry: Optional ToolRegistry for config-driven setup
        force_new: If True, create a new client even if one exists

    Returns:
        Initialized MCPToolClient instance
    """
    global _global_client

    # force_new bypasses the cache (e.g. tests, or reconfiguring server_url
    # / tool_registry mid-process); otherwise the first caller's arguments
    # win and later callers just get that same client re-initialized below.
    if _global_client is None or force_new:
        _global_client = MCPToolClient(
            server_url=server_url, tool_registry=tool_registry
        )

    # Always ensure it's initialized (safe to call multiple times)
    await _global_client.initialize()

    return _global_client


def reset_mcp_client() -> None:
    """Reset the global MCP client (primarily for testing)."""
    global _global_client
    _global_client = None

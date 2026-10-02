"""MCP clients and availability probes for configured literature sources.

Supports single-server and multi-server configurations. Availability probes
and the process-wide client singleton live here; transport and per-tool
timeout handling live in ``session``.
"""

import asyncio
import logging
import threading
import weakref
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.llm import campaign_free_mode
from co_scientist.mcp_client.availability import (
    _call_check_tool,
    _has_any_tools,
    _log_mcp_test_start,
    _log_mcp_unavailable,
    _probe_literature_source_availability,
    _resolve_availability_check_tool,
)
from co_scientist.mcp_client.helpers import (
    DEFAULT_MCP_SERVER_URL as DEFAULT_MCP_SERVER_URL,
)
from co_scientist.mcp_client.helpers import (
    _resolve_server_configs as _resolve_server_configs,
)
from co_scientist.mcp_client.helpers import (
    _resolve_server_url,
)
from co_scientist.mcp_client.session import (
    DEFAULT_MCP_TOOL_TIMEOUT_SECONDS as DEFAULT_MCP_TOOL_TIMEOUT_SECONDS,
)
from co_scientist.mcp_client.session import (
    MCP_TOOL_TIMEOUT_ENV as MCP_TOOL_TIMEOUT_ENV,
)
from co_scientist.mcp_client.session import (
    MCPToolClient as MCPToolClient,
)
from co_scientist.mcp_client.session import (
    mcp_tool_timeout_seconds as mcp_tool_timeout_seconds,
)

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


# MCP clients own asyncio locks and SDK sessions. Durable worker cohorts use
# separate event loops, so each loop gets an independent config/policy cache.
# Weak keys release worker clients (and their captured headers) with the loop.
_global_clients: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[tuple[Any, bool], MCPToolClient]
] = weakref.WeakKeyDictionary()
_global_clients_lock = threading.Lock()


def _freeze_config(value: Any) -> Any:
    """Return a hashable representation of resolved MCP configuration."""
    if isinstance(value, dict):
        return tuple(
            sorted((key, _freeze_config(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_config(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_config(item) for item in value))
    try:
        hash(value)
    except TypeError:
        return (type(value), id(value))
    return value


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
        # raising, so callers (e.g. HypothesisGenerator.prepare_task_state)
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


# The MCP server's own verdict on whether a web search would reach a
# provider, and the tool it gates. Older server images expose only the
# second: the api and mcp services deploy separately, so the probe has to
# work against an image that predates the check.
WEB_SEARCH_CHECK_TOOL = "check_web_search_available"
WEB_SEARCH_TOOL = "search_web"


async def check_web_search_available(
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
) -> bool:
    """Check whether a web search issued now would reach a provider.

    Presence of ``search_web`` is not the same question. The server
    registers that tool when a provider key is *set*, which stays true
    after the provider starts refusing the key -- and since a refused
    search degrades to an empty result set, the connector then reads as
    healthy while every run gets nothing back. Ask the server instead,
    falling back to presence only against an image too old to answer.

    Args:
        server_url: URL of the MCP server (legacy).
        tool_registry: Optional ToolRegistry for multi-server configs.

    Returns:
        True if a web search would reach a provider, False otherwise --
        including when the server is unreachable.
    """
    if server_url is None and tool_registry is None:
        server_url = _resolve_server_url()

    try:
        probe_client = MCPToolClient(
            server_url=server_url, tool_registry=tool_registry
        )
        await probe_client.initialize()
        tools, _ = probe_client.get_tools()
        if WEB_SEARCH_CHECK_TOOL in tools:
            return await _call_check_tool(
                probe_client, WEB_SEARCH_CHECK_TOOL, tools
            )
        return WEB_SEARCH_TOOL in tools
    except Exception as e:
        # Broad catch to False, matching the probes around it: an
        # unreachable server means the capability is not usable now.
        logger.debug("web search availability check failed: %s", e)
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
    configs = _resolve_server_configs(tool_registry, None, server_url)
    key = (_freeze_config(configs), campaign_free_mode())
    loop = asyncio.get_running_loop()
    with _global_clients_lock:
        for cached_loop in list(_global_clients):
            if cached_loop.is_closed():
                del _global_clients[cached_loop]
        loop_clients = _global_clients.setdefault(loop, {})
        if force_new or key not in loop_clients:
            loop_clients[key] = MCPToolClient(
                server_url=server_url, tool_registry=tool_registry
            )

    # Always ensure it's initialized (safe to call multiple times)
    client = loop_clients[key]
    await client.initialize()

    return client


def reset_mcp_client() -> None:
    """Reset the global MCP client (primarily for testing)."""
    with _global_clients_lock:
        _global_clients.clear()

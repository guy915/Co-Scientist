"""MCP (Model Context Protocol) client for interacting with MCP servers.

This module provides utilities for connecting to MCP servers and accessing
their tools for use with LiteLLM agents.

Supports both single-server (legacy) and multi-server configurations.

The connection helpers and availability-probe helpers live in
``mcp_client_helpers`` and ``mcp_client_availability`` respectively and are
re-exported here so callers keep importing from ``co_scientist.mcp_client``.
"""

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Optional, cast

from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection

from co_scientist.exceptions import MCPToolTimeoutError
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
    _ensure_tools_initialized,
    _filter_tools_by_whitelist,
    _resolve_server_configs,
    _resolve_server_url,
    _truncate_for_log,
    _unwrap_tool_result,
)
from co_scientist.mcp_client_helpers import (
    _is_wrapped_text_result as _is_wrapped_text_result,
)

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)

MCP_TOOL_TIMEOUT_ENV = "COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS"
# Generous next to a search or a full-text fetch, tiny next to forever. The
# failure this bounds is not a slow tool but a dead one: an MCP stream that
# broke mid-call leaves the await pending with nothing to complete it.
DEFAULT_MCP_TOOL_TIMEOUT_SECONDS = 300.0


def mcp_tool_timeout_seconds() -> float | None:
    """Return the per-tool-call wall-clock ceiling, or None when disabled.

    Read from the environment on every call rather than cached, so tests and
    operators can change the ceiling without restarting the process. Mirrors
    ``llm_request.llm_timeout_seconds``.

    Returns:
        The timeout in seconds, or None when it is disabled (a value of zero
        or less) or the configured value is not a number.
    """
    raw = os.environ.get(MCP_TOOL_TIMEOUT_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_MCP_TOOL_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        logger.warning(
            "ignoring non-numeric %s=%r; using default %ss",
            MCP_TOOL_TIMEOUT_ENV,
            raw,
            DEFAULT_MCP_TOOL_TIMEOUT_SECONDS,
        )
        return DEFAULT_MCP_TOOL_TIMEOUT_SECONDS
    return seconds if seconds > 0 else None


async def _ainvoke_within_timeout(
    tool: Any, tool_args: Any, tool_name: str
) -> Any:
    """Invoke one MCP tool under a wall-clock ceiling.

    Args:
        tool: The MCP tool object to invoke.
        tool_args: Arguments to pass to the tool.
        tool_name: Name of the tool, for the error message.

    Returns:
        Whatever the tool returned.

    Raises:
        MCPToolTimeoutError: If the call outlives the configured ceiling.
    """
    timeout = mcp_tool_timeout_seconds()
    if timeout is None:
        return await tool.ainvoke(tool_args)
    try:
        return await asyncio.wait_for(tool.ainvoke(tool_args), timeout=timeout)
    except asyncio.TimeoutError as exc:
        # wait_for has already cancelled the underlying call, so the broken
        # stream is not left holding the task.
        raise MCPToolTimeoutError(
            f"MCP tool '{tool_name}' did not respond within {timeout}s"
        ) from exc


class MCPToolClient:
    """Client for accessing MCP tools from one or more MCP servers.

    Supports both legacy single-server mode and multi-server mode via
    ToolRegistry.
    """

    def __init__(
        self,
        server_url: str | None = None,
        server_configs: dict[str, dict[str, str]] | None = None,
        tool_registry: Optional["ToolRegistry"] = None,
    ):
        """Initialize the MCP client.

        Args:
            server_url: URL of a single MCP server (legacy mode). If None,
                       reads from MCP_SERVER_URL env var, falling back to
                       http://localhost:8888/mcp
            server_configs: Dict of server configs for multi-server mode.
                           Format: {server_id: {"transport": "...",
                           "url": "..."}}
            tool_registry: ToolRegistry instance for config-driven
                          multi-server mode. Takes precedence over
                          server_configs and server_url.

        At least one of server_url, server_configs, or tool_registry must be
        provided
        (or server_url will default from environment).
        """
        self._tool_registry = tool_registry
        self._client: MultiServerMCPClient | None = None
        self._tools_dict: dict[str, Any] | None = None
        self._openai_tools: list[dict[str, Any]] | None = None
        self._initialize_lock = asyncio.Lock()
        self._tool_to_server: dict[str, str] = {}  # maps tool_name -> server_id

        self._server_configs = _resolve_server_configs(
            tool_registry, server_configs, server_url
        )

        # Store for backwards compatibility
        self.server_url = (
            next(iter(self._server_configs.values())).get("url")
            if self._server_configs
            else None
        )

    async def initialize(self) -> None:
        """Initialize the client and fetch available tools from all servers."""
        # Tool indexes, rather than transport construction, define readiness.
        # A concurrent caller must not observe the transport during the await
        # below and mistake that half-initialized state for a usable client.
        if self._tools_dict is not None:
            logger.debug("MCP client already initialized")
            return

        async with self._initialize_lock:
            if self._tools_dict is not None:
                logger.debug("MCP client initialized by concurrent caller")
                return
            if not self._server_configs:
                raise RuntimeError("no server configurations available")

            server_names = list(self._server_configs.keys())
            logger.info(
                "initializing MCP client for %s server(s): %s",
                len(server_names),
                server_names,
            )

            client = MultiServerMCPClient(
                cast(dict[str, Connection], self._server_configs)
            )
            # This round-trips to every configured server. Publish the client
            # only after its tool indexes are ready so all callers see one
            # complete initialization state.
            tools = await client.get_tools()
            self._client = client
            self._index_tools(tools)

            assert self._tools_dict is not None  # set by _index_tools above
            logger.info(
                "MCP client initialized with %s tools: %s",
                len(self._tools_dict),
                list(self._tools_dict.keys()),
            )

    def _index_tools(self, tools: list[Any]) -> None:
        """Populate lookup structures from the tools fetched by initialize().

        Sets self._tools_dict (name -> tool), self._tool_to_server (name ->
        server id, where known via the tool registry), and self._openai_tools
        (the OpenAI-format conversion of `tools`, for LiteLLM).

        Args:
            tools: Tools fetched from self._client.get_tools().
        """
        # Create dict for easy lookup and track which server provides each tool
        self._tools_dict = {}
        self._tool_to_server = {}

        for tool in tools:
            self._tools_dict[tool.name] = tool
            # Infer server from tool metadata if available
            # MultiServerMCPClient prefixes tools with server name in some
            # versions For now, we'll track based on the tool registry if
            # available
            if self._tool_registry:
                tool_config = self._tool_registry.get_tool_by_mcp_name(
                    tool.name
                )
                if tool_config:
                    self._tool_to_server[tool.name] = tool_config.server

        # Convert to OpenAI format for LiteLLM
        self._openai_tools = [convert_to_openai_tool(tool) for tool in tools]

    # Direct-call convenience path used when the caller already knows the
    # tool name/args (e.g. availability checks, literature_review.py) --
    # contrast with execute_tool_call, which unpacks an LLM tool-call object.
    async def call_tool(self, tool_name: str, **kwargs: Any) -> str:
        """Call an MCP tool directly with arguments.

        This is a convenience method for calling tools directly without
        constructing a LiteLLM-style tool call object.

        Args:
            tool_name: Name of the tool to call
            **kwargs: Tool arguments as keyword arguments

        Returns:
            Tool result as a string (often JSON)

        Raises:
            RuntimeError: If client not initialized
            ValueError: If tool not found
        """
        tools_dict = _ensure_tools_initialized(self._tools_dict)

        if tool_name not in tools_dict:
            raise ValueError(
                f"tool '{tool_name}' not found. "
                f"available tools: {list(tools_dict.keys())}"
            )

        logger.debug("calling mcp tool: %s with args: %s", tool_name, kwargs)

        # Raises MCPToolTimeoutError on a dead call rather than returning a
        # sentinel: every caller on this path (the availability probe, each
        # literature source) already catches broadly and degrades, so a stuck
        # tool costs that one source instead of the whole run.
        result = _unwrap_tool_result(
            await _ainvoke_within_timeout(
                tools_dict[tool_name], kwargs, tool_name
            )
        )

        logger.debug(
            "mcp tool result for %s: %s",
            tool_name,
            _truncate_for_log(str(result)),
        )

        return cast(str, result)

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Execute an MCP tool call.

        Args:
            tool_call: Tool call object from LiteLLM with function name
                and arguments

        Returns:
            Dictionary formatted as a tool response message
        """
        # The returned dict's shape (role/name/tool_call_id/content) matches
        # what call_llm_with_tools (llm.py) appends to its message history
        # after invoking the tool_executor callback passed in by the caller
        # (see tools/provider.py's ToolProvider.execute_tool_call, which
        # wraps this method for tool-call-counting).
        if self._tools_dict is None:
            raise RuntimeError(
                "mcp client not initialized. call initialize() first."
            )

        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)

        logger.debug(
            "executing mcp tool: %s with args: %s", tool_name, tool_args
        )

        # Execute using the original MCP tool. Unwrap the content-block
        # list shape exactly like call_tool, so the tool message carries
        # the inner string the provider expects, not a list of dicts.
        #
        # A timeout is reported back to the model as the tool's result rather
        # than raised. This path runs under _execute_tool_calls' asyncio.gather
        # without return_exceptions, so raising would take down every sibling
        # tool call in the same turn and fail the run; telling the model this
        # one tool did not answer lets it proceed on what it does have.
        try:
            result = _unwrap_tool_result(
                await _ainvoke_within_timeout(
                    self._tools_dict[tool_name], tool_args, tool_name
                )
            )
        except MCPToolTimeoutError as exc:
            logger.warning("%s; reporting the timeout to the model", exc)
            result = f"Error: {exc}. No result was returned."

        logger.debug(
            "mcp tool result for %s: %s%s",
            tool_name,
            str(result)[:200],
            "..." if len(str(result)) > 200 else "",
        )

        return {
            "role": "tool",
            "name": tool_name,
            "tool_call_id": tool_call.id,
            "content": result,  # MCP tools return strings (often JSON)
        }

    # Callers (see tools/provider.py's MCPToolProvider.get_tools) pass a
    # workflow's whitelist here so a node's LLM only ever sees the subset of
    # tools that workflow's YAML config authorizes for that phase.
    def get_tools(
        self, whitelist: list[str] | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Get MCP tools, optionally filtered by whitelist.

        Args:
            whitelist: Optional list of tool names to include. If None,
                returns all tools.

        Returns:
            Tuple of (tools_dict, openai_tools) where:
            - tools_dict: Dict mapping tool names to tool objects
            - openai_tools: List of tools in OpenAI format for LiteLLM
        """
        if self._tools_dict is None or self._openai_tools is None:
            raise RuntimeError(
                "MCP client not initialized. Call initialize() first."
            )

        if whitelist is None:
            return self._tools_dict, self._openai_tools

        return _filter_tools_by_whitelist(self._tools_dict, whitelist)

    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool is available."""
        if self._tools_dict is None:
            return False
        return tool_name in self._tools_dict


# Process-wide singleton, shared across nodes so they reuse one MCP session
# instead of each opening a fresh connection to every configured server.
# Global client instance
_global_client: MCPToolClient | None = None


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

    try:
        # One throwaway client serves both the server-availability probe and
        # the tool-name lookup. Deliberately not the cached global client: a
        # down server must not poison global state.
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


# Backwards compatibility alias
# Still the entry point generator.py calls (and tests monkeypatch) for the
# PubMed-specific availability probe, despite the name predating the
# generic multi-source check_literature_source_available it wraps.
async def check_pubmed_available_via_mcp(
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
) -> bool:
    """Deprecated: use check_literature_source_available instead."""
    return await check_literature_source_available(server_url, tool_registry)


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

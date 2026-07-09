"""MCP (Model Context Protocol) client for interacting with MCP servers.

This module provides utilities for connecting to MCP servers and accessing
their tools for use with LiteLLM agents.

Supports both single-server (legacy) and multi-server configurations.
"""
# pylint: disable=inconsistent-quotes

import json
import logging
import os
from typing import Any, Optional, TYPE_CHECKING, cast

from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_MCP_SERVER_URL = "http://localhost:8888/mcp"
"""Fallback MCP server URL when MCP_SERVER_URL is unset."""


def _resolve_server_url() -> str:
    """Return the MCP server URL from the environment or the default."""
    return os.environ.get("MCP_SERVER_URL", DEFAULT_MCP_SERVER_URL)


def _resolve_server_configs(
    tool_registry: Optional["ToolRegistry"],
    server_configs: dict[str, dict[str, str]] | None,
    server_url: str | None,
) -> dict[str, dict[str, str]]:
    """Resolve which MCP server configs MCPToolClient.__init__ should use.

    Precedence: an explicit tool_registry wins, then explicit
    server_configs, then a single legacy server_url (falling back to the
    env var / default).

    Args:
        tool_registry: ToolRegistry instance for config-driven multi-server
            mode, if provided.
        server_configs: Dict of server configs for multi-server mode, if
            provided.
        server_url: URL of a single MCP server (legacy mode), if provided.

    Returns:
        Dict of {server_id: {"transport": ..., "url": ...}}.
    """
    if tool_registry is not None:
        # Use registry-provided server configs
        configs = tool_registry.get_server_configs_for_langchain()
        logger.debug("using %s servers from tool registry", len(configs))
        return configs

    if server_configs is not None:
        logger.debug("using %s provided server configs", len(server_configs))
        return server_configs

    # Legacy single-server mode
    if server_url is None:
        server_url = _resolve_server_url()
    logger.debug("using single server: %s", server_url)
    return {"default": {"transport": "streamable_http", "url": server_url}}


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
        self._tool_to_server: dict[str, str] = {}  # maps tool_name -> server_id

        self._server_configs = _resolve_server_configs(tool_registry,
                                                       server_configs,
                                                       server_url)

        # Store for backwards compatibility
        self.server_url = list(self._server_configs.values())[0].get(
            "url") if self._server_configs else None

    async def initialize(self) -> None:
        """Initialize the client and fetch available tools from all servers."""
        # Idempotent: get_mcp_client() calls this on every lookup, so a
        # second call on an already-connected client is a cheap no-op.
        if self._client is not None:
            logger.debug("MCP client already initialized")
            return

        if not self._server_configs:
            raise RuntimeError("no server configurations available")

        server_names = list(self._server_configs.keys())
        logger.info("initializing MCP client for %s server(s): %s",
                    len(server_names), server_names)

        self._client = MultiServerMCPClient(
            cast(dict[str, Connection], self._server_configs))
        # This round-trips to every configured server. A server that is down
        # or unreachable surfaces as a raised exception here, which
        # check_mcp_available / check_literature_source_available below catch
        # and turn into an availability=False result rather than propagating.
        tools = await self._client.get_tools()

        self._index_tools(tools)

        assert self._tools_dict is not None  # set by _index_tools above
        logger.info("MCP client initialized with %s tools: %s",
                    len(self._tools_dict), list(self._tools_dict.keys()))

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
                    tool.name)
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
        if self._tools_dict is None:
            raise RuntimeError(
                "mcp client not initialized. call initialize() first.")

        if tool_name not in self._tools_dict:
            raise ValueError(
                f"tool '{tool_name}' not found. "
                f"available tools: {list(self._tools_dict.keys())}")

        logger.debug("calling mcp tool: %s with args: %s", tool_name, kwargs)

        result = await self._tools_dict[tool_name].ainvoke(kwargs)

        # Wrap to support earlier/recent langchain versions
        if isinstance(result, list) and len(result) > 0:
            if isinstance(result[0], dict) and "text" in result[0]:
                result = result[0]["text"]

        logger.debug("mcp tool result for %s: %s%s", tool_name,
                     str(result)[:200], "..." if len(str(result)) > 200 else "")

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
                "mcp client not initialized. call initialize() first.")

        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)

        logger.debug("executing mcp tool: %s with args: %s", tool_name,
                     tool_args)

        # Execute using the original MCP tool
        result = await self._tools_dict[tool_name].ainvoke(tool_args)

        logger.debug("mcp tool result for %s: %s%s", tool_name,
                     str(result)[:200], '...' if len(str(result)) > 200 else '')

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
        self,
        whitelist: list[str] | None = None
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
                "MCP client not initialized. Call initialize() first.")

        if whitelist is None:
            return self._tools_dict, self._openai_tools

        # Filter tools by whitelist
        filtered_tools_dict = {
            k: v for k, v in self._tools_dict.items() if k in whitelist
        }
        # Iterates whitelist order (not self._tools_dict order) so the
        # OpenAI-format tool list is presented to the LLM in the order the
        # workflow config declared it, e.g. preferred tools first.
        filtered_openai_tools = [
            convert_to_openai_tool(filtered_tools_dict[k])
            for k in whitelist
            if k in filtered_tools_dict
        ]

        logger.debug("filtered to %s tools: %s", len(filtered_tools_dict),
                     list(filtered_tools_dict.keys()))

        return filtered_tools_dict, filtered_openai_tools

    def get_server_for_tool(self, tool_name: str) -> str | None:
        """Get the server ID that provides a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Server ID or None if unknown
        """
        return self._tool_to_server.get(tool_name)

    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool is available."""
        if self._tools_dict is None:
            return False
        return tool_name in self._tools_dict

    @property
    def available_tools(self) -> list[str]:
        """Get list of available tool names."""
        if self._tools_dict is None:
            return []
        return list(self._tools_dict.keys())


# Process-wide singleton, shared across nodes so they reuse one MCP session
# instead of each opening a fresh connection to every configured server.
# Global client instance
_global_client: MCPToolClient | None = None


def _resolve_availability_check_tool(
    tool_registry: Optional["ToolRegistry"],) -> tuple[str | None, bool]:
    """Determine which MCP tool (if any) to use for an availability probe.

    Args:
        tool_registry: Optional ToolRegistry for config-driven tool lookup.

    Returns:
        A (check_tool_name, skip_availability_check) pair. When
        skip_availability_check is True, the caller should treat the source
        as available once the MCP server itself responds, without invoking
        any tool. check_tool_name defaults to "check_pubmed_available" for
        backwards compatibility when no registry is supplied.
    """
    if tool_registry is None:
        # Default for backwards compat when no registry is supplied.
        return "check_pubmed_available", False

    workflow = tool_registry.get_workflow("literature_review")
    if not workflow:
        return None, False

    if not workflow.availability_check:
        # availability_check is null/None - skip the check
        logger.debug("availability check disabled in config"
                     " (availability_check: null)")
        return None, True

    # Explicit check tool configured.
    tool_config = tool_registry.get_tool(workflow.availability_check)
    check_tool_name = tool_config.mcp_tool_name if tool_config else None
    return check_tool_name, False


def _interpret_availability_result(result: Any, check_tool_name: str) -> bool:
    """Coerce an availability-check tool's raw result to a bool.

    Args:
        result: Raw MCP tool result. The tool contract is a bool or a
            "true"/"false" string; anything else is unexpected.
        check_tool_name: Name of the tool that produced the result, used
            only for the unexpected-shape warning.

    Returns:
        True/False per the tool's answer; False if the shape is unexpected.
    """
    if isinstance(result, bool):
        return result
    if isinstance(result, str):
        return result.lower() == "true"
    logger.warning("unexpected result from %s: %s", check_tool_name, result)
    return False


async def _probe_literature_source_availability(
    mcp_client: "MCPToolClient",
    check_tool_name: str | None,
    skip_availability_check: bool,
) -> bool:
    """Determine availability from an already-initialized MCP client.

    Args:
        mcp_client: An initialized MCPToolClient to query for tools and, if
            needed, to call the availability check tool on.
        check_tool_name: Name of the availability-check tool to call, or
            None if no such tool is configured.
        skip_availability_check: When True, the source is treated as
            available once the MCP server itself responds, without calling
            a tool.

    Returns:
        True if the literature source is available via MCP server, False
        otherwise.
    """
    # Get available tools; an empty tool list means the MCP server is not
    # usable, so the literature source is unavailable.
    all_tools_dict, _ = mcp_client.get_tools()
    if not all_tools_dict:
        logger.warning("MCP server responded but provided no tools,"
                       " literature source unavailable")
        return False

    # If no availability check configured, assume available since MCP is up
    if skip_availability_check:
        logger.info("MCP server available, skipping source-specific"
                    " availability check")
        return True

    # If no check tool configured but we have a registry, assume available
    if check_tool_name is None:
        logger.info("no availability check tool configured,"
                    " assuming source available")
        return True

    logger.debug("checking literature source availability (tool: %s)",
                 check_tool_name)
    logger.debug("available mcp tools: %s", list(all_tools_dict.keys()))

    if check_tool_name not in all_tools_dict:
        logger.warning(
            "availability check tool '%s' not found. available tools: %s",
            check_tool_name, list(all_tools_dict.keys()))
        return False

    logger.debug("%s tool found, executing", check_tool_name)

    # Call tool directly
    result = await mcp_client.call_tool(check_tool_name)

    # Result should be a boolean or "true"/"false" string
    return _interpret_availability_result(result, check_tool_name)


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
    check_tool_name, skip_availability_check = (
        _resolve_availability_check_tool(tool_registry))

    if server_url is None and tool_registry is None:
        server_url = _resolve_server_url()

    try:
        # One throwaway client serves both the server-availability probe and
        # the tool-name lookup. Deliberately not the cached global client: a
        # down server must not poison global state.
        mcp_client = MCPToolClient(server_url=server_url,
                                   tool_registry=tool_registry)
        await mcp_client.initialize()

        return await _probe_literature_source_availability(
            mcp_client, check_tool_name, skip_availability_check)

    except Exception as e:  # pylint: disable=broad-exception-caught
        # Deliberately broad: any MCP hiccup (connection refused, timeout,
        # malformed tool schema) degrades to "unavailable" here rather than
        # raising, so callers (e.g. HypothesisGenerator._prepare_generation)
        # can fall back to LLM-only mode instead of aborting the run.
        logger.warning("error checking literature source availability: %s: %s",
                       type(e).__name__, e)
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
        if tool_registry:
            logger.debug("testing mcp availability for %s server(s)",
                         len(tool_registry.get_enabled_servers()))
        else:
            logger.debug("testing mcp server availability at %s", server_url)

        test_client = MCPToolClient(server_url=server_url,
                                    tool_registry=tool_registry)
        await test_client.initialize()

        # Check if we got any tools
        tools_dict = test_client._tools_dict  # pylint: disable=protected-access
        if tools_dict and len(tools_dict) > 0:
            logger.info("MCP server available with %s tools", len(tools_dict))
            return True
        else:
            logger.warning("MCP server responded but provided no tools")
            return False

    except Exception as e:  # pylint: disable=broad-exception-caught
        # Same broad-catch-to-False fallback as
        # check_literature_source_available: an unreachable server here must
        # not raise, since this result gates whether the literature_review
        # node is added to the graph at all (see generator.py).
        if tool_registry:
            logger.warning("MCP servers unavailable: %s", e)
        else:
            logger.warning("MCP server unavailable at %s", server_url)
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
        _global_client = MCPToolClient(server_url=server_url,
                                       tool_registry=tool_registry)

    # Always ensure it's initialized (safe to call multiple times)
    await _global_client.initialize()

    return _global_client


def reset_mcp_client() -> None:
    """Reset the global MCP client (primarily for testing)."""
    global _global_client
    _global_client = None

"""MCP tool-client session: ``MCPToolClient`` and its timeout ceiling.

Split from ``mcp_client`` to keep that module within size conventions:
this module holds the client class itself plus the per-tool-call timeout
helpers it invokes, while ``mcp_client`` keeps the availability probes and
the process-wide client singleton and re-exports everything defined here.
This module must not import ``mcp_client`` (the probes there instantiate
``MCPToolClient``, so an import back would be a cycle).
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Optional, cast

from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection

from co_scientist.config.env_vars import parse_timeout_env
from co_scientist.exceptions import MCPToolTimeoutError
from co_scientist.mcp_client_helpers import (
    NOT_INITIALIZED_MESSAGE,
    _ensure_tools_initialized,
    _filter_tools_by_whitelist,
    _resolve_server_configs,
    _truncate_for_log,
    _unwrap_tool_result,
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
    return parse_timeout_env(
        MCP_TOOL_TIMEOUT_ENV, DEFAULT_MCP_TOOL_TIMEOUT_SECONDS
    )


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

    @staticmethod
    def _require_tool(tools_dict: dict[str, Any], tool_name: str) -> Any:
        """Return the tool object for tool_name, or raise if not found."""
        if tool_name not in tools_dict:
            raise ValueError(
                f"tool '{tool_name}' not found. "
                f"available tools: {list(tools_dict.keys())}"
            )
        return tools_dict[tool_name]

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
        tool = self._require_tool(tools_dict, tool_name)

        logger.debug("calling mcp tool: %s with args: %s", tool_name, kwargs)

        # Raises MCPToolTimeoutError on a dead call rather than returning a
        # sentinel: every caller on this path (the availability probe, each
        # literature source) already catches broadly and degrades, so a stuck
        # tool costs that one source instead of the whole run.
        result = _unwrap_tool_result(
            await _ainvoke_within_timeout(tool, kwargs, tool_name)
        )

        logger.debug(
            "mcp tool result for %s: %s",
            tool_name,
            _truncate_for_log(str(result)),
        )

        return cast(str, result)

    @staticmethod
    async def _invoke_or_timeout_result(
        tool: Any, tool_args: dict[str, Any], tool_name: str
    ) -> str:
        """Invoke tool_name, reporting a timeout as its result string.

        Unlike call_tool, this runs under _execute_tool_calls' asyncio.gather
        without return_exceptions, so raising would take down every sibling
        tool call in the same turn and fail the run; telling the model this
        one tool did not answer lets it proceed on what it does have.
        """
        try:
            return cast(
                str,
                _unwrap_tool_result(
                    await _ainvoke_within_timeout(tool, tool_args, tool_name)
                ),
            )
        except MCPToolTimeoutError as exc:
            logger.warning("%s; reporting the timeout to the model", exc)
            return f"Error: {exc}. No result was returned."

    def _require_initialized_tools(self) -> dict[str, Any]:
        """Return self._tools_dict, raising if not yet initialized."""
        return _ensure_tools_initialized(self._tools_dict)

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Execute an MCP tool call.

        The returned dict's shape (role/name/tool_call_id/content) matches
        what call_llm_with_tools (llm.py) appends to its message history
        after invoking the tool_executor callback passed in by the caller
        (see tools/provider.py's ToolProvider.execute_tool_call, which wraps
        this method for tool-call-counting). Content is unwrapped from the
        MCP content-block list shape exactly like call_tool.

        Args:
            tool_call: Tool call object from LiteLLM with function name
                and arguments

        Returns:
            Dictionary formatted as a tool response message
        """
        tools_dict = self._require_initialized_tools()
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)

        logger.debug(
            "executing mcp tool: %s with args: %s", tool_name, tool_args
        )
        result = await self._invoke_or_timeout_result(
            tools_dict[tool_name], tool_args, tool_name
        )
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
        tools_dict = _ensure_tools_initialized(self._tools_dict)
        # A separate condition, not a restatement of the one above: both are
        # populated together by _index_tools, so an unset OpenAI-format list
        # is its own half-initialized state, and letting it through would
        # hand callers a None where they expect the LiteLLM tool schemas.
        if self._openai_tools is None:
            raise RuntimeError(NOT_INITIALIZED_MESSAGE)

        if whitelist is None:
            return tools_dict, self._openai_tools

        return _filter_tools_by_whitelist(tools_dict, whitelist)

    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool is available."""
        if self._tools_dict is None:
            return False
        return tool_name in self._tools_dict

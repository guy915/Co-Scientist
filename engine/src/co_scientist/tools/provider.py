"""Tool provider wrapping MCPToolClient for LLM tool calling."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from co_scientist.exceptions import ConfigError
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.messages import tool_error_message

logger = logging.getLogger(__name__)


# Thin wrapper used by the tool-calling generation nodes (draft/validate/
# debate agents) so they interact with a small, stable interface regardless
# of what the underlying MCPToolClient looks like.
class MCPToolProvider:
    """Uniform tool interface over an MCP client.

    Tracks the tools exposed via get_tools so execute_tool_call can reject
    unknown names with an error tool-response instead of raising.

    example usage:
        provider = MCPToolProvider(mcp_client=mcp_client)

        tools_dict, openai_tools = provider.get_tools(
            mcp_whitelist=["pubmed_search_with_fulltext"])

        result = await provider.execute_tool_call(tool_call)
    """

    def __init__(self, mcp_client: MCPToolClient | None = None):
        """Initialize the tool provider.

        Args:
            mcp_client: optional MCP client for MCP tools
        """
        self.mcp_client = mcp_client

        # Names exposed via get_tools; used to reject unknown tool calls.
        self._tool_names: set[str] = set()

    def get_tools(
        self,
        mcp_whitelist: list[str] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Get tools from the MCP client.

        Args:
            mcp_whitelist: optional list of MCP tool names to include.
                None exposes every tool the MCP client offers; an empty
                list is a valid "no tools" request.

        Returns:
            tuple of (tools_dict, openai_tools_list)
            tools_dict is {tool_name: tool_object}
            openai_tools_list is a list of OpenAI-format tools
        """
        tools_dict: dict[str, Any] = {}
        openai_tools: list[dict[str, Any]] = []

        # The whitelist is forwarded as-is: MCPToolClient.get_tools treats
        # None as "all tools" and an empty list filters everything out.
        if self.mcp_client is not None:
            try:
                tools_dict, openai_tools = self.mcp_client.get_tools(
                    whitelist=mcp_whitelist
                )
                self._tool_names.update(tools_dict.keys())
                logger.debug("added %s MCP tools", len(tools_dict))
            except Exception as e:
                # Degrade gracefully: a transient MCP outage should not
                # crash the caller, just leave it with no tools available.
                logger.warning("Failed to get MCP tools: %s", e)

        logger.info("tool provider ready: %s tools", len(tools_dict))
        return tools_dict, openai_tools

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Execute a tool call via the MCP client.

        Args:
            tool_call: LiteLLM tool call object with .id, .function.name,
                .function.arguments

        Returns:
            tool response message dict:
                {role: "tool", name: ..., tool_call_id: ..., content: ...}
        """
        tool_name = tool_call.function.name
        tool_call_id = tool_call.id

        # Reject names never advertised via get_tools() rather than letting
        # the LLM invoke arbitrary/hallucinated names; the model still gets
        # an error tool-response so the conversation loop can continue.
        if tool_name not in self._tool_names:
            error_msg = f"unknown tool: {tool_name}"
            logger.error(error_msg)
            return self._create_error_response(
                tool_name, tool_call_id, error_msg
            )

        try:
            # Defensive: _tool_names is only populated when a client exists,
            # so this branch should be unreachable in practice.
            if self.mcp_client is None:
                raise ConfigError("MCP client not configured")
            return await self.mcp_client.execute_tool_call(tool_call)
        except Exception as e:
            # Any failure (network error, malformed args, tool-side
            # exception) becomes a tool-role error message rather than a
            # raised exception, so one bad call cannot crash the multi-turn
            # tool-calling loop.
            error_msg = f"tool execution failed: {e!s}"
            logger.error("%s error: %s", tool_name, error_msg)
            return self._create_error_response(
                tool_name, tool_call_id, error_msg
            )

    # Used by the draft and validate literature-tools agents (each passes its
    # own phase label, e.g. "Draft") to log and cap per-tool call volume
    # across a multi-iteration tool-calling loop.
    def tracked_executor(
        self,
        label: str,
    ) -> tuple[Callable[[Any], Awaitable[dict[str, Any]]], dict[str, int]]:
        """Wrap execute_tool_call with per-tool-name call counting.

        Args:
            label: Log prefix identifying the calling phase, e.g. "Draft".

        Returns:
            An (executor, counts) pair. The executor delegates to
            execute_tool_call; counts maps tool name to call count and is
            updated in place as the executor runs.
        """
        counts: dict[str, int] = {}

        async def executor(tool_call: Any) -> dict[str, Any]:
            name = tool_call.function.name
            counts[name] = counts.get(name, 0) + 1
            logger.info("%s: %s call #%s", label, name, counts[name])
            return await self.execute_tool_call(tool_call)

        return executor, counts

    # Shape matches the OpenAI/LiteLLM "tool" role message so downstream
    # code can treat error responses the same as successful tool results.
    def _create_error_response(
        self, tool_name: str, tool_call_id: str, error_msg: str
    ) -> dict[str, Any]:
        """Create error response message for failed tool call.

        Args:
            tool_name: name of tool that failed
            tool_call_id: tool call ID
            error_msg: error message

        Returns:
            tool response message dict with error
        """
        return tool_error_message(tool_name, tool_call_id, error_msg)

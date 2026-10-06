import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from co_scientist.exceptions import ConfigError
from co_scientist.mcp_client import MCPToolClient

logger = logging.getLogger(__name__)


# Bound excerpts to recognize upstream HTML/throttling without logging entire
# bodies.
_PAYLOAD_EXCERPT_CHARS = 200


def parse_mcp_result(result: Any) -> Any:
    """Accept raw JSON text and already-decoded client payloads."""
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(
                f"{exc.msg} (payload: {_payload_excerpt(result)})",
                exc.doc,
                exc.pos,
            ) from exc
    return result


def _payload_excerpt(payload: str) -> str:
    """Bound diagnostic excerpts without losing clues that distinguish HTML,
    throttling and empty bodies.
    """
    head = " ".join(payload.split())[:_PAYLOAD_EXCERPT_CHARS]
    if not head:
        return "empty"
    suffix = "..." if len(head) < len(payload.strip()) else ""
    return f"{head!r}{suffix}"


def tool_result_message(tool_name: str, tool_call_id: str, payload: Any) -> dict[str, Any]:
    return {
        "role": "tool",
        "name": tool_name,
        "tool_call_id": tool_call_id,
        "content": json.dumps(payload, default=str),
    }


def tool_error_message(tool_name: str, tool_call_id: str, error: str) -> dict[str, Any]:
    return tool_result_message(tool_name, tool_call_id, {"error": error})


def tracked_executor(
    provider: Any, label: str
) -> tuple[Callable[[Any], Awaitable[dict[str, Any]]], dict[str, int]]:
    counts: dict[str, int] = {}

    async def executor(tool_call: Any) -> dict[str, Any]:
        name = tool_call.function.name
        counts[name] = counts.get(name, 0) + 1
        logger.info("%s: %s call #%s", label, name, counts[name])
        result: dict[str, Any] = await provider.execute_tool_call(tool_call)
        return result

    return executor, counts


class MCPToolProvider:
    def __init__(self, mcp_client: MCPToolClient | None = None):
        self.mcp_client = mcp_client

        self._tool_names: set[str] = set()

    def get_tools(
        self,
        mcp_whitelist: list[str] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """None exposes all tools; an empty whitelist exposes none."""
        tools_dict: dict[str, Any] = {}
        openai_tools: list[dict[str, Any]] = []

        # Forward None versus [] unchanged: all tools versus none.
        if self.mcp_client is not None:
            try:
                tools_dict, openai_tools = self.mcp_client.get_tools(whitelist=mcp_whitelist)
                self._tool_names.update(tools_dict.keys())
                logger.debug("added %s MCP tools", len(tools_dict))
            except Exception as e:
                # Transient MCP outages degrade to no tools rather than aborting
                # the loop.
                logger.warning("Failed to get MCP tools: %s", e)

        logger.info("tool provider ready: %s tools", len(tools_dict))
        return tools_dict, openai_tools

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Reject unadvertised names; return failures as tool messages so the
        loop can continue.
        """
        tool_name = tool_call.function.name
        tool_call_id = tool_call.id

        # Reject names never advertised to the model.
        if tool_name not in self._tool_names:
            error_msg = f"unknown tool: {tool_name}"
            logger.error(error_msg)
            return tool_error_message(tool_name, tool_call_id, error_msg)

        try:
            if self.mcp_client is None:
                raise ConfigError("MCP client not configured")
            return await self.mcp_client.execute_tool_call(tool_call)
        except Exception as e:
            # Return failures as tool messages so one bad call cannot abort the
            # multi-turn loop.
            error_msg = f"tool execution failed: {e!s}"
            logger.error("%s error: %s", tool_name, error_msg)
            return tool_error_message(tool_name, tool_call_id, error_msg)

    def tracked_executor(
        self,
        label: str,
    ) -> tuple[Callable[[Any], Awaitable[dict[str, Any]]], dict[str, int]]:
        return tracked_executor(self, label)

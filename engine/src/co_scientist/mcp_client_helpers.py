"""Connection and tool-result helpers for the MCP client.

These pure utilities back ``MCPToolClient`` and the availability probes in
``co_scientist.mcp_client``; keeping them here lets the client module stay
focused on the client class and its lifecycle.
"""

import logging
import os
from typing import TYPE_CHECKING, Any, Optional

from langchain_core.utils.function_calling import convert_to_openai_tool

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


NOT_INITIALIZED_MESSAGE = "mcp client not initialized. call initialize() first."
"""Single wording for every "initialize() has not run" guard on the client.

Each guard raising its own literal is how the wording drifted before (one
copy was capitalized differently), so they all read it from here.
"""


def _ensure_tools_initialized(
    tools_dict: dict[str, Any] | None,
) -> dict[str, Any]:
    """Guards that a client's tools dict has been populated by initialize().

    Args:
        tools_dict: A client's ``_tools_dict``, or None if initialize()
            hasn't run.

    Returns:
        The non-None tools dict.

    Raises:
        RuntimeError: If tools_dict is None.
    """
    if tools_dict is None:
        raise RuntimeError(NOT_INITIALIZED_MESSAGE)
    return tools_dict


def _is_wrapped_text_result(result: Any) -> bool:
    """Checks whether result is the ``[{"text": ...}]`` wrapper shape.

    Some langchain versions wrap MCP tool results this way instead of
    returning the raw string.

    Args:
        result: Raw ``ainvoke()`` return value.

    Returns:
        True if result is a non-empty list whose first item is a dict
        containing a "text" key.
    """
    return (
        isinstance(result, list)
        and len(result) > 0
        and isinstance(result[0], dict)
        and "text" in result[0]
    )


def _unwrap_tool_result(result: Any) -> Any:
    """Unwraps the ``[{"text": ...}]`` shape some langchain versions return.

    Args:
        result: Raw ``ainvoke()`` return value.

    Returns:
        ``result[0]["text"]`` when result matches that shape, else result
        unchanged.
    """
    return result[0]["text"] if _is_wrapped_text_result(result) else result


def _filter_tools_by_whitelist(
    tools_dict: dict[str, Any],
    whitelist: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Filters a client's tools down to a workflow's whitelist.

    Args:
        tools_dict: All available tools, keyed by name.
        whitelist: Tool names to keep, in the order the LLM should see them.

    Returns:
        Tuple of (filtered_tools_dict, filtered_openai_tools). The latter
        follows whitelist order (not tools_dict's order) so the OpenAI-format
        tool list is presented to the LLM in the order the workflow config
        declared it, e.g. preferred tools first.
    """
    filtered_tools_dict = {
        k: v for k, v in tools_dict.items() if k in whitelist
    }
    filtered_openai_tools = [
        convert_to_openai_tool(filtered_tools_dict[k])
        for k in whitelist
        if k in filtered_tools_dict
    ]

    logger.debug(
        "filtered to %s tools: %s",
        len(filtered_tools_dict),
        list(filtered_tools_dict.keys()),
    )

    return filtered_tools_dict, filtered_openai_tools

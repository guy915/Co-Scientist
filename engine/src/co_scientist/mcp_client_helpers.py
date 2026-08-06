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

MCP_SHARED_SECRET_ENV = "COSCIENTIST_MCP_SHARED_SECRET"
"""Env var carrying the shared-secret token sent with every MCP call.

Set identically on the api and mcp services (see AGENTS.md's deployment
section) so the reference MCP server can require it instead of trusting
network placement alone. Left unset on either side reproduces the prior
behaviour exactly -- no header is sent, and the server does not require one
-- so introducing this cannot break a deployment that has not set it yet.
"""

MCP_AUTH_HEADER = "X-MCP-Shared-Secret"
"""HTTP header name carrying the shared secret, checked by the MCP server."""


def _resolve_server_url() -> str:
    """Return the MCP server URL from the environment or the default."""
    return os.environ.get("MCP_SERVER_URL", DEFAULT_MCP_SERVER_URL)


def _mcp_auth_headers() -> dict[str, Any] | None:
    """Return the shared-secret header this client should send, if any.

    Returns:
        A single-entry headers dict when ``COSCIENTIST_MCP_SHARED_SECRET``
        is set, else None -- so callers can omit the "headers" key entirely
        rather than sending an empty one.
    """
    secret = os.environ.get(MCP_SHARED_SECRET_ENV)
    return {MCP_AUTH_HEADER: secret} if secret else None


def _with_shared_secret(
    configs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Attach the shared-secret header to every resolved server config.

    Applied once here, after the config is resolved, so every path into
    MCPToolClient -- registry-driven, explicit configs, or the legacy
    single-URL fallback -- sends the same header without each branch having
    to remember to.

    Args:
        configs: Server configs as {server_id: {"transport": ..., "url":
            ...}}.

    Returns:
        The same configs, each carrying a merged "headers" entry, when a
        shared secret is configured; unchanged otherwise.
    """
    headers = _mcp_auth_headers()
    if headers is None:
        return configs
    return {
        server_id: {
            **cfg,
            "headers": {**(cfg.get("headers") or {}), **headers},
        }
        for server_id, cfg in configs.items()
    }


def _resolve_server_configs(
    tool_registry: Optional["ToolRegistry"],
    server_configs: dict[str, dict[str, Any]] | None,
    server_url: str | None,
) -> dict[str, dict[str, Any]]:
    """Resolve which MCP server configs MCPToolClient.__init__ should use.

    Precedence: an explicit tool_registry wins, then explicit
    server_configs, then a single legacy server_url (falling back to the
    env var / default). Every path is given the shared-secret header before
    returning, when one is configured.

    Args:
        tool_registry: ToolRegistry instance for config-driven multi-server
            mode, if provided.
        server_configs: Dict of server configs for multi-server mode, if
            provided.
        server_url: URL of a single MCP server (legacy mode), if provided.

    Returns:
        Dict of {server_id: {"transport": ..., "url": ..., "headers": ...}}.
    """
    if tool_registry is not None:
        # Use registry-provided server configs
        configs = tool_registry.get_server_configs_for_langchain()
        logger.debug("using %s servers from tool registry", len(configs))
        return _with_shared_secret(configs)

    if server_configs is not None:
        logger.debug("using %s provided server configs", len(server_configs))
        return _with_shared_secret(server_configs)

    # Legacy single-server mode
    if server_url is None:
        server_url = _resolve_server_url()
    logger.debug("using single server: %s", server_url)
    return _with_shared_secret(
        {"default": {"transport": "streamable_http", "url": server_url}}
    )


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

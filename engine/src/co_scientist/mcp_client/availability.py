"""Availability-probe helpers for the MCP client.

These functions decide whether an MCP server (and a specific literature
source) is reachable. They operate on an already-initialized
``MCPToolClient`` and are re-exported from ``co_scientist.mcp_client``,
which owns the public ``check_*`` entry points that call them.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry
    from co_scientist.mcp_client import MCPToolClient

logger = logging.getLogger(__name__)


def _resolve_availability_check_tool(
    tool_registry: Optional["ToolRegistry"],
) -> tuple[str | None, bool]:
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
        logger.debug(
            "availability check disabled in config (availability_check: null)"
        )
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


def _short_circuit_availability(
    all_tools_dict: dict[str, Any],
    check_tool_name: str | None,
    skip_availability_check: bool,
) -> bool | None:
    """Resolves availability without calling any tool, when possible.

    Checks, in order: no tools at all (unavailable), the workflow config
    opts out of a source-specific check, or no check tool is configured
    (both available since the server itself responded). Returns None when
    none apply, meaning the caller must actually invoke check_tool_name.

    Args:
        all_tools_dict: Tools available on the already-initialized client.
        check_tool_name: Availability-check tool name, or None if none is
            configured.
        skip_availability_check: Whether the server responding is enough,
            without calling a tool.

    Returns:
        True/False if availability is already decided, else None.
    """
    if not all_tools_dict:
        logger.warning(
            "MCP server responded but provided no tools,"
            " literature source unavailable"
        )
        return False

    if skip_availability_check or check_tool_name is None:
        logger.info(
            "MCP server available, skipping source-specific availability check"
            if skip_availability_check
            else "no availability check tool configured, assuming source"
            " available"
        )
        return True

    return None


async def _call_check_tool(
    mcp_client: "MCPToolClient",
    check_tool_name: str | None,
    all_tools_dict: dict[str, Any],
) -> bool:
    """Calls check_tool_name and interprets its result, if it exists.

    Args:
        mcp_client: An initialized MCPToolClient to call the tool on.
        check_tool_name: Name of the availability-check tool to call.
        all_tools_dict: Tools available on the already-initialized client.

    Returns:
        True/False per the tool's answer, or False if the tool is absent.
    """
    if check_tool_name not in all_tools_dict:
        logger.warning(
            "availability check tool '%s' not found. available tools: %s",
            check_tool_name,
            list(all_tools_dict.keys()),
        )
        return False

    logger.debug("%s tool found, executing", check_tool_name)
    # Result should be a boolean or "true"/"false" string.
    result = await mcp_client.call_tool(check_tool_name)
    return _interpret_availability_result(result, check_tool_name)


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
    all_tools_dict, _ = mcp_client.get_tools()

    shortcut = _short_circuit_availability(
        all_tools_dict, check_tool_name, skip_availability_check
    )
    if shortcut is not None:
        return shortcut

    logger.debug(
        "checking literature source availability (tool: %s)", check_tool_name
    )
    logger.debug("available mcp tools: %s", list(all_tools_dict.keys()))

    return await _call_check_tool(mcp_client, check_tool_name, all_tools_dict)


def _log_mcp_test_start(
    tool_registry: Optional["ToolRegistry"], server_url: str | None
) -> None:
    """Logs which MCP target check_mcp_available is about to probe.

    Args:
        tool_registry: ToolRegistry driving multi-server mode, if any.
        server_url: Single legacy server URL, used when tool_registry isn't.
    """
    if tool_registry:
        logger.debug(
            "testing mcp availability for %s server(s)",
            len(tool_registry.get_enabled_servers()),
        )
    else:
        logger.debug("testing mcp server availability at %s", server_url)


def _has_any_tools(tools_dict: dict[str, Any] | None) -> bool:
    """Checks whether an initialized client actually reports any tools.

    Args:
        tools_dict: The probe client's populated tools dict.

    Returns:
        True (and logs success) if non-empty; False (and logs a warning)
        otherwise.
    """
    if tools_dict and len(tools_dict) > 0:
        logger.info("MCP server available with %s tools", len(tools_dict))
        return True
    logger.warning("MCP server responded but provided no tools")
    return False


def _log_mcp_unavailable(
    tool_registry: Optional["ToolRegistry"],
    server_url: str | None,
    error: Exception,
) -> None:
    """Logs the check_mcp_available exception-fallback-to-False path.

    Args:
        tool_registry: ToolRegistry driving multi-server mode, if any.
        server_url: Single legacy server URL, used when tool_registry isn't.
        error: The exception that triggered the fallback.
    """
    if tool_registry:
        logger.warning("MCP servers unavailable: %s", error)
    else:
        logger.warning("MCP server unavailable at %s", server_url)

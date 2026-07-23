"""Tool-provider setup for the tool-based generation phases.

Shared by the Phase 1 draft agent (draft.py) and the validation synthesis
stage (validate_synthesis.py, via draft.py's re-export). Resolves the tool
registry and MCP whitelist, then initializes an MCP tool provider.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.tools.provider import MCPToolProvider

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


def _resolve_tool_registry_fallback(
    tool_registry: Optional["ToolRegistry"], label: str, log: logging.Logger
) -> Optional["ToolRegistry"]:
    """Fall back to the process-global tool registry when none was passed.

    Args:
        tool_registry: optional ToolRegistry threaded from WorkflowState.
        label: short phase label used in log messages.
        log: the calling module's logger.

    Returns:
        The resolved ToolRegistry, or None if none is available.
    """
    if tool_registry is not None:
        return tool_registry
    try:
        # Imported at call time so tests can monkeypatch
        # config.get_tool_registry on the config module namespace.
        from co_scientist.config import get_tool_registry

        tool_registry = get_tool_registry()
        log.info("Using global tool registry for %s", label)
    except Exception as e:
        log.warning("Failed to get tool registry: %s", e)
    return tool_registry


def _resolve_mcp_whitelist(
    tool_registry: Optional["ToolRegistry"],
    workflow_name: str,
    label: str,
    log: logging.Logger,
) -> list[str] | None:
    """Resolve the MCP tool-name whitelist for a workflow from its registry.

    Args:
        tool_registry: resolved ToolRegistry, or None.
        workflow_name: registry workflow key selecting the tool whitelist.
        label: short phase label used in log messages.
        log: the calling module's logger.

    Returns:
        The MCP tool-name whitelist, or None to allow every available tool.
    """
    if not tool_registry:
        # No registry available - let provider use all available tools
        log.warning("No tool registry - using all available MCP tools")
        return None

    tool_ids = tool_registry.get_tools_for_workflow(workflow_name)
    mcp_whitelist = tool_registry.get_mcp_tool_names(tool_ids)
    log.info("Tool whitelist for %s: %s", label, mcp_whitelist)
    return mcp_whitelist


def _setup_tool_provider(
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    workflow_name: str,
    label: str,
    log: logging.Logger,
) -> tuple[MCPToolProvider, list[Any], Optional["ToolRegistry"]]:
    """Resolve the tool registry/whitelist and init an MCP tool provider.

    Shared by the draft phase here and the validation synthesis stage
    (validate_synthesis.py). Fallback chain: passed-in registry (threaded
    from WorkflowState) -> process-global registry (covers standalone/dev
    scripts that never thread one through state) -> no whitelist at all
    (provider uses every available tool).

    Args:
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection; resolved from the global registry when None.
        workflow_name: registry workflow key selecting the tool whitelist.
        label: short phase label used in log messages.
        log: the calling module's logger, so log records keep their
            per-phase attribution.

    Returns:
        Tuple of (provider, openai_tools, resolved tool_registry).
    """
    tool_registry = _resolve_tool_registry_fallback(tool_registry, label, log)

    provider = MCPToolProvider(mcp_client=mcp_client)

    mcp_whitelist = _resolve_mcp_whitelist(
        tool_registry, workflow_name, label, log
    )

    tools_dict, openai_tools = provider.get_tools(mcp_whitelist=mcp_whitelist)
    log.info("Initialized %s provider with %s tools", label, len(tools_dict))

    return provider, openai_tools, tool_registry

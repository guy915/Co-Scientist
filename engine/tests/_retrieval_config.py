"""Shared ``ToolConfig`` builder for the literature-review tests.

The retrieval-support tests (PDF discovery, content fetch) resolve tools
through a duck-typed registry keyed by tool id, and the search/query tests
hand a tool config straight to the function under test; both need the same
minimal ``ToolConfig``. This builder makes it, leaving every field a test
does not exercise at its schema default.
"""

from typing import Any

from co_scientist.config.schema import ToolConfig


def make_tool_config(
    mcp_tool_name: str = "search_x", **overrides: Any
) -> ToolConfig:
    """Build a minimal ToolConfig with the given MCP-facing tool name.

    Args:
        mcp_tool_name: The tool's MCP-facing name, the field nearly every
            call site varies.
        **overrides: Any other ToolConfig fields to set (e.g. ``enabled``,
            ``source_type``, ``response_format``).

    Returns:
        A ToolConfig on the placeholder ``"s"`` server.
    """
    return ToolConfig(server="s", mcp_tool_name=mcp_tool_name, **overrides)

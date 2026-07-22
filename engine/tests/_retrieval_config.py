"""Shared builder for the literature-review retrieval-support tests.

Both ``test_literature_review_retrieval_support`` (PDF discovery) and
``test_literature_review_retrieval_content`` (content fetch) resolve tools
through a duck-typed registry keyed by tool id; this builder makes the
minimal ``ToolConfig`` those registries hand back.
"""

from co_scientist.config.schema import ToolConfig


def make_tool_config(mcp_tool_name: str) -> ToolConfig:
    """Build a minimal ToolConfig with the given MCP-facing tool name."""
    return ToolConfig(server="s", mcp_tool_name=mcp_tool_name)

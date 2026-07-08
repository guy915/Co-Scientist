"""Tools module for co-scientist-engine.

Exposes MCP server tools as callable tools for LLM agents and parses their
responses into engine models.
"""

# Re-export the provider and parser so callers can import them directly
# from co_scientist.tools instead of reaching into the submodules.
from co_scientist.tools.provider import MCPToolProvider
from co_scientist.tools.response_parser import ResponseParser

# Public API of this subpackage.
__all__ = [
    "MCPToolProvider",
    "ResponseParser",
]

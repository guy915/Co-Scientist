"""Configuration module for tool registry and MCP server definitions.

Provides YAML-based configuration for bringing your own MCP tools.
"""

# Re-exports the config package's public surface so callers elsewhere in
# the engine can do `from co_scientist.config import ToolRegistry` etc.
# instead of reaching into the schema/registry submodules directly. schema
# defines the dataclasses tools.yaml is parsed into; registry.py loads,
# merges, and serves that parsed config at runtime.
from co_scientist.config.registry import ToolRegistry, get_tool_registry
from co_scientist.config.schema import (
    EnrichmentConfig,
    ParameterConfig,
    ResponseFormat,
    SearchSourceConfig,
    ServerConfig,
    ToolConfig,
    ToolsConfig,
    WorkflowConfig,
)

# Declares these names as intentionally re-exported, so linters don't flag
# the imports above as unused just because this module never calls them.
__all__ = [
    "EnrichmentConfig",
    "ParameterConfig",
    "ResponseFormat",
    "SearchSourceConfig",
    "ServerConfig",
    "ToolConfig",
    "ToolRegistry",
    "ToolsConfig",
    "WorkflowConfig",
    "get_tool_registry",
]

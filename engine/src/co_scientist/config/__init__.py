"""Configuration module for tool registry and MCP server definitions.

Provides YAML-based configuration for bringing your own MCP tools.
"""

from co_scientist.config.schema import (
    EnrichmentConfig,
    ServerConfig,
    ResponseFormat,
    ParameterConfig,
    ToolConfig,
    SearchSourceConfig,
    WorkflowConfig,
    ToolsConfig,
    Settings,
)
from co_scientist.config.registry import ToolRegistry, get_tool_registry

__all__ = [
    "EnrichmentConfig",
    "ServerConfig",
    "ResponseFormat",
    "ParameterConfig",
    "ToolConfig",
    "SearchSourceConfig",
    "WorkflowConfig",
    "ToolsConfig",
    "Settings",
    "ToolRegistry",
    "get_tool_registry",
]

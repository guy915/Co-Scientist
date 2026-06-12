# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Configuration module for tool registry and MCP server definitions.

Provides YAML-based configuration for bringing your own MCP tools.
"""

from .schema import (
    EnrichmentConfig,
    ServerConfig,
    ResponseFormat,
    ParameterConfig,
    ToolConfig,
    WorkflowConfig,
    ToolsConfig,
    Settings,
)
from .registry import ToolRegistry, get_tool_registry

__all__ = [
    "EnrichmentConfig",
    "ServerConfig",
    "ResponseFormat",
    "ParameterConfig",
    "ToolConfig",
    "WorkflowConfig",
    "ToolsConfig",
    "Settings",
    "ToolRegistry",
    "get_tool_registry",
]

"""Root schema and public exports for tool configuration.

The registry merges tools.yaml overlays and parses them through ToolsConfig.
Server/tool dataclasses and parsing helpers live in tool_schema; workflow,
enrichment and prompt dataclasses live in workflow_schema. Unknown YAML
fields are ignored and absent fields use the dataclass defaults.
"""

from dataclasses import dataclass, field
from typing import Any

from co_scientist.config.tool_schema import (
    ParameterConfig,
    ResponseFormat,
    ServerConfig,
    ToolConfig,
    _declared_field_kwargs,
    resolve_content_params,
)
from co_scientist.config.workflow_schema import (
    EnrichmentConfig,
    PromptsConfig,
    SearchSourceConfig,
    WorkflowConfig,
)

__all__ = [
    "EnrichmentConfig",
    "ParameterConfig",
    "PromptsConfig",
    "ResponseFormat",
    "SearchSourceConfig",
    "ServerConfig",
    "ToolConfig",
    "ToolsConfig",
    "WorkflowConfig",
    "resolve_content_params",
]


# Each parses one top-level tools.yaml section into its nested dataclasses;
# split out of ToolsConfig.from_dict() below so that function reads as a
# sequence of named phases rather than a run of inline loops.
def _parse_servers(data: dict[str, Any]) -> dict[str, ServerConfig]:
    """Parse the top-level ``servers`` section into ServerConfig objects."""
    servers = {}
    for server_id, server_data in data.get("servers", {}).items():
        servers[server_id] = ServerConfig.from_dict(server_data)
    return servers


def _parse_workflows(data: dict[str, Any]) -> dict[str, WorkflowConfig]:
    """Parse the top-level ``workflows`` section into WorkflowConfig objects."""
    workflows = {}
    for workflow_id, workflow_data in data.get("workflows", {}).items():
        workflows[workflow_id] = WorkflowConfig.from_dict(workflow_data)
    return workflows


def _parse_tools_by_category(
    data: dict[str, Any],
) -> dict[str, dict[str, ToolConfig]]:
    """Parse the top-level ``tools`` section, keyed by category then id."""
    tools: dict[str, dict[str, ToolConfig]] = {}
    tools_data = data.get("tools", {})
    for category, category_tools in tools_data.items():
        tools[category] = {}
        for tool_id, tool_data in category_tools.items():
            tools[category][tool_id] = ToolConfig.from_dict(tool_data, tool_id)
    return tools


@dataclass
class ToolsConfig:
    """Root configuration object containing all tool definitions.

    This is the top-level structure parsed from tools.yaml.
    """

    # tools is keyed first by category (e.g. search_tools, read_tools,
    # utility_tools, matching the top-level grouping in tools.yaml) and then
    # by tool id, so a tool id must be unique across categories for
    # get_tool()/get_all_tools() below to resolve it unambiguously.
    version: str = "1.0"
    servers: dict[str, ServerConfig] = field(default_factory=dict)
    tools: dict[str, dict[str, ToolConfig]] = field(default_factory=dict)
    workflows: dict[str, WorkflowConfig] = field(default_factory=dict)
    prompts: PromptsConfig = field(default_factory=PromptsConfig)
    enrichments: list[EnrichmentConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolsConfig":
        """Create ToolsConfig from dictionary (parsed YAML)."""
        servers = _parse_servers(data)
        tools = _parse_tools_by_category(data)
        workflows = _parse_workflows(data)
        prompts = PromptsConfig.from_dict(data.get("prompts", {}))
        enrichments = [
            EnrichmentConfig.from_dict(e) for e in data.get("enrichments", [])
        ]

        # Every section above is parsed into nested dataclasses; only plain
        # scalar fields (currently just version) go through the generic path.
        # The YAML settings section is read from the raw dict by the registry
        # (merge_strategy), so it has no parsed counterpart here.
        kwargs = _declared_field_kwargs(
            cls,
            data,
            exclude=(
                "servers",
                "tools",
                "workflows",
                "settings",
                "prompts",
                "enrichments",
            ),
        )
        return cls(
            servers=servers,
            tools=tools,
            workflows=workflows,
            prompts=prompts,
            enrichments=enrichments,
            **kwargs,
        )

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Get a tool config by ID, searching all categories."""
        for category_tools in self.tools.values():
            if tool_id in category_tools:
                return category_tools[tool_id]
        return None

    def get_all_tools(self) -> dict[str, ToolConfig]:
        """Get all tools as a flat dict."""
        all_tools = {}
        for category_tools in self.tools.values():
            all_tools.update(category_tools)
        return all_tools

    def get_enabled_tools(self) -> dict[str, ToolConfig]:
        """Get all enabled tools as a flat dict."""
        return {
            tool_id: tool
            for tool_id, tool in self.get_all_tools().items()
            if tool.enabled
        }

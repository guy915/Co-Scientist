import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

import yaml

from co_scientist.config.env_vars import parse_bool_env, substitute_env_vars
from co_scientist.config.schema import (
    EnrichmentConfig,
    PromptsConfig,
    ServerConfig,
    ToolConfig,
    ToolsConfig,
    WorkflowConfig,
)
from co_scientist.exceptions import ConfigError


def _both_dicts(existing: Any, value: Any) -> bool:
    return isinstance(value, dict) and isinstance(existing, dict)


def _both_lists_to_extend(existing: Any, value: Any, strategy: str) -> bool:
    return (
        strategy == "extend"
        and isinstance(value, list)
        and isinstance(existing, list)
    )


def _determine_merge_strategy(
    user: dict[str, Any] | None, custom: dict[str, Any] | None
) -> str:
    for overlay in (custom, user):
        if overlay and "settings" in overlay:
            strategy: str = overlay["settings"].get(
                "merge_strategy", "override"
            )
            return strategy
    return "override"


logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "USER_CONFIG_PATHS",
    "ToolRegistry",
    "get_tool_registry",
    "parse_bool_env",
    "reset_tool_registry",
    "substitute_env_vars",
]

DEFAULT_CONFIG_PATH = Path(__file__).parent / "tools.yaml"

# Use only the first existing path; XDG is a legacy fallback, not another
# overlay.
USER_CONFIG_PATHS = [
    Path.home() / ".coscientist" / "tools.yaml",
    Path.home() / ".config" / "coscientist" / "tools.yaml",
]


def _coerce_enabled(entries: Iterable[dict[str, Any]]) -> None:
    """Environment substitution leaves YAML enabled flags as strings;
    dataclasses need real booleans.
    """
    for entry in entries:
        if isinstance(entry.get("enabled"), str):
            entry["enabled"] = parse_bool_env(entry["enabled"])


class ToolRegistry:
    def __init__(
        self,
        config_path: str | None = None,
        disabled_tools: list[str] | None = None,
        skip_user_config: bool = False,
    ):
        self._config: ToolsConfig | None = None
        self._custom_config_path = config_path
        self._disabled_tools = set(disabled_tools or [])
        self._skip_user_config = skip_user_config

        self._load_config()

    def _load_config(self) -> None:
        # Merge defaults < user < custom before substitution and boolean
        # coercion.
        default_data = self._load_yaml_file(DEFAULT_CONFIG_PATH)
        if default_data is None:
            logger.warning(
                "default config not found at %s, using empty config",
                DEFAULT_CONFIG_PATH,
            )
            default_data = {}

        user_data = self._load_user_config()
        custom_data = self._load_custom_config()

        merged_data = self._merge_configs(default_data, user_data, custom_data)

        merged_data = substitute_env_vars(merged_data)

        self._parse_enabled_values(merged_data)

        self._config = ToolsConfig.from_dict(merged_data)

        self._apply_disabled_tools()

        logger.info(
            "Tool registry initialized: %s servers, %s enabled tools",
            len(self._config.servers),
            len(self._config.get_enabled_tools()),
        )

    def _load_user_config(self) -> dict[str, Any] | None:
        """First-existing paths are alternatives, never multiple overlay
        layers.
        """
        if self._skip_user_config:
            return None

        for user_path in USER_CONFIG_PATHS:
            user_data = self._load_yaml_file(user_path)
            if user_data is not None:
                logger.info("loaded user config from %s", user_path)
                return user_data

        return None

    def _load_custom_config(self) -> dict[str, Any] | None:
        if not self._custom_config_path:
            return None

        custom_data = self._load_yaml_file(Path(self._custom_config_path))
        if custom_data is not None:
            logger.info(
                "loaded custom config from %s", self._custom_config_path
            )
        else:
            logger.warning(
                "custom config not found at %s", self._custom_config_path
            )
        return custom_data

    def _load_yaml_file(self, path: Path) -> dict[str, Any] | None:
        try:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    return cast(dict[str, Any] | None, yaml.safe_load(f))
        except Exception as e:
            logger.error("failed to load %s: %s", path, e)
        return None

    def _parse_enabled_values(self, data: dict[str, Any]) -> None:
        _coerce_enabled(data.get("servers", {}).values())
        for category_tools in data.get("tools", {}).values():
            _coerce_enabled(category_tools.values())

    def _merge_configs(
        self,
        default: dict[str, Any],
        user: dict[str, Any] | None,
        custom: dict[str, Any] | None,
    ) -> dict[str, Any]:
        result = dict(default)
        strategy = _determine_merge_strategy(user, custom)

        if user:
            result = self._merge_dict(result, user, strategy)

        if custom:
            result = self._merge_dict(result, custom, strategy)

        return result

    def _merge_dict(
        self, base: dict[str, Any], overlay: dict[str, Any], strategy: str
    ) -> dict[str, Any]:
        if strategy == "replace":
            return dict(overlay)

        result = dict(base)
        for key, value in overlay.items():
            if key not in result:
                result[key] = value
            else:
                result[key] = self._merge_value(result[key], value, strategy)

        return result

    def _merge_value(self, existing: Any, value: Any, strategy: str) -> Any:
        if _both_dicts(existing, value):
            return self._merge_dict(existing, value, strategy)
        if strategy == "override":
            return value
        if _both_lists_to_extend(existing, value, strategy):
            return existing + value
        # Extending a non-list preserves its existing value.
        return existing

    def _apply_disabled_tools(self) -> None:
        """Source selection reads its own enabled flag; reconcile
        missing/disabled backing tools centrally.
        """
        if not self._config:
            return
        self._disable_configured_tools(self._config)
        self._disable_sources_with_disabled_tools(self._config)

    def _disable_configured_tools(self, config: ToolsConfig) -> None:
        for tool_id in self._disabled_tools:
            tool = config.get_tool(tool_id)
            if tool:
                tool.enabled = False
                logger.debug("disabled tool: %s", tool_id)

    def _disable_sources_with_disabled_tools(self, config: ToolsConfig) -> None:
        for workflow in config.workflows.values():
            for source in workflow.search_sources:
                tool = config.get_tool(source.tool)
                if source.enabled and (tool is None or not tool.enabled):
                    source.enabled = False
                    logger.debug("disabled search source: %s", source.tool)

    @property
    def config(self) -> ToolsConfig:
        if self._config is None:
            raise ConfigError("tool registry not initialized")
        return self._config

    def get_server(self, server_id: str) -> ServerConfig | None:
        return self.config.servers.get(server_id)

    def get_enabled_servers(self) -> dict[str, ServerConfig]:
        return {
            server_id: server
            for server_id, server in self.config.servers.items()
            if server.enabled
        }

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        return self.config.get_tool(tool_id)

    def get_enabled_tools(self) -> dict[str, ToolConfig]:
        return self.config.get_enabled_tools()

    def get_tools_for_workflow(self, workflow_name: str) -> list[str]:
        workflow = self.config.workflows.get(workflow_name)
        if not workflow:
            logger.warning("workflow '%s' not found in config", workflow_name)
            return []

        return self._enabled_tool_ids(workflow.get_all_tools(), workflow_name)

    def _enabled_tool_ids(
        self, tool_ids: list[str], workflow_name: str
    ) -> list[str]:
        enabled_ids = []
        for tool_id in tool_ids:
            tool = self.get_tool(tool_id)
            if tool and tool.enabled:
                enabled_ids.append(tool_id)
            elif tool_id:
                logger.debug(
                    "tool '%s' in workflow '%s' is disabled or missing",
                    tool_id,
                    workflow_name,
                )

        return enabled_ids

    def get_workflow(self, workflow_name: str) -> WorkflowConfig | None:
        return self.config.workflows.get(workflow_name)

    def get_mcp_tool_names(self, tool_ids: list[str]) -> list[str]:
        mcp_names = []
        for tool_id in tool_ids:
            tool = self.get_tool(tool_id)
            if tool and tool.enabled:
                mcp_names.append(tool.mcp_tool_name)
        return mcp_names

    def get_tool_by_mcp_name(self, mcp_tool_name: str) -> ToolConfig | None:
        for tool in self.config.get_all_tools().values():
            if tool.mcp_tool_name == mcp_tool_name:
                return tool
        return None

    def get_prompts_config(self) -> PromptsConfig:
        return self.config.prompts

    def get_enrichment_configs(
        self, workflow: str = "generation"
    ) -> list[EnrichmentConfig]:
        return [
            e
            for e in self.config.enrichments
            if e.enabled and (workflow == "all" or e.workflow == workflow)
        ]

    def get_server_configs_for_langchain(self) -> dict[str, dict[str, str]]:
        result = {}
        for server_id, server in self.get_enabled_servers().items():
            result[server_id] = {
                "transport": server.transport,
                "url": server.url,
            }
        return result


# Nodes and prompt loading share this singleton; later arguments require
# force_reload.
_global_registry: ToolRegistry | None = None


def get_tool_registry(
    config_path: str | None = None,
    disabled_tools: list[str] | None = None,
    force_reload: bool = False,
) -> ToolRegistry:
    """This singleton ignores later config arguments unless force_reload is
    explicit.
    """
    global _global_registry

    if _global_registry is None or force_reload:
        _global_registry = ToolRegistry(
            config_path=config_path,
            disabled_tools=disabled_tools,
        )

    return _global_registry


def reset_tool_registry() -> None:
    global _global_registry
    _global_registry = None

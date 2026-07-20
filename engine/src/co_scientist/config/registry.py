"""Tool registry for managing MCP tool configurations.

Handles loading YAML configs, merging user configs with defaults, and
providing access to tool definitions. Environment-variable substitution
lives in ``env_vars`` and the raw-dict merge helpers in ``merging``; this
module re-exports the names historically importable from
``co_scientist.config.registry``.
"""

import logging
from pathlib import Path
from typing import Any, cast

import yaml

from co_scientist.config.env_vars import parse_bool_env, substitute_env_vars
from co_scientist.config.merging import (
    _both_dicts,
    _both_lists_to_extend,
    _determine_merge_strategy,
)
from co_scientist.config.schema import (
    EnrichmentConfig,
    PromptsConfig,
    ServerConfig,
    ToolConfig,
    ToolsConfig,
    WorkflowConfig,
)
from co_scientist.exceptions import ConfigError

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

# Default config file location (relative to this module)
# Ships with the package; defines every built-in tool/server/workflow so the
# engine works out of the box with no user configuration at all.
DEFAULT_CONFIG_PATH = Path(__file__).parent / "tools.yaml"

# User config locations (in order of precedence)
# Only the first of these two paths that exists is loaded (see
# _load_config's user_data loop below); the second is a legacy/XDG-style
# fallback location, not an additional override layer.
USER_CONFIG_PATHS = [
    Path.home() / ".coscientist" / "tools.yaml",
    Path.home() / ".config" / "coscientist" / "tools.yaml",
]


class ToolRegistry:
    """Central registry for tool configurations.

    Loads tool definitions from YAML configs, supports user overrides,
    and provides access methods for nodes and prompt builders.
    """

    def __init__(
        self,
        config_path: str | None = None,
        disabled_tools: list[str] | None = None,
        skip_user_config: bool = False,
    ):
        """Initialize the tool registry.

        Args:
            config_path: Optional path to custom YAML config
                (overrides defaults)
            disabled_tools: Optional list of tool IDs to disable
            skip_user_config: If True, don't load user config from
                ~/.coscientist/
        """
        self._config: ToolsConfig | None = None
        self._custom_config_path = config_path
        self._disabled_tools = set(disabled_tools or [])
        self._skip_user_config = skip_user_config

        # Load config on init
        self._load_config()

    def _load_config(self) -> None:
        """Load and merge configuration files."""
        # Pipeline: merge three YAML tiers (default < user < custom) as raw
        # dicts, substitute ${VAR} placeholders, coerce string "enabled"
        # flags left over from env substitution into real bools, then parse
        # the merged dict into typed dataclasses via ToolsConfig.from_dict.
        # Start with default config
        default_data = self._load_yaml_file(DEFAULT_CONFIG_PATH)
        if default_data is None:
            logger.warning(
                "default config not found at %s, using empty config",
                DEFAULT_CONFIG_PATH,
            )
            default_data = {}

        user_data = self._load_user_config()
        custom_data = self._load_custom_config()

        # Merge configs
        merged_data = self._merge_configs(default_data, user_data, custom_data)

        # Substitute environment variables
        merged_data = substitute_env_vars(merged_data)

        # Parse enabled values that might be env var strings
        self._parse_enabled_values(merged_data)

        # Create config object
        self._config = ToolsConfig.from_dict(merged_data)

        # Apply disabled tools
        self._apply_disabled_tools()

        logger.info(
            "Tool registry initialized: %s servers, %s enabled tools",
            len(self._config.servers),
            len(self._config.get_enabled_tools()),
        )

    def _load_user_config(self) -> dict[str, Any] | None:
        """Load the first existing user config from USER_CONFIG_PATHS.

        Returns:
            The parsed YAML dict of the first existing path, or None if
            skip_user_config is set or no user config file exists.
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
        """Load the custom config path passed to __init__, if any.

        Returns:
            The parsed YAML dict, or None if no custom config path was
            given or the file could not be loaded.
        """
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
        """Load a YAML file, returning None if not found."""
        try:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    return cast(dict[str, Any] | None, yaml.safe_load(f))
        except Exception as e:
            logger.error("failed to load %s: %s", path, e)
        return None

    def _parse_enabled_values(self, data: dict[str, Any]) -> None:
        """Parse 'enabled' fields that may be string booleans from env vars."""
        # substitute_env_vars() only replaces ${VAR} text, so a YAML
        # `enabled: ${SOME_FLAG}` becomes the literal string "true"/"false"
        # rather than a bool; this pass coerces those strings before the
        # dataclasses (which expect real bools) are built.
        # Parse server enabled values
        for server_data in data.get("servers", {}).values():
            if isinstance(server_data.get("enabled"), str):
                server_data["enabled"] = parse_bool_env(server_data["enabled"])

        # Parse tool enabled values
        for category_tools in data.get("tools", {}).values():
            self._parse_tool_category_enabled_values(category_tools)

    def _parse_tool_category_enabled_values(
        self, category_tools: dict[str, Any]
    ) -> None:
        """Coerce string 'enabled' values to bool for one tools.yaml category.

        Args:
            category_tools: Mapping of tool id to tool data for a single
                category (e.g. all entries under "search_tools").
        """
        for tool_data in category_tools.values():
            if isinstance(tool_data.get("enabled"), str):
                tool_data["enabled"] = parse_bool_env(tool_data["enabled"])

    def _merge_configs(
        self,
        default: dict[str, Any],
        user: dict[str, Any] | None,
        custom: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Merge configuration dicts based on merge strategy.

        Priority: custom > user > default
        """
        result = dict(default)
        strategy = _determine_merge_strategy(user, custom)

        # Apply user config
        if user:
            result = self._merge_dict(result, user, strategy)

        # Apply custom config (highest priority)
        if custom:
            result = self._merge_dict(result, custom, strategy)

        return result

    def _merge_dict(
        self, base: dict[str, Any], overlay: dict[str, Any], strategy: str
    ) -> dict[str, Any]:
        """Merge overlay dict into base dict.

        Strategies:
        - override: overlay values replace base values for matching keys
        - extend: overlay adds to base, doesn't replace
        - replace: overlay completely replaces base
        """
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
        """Resolve the merged value for a key present in both dicts.

        Args:
            existing: Current base value for the key.
            value: Overlay value for the key.
            strategy: Merge strategy ("override" or "extend"; "replace" is
                handled by the caller before this is reached).

        Returns:
            The value the key should take after merging.
        """
        if _both_dicts(existing, value):
            return self._merge_dict(existing, value, strategy)
        if strategy == "override":
            return value
        if _both_lists_to_extend(existing, value, strategy):
            return existing + value
        # For non-lists, extend doesn't replace existing values.
        return existing

    def _apply_disabled_tools(self) -> None:
        """Apply disabled_tools, then reconcile search sources with tools.

        The multi-source literature pipeline selects sources on
        ``SearchSourceConfig.enabled`` alone and never consults the tool's
        own flag, so a source whose backing tool is off would keep being
        searched -- the workflow whitelists would drop the tool while the
        literature review went on calling it. Reconciling here, at the one
        place tool flags become final, covers every way a tool can be off
        (the ``disabled_tools`` argument, a YAML ``enabled: false``, or a
        source naming a tool that does not exist) for every consumer of
        ``get_enabled_search_sources()``.
        """
        if not self._config:
            return

        for tool_id in self._disabled_tools:
            tool = self._config.get_tool(tool_id)
            if tool:
                tool.enabled = False
                logger.debug("disabled tool: %s", tool_id)

        for workflow in self._config.workflows.values():
            for source in workflow.search_sources:
                tool = self._config.get_tool(source.tool)
                if source.enabled and (tool is None or not tool.enabled):
                    source.enabled = False
                    logger.debug("disabled search source: %s", source.tool)

    @property
    def config(self) -> ToolsConfig:
        """Get the loaded configuration."""
        if self._config is None:
            raise ConfigError("tool registry not initialized")
        return self._config

    def get_server(self, server_id: str) -> ServerConfig | None:
        """Get a server configuration by ID."""
        return self.config.servers.get(server_id)

    def get_enabled_servers(self) -> dict[str, ServerConfig]:
        """Get all enabled server configurations."""
        return {
            server_id: server
            for server_id, server in self.config.servers.items()
            if server.enabled
        }

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Get a tool configuration by ID."""
        return self.config.get_tool(tool_id)

    def get_enabled_tools(self) -> dict[str, ToolConfig]:
        """Get all enabled tool configurations."""
        return self.config.get_enabled_tools()

    def get_tools_for_workflow(self, workflow_name: str) -> list[str]:
        """Get list of tool IDs for a workflow phase.

        Args:
            workflow_name: Name of workflow
                (literature_review, draft_generation, validation)

        Returns:
            List of tool IDs configured for this workflow
        """
        workflow = self.config.workflows.get(workflow_name)
        if not workflow:
            logger.warning("workflow '%s' not found in config", workflow_name)
            return []

        # Get all referenced tools, filtering to only enabled ones
        return self._enabled_tool_ids(workflow.get_all_tools(), workflow_name)

    def _enabled_tool_ids(
        self, tool_ids: list[str], workflow_name: str
    ) -> list[str]:
        """Filter tool_ids down to enabled tools, logging skipped ones.

        Args:
            tool_ids: Tool IDs referenced by a workflow.
            workflow_name: Name of the workflow, used for the debug log.

        Returns:
            The subset of tool_ids that resolve to an enabled tool.
        """
        enabled_ids = []
        for tool_id in tool_ids:
            tool = self.get_tool(tool_id)
            if tool and tool.enabled:
                enabled_ids.append(tool_id)
            elif tool_id:  # only warn if tool_id is not empty
                logger.debug(
                    "tool '%s' in workflow '%s' is disabled or missing",
                    tool_id,
                    workflow_name,
                )

        return enabled_ids

    def get_workflow(self, workflow_name: str) -> WorkflowConfig | None:
        """Get a workflow configuration by name."""
        return self.config.workflows.get(workflow_name)

    def get_mcp_tool_names(self, tool_ids: list[str]) -> list[str]:
        """Convert tool IDs to MCP tool names.

        Args:
            tool_ids: List of internal tool IDs

        Returns:
            List of actual MCP tool names
        """
        mcp_names = []
        for tool_id in tool_ids:
            tool = self.get_tool(tool_id)
            if tool and tool.enabled:
                mcp_names.append(tool.mcp_tool_name)
        return mcp_names

    def get_tool_by_mcp_name(self, mcp_tool_name: str) -> ToolConfig | None:
        """Find a tool config by its MCP tool name.

        Args:
            mcp_tool_name: The actual tool name on the MCP server

        Returns:
            ToolConfig if found, None otherwise
        """
        for tool in self.config.get_all_tools().values():
            if tool.mcp_tool_name == mcp_tool_name:
                return tool
        return None

    def get_prompts_config(self) -> PromptsConfig:
        """Get the domain-specific prompts configuration."""
        return self.config.prompts

    def get_enrichment_configs(
        self, workflow: str = "generation"
    ) -> list[EnrichmentConfig]:
        """Get enabled enrichment configurations for a given workflow phase.

        Args:
            workflow: "generation" (default) returns configs run by the
                      generation coordinator. "reflection" returns configs
                      for the
                      reflection node.
                      Passing "all" returns every enabled config regardless of
                      phase.
        """
        return [
            e
            for e in self.config.enrichments
            if e.enabled and (workflow == "all" or e.workflow == workflow)
        ]

    def get_server_configs_for_langchain(self) -> dict[str, dict[str, str]]:
        """Get server configs in the langchain MultiServerMCPClient format.

        Returns:
            Dict of {server_id: {"transport": ..., "url": ...}}
        """
        result = {}
        for server_id, server in self.get_enabled_servers().items():
            result[server_id] = {
                "transport": server.transport,
                "url": server.url,
            }
        return result


# Global registry instance
# Process-wide singleton: nodes and prompts.py call get_tool_registry() with
# no arguments to fetch this instance, so config_path/disabled_tools below
# only take effect on the very first call (or an explicit force_reload).
_global_registry: ToolRegistry | None = None


def get_tool_registry(
    config_path: str | None = None,
    disabled_tools: list[str] | None = None,
    force_reload: bool = False,
) -> ToolRegistry:
    """Get or create the global tool registry instance.

    Args:
        config_path: Optional path to custom config (only used on first
            call or force_reload)
        disabled_tools: Optional list of tools to disable (only used on
            first call or force_reload)
        force_reload: If True, reload configuration even if already initialized

    Returns:
        Initialized ToolRegistry instance
    """
    global _global_registry

    if _global_registry is None or force_reload:
        _global_registry = ToolRegistry(
            config_path=config_path,
            disabled_tools=disabled_tools,
        )

    return _global_registry


def reset_tool_registry() -> None:
    """Reset the global registry (primarily for testing)."""
    global _global_registry
    _global_registry = None

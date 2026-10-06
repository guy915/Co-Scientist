from __future__ import annotations

import datetime
import textwrap
from pathlib import Path
from typing import Any

import pytest

from co_scientist.config import ToolConfig, ToolRegistry
from co_scientist.config import registry as config_registry
from co_scientist.config.registry import substitute_env_vars
from co_scientist.config.schema import resolve_content_params
from co_scientist.exceptions import ConfigError
from tests._research_fakes import REPLACE_CONFIG as _REPLACE_CONFIG
from tests._research_fakes import write_config as _write_config


@pytest.fixture()
def _config_registry_registry(tmp_path: Path) -> ToolRegistry:
    path = _write_config(tmp_path, _REPLACE_CONFIG)
    return ToolRegistry(config_path=path, skip_user_config=True)


def test_registry_lookups_over_a_loaded_config(
    _config_registry_registry: ToolRegistry,
) -> None:
    registry = _config_registry_registry
    assert registry.get_server_configs_for_langchain() == {
        "myserver": {
            "transport": "streamable_http",
            "url": "http://example.test/mcp",
        }
    }
    assert set(registry.get_enabled_servers()) == {"myserver"}
    alpha = registry.get_tool_by_mcp_name("search_alpha")
    assert alpha is not None and alpha.display_name == "Alpha Search"
    assert registry.get_tool("pubmed_search") is None
    assert registry.get_tools_for_workflow("does_not_exist") == []
    assert registry.get_prompts_config().domain_context == (
        "test domain context"
    )
    assert [e.output_key for e in registry.get_enrichment_configs("all")] == [
        "gamma_out",
        "alpha_out",
    ]
    registry._config = None
    with pytest.raises(ConfigError):
        _ = registry.config


def test_a_missing_default_config_leaves_an_empty_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        config_registry, "DEFAULT_CONFIG_PATH", tmp_path / "absent.yaml"
    )
    registry = ToolRegistry(skip_user_config=True)
    assert registry.get_enabled_tools() == {}


def test_malformed_config_falls_back_to_default(tmp_path: Path) -> None:
    path = _write_config(tmp_path, "this: is: : not valid: yaml: :\n  - x")
    _config_registry_registry = ToolRegistry(
        config_path=path, skip_user_config=True
    )
    assert _config_registry_registry.get_tool("pubmed_search") is not None


def test_substitute_env_vars_set_default_and_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COS_TEST_VAR", "hello")
    monkeypatch.delenv("COS_TEST_MISSING", raising=False)

    assert substitute_env_vars("a-${COS_TEST_VAR}-b") == "a-hello-b"
    assert substitute_env_vars("${COS_TEST_MISSING:-fallback}") == "fallback"
    assert substitute_env_vars("${COS_TEST_MISSING}") == ""


_SOURCE_CONFIG = textwrap.dedent("""
    version: "2.0"
    servers:
      myserver:
        url: "http://example.test/mcp"
        enabled: true
    tools:
      search_tools:
        alpha_search:
          server: "myserver"
          mcp_tool_name: "search_alpha"
          enabled: true
        beta_search:
          server: "myserver"
          mcp_tool_name: "search_beta"
          enabled: true
        gamma_search:
          server: "myserver"
          mcp_tool_name: "search_gamma"
          enabled: false
    workflows:
      literature_review:
        search_sources:
          - tool: "alpha_search"
            enabled: true
          - tool: "beta_search"
            enabled: true
          - tool: "gamma_search"
            enabled: true
          - tool: "ghost_search"
            enabled: true
""")


def _enabled_sources(tmp_path: Path, **kwargs: Any) -> list[str]:
    registry = ToolRegistry(
        config_path=_write_config(tmp_path, _SOURCE_CONFIG),
        skip_user_config=True,
        **kwargs,
    )
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    return [s.tool for s in workflow.get_enabled_search_sources()]


def test_disabled_tools_argument_removes_tool_from_workflows(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry(
        config_path=_write_config(tmp_path, _REPLACE_CONFIG),
        skip_user_config=True,
        disabled_tools=["alpha_search"],
    )
    assert registry.get_tools_for_workflow("literature_review") == [
        "gamma_util",
    ]


def test_yaml_disabled_or_missing_tool_disables_its_search_source(
    tmp_path: Path,
) -> None:
    """Source reconciliation covers YAML-disabled and undefined tools too."""
    assert _enabled_sources(tmp_path) == ["alpha_search", "beta_search"]


def _tool(registry: ToolRegistry, tool_id: str) -> ToolConfig:
    tool_config = registry.get_tool(tool_id)
    assert tool_config is not None, f"{tool_id} must be configured"
    return tool_config


def test_resolve_content_params_resolves_multiple_keys() -> None:
    params = {
        "query": "{research_goal}",
        "tags": ["{focus_areas}", "static-tag"],
        "limit": 10,
    }
    context = {"research_goal": "Cure cancer", "focus_areas": "immunotherapy"}
    assert resolve_content_params(params, context) == {
        "query": "Cure cancer",
        "tags": ["immunotherapy", "static-tag"],
        "limit": 10,
    }
    assert params["query"] == "{research_goal}"
    assert params["tags"] == ["{focus_areas}", "static-tag"]


def test_map_parameters_converts_recency_years_to_starting_year() -> None:
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"recency_years": "starting_year"},
    )
    result = tool.map_parameters({"recency_years": 5})
    assert result == {"starting_year": datetime.datetime.now().year - 5}

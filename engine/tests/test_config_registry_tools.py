"""Tests for per-run tool disabling in the tool registry.

Split from ``test_config_registry.py``: covers the ``disabled_tools``
constructor argument and the load-time reconciliation that keeps a dead
tool's search source from staying live -- the multi-source literature
pipeline selects sources on ``SearchSourceConfig.enabled`` alone, so a
disabled (or never-defined) tool must also flip its source's flag.
"""

import textwrap
from pathlib import Path

from co_scientist.config.registry import ToolRegistry
from tests._registry_config import REPLACE_CONFIG as _REPLACE_CONFIG
from tests._registry_config import write_config as _write_config

# --- disabled_tools constructor argument ----------------------------------


def test_disabled_tools_argument_flips_enabled(tmp_path: Path) -> None:
    """``disabled_tools`` disables a tool that was enabled in the config."""
    path = _write_config(tmp_path, _REPLACE_CONFIG)
    registry = ToolRegistry(
        config_path=path,
        skip_user_config=True,
        disabled_tools=["alpha_search"],
    )
    alpha = registry.get_tool("alpha_search")
    assert alpha is not None and alpha.enabled is False
    # With alpha disabled, the literature_review workflow drops to gamma only.
    assert registry.get_tools_for_workflow("literature_review") == [
        "gamma_util",
    ]


def test_disabled_tools_also_disables_its_search_source(
    tmp_path: Path,
) -> None:
    """A disabled tool must not survive as a live search source.

    The multi-source literature pipeline picks sources on
    ``SearchSourceConfig.enabled`` and never consults the tool's own flag,
    so a caller-disabled tool would otherwise keep being searched while the
    workflow whitelists correctly dropped it -- the gap that let a
    per-audience tool restriction leak into the literature review.
    """
    config = textwrap.dedent("""
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
        workflows:
          literature_review:
            search_sources:
              - tool: "alpha_search"
                papers_per_query: 4
                enabled: true
              - tool: "beta_search"
                papers_per_query: 4
                enabled: true
    """)
    path = _write_config(tmp_path, config)

    enabled = ToolRegistry(config_path=path, skip_user_config=True)
    workflow = enabled.get_workflow("literature_review")
    assert workflow is not None
    assert [s.tool for s in workflow.get_enabled_search_sources()] == [
        "alpha_search",
        "beta_search",
    ]

    restricted = ToolRegistry(
        config_path=path,
        skip_user_config=True,
        disabled_tools=["alpha_search"],
    )
    restricted_workflow = restricted.get_workflow("literature_review")
    assert restricted_workflow is not None
    assert [
        s.tool for s in restricted_workflow.get_enabled_search_sources()
    ] == ["beta_search"]


def test_yaml_disabled_or_missing_tool_disables_its_search_source(
    tmp_path: Path,
) -> None:
    """Source flags are reconciled with tool flags however a tool is off.

    ``disabled_tools`` is not the only way a source's tool can be dead: the
    YAML itself may disable the tool while leaving the source enabled, or a
    source may name a tool that was never defined. The load-time
    reconciliation must cover those too, since the search phase trusts
    ``get_enabled_search_sources()`` alone.
    """
    config = textwrap.dedent("""
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
              enabled: false
        workflows:
          literature_review:
            search_sources:
              - tool: "alpha_search"
                papers_per_query: 4
                enabled: true
              - tool: "beta_search"
                papers_per_query: 4
                enabled: true
              - tool: "ghost_search"
                papers_per_query: 4
                enabled: true
    """)
    path = _write_config(tmp_path, config)

    registry = ToolRegistry(config_path=path, skip_user_config=True)
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    assert [s.tool for s in workflow.get_enabled_search_sources()] == [
        "alpha_search",
    ]

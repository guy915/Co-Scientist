"""Tests for the tool registry: config loading, merging, and queries.

The registry always loads the bundled default ``tools.yaml`` first, then merges
a user config (skipped here for determinism) and an optional custom config on
top. These tests drive a custom config written to ``tmp_path`` so behavior does
not depend on the developer's home directory. A ``merge_strategy: replace`` in
the custom config yields a registry containing *exactly* the test fixture, which
lets us assert on precise parsed structures rather than "it loaded".
"""

import textwrap
from pathlib import Path

import pytest

from co_scientist.config.registry import (
    get_tool_registry,
    parse_bool_env,
    reset_tool_registry,
    substitute_env_vars,
    ToolRegistry,
)
from co_scientist.exceptions import ConfigError

# A self-contained config that fully replaces the bundled default
# (``settings.merge_strategy: replace``), so the resulting registry contains
# only the tools/servers/workflows defined here. Values are literal (no ${...}
# placeholders) so env-var substitution is a no-op and the tests are
# deterministic regardless of the environment.
_REPLACE_CONFIG = textwrap.dedent("""
    version: "2.0"
    servers:
      myserver:
        url: "http://example.test/mcp"
        transport: "streamable_http"
        enabled: true
      offserver:
        url: "http://off.test/mcp"
        enabled: false
    tools:
      search_tools:
        alpha_search:
          server: "myserver"
          mcp_tool_name: "search_alpha"
          display_name: "Alpha Search"
          category: "search"
          enabled: true
        beta_search:
          server: "myserver"
          mcp_tool_name: "search_beta"
          enabled: false
      utility_tools:
        gamma_util:
          server: "myserver"
          mcp_tool_name: "util_gamma"
          enabled: true
    workflows:
      literature_review:
        primary_search: "alpha_search"
        fallback_search: "beta_search"
        availability_check: "gamma_util"
      draft_generation:
        search_tools:
          - "alpha_search"
          - "beta_search"
    enrichments:
      - tool: "gamma_util"
        output_key: "gamma_out"
        enabled: true
        workflow: "generation"
      - tool: "alpha_search"
        output_key: "alpha_out"
        enabled: true
        workflow: "reflection"
      - tool: "beta_search"
        output_key: "beta_out"
        enabled: false
        workflow: "generation"
    prompts:
      domain_context: "test domain context"
      generation_guidance: "test generation guidance"
    settings:
      merge_strategy: "replace"
    """)


def _write_config(tmp_path: Path, body: str) -> str:
    """Write ``body`` to a YAML file under ``tmp_path`` and return its path."""
    path = tmp_path / "tools.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


@pytest.fixture()
def registry(tmp_path: Path) -> ToolRegistry:
    """A registry built from ``_REPLACE_CONFIG`` with no default/user merge."""
    path = _write_config(tmp_path, _REPLACE_CONFIG)
    return ToolRegistry(config_path=path, skip_user_config=True)


# --- Parsing: servers, tools, and field defaults --------------------------


def test_replace_strategy_yields_only_custom_config(
        registry: ToolRegistry) -> None:
    """``merge_strategy: replace`` drops the bundled defaults entirely."""
    assert registry.config.version == "2.0"
    assert set(registry.config.servers) == {"myserver", "offserver"}
    # The default tools.yaml ships ``pubmed_search``; replace must remove it.
    assert registry.get_tool("pubmed_search") is None
    assert set(registry.config.get_all_tools()) == {
        "alpha_search",
        "beta_search",
        "gamma_util",
    }


def test_tool_fields_parse_with_defaults(registry: ToolRegistry) -> None:
    """Tool dicts parse into ToolConfig, with documented field defaults."""
    alpha = registry.get_tool("alpha_search")
    assert alpha is not None
    assert alpha.server == "myserver"
    assert alpha.mcp_tool_name == "search_alpha"
    assert alpha.display_name == "Alpha Search"
    assert alpha.category == "search"
    assert alpha.enabled is True

    # beta omits display_name -> it defaults to the YAML tool id, and omits
    # category -> defaults to "utility".
    beta = registry.get_tool("beta_search")
    assert beta is not None
    assert beta.display_name == "beta_search"
    assert beta.category == "utility"
    assert beta.enabled is False


def test_unknown_tool_returns_none(registry: ToolRegistry) -> None:
    """Looking up a tool id that is not configured returns None."""
    assert registry.get_tool("no_such_tool") is None


# --- Server queries -------------------------------------------------------


def test_get_enabled_servers_filters_disabled(
        registry: ToolRegistry) -> None:
    """Only servers with ``enabled: true`` are returned."""
    assert set(registry.get_enabled_servers()) == {"myserver"}
    off = registry.get_server("offserver")
    assert off is not None and off.enabled is False


def test_server_configs_for_langchain_shape(
        registry: ToolRegistry) -> None:
    """Langchain mapping contains transport+url for enabled servers only."""
    assert registry.get_server_configs_for_langchain() == {
        "myserver": {
            "transport": "streamable_http",
            "url": "http://example.test/mcp",
        }
    }


# --- Enabled-tool queries -------------------------------------------------


def test_get_enabled_tools_excludes_disabled(
        registry: ToolRegistry) -> None:
    """``beta_search`` is disabled and must not appear in enabled tools."""
    assert set(registry.get_enabled_tools()) == {"alpha_search", "gamma_util"}


# --- Workflow queries -----------------------------------------------------


def test_get_tools_for_workflow_returns_enabled_ids(
        registry: ToolRegistry) -> None:
    """Workflow tool lists are filtered down to enabled tools only.

    literature_review references alpha (enabled), beta (disabled), and gamma
    (enabled); the disabled beta is dropped.
    """
    assert registry.get_tools_for_workflow("literature_review") == [
        "alpha_search",
        "gamma_util",
    ]
    # draft_generation lists alpha + beta; only the enabled alpha survives.
    assert registry.get_tools_for_workflow("draft_generation") == [
        "alpha_search",
    ]


def test_get_tools_for_unknown_workflow_returns_empty(
        registry: ToolRegistry) -> None:
    """An unknown workflow name resolves to an empty list (documented)."""
    assert registry.get_tools_for_workflow("does_not_exist") == []


def test_get_workflow_returns_config_or_none(
        registry: ToolRegistry) -> None:
    """``get_workflow`` returns the parsed WorkflowConfig or None."""
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    assert workflow.primary_search == "alpha_search"
    assert workflow.fallback_search == "beta_search"
    assert workflow.availability_check == "gamma_util"
    assert registry.get_workflow("does_not_exist") is None


# --- MCP-name mapping -----------------------------------------------------


def test_get_mcp_tool_names_maps_and_drops_disabled(
        registry: ToolRegistry) -> None:
    """IDs map to mcp_tool_name; disabled tools are skipped, order preserved."""
    names = registry.get_mcp_tool_names(
        ["alpha_search", "beta_search", "gamma_util"])
    # beta_search is disabled -> dropped, leaving alpha + gamma in order.
    assert names == ["search_alpha", "util_gamma"]


def test_get_mcp_tool_names_ignores_unknown_ids(
        registry: ToolRegistry) -> None:
    """Unknown tool ids are silently skipped."""
    assert registry.get_mcp_tool_names(["nope", "alpha_search"]) == [
        "search_alpha",
    ]


def test_get_tool_by_mcp_name(registry: ToolRegistry) -> None:
    """Reverse lookup finds a tool by its MCP name, or returns None."""
    found = registry.get_tool_by_mcp_name("util_gamma")
    assert found is not None and found.display_name == "gamma_util"
    assert registry.get_tool_by_mcp_name("absent_mcp_name") is None


# --- Enrichment queries ---------------------------------------------------


def test_get_enrichment_configs_filters_by_workflow(
        registry: ToolRegistry) -> None:
    """Enrichments are filtered by ``enabled`` and ``workflow`` phase."""
    generation = registry.get_enrichment_configs("generation")
    assert [e.output_key for e in generation] == ["gamma_out"]

    reflection = registry.get_enrichment_configs("reflection")
    assert [e.output_key for e in reflection] == ["alpha_out"]

    # "all" returns every *enabled* enrichment regardless of phase; the
    # disabled beta_out enrichment is excluded.
    every = registry.get_enrichment_configs("all")
    assert [e.output_key for e in every] == ["gamma_out", "alpha_out"]


# --- prompts config -------------------------------------------------------


def test_get_prompts_config_parses_domain_fields(
        registry: ToolRegistry) -> None:
    """The domain-specific prompts section parses into a PromptsConfig."""
    prompts = registry.get_prompts_config()
    assert prompts.domain_context == "test domain context"
    assert prompts.generation_guidance == "test generation guidance"
    # Unset fields default to empty strings.
    assert prompts.review_guidance == ""


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


# --- override merge strategy (default) ------------------------------------


def test_override_merge_keeps_defaults_and_adds_custom(
        tmp_path: Path) -> None:
    """Without ``replace``, custom tools are added on top of the defaults."""
    custom = textwrap.dedent("""
        tools:
          search_tools:
            custom_search:
              server: "default_pubmed"
              mcp_tool_name: "search_custom"
              enabled: true
        """)
    path = _write_config(tmp_path, custom)
    registry = ToolRegistry(config_path=path, skip_user_config=True)
    # The custom tool is present...
    custom_tool = registry.get_tool("custom_search")
    assert custom_tool is not None
    assert custom_tool.mcp_tool_name == "search_custom"
    # ...and the bundled default tool is still present (merge, not replace).
    assert registry.get_tool("pubmed_search") is not None


# --- string-boolean env values (_parse_enabled_values) --------------------


def test_string_enabled_values_parse_to_bools(tmp_path: Path) -> None:
    """``enabled`` given as a string (e.g. from an env var) becomes a bool."""
    config = textwrap.dedent("""
        servers:
          s1:
            url: "http://x.test"
            enabled: "false"
        tools:
          search_tools:
            t1:
              server: "s1"
              mcp_tool_name: "m1"
              enabled: "true"
            t2:
              server: "s1"
              mcp_tool_name: "m2"
              enabled: "no"
        settings:
          merge_strategy: "replace"
        """)
    path = _write_config(tmp_path, config)
    registry = ToolRegistry(config_path=path, skip_user_config=True)

    server = registry.get_server("s1")
    assert server is not None and server.enabled is False

    tool_one = registry.get_tool("t1")
    assert tool_one is not None and tool_one.enabled is True

    tool_two = registry.get_tool("t2")
    assert tool_two is not None and tool_two.enabled is False


# --- malformed config: silent fallback to default -------------------------


def test_malformed_config_falls_back_to_default(tmp_path: Path) -> None:
    """A syntactically broken config is swallowed; defaults load instead.

    ``_load_yaml_file`` catches the YAML parse error and returns None, so the
    custom config is treated as absent and the registry serves the bundled
    default ``tools.yaml`` (which defines ``pubmed_search``).
    """
    path = _write_config(tmp_path, "this: is: : not valid: yaml: :\n  - x")
    registry = ToolRegistry(config_path=path, skip_user_config=True)
    assert registry.get_tool("pubmed_search") is not None


# --- ConfigError guard ----------------------------------------------------


def test_config_property_raises_when_uninitialized(
        registry: ToolRegistry) -> None:
    """The ``config`` property raises ConfigError when state is missing.

    This is the only path in the registry that raises ConfigError. Malformed
    files do not raise (they fall back); they only leave ``_config`` unset if it
    were never loaded, which we simulate here.
    """
    registry._config = None  # pylint: disable=protected-access
    with pytest.raises(ConfigError):
        _ = registry.config


# --- module-level helpers -------------------------------------------------


def test_substitute_env_vars_set_default_and_missing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``${VAR}`` / ``${VAR:-default}`` expand from env, default, or empty."""
    monkeypatch.setenv("COS_TEST_VAR", "hello")
    monkeypatch.delenv("COS_TEST_MISSING", raising=False)

    assert substitute_env_vars("a-${COS_TEST_VAR}-b") == "a-hello-b"
    assert substitute_env_vars("${COS_TEST_MISSING:-fallback}") == "fallback"
    # No env var and no default -> empty string.
    assert substitute_env_vars("${COS_TEST_MISSING}") == ""


def test_substitute_env_vars_recurses_into_containers(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Substitution recurses through nested dicts and lists; leaves non-strings.
    """
    monkeypatch.setenv("COS_TEST_VAR", "X")
    result = substitute_env_vars({
        "url": "${COS_TEST_VAR}",
        "items": ["${COS_TEST_VAR}", 5],
        "flag": True,
    })
    assert result == {"url": "X", "items": ["X", 5], "flag": True}


def test_parse_bool_env_truthy_and_falsy() -> None:
    """Only a known set of strings parse to True; everything else is False."""
    assert parse_bool_env("true") is True
    assert parse_bool_env("TRUE") is True
    assert parse_bool_env("1") is True
    assert parse_bool_env("yes") is True
    assert parse_bool_env("on") is True
    assert parse_bool_env("false") is False
    assert parse_bool_env("no") is False
    assert parse_bool_env("") is False
    assert parse_bool_env("maybe") is False


# --- global registry singleton --------------------------------------------


def test_get_tool_registry_caches_and_force_reloads(
        tmp_path: Path) -> None:
    """The module-global registry is cached and rebuilt on force_reload.

    Identity is asserted (not contents) so the test stays deterministic even
    though ``get_tool_registry`` has no ``skip_user_config`` knob.
    """
    path = _write_config(tmp_path, _REPLACE_CONFIG)
    reset_tool_registry()
    try:
        first = get_tool_registry(config_path=path)
        # A subsequent call without force_reload returns the same instance.
        assert get_tool_registry() is first
        # force_reload builds a fresh instance.
        reloaded = get_tool_registry(config_path=path, force_reload=True)
        assert reloaded is not first
    finally:
        # Restore global state so other tests/modules are unaffected.
        reset_tool_registry()

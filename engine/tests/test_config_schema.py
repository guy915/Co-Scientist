"""Tests for config schema dataclasses: from_dict default handling.

Every ``from_dict`` builds constructor kwargs only from keys present in the
input dict, so the dataclass declaration is the single source of truth for
field defaults. These tests construct each config from a dict omitting all
optional keys and assert the result equals a directly constructed instance,
pinning that YAML-loaded and programmatically-constructed configs cannot
fork behavior.
"""

import dataclasses
from typing import Any

from co_scientist.config.schema import (
    EnrichmentConfig,
    ParameterConfig,
    PromptsConfig,
    ResponseFormat,
    SearchSourceConfig,
    ServerConfig,
    ToolConfig,
    ToolsConfig,
    WorkflowConfig,
)


def _assert_declared_defaults(
    instance: Any, skip: tuple[str, ...] = ()
) -> None:
    """Assert every non-skipped field carries its declared default."""
    for f in dataclasses.fields(instance):
        if f.name in skip:
            continue
        if f.default is not dataclasses.MISSING:
            expected = f.default
        elif f.default_factory is not dataclasses.MISSING:
            expected = f.default_factory()
        else:
            continue  # Required field with no declared default.
        assert getattr(instance, f.name) == expected, (
            f"{type(instance).__name__}.{f.name} did not use the dataclass "
            f"default"
        )


# --- Minimal dicts: dataclass defaults fill every omitted key --------------


def test_server_config_minimal_dict_uses_dataclass_defaults() -> None:
    """Omitting optional keys yields the dataclass-declared defaults."""
    config = ServerConfig.from_dict({"url": "http://x.test"})
    assert config == ServerConfig(url="http://x.test")
    _assert_declared_defaults(config)
    # A missing url is tolerated and coerced to an empty string.
    assert ServerConfig.from_dict({}).url == ""


def test_response_format_minimal_dict_uses_dataclass_defaults() -> None:
    """Empty and partial dicts fall back to the declared defaults."""
    assert ResponseFormat.from_dict({}) == ResponseFormat()
    partial = ResponseFormat.from_dict({"results_path": "results"})
    assert partial.results_path == "results"
    _assert_declared_defaults(partial, skip=("results_path",))


def test_parameter_config_minimal_dict_uses_dataclass_defaults() -> None:
    """Empty and partial dicts fall back to the declared defaults."""
    assert ParameterConfig.from_dict({}) == ParameterConfig()
    partial = ParameterConfig.from_dict({"required": True})
    assert partial.required is True
    _assert_declared_defaults(partial, skip=("required",))


def test_tool_config_minimal_dict_uses_dataclass_defaults() -> None:
    """Omitted optional keys resolve to the dataclass defaults.

    server, mcp_tool_name, and display_name keep explicit YAML fallbacks
    ("default" and the YAML tool id respectively), so they are asserted
    separately from the generic defaults.
    """
    config = ToolConfig.from_dict({}, tool_id="my_tool")
    assert config == ToolConfig(
        server="default",
        mcp_tool_name="my_tool",
        display_name="my_tool",
    )
    _assert_declared_defaults(config, skip=("display_name",))
    assert config.response_format == ResponseFormat()
    assert config.parameters == {}


def test_tool_config_parses_nested_parameters() -> None:
    """Nested parameter dicts and bare defaults parse into ParameterConfig."""
    config = ToolConfig.from_dict(
        {
            "server": "s1",
            "parameters": {
                "query": {"type": "string", "required": True},
                "max_results": 5,
            },
        },
        tool_id="t1",
    )
    assert config.parameters["query"] == ParameterConfig(
        type="string", required=True
    )
    assert config.parameters["max_results"] == ParameterConfig(default=5)


def test_search_source_config_minimal_dict_uses_dataclass_defaults() -> None:
    """Dict and string shorthand forms both fall back to declared defaults."""
    config = SearchSourceConfig.from_dict({"tool": "arxiv_search"})
    assert config == SearchSourceConfig(tool="arxiv_search")
    _assert_declared_defaults(config)
    # String shorthand: just the tool name.
    assert SearchSourceConfig.from_dict("arxiv_search") == config


def test_workflow_config_minimal_dict_uses_dataclass_defaults() -> None:
    """Empty and partial dicts fall back to the declared defaults."""
    assert WorkflowConfig.from_dict({}) == WorkflowConfig()
    partial = WorkflowConfig.from_dict({"primary_search": "pubmed_search"})
    assert partial.primary_search == "pubmed_search"
    _assert_declared_defaults(partial, skip=("primary_search",))


def test_workflow_config_parses_nested_search_sources() -> None:
    """search_sources entries parse into SearchSourceConfig objects."""
    config = WorkflowConfig.from_dict(
        {
            "search_sources": [
                "plain_tool",
                {"tool": "rich_tool", "papers_per_query": 7},
            ]
        }
    )
    assert config.search_sources == [
        SearchSourceConfig(tool="plain_tool"),
        SearchSourceConfig(tool="rich_tool", papers_per_query=7),
    ]


def test_enrichment_config_minimal_dict_uses_dataclass_defaults() -> None:
    """Omitting optional keys yields the dataclass-declared defaults."""
    config = EnrichmentConfig.from_dict({"tool": "nvd_cve_search"})
    assert config == EnrichmentConfig(tool="nvd_cve_search")
    _assert_declared_defaults(config)


def test_prompts_config_minimal_dict_uses_dataclass_defaults() -> None:
    """Empty and partial dicts fall back to the declared defaults."""
    assert PromptsConfig.from_dict({}) == PromptsConfig()
    partial = PromptsConfig.from_dict({"domain_context": "ctx"})
    assert partial.domain_context == "ctx"
    _assert_declared_defaults(partial, skip=("domain_context",))


def test_tools_config_minimal_dict_uses_dataclass_defaults() -> None:
    """An empty dict yields a ToolsConfig equal to the bare constructor."""
    assert ToolsConfig.from_dict({}) == ToolsConfig()
    partial = ToolsConfig.from_dict({"version": "3.1"})
    assert partial.version == "3.1"
    _assert_declared_defaults(partial, skip=("version",))


# --- Unknown keys and explicit nulls ---------------------------------------


def test_unknown_keys_are_ignored() -> None:
    """Keys that are not declared fields are silently dropped."""
    config = WorkflowConfig.from_dict(
        {
            "primary_search": "pubmed_search",
            "bogus_key": "ignored",
        }
    )
    assert config.primary_search == "pubmed_search"
    assert not hasattr(config, "bogus_key")


def test_yaml_tool_id_is_not_read_from_yaml() -> None:
    """The internal _yaml_tool_id field is never populated from YAML data."""
    config = ToolConfig.from_dict({"_yaml_tool_id": "sneaky"}, tool_id="t1")
    assert config._yaml_tool_id is None


def test_explicit_null_overrides_default_when_key_present() -> None:
    """A key present with None wins over the default (legacy data.get).

    Shipped configs use ``availability_check: null``; presence-based kwargs
    must forward the None rather than dropping the key.
    """
    config = WorkflowConfig.from_dict({"availability_check": None})
    assert config.availability_check is None
    # Presence wins even where the declared default is non-None.
    tool = ToolConfig.from_dict({"applies_to": None}, tool_id="t1")
    assert tool.applies_to is None

"""Offline contracts for config schema."""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any

import pytest

from co_scientist.config.registry import (
    _both_dicts,
    _both_lists_to_extend,
    _determine_merge_strategy,
)
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
    _recency_years_to_starting_year,
    resolve_content_params,
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


def test_from_dict_tolerates_an_empty_yaml_section() -> None:
    """A section written with no body parses to None, not to ``{}``.

    ``prompts:`` / ``response_format:`` with nothing under it is valid YAML
    and yields None, which reaches ``from_dict`` through
    ``data.get(key, {})`` because the key *is* present. Every such config
    must fall back to its declared defaults rather than raise.
    """
    assert PromptsConfig.from_dict(None) == PromptsConfig()  # type: ignore[arg-type]
    assert ResponseFormat.from_dict(None) == ResponseFormat()  # type: ignore[arg-type]
    assert ParameterConfig.from_dict(None) == ParameterConfig()  # type: ignore[arg-type]
    assert WorkflowConfig.from_dict(None) == WorkflowConfig()  # type: ignore[arg-type]


# --- _recency_years_to_starting_year --------------------------------------


def test_recency_years_to_starting_year_positive_value() -> None:
    """A positive lookback window converts to an absolute starting year."""
    current_year = datetime.datetime.now().year
    assert _recency_years_to_starting_year(7) == current_year - 7


def test_recency_years_to_starting_year_zero_is_none() -> None:
    """A zero lookback window has no meaningful starting year."""
    assert _recency_years_to_starting_year(0) is None


def test_recency_years_to_starting_year_negative_is_none() -> None:
    """A negative lookback window has no meaningful starting year."""
    assert _recency_years_to_starting_year(-3) is None


# --- ToolConfig.map_parameters: no mapping configured ----------------------


def test_map_parameters_without_mapping_returns_as_is() -> None:
    """With no parameter_mapping configured, params pass through unchanged."""
    tool = ToolConfig(server="s1", mcp_tool_name="search")
    result = tool.map_parameters({"query": "cancer", "max_papers": 5})
    assert result == {"query": "cancer", "max_papers": 5}


# --- ToolConfig.map_parameters: recency_years -> starting_year -------------


def test_map_parameters_converts_recency_years_to_starting_year() -> None:
    """recency_years maps to starting_year via the absolute-year helper."""
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"recency_years": "starting_year"},
    )
    current_year = datetime.datetime.now().year

    result = tool.map_parameters({"recency_years": 5})

    assert result == {"starting_year": current_year - 5}


def test_map_parameters_recency_years_zero_maps_to_none() -> None:
    """A zero recency_years value maps starting_year to None."""
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"recency_years": "starting_year"},
    )
    result = tool.map_parameters({"recency_years": 0})
    assert result == {"starting_year": None}


def test_map_parameters_renames_without_recency_conversion() -> None:
    """A plain rename (not recency_years->starting_year) passes value as-is."""
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"max_papers": "max_results"},
    )
    result = tool.map_parameters({"max_papers": 10})
    assert result == {"max_results": 10}


def test_map_parameters_null_mapping_drops_parameter() -> None:
    """A parameter explicitly mapped to null in YAML is dropped entirely."""
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"unused_param": None},
    )
    result = tool.map_parameters({"unused_param": "x", "query": "cancer"})
    assert result == {"query": "cancer"}


def test_map_parameters_unmapped_key_uses_canonical_name() -> None:
    """A canonical key absent from parameter_mapping keeps its own name."""
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"max_papers": "max_results"},
    )
    result = tool.map_parameters({"query": "cancer"})
    assert result == {"query": "cancer"}


# --- _both_dicts -------------------------------------------------------


def test_both_dicts_true_when_both_are_dicts() -> None:
    """Two dict values are mergeable."""
    assert _both_dicts({"a": 1}, {"b": 2}) is True


def test_both_dicts_false_when_existing_is_not_a_dict() -> None:
    """A non-dict existing value is never mergeable, even with a dict."""
    assert _both_dicts([1, 2], {"a": 1}) is False


def test_both_dicts_false_when_value_is_not_a_dict() -> None:
    """A non-dict overlay value is never mergeable, even with a dict."""
    assert _both_dicts({"a": 1}, [1, 2]) is False


def test_both_dicts_false_when_neither_is_a_dict() -> None:
    """Two non-dict values are not mergeable."""
    assert _both_dicts("x", "y") is False


# --- _both_lists_to_extend -----------------------------------------------


def test_both_lists_to_extend_true_for_extend_strategy_and_lists() -> None:
    """Both lists under the "extend" strategy should be concatenated."""
    assert _both_lists_to_extend([1], [2], "extend") is True


def test_both_lists_to_extend_false_for_non_extend_strategy() -> None:
    """Lists under any other strategy are not extended by this helper."""
    assert _both_lists_to_extend([1], [2], "override") is False


def test_both_lists_to_extend_false_when_existing_is_not_a_list() -> None:
    """A non-list existing value blocks extension even under "extend"."""
    assert _both_lists_to_extend("a", [2], "extend") is False


def test_both_lists_to_extend_false_when_value_is_not_a_list() -> None:
    """A non-list overlay value blocks extension even under "extend"."""
    assert _both_lists_to_extend([1], "b", "extend") is False


# --- _determine_merge_strategy --------------------------------------------


def test_determine_merge_strategy_defaults_to_override_with_no_configs() -> (
    None
):
    """Absent user and custom configs fall back to "override"."""
    assert _determine_merge_strategy(None, None) == "override"


def test_determine_merge_strategy_neither_has_settings_key() -> None:
    """Configs present but without a "settings" key default to "override"."""
    assert _determine_merge_strategy({"foo": 1}, {"bar": 2}) == "override"


def test_determine_merge_strategy_uses_custom_settings_when_present() -> None:
    """A custom-only "settings" block sets the strategy."""
    custom = {"settings": {"merge_strategy": "extend"}}
    assert _determine_merge_strategy(None, custom) == "extend"


def test_determine_merge_strategy_custom_wins_over_user() -> None:
    """When both declare a strategy, the custom config's choice wins."""
    user = {"settings": {"merge_strategy": "replace"}}
    custom = {"settings": {"merge_strategy": "extend"}}
    assert _determine_merge_strategy(user, custom) == "extend"


def test_determine_merge_strategy_falls_back_to_user_settings() -> None:
    """With no custom config, the user config's "settings" block is used."""
    user = {"settings": {"merge_strategy": "extend"}}
    assert _determine_merge_strategy(user, None) == "extend"


def test_determine_merge_strategy_custom_without_settings_falls_to_user() -> (
    None
):
    """A custom config lacking "settings" falls through to the user's."""
    user = {"settings": {"merge_strategy": "extend"}}
    custom = {"other_key": True}
    assert _determine_merge_strategy(user, custom) == "extend"


def test_determine_merge_strategy_settings_present_without_merge_key() -> None:
    """A "settings" block with no "merge_strategy" key defaults to override."""
    custom: dict[str, dict[str, str]] = {"settings": {}}
    assert _determine_merge_strategy(None, custom) == "override"


@pytest.mark.parametrize(
    ("value", "context", "expected"),
    [
        ("plain string", {}, "plain string"),
        ("{unknown}", {}, "{unknown}"),
        ("{goal}", {"goal": ["a", "b"]}, ["a", "b"]),
        ("{goal}", {"goal": {"nested": 1}}, {"nested": 1}),
        ("{count}", {"count": 5}, 5),
        ("study {name}", {"name": "cancer"}, "study cancer"),
        (
            "prefix {goal} suffix",
            {"goal": ["a", "b"]},
            "prefix ['a', 'b'] suffix",
        ),
        ("{a}-{b}", {"a": "X", "b": "Y"}, "X-Y"),
        ("{a}-{b}", {"a": "{b}", "b": "Y"}, "Y-Y"),
        (
            "{known} and {unknown}",
            {"known": "value"},
            "value and {unknown}",
        ),
        (
            ["{topic}", "static", 3],
            {"topic": "genomics"},
            ["genomics", "static", 3],
        ),
        (["{nums}"], {"nums": [1, 2, 3]}, ["[1, 2, 3]"]),
        (42, {"x": "y"}, 42),
        (True, {"x": "y"}, True),
        ({"inner": "{x}"}, {"x": "y"}, {"inner": "{x}"}),
    ],
)
def test_resolve_content_parameter(
    value: Any, context: dict[str, Any], expected: Any
) -> None:
    """Typed whole values and string list entries follow distinct rules."""
    assert resolve_content_params({"value": value}, context) == {
        "value": expected
    }


def test_resolve_content_params_empty_params_returns_empty_dict() -> None:
    """An empty params dict resolves to an empty dict."""
    assert resolve_content_params({}, {"research_goal": "X"}) == {}


def test_resolve_content_params_resolves_multiple_keys() -> None:
    """Every key is resolved independently without changing the input."""
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


def test_resolve_content_params_leaves_nested_containers_untouched() -> None:
    """Containers inside values pass through without recursive substitution."""
    nested = {"inner": "{x}"}
    result = resolve_content_params(
        {"nested": nested, "list": [nested]}, {"x": "y"}
    )
    assert result["nested"] is nested
    assert result["list"][0] is nested

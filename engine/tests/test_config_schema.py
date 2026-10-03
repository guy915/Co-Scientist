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
    for f in dataclasses.fields(instance):
        if f.name in skip:
            continue
        if f.default is not dataclasses.MISSING:
            expected = f.default
        elif f.default_factory is not dataclasses.MISSING:
            expected = f.default_factory()
        else:
            continue
        assert getattr(instance, f.name) == expected, (
            f"{type(instance).__name__}.{f.name} did not use the dataclass "
            f"default"
        )


def test_server_config_minimal_dict_uses_dataclass_defaults() -> None:
    config = ServerConfig.from_dict({"url": "http://x.test"})
    assert config == ServerConfig(url="http://x.test")
    _assert_declared_defaults(config)
    assert ServerConfig.from_dict({}).url == ""


def test_response_format_minimal_dict_uses_dataclass_defaults() -> None:
    assert ResponseFormat.from_dict({}) == ResponseFormat()
    partial = ResponseFormat.from_dict({"results_path": "results"})
    assert partial.results_path == "results"
    _assert_declared_defaults(partial, skip=("results_path",))


def test_parameter_config_minimal_dict_uses_dataclass_defaults() -> None:
    assert ParameterConfig.from_dict({}) == ParameterConfig()
    partial = ParameterConfig.from_dict({"required": True})
    assert partial.required is True
    _assert_declared_defaults(partial, skip=("required",))


def test_tool_config_minimal_dict_uses_dataclass_defaults() -> None:
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
    config = SearchSourceConfig.from_dict({"tool": "arxiv_search"})
    assert config == SearchSourceConfig(tool="arxiv_search")
    _assert_declared_defaults(config)
    assert SearchSourceConfig.from_dict("arxiv_search") == config


def test_workflow_config_minimal_dict_uses_dataclass_defaults() -> None:
    assert WorkflowConfig.from_dict({}) == WorkflowConfig()
    partial = WorkflowConfig.from_dict({"primary_search": "pubmed_search"})
    assert partial.primary_search == "pubmed_search"
    _assert_declared_defaults(partial, skip=("primary_search",))


def test_workflow_config_parses_nested_search_sources() -> None:
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
    config = EnrichmentConfig.from_dict({"tool": "nvd_cve_search"})
    assert config == EnrichmentConfig(tool="nvd_cve_search")
    _assert_declared_defaults(config)


def test_prompts_config_minimal_dict_uses_dataclass_defaults() -> None:
    assert PromptsConfig.from_dict({}) == PromptsConfig()
    partial = PromptsConfig.from_dict({"domain_context": "ctx"})
    assert partial.domain_context == "ctx"
    _assert_declared_defaults(partial, skip=("domain_context",))


def test_tools_config_minimal_dict_uses_dataclass_defaults() -> None:
    assert ToolsConfig.from_dict({}) == ToolsConfig()
    partial = ToolsConfig.from_dict({"version": "3.1"})
    assert partial.version == "3.1"
    _assert_declared_defaults(partial, skip=("version",))


def test_unknown_keys_are_ignored() -> None:
    config = WorkflowConfig.from_dict(
        {
            "primary_search": "pubmed_search",
            "bogus_key": "ignored",
        }
    )
    assert config.primary_search == "pubmed_search"
    assert not hasattr(config, "bogus_key")


def test_yaml_tool_id_is_not_read_from_yaml() -> None:
    config = ToolConfig.from_dict({"_yaml_tool_id": "sneaky"}, tool_id="t1")
    assert config._yaml_tool_id is None


def test_explicit_null_overrides_default_when_key_present() -> None:
    """Shipped YAML uses explicit nulls, which must not become absent keys."""
    config = WorkflowConfig.from_dict({"availability_check": None})
    assert config.availability_check is None
    tool = ToolConfig.from_dict({"applies_to": None}, tool_id="t1")
    assert tool.applies_to is None


def test_from_dict_tolerates_an_empty_yaml_section() -> None:
    """An empty YAML section parses to None rather than an empty dict."""
    assert PromptsConfig.from_dict(None) == PromptsConfig()  # type: ignore[arg-type]
    assert ResponseFormat.from_dict(None) == ResponseFormat()  # type: ignore[arg-type]
    assert ParameterConfig.from_dict(None) == ParameterConfig()  # type: ignore[arg-type]
    assert WorkflowConfig.from_dict(None) == WorkflowConfig()  # type: ignore[arg-type]


def test_recency_years_to_starting_year_positive_value() -> None:
    current_year = datetime.datetime.now().year
    assert _recency_years_to_starting_year(7) == current_year - 7


def test_recency_years_to_starting_year_zero_is_none() -> None:
    assert _recency_years_to_starting_year(0) is None


def test_recency_years_to_starting_year_negative_is_none() -> None:
    assert _recency_years_to_starting_year(-3) is None


def test_map_parameters_without_mapping_returns_as_is() -> None:
    tool = ToolConfig(server="s1", mcp_tool_name="search")
    result = tool.map_parameters({"query": "cancer", "max_papers": 5})
    assert result == {"query": "cancer", "max_papers": 5}


def test_map_parameters_converts_recency_years_to_starting_year() -> None:
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"recency_years": "starting_year"},
    )
    current_year = datetime.datetime.now().year

    result = tool.map_parameters({"recency_years": 5})

    assert result == {"starting_year": current_year - 5}


def test_map_parameters_recency_years_zero_maps_to_none() -> None:
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"recency_years": "starting_year"},
    )
    result = tool.map_parameters({"recency_years": 0})
    assert result == {"starting_year": None}


def test_map_parameters_renames_without_recency_conversion() -> None:
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"max_papers": "max_results"},
    )
    result = tool.map_parameters({"max_papers": 10})
    assert result == {"max_results": 10}


def test_map_parameters_null_mapping_drops_parameter() -> None:
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"unused_param": None},
    )
    result = tool.map_parameters({"unused_param": "x", "query": "cancer"})
    assert result == {"query": "cancer"}


def test_map_parameters_unmapped_key_uses_canonical_name() -> None:
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"max_papers": "max_results"},
    )
    result = tool.map_parameters({"query": "cancer"})
    assert result == {"query": "cancer"}


def test_both_dicts_true_when_both_are_dicts() -> None:
    assert _both_dicts({"a": 1}, {"b": 2}) is True


def test_both_dicts_false_when_existing_is_not_a_dict() -> None:
    assert _both_dicts([1, 2], {"a": 1}) is False


def test_both_dicts_false_when_value_is_not_a_dict() -> None:
    assert _both_dicts({"a": 1}, [1, 2]) is False


def test_both_dicts_false_when_neither_is_a_dict() -> None:
    assert _both_dicts("x", "y") is False


def test_both_lists_to_extend_true_for_extend_strategy_and_lists() -> None:
    assert _both_lists_to_extend([1], [2], "extend") is True


def test_both_lists_to_extend_false_for_non_extend_strategy() -> None:
    assert _both_lists_to_extend([1], [2], "override") is False


def test_both_lists_to_extend_false_when_existing_is_not_a_list() -> None:
    assert _both_lists_to_extend("a", [2], "extend") is False


def test_both_lists_to_extend_false_when_value_is_not_a_list() -> None:
    assert _both_lists_to_extend([1], "b", "extend") is False


def test_determine_merge_strategy_defaults_to_override_with_no_configs() -> (
    None
):
    assert _determine_merge_strategy(None, None) == "override"


def test_determine_merge_strategy_neither_has_settings_key() -> None:
    assert _determine_merge_strategy({"foo": 1}, {"bar": 2}) == "override"


def test_determine_merge_strategy_uses_custom_settings_when_present() -> None:
    custom = {"settings": {"merge_strategy": "extend"}}
    assert _determine_merge_strategy(None, custom) == "extend"


def test_determine_merge_strategy_custom_wins_over_user() -> None:
    user = {"settings": {"merge_strategy": "replace"}}
    custom = {"settings": {"merge_strategy": "extend"}}
    assert _determine_merge_strategy(user, custom) == "extend"


def test_determine_merge_strategy_falls_back_to_user_settings() -> None:
    user = {"settings": {"merge_strategy": "extend"}}
    assert _determine_merge_strategy(user, None) == "extend"


def test_determine_merge_strategy_custom_without_settings_falls_to_user() -> (
    None
):
    user = {"settings": {"merge_strategy": "extend"}}
    custom = {"other_key": True}
    assert _determine_merge_strategy(user, custom) == "extend"


def test_determine_merge_strategy_settings_present_without_merge_key() -> None:
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
    assert resolve_content_params({"value": value}, context) == {
        "value": expected
    }


def test_resolve_content_params_empty_params_returns_empty_dict() -> None:
    assert resolve_content_params({}, {"research_goal": "X"}) == {}


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


def test_resolve_content_params_leaves_nested_containers_untouched() -> None:
    nested = {"inner": "{x}"}
    result = resolve_content_params(
        {"nested": nested, "list": [nested]}, {"x": "y"}
    )
    assert result["nested"] is nested
    assert result["list"][0] is nested

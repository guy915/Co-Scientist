from __future__ import annotations

import datetime
from typing import Any

import pytest

from co_scientist.config.schema import (
    ParameterConfig,
    PromptsConfig,
    ResponseFormat,
    SearchSourceConfig,
    ToolConfig,
    WorkflowConfig,
    resolve_content_params,
)


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


def test_unknown_keys_are_ignored() -> None:
    config = WorkflowConfig.from_dict(
        {
            "primary_search": "pubmed_search",
            "bogus_key": "ignored",
        }
    )
    assert config.primary_search == "pubmed_search"
    assert not hasattr(config, "bogus_key")


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


@pytest.mark.parametrize(
    ("mapping", "params", "expected"),
    [
        (
            None,
            {"query": "cancer", "max_papers": 5},
            {"query": "cancer", "max_papers": 5},
        ),
        (
            {"max_papers": "max_results"},
            {"max_papers": 10, "query": "q"},
            {"max_results": 10, "query": "q"},
        ),
        (
            {"unused_param": None},
            {"unused_param": "x", "query": "q"},
            {"query": "q"},
        ),
        (
            {"recency_years": "starting_year"},
            {"recency_years": 0},
            {"starting_year": None},
        ),
    ],
)
def test_map_parameters_renames_and_drops_per_tool_mapping(
    mapping: dict[str, str | None] | None,
    params: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    tool = ToolConfig(
        server="s1", mcp_tool_name="search", parameter_mapping=mapping or {}
    )
    assert tool.map_parameters(params) == expected


def test_map_parameters_converts_recency_years_to_starting_year() -> None:
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"recency_years": "starting_year"},
    )
    result = tool.map_parameters({"recency_years": 5})
    assert result == {"starting_year": datetime.datetime.now().year - 5}

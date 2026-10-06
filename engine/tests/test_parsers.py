from __future__ import annotations

from typing import Any

import pytest

from co_scientist.config.schema import ResponseFormat, ToolConfig
from co_scientist.llm import coerce_json_list
from co_scientist.tools.response_parser import ResponseParser


@pytest.mark.parametrize(
    ("value", "kwargs", "expected"),
    [
        ([{"a": 1}, "x", {"a": 2}], {"element": "dict"}, [{"a": 1}, {"a": 2}]),
        ({"a": 1}, {"element": "dict"}, [{"a": 1}]),
        (
            {"items": [{"a": 1}]},
            {"element": "dict", "keys": ("items",)},
            [{"a": 1}],
        ),
        (None, {"element": "dict"}, []),
        ("just a string", {"element": "dict"}, []),
        ("single query", {"element": "str"}, ["single query"]),
        ("   ", {"element": "str"}, []),
        ([" a ", "", "b", 42, None], {"element": "str"}, ["a", "b"]),
    ],
)
def test_coerce_json_list_keeps_only_well_typed_elements(
    value: Any, kwargs: dict[str, Any], expected: list[Any]
) -> None:
    assert coerce_json_list(value, site="s", **kwargs) == expected


@pytest.mark.parametrize(
    ("response_format", "raw", "expected"),
    [
        (ResponseFormat(), '{"k": 1}', {"k": 1}),
        (ResponseFormat(), "  [1, 2]  ", [1, 2]),
        (ResponseFormat(), "not json", "not json"),
        (ResponseFormat(), {"already": "parsed"}, {"already": "parsed"}),
        (ResponseFormat(type="boolean_string"), "True", True),
        (ResponseFormat(type="boolean_string"), "nope", False),
    ],
)
def test_parse_response_decodes_by_response_format(
    response_format: ResponseFormat, raw: Any, expected: Any
) -> None:
    tc = ToolConfig(
        server="s", mcp_tool_name="t", response_format=response_format
    )
    assert ResponseParser(tc).parse_response(raw) == expected


def _search_tool(**format_kwargs: Any) -> ToolConfig:
    return ToolConfig(
        server="s",
        mcp_tool_name="t",
        category="search",
        source_type="preprint",
        response_format=ResponseFormat(type="json", **format_kwargs),
    )


def test_parse_to_articles_navigates_paths_and_applies_transforms() -> None:
    tool = _search_tool(
        results_path="data.hits",
        field_mapping={
            "title": "meta.names[1]",
            "year": "date|split:/|index:0|int",
            "authors": "authors|wrap_list",
            "venue": "venue|default:N/A",
        },
    )
    response = {
        "data": {
            "hits": [
                {
                    "meta": {"names": ["x", "Paper One"]},
                    "date": "2021/01/02",
                    "authors": "X Y",
                },
                {"no_name": "skipped: no title"},
            ]
        }
    }
    (art,) = ResponseParser(tool).parse_to_articles(response)
    assert art.title == "Paper One"
    assert art.year == 2021
    assert art.authors == ["X Y"]
    assert art.venue == "N/A"
    assert art.source == "preprint"
    assert art.used_in_analysis is True


def test_parse_to_articles_of_a_null_response_is_empty() -> None:
    tool = _search_tool(results_path=".", field_mapping={"title": "name"})
    assert ResponseParser(tool).parse_to_articles("null") == []

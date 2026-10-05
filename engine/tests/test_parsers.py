from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.config.schema import ResponseFormat, ToolConfig
from co_scientist.exceptions import (
    LLMBudgetExhaustedError,
    LLMThinkingOnlyError,
)
from co_scientist.llm import coerce_json_list, parse_tool_loop_json
from co_scientist.llm.request.response import (
    TokenUsage,
    _extract_completion_content,
    extract_token_usage,
)
from co_scientist.llm.structured.validate import _try_minor_repairs
from co_scientist.tools.response_parser import ResponseParser

_JUDGEMENT = (
    '{\n  "comparison": "Hypothesis B commits to a negative control.\n\n'
    'better idea: 2",\n  "confidence_level": "High"\n}'
)


def test_repair_keeps_line_breaks_in_strings_and_refuses_truncation() -> None:
    repaired = _try_minor_repairs(_JUDGEMENT)
    assert repaired is not None
    assert repaired["confidence_level"] == "High"
    assert "\n\nbetter idea: 2" in repaired["comparison"]
    assert _try_minor_repairs('{"a": "one\ttwo"}') == {"a": "one\ttwo"}
    assert _try_minor_repairs('{"a": "unterminated') is None


def test_parse_tool_loop_json_single_dict_becomes_one_item(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    single_draft = (
        '{"drafts": {"hypothesis": "h", "explanation": "e", '
        '"gap_reasoning": "g", "literature_sources": "[C1]", '
        '"experiment": "x"}}'
    )

    result = parse_tool_loop_json(single_draft, "drafts", "Draft phase")

    assert result == [
        {
            "hypothesis": "h",
            "explanation": "e",
            "gap_reasoning": "g",
            "literature_sources": "[C1]",
            "experiment": "x",
        }
    ]
    assert "Draft phase" in caplog.text


def test_extract_token_usage_reads_all_fields() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=45,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=30),
        )
    )
    assert extract_token_usage(response) == TokenUsage(120, 45, 30)


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


def test_coerce_json_list_warns_only_when_it_coerced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    coerce_json_list([{"a": 1}], element="dict", site="draft phase")
    coerce_json_list(None, element="dict", site="draft phase")
    assert caplog.text == ""
    coerce_json_list({"a": 1}, element="dict", site="draft phase")
    assert "draft phase" in caplog.text


def _empty_response(
    finish_reason: str | None, reasoning_tokens: int
) -> SimpleNamespace:
    message = SimpleNamespace(content=None)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=reasoning_tokens,
        completion_tokens_details=SimpleNamespace(
            reasoning_tokens=reasoning_tokens
        ),
    )
    return SimpleNamespace(choices=[choice], usage=usage)


@pytest.mark.parametrize(
    ("finish_reason", "reasoning_tokens", "raised"),
    [
        # An upstream mid-stream error must stay a plain retryable failure so
        # later attempts do not disable thinking.
        ("error", 519, ValueError),
        ("stop", 1149, LLMThinkingOnlyError),
        ("length", 18000, LLMBudgetExhaustedError),
    ],
)
def test_empty_completion_is_classified_by_finish_reason(
    finish_reason: str, reasoning_tokens: int, raised: type[Exception]
) -> None:
    response = _empty_response(finish_reason, reasoning_tokens)
    with pytest.raises(raised) as caught:
        _extract_completion_content(response, "openrouter/z-ai/glm-5.3-flash")
    assert type(caught.value) is raised


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


def test_parse_to_articles_maps_dict_keyed_results() -> None:
    tool = _search_tool(
        results_path=".",
        is_dict=True,
        field_mapping={
            "title": "title",
            "source_id": "@key",
            "url": "@url_from_key",
        },
    )
    (art,) = ResponseParser(tool).parse_to_articles(
        {"12345": {"title": "KG paper"}}
    )
    assert art.source_id == "12345"
    assert art.url == "https://pubmed.ncbi.nlm.nih.gov/12345/"


def test_parse_to_articles_of_a_null_response_is_empty() -> None:
    tool = _search_tool(results_path=".", field_mapping={"title": "name"})
    assert ResponseParser(tool).parse_to_articles("null") == []

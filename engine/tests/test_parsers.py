from __future__ import annotations

import json
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


def test_a_raw_newline_inside_a_string_is_not_valid_json() -> None:
    """An escaped newline would stop exercising invalid JSON repair."""
    try:
        json.loads(_JUDGEMENT)
    except json.JSONDecodeError as exc:
        assert "control character" in str(exc)
    else:  # pragma: no cover - the fixture would no longer test anything
        raise AssertionError("fixture is valid JSON; it tests nothing")


def test_prose_with_a_line_break_survives_repair() -> None:
    repaired = _try_minor_repairs(_JUDGEMENT)

    assert repaired is not None
    assert repaired["confidence_level"] == "High"
    assert "\n\nbetter idea: 2" in repaired["comparison"]


def test_a_tab_inside_a_string_survives_too() -> None:
    repaired = _try_minor_repairs('{"a": "one\ttwo"}')

    assert repaired is not None
    assert repaired["a"] == "one\ttwo"


def test_repair_still_refuses_genuinely_broken_json() -> None:
    """Truncation repair belongs to major strategies on the final attempt."""
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


def test_coerce_json_list_passes_a_well_typed_list_through() -> None:
    items = [{"a": 1}, {"a": 2}]
    assert coerce_json_list(items, element="dict", site="s") == items


def test_coerce_json_list_wraps_a_single_dict() -> None:
    assert coerce_json_list({"a": 1}, element="dict", site="s") == [{"a": 1}]


def test_coerce_json_list_drops_wrong_typed_elements() -> None:
    result = coerce_json_list(
        [{"a": 1}, "not a dict", {"a": 2}], element="dict", site="s"
    )
    assert result == [{"a": 1}, {"a": 2}]


def test_coerce_json_list_finds_the_list_under_a_plausible_key() -> None:
    value = {"items": [{"a": 1}]}
    result = coerce_json_list(value, keys=("items",), element="dict", site="s")
    assert result == [{"a": 1}]


def test_coerce_json_list_none_is_empty() -> None:
    assert coerce_json_list(None, element="dict", site="s") == []


def test_coerce_json_list_scalar_that_cannot_be_a_dict_is_empty() -> None:
    assert coerce_json_list("just a string", element="dict", site="s") == []


def test_coerce_json_list_str_wraps_a_bare_string() -> None:
    assert coerce_json_list("single query", element="str", site="s") == [
        "single query"
    ]


def test_coerce_json_list_str_blank_string_is_empty() -> None:
    assert coerce_json_list("   ", element="str", site="s") == []


def test_coerce_json_list_str_strips_and_drops_blank_elements() -> None:
    result = coerce_json_list([" a ", "", "b"], element="str", site="s")
    assert result == ["a", "b"]


def test_coerce_json_list_warns_with_the_site_when_coerced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    coerce_json_list({"a": 1}, element="dict", site="draft phase")
    assert "draft phase" in caplog.text


def test_coerce_json_list_no_warning_for_an_already_valid_list(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    coerce_json_list([{"a": 1}], element="dict", site="draft phase")
    assert caplog.text == ""


def test_coerce_json_list_no_warning_for_a_genuinely_empty_list(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    coerce_json_list(None, element="dict", site="draft phase")
    assert caplog.text == ""


def test_coerce_json_list_str_element_returns_only_str_instances() -> None:
    """Static overload checks cannot prove the runtime element types."""
    result = coerce_json_list(
        ["a query", 42, None, {"nested": "dict"}, "another query"],
        element="str",
        site="s",
    )
    assert result == ["a query", "another query"]
    assert all(isinstance(item, str) for item in result)


def test_coerce_json_list_dict_element_returns_only_dict_instances() -> None:
    result = coerce_json_list(
        [{"a": 1}, "a string", 42, None, {"b": 2}],
        element="dict",
        site="s",
    )
    assert result == [{"a": 1}, {"b": 2}]
    assert all(isinstance(item, dict) for item in result)


def test_extract_token_usage_reads_all_fields() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=45,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=30),
        )
    )
    assert extract_token_usage(response) == TokenUsage(120, 45, 30)


def test_extract_token_usage_defaults_missing_usage_to_zero() -> None:
    response = SimpleNamespace(choices=[])
    assert extract_token_usage(response) == TokenUsage(0, 0, 0)


def test_extract_token_usage_defaults_missing_reasoning_to_zero() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    )
    assert extract_token_usage(response) == TokenUsage(10, 5, 0)


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


def test_finish_reason_error_is_a_plain_retryable_failure() -> None:
    """Upstream mid-stream errors must not disable thinking on later
    attempts."""
    response = _empty_response("error", reasoning_tokens=519)

    with pytest.raises(ValueError) as caught:
        _extract_completion_content(response, "openrouter/z-ai/glm-5.3-flash")

    assert type(caught.value) is ValueError
    assert "error" in str(caught.value).lower()


def test_finish_reason_stop_with_reasoning_still_classifies_thinking_only() -> (
    None
):
    response = _empty_response("stop", reasoning_tokens=1149)

    with pytest.raises(LLMThinkingOnlyError):
        _extract_completion_content(response, "openrouter/z-ai/glm-5.3-flash")


def test_finish_reason_length_still_classifies_budget_exhausted() -> None:
    response = _empty_response("length", reasoning_tokens=18000)

    with pytest.raises(LLMBudgetExhaustedError):
        _extract_completion_content(response, "openrouter/z-ai/glm-5.3-flash")


def _parser(
    response_format: ResponseFormat | None = None, **tool_kwargs: Any
) -> ResponseParser:
    tc = ToolConfig(
        server="s",
        mcp_tool_name="t",
        response_format=response_format or ResponseFormat(),
        **tool_kwargs,
    )
    return ResponseParser(tc)


def test_parse_response_valid_json_string() -> None:
    assert _parser().parse_response('{"k": 1}') == {"k": 1}


def test_parse_response_strips_whitespace_before_decode() -> None:
    assert _parser().parse_response("  [1, 2]  ") == [1, 2]


def test_parse_response_invalid_json_returns_raw_string() -> None:
    assert _parser().parse_response("not json") == "not json"


def test_parse_response_passes_through_non_string() -> None:
    payload = {"already": "parsed"}
    assert _parser().parse_response(payload) is payload


def test_parse_response_boolean_string_true() -> None:
    p = _parser(ResponseFormat(type="boolean_string"))
    assert p.parse_response("True") is True


def test_parse_response_boolean_string_false() -> None:
    p = _parser(ResponseFormat(type="boolean_string"))
    assert p.parse_response("nope") is False


def test_navigate_root_with_dot() -> None:
    data = {"a": 1}
    assert _parser()._navigate_path(data, ".") is data


def test_navigate_root_with_empty_path() -> None:
    data = {"a": 1}
    assert _parser()._navigate_path(data, "") is data


def test_navigate_nested_key() -> None:
    assert _parser()._navigate_path({"a": {"b": 2}}, "a.b") == 2


def test_navigate_array_index() -> None:
    assert _parser()._navigate_path({"a": [10, 20]}, "a[1]") == 20


def test_navigate_array_index_out_of_range_returns_none() -> None:
    assert _parser()._navigate_path({"a": [10]}, "a[5]") is None


def test_navigate_missing_key_returns_none() -> None:
    assert _parser()._navigate_path({"a": 1}, "x.y") is None


def test_navigate_through_non_dict_returns_none() -> None:
    assert _parser()._navigate_path({"a": 5}, "a.b") is None


def test_transform_split() -> None:
    assert _parser()._apply_transform("split:/", "2023/01/02") == [
        "2023",
        "01",
        "02",
    ]


def test_transform_index() -> None:
    assert _parser()._apply_transform("index:0", ["a", "b"]) == "a"


def test_transform_index_out_of_range_returns_none() -> None:
    assert _parser()._apply_transform("index:5", ["a"]) is None


def test_transform_int_valid() -> None:
    assert _parser()._apply_transform("int", "42") == 42


def test_transform_int_invalid_returns_none() -> None:
    assert _parser()._apply_transform("int", "xx") is None


def test_transform_float_valid() -> None:
    assert _parser()._apply_transform("float", "3.5") == 3.5


def test_transform_default_on_none_coerces_int() -> None:
    result = _parser()._apply_transform("default:0", None)
    assert result == 0
    assert isinstance(result, int)


def test_transform_default_on_none_keeps_non_numeric_string() -> None:
    assert _parser()._apply_transform("default:N/A", None) == "N/A"


def test_transform_wrap_list_scalar() -> None:
    assert _parser()._apply_transform("wrap_list", "x") == ["x"]


def test_transform_wrap_list_passes_through_list() -> None:
    assert _parser()._apply_transform("wrap_list", ["x"]) == ["x"]


def test_transform_wrap_list_none_returns_none() -> None:
    assert _parser()._apply_transform("wrap_list", None) is None


def test_transform_unknown_passes_value_through() -> None:
    assert _parser()._apply_transform("zzz", "keepme") == "keepme"


def test_evaluate_static_quoted_string() -> None:
    assert _parser()._evaluate_expression("'pubmed'", {}) == "pubmed"


def test_evaluate_key_token() -> None:
    assert _parser()._evaluate_expression("@key", {}, dict_key="abc") == "abc"


def test_evaluate_url_from_key() -> None:
    result = _parser()._evaluate_expression("@url_from_key", {}, dict_key="123")
    assert result == "https://pubmed.ncbi.nlm.nih.gov/123/"


def test_evaluate_url_from_key_none_when_no_key() -> None:
    assert _parser()._evaluate_expression("@url_from_key", {}) is None


def test_evaluate_simple_field_access() -> None:
    assert _parser()._evaluate_expression("title", {"title": "T"}) == "T"


def test_evaluate_transform_chain() -> None:
    result = _parser()._evaluate_expression(
        "date|split:/|index:0|int", {"date": "2023/01/02"}
    )
    assert result == 2023


def test_parse_to_articles_list_search_maps_articles() -> None:
    rf = ResponseFormat(
        type="json",
        results_path="results",
        is_dict=False,
        field_mapping={
            "title": "name",
            "year": "pub_year|int",
            "authors": "authors",
        },
    )
    tc = ToolConfig(
        server="s",
        mcp_tool_name="t",
        category="search",
        source_type="preprint",
        response_format=rf,
    )
    resp = {
        "results": [
            {"name": "Paper One", "pub_year": "2021", "authors": ["X Y"]}
        ]
    }
    articles = ResponseParser(tc).parse_to_articles(resp)
    assert len(articles) == 1
    art = articles[0]
    assert art.title == "Paper One"
    assert art.year == 2021
    assert art.authors == ["X Y"]
    assert art.source == "preprint"
    assert art.used_in_analysis is True


def test_parse_to_articles_skips_items_without_title() -> None:
    rf = ResponseFormat(
        type="json",
        results_path="results",
        field_mapping={"title": "name"},
    )
    tc = ToolConfig(
        server="s", mcp_tool_name="t", category="search", response_format=rf
    )
    resp = {"results": [{"name": "Has Title"}, {"no_name": "x"}]}
    articles = ResponseParser(tc).parse_to_articles(resp)
    assert [a.title for a in articles] == ["Has Title"]


def test_parse_to_articles_dict_results_with_key_mapping() -> None:
    rf = ResponseFormat(
        type="json",
        results_path=".",
        is_dict=True,
        field_mapping={
            "title": "title",
            "source_id": "@key",
            "url": "@url_from_key",
        },
    )
    tc = ToolConfig(
        server="s", mcp_tool_name="t", category="search", response_format=rf
    )
    resp = {"12345": {"title": "KG paper"}}
    articles = ResponseParser(tc).parse_to_articles(resp)
    assert len(articles) == 1
    art = articles[0]
    assert art.title == "KG paper"
    assert art.source_id == "12345"
    assert art.url == "https://pubmed.ncbi.nlm.nih.gov/12345/"


def test_parse_to_articles_boolean_category() -> None:
    tc = ToolConfig(
        server="s",
        mcp_tool_name="t",
        category="utility",
        response_format=ResponseFormat(type="boolean_string"),
    )
    assert ResponseParser(tc).parse_response("true") is True


def test_parse_to_articles_non_search_returns_raw() -> None:
    tc = ToolConfig(
        server="s",
        mcp_tool_name="t",
        category="read",
        response_format=ResponseFormat(),
    )
    assert ResponseParser(tc).parse_response('{"a": 1}') == {"a": 1}


def test_parse_to_articles_none_response_returns_empty() -> None:
    rf = ResponseFormat(results_path=".", field_mapping={"title": "name"})
    tc = ToolConfig(
        server="s", mcp_tool_name="t", category="search", response_format=rf
    )
    assert ResponseParser(tc).parse_to_articles("null") == []

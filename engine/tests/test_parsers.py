"""Offline contracts for parsers."""

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
    """The premise: this is a parse error, not a strict-mode preference.

    Pinned so the fixture cannot quietly stop exercising the defect -- an
    escaped newline would make every assertion below pass for the wrong
    reason.
    """
    try:
        json.loads(_JUDGEMENT)
    except json.JSONDecodeError as exc:
        assert "control character" in str(exc)
    else:  # pragma: no cover - the fixture would no longer test anything
        raise AssertionError("fixture is valid JSON; it tests nothing")


def test_prose_with_a_line_break_survives_repair() -> None:
    """The field is recovered whole, newline and all.

    The newline is content the model meant to write, so it has to arrive in
    the value rather than being stripped: this text is read back by a human
    in a report, and by the ranking node as a verdict.
    """
    repaired = _try_minor_repairs(_JUDGEMENT)

    assert repaired is not None
    assert repaired["confidence_level"] == "High"
    assert "\n\nbetter idea: 2" in repaired["comparison"]


def test_a_tab_inside_a_string_survives_too() -> None:
    """Newline is the common case, not the only illegal character."""
    repaired = _try_minor_repairs('{"a": "one\ttwo"}')

    assert repaired is not None
    assert repaired["a"] == "one\ttwo"


def test_repair_still_refuses_genuinely_broken_json() -> None:
    """Loosening one rule must not make the ladder accept anything.

    A truncated object is the failure the *major* strategies exist to
    handle, on the final attempt only, because it means something was lost.
    Admitting it here would spend that distinction.
    """
    assert _try_minor_repairs('{"a": "unterminated') is None


# -----------------------------------------------------------------------------
# parse_tool_loop_json -- the real, schema-less call site
# -----------------------------------------------------------------------------


def test_parse_tool_loop_json_single_dict_becomes_one_item(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A single draft object, not wrapped in a list, becomes one-item list.

    This is the tool-based drafting phase's real final response shape when
    a model asked for a list of one plausibly writes the single object
    directly (see ``agents/generation/literature_tools/draft.py``, whose
    prompt asks for a "drafts" array of objects).
    """
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


# -----------------------------------------------------------------------------
# coerce_json_list -- element="dict"
# -----------------------------------------------------------------------------


def test_coerce_json_list_passes_a_well_typed_list_through() -> None:
    """A list of dicts already in the right shape is returned unchanged."""
    items = [{"a": 1}, {"a": 2}]
    assert coerce_json_list(items, element="dict", site="s") == items


def test_coerce_json_list_wraps_a_single_dict() -> None:
    """A bare dict, the single element wanted, becomes a one-item list."""
    assert coerce_json_list({"a": 1}, element="dict", site="s") == [{"a": 1}]


def test_coerce_json_list_drops_wrong_typed_elements() -> None:
    """A list mixing dicts with a stray string drops the string."""
    result = coerce_json_list(
        [{"a": 1}, "not a dict", {"a": 2}], element="dict", site="s"
    )
    assert result == [{"a": 1}, {"a": 2}]


def test_coerce_json_list_finds_the_list_under_a_plausible_key() -> None:
    """A dict wrapping the list under one of the caller's known keys."""
    value = {"items": [{"a": 1}]}
    result = coerce_json_list(value, keys=("items",), element="dict", site="s")
    assert result == [{"a": 1}]


def test_coerce_json_list_none_is_empty() -> None:
    """A missing value coerces to an empty list, not an error."""
    assert coerce_json_list(None, element="dict", site="s") == []


def test_coerce_json_list_scalar_that_cannot_be_a_dict_is_empty() -> None:
    """A bare string where dict elements were wanted yields no elements."""
    assert coerce_json_list("just a string", element="dict", site="s") == []


# -----------------------------------------------------------------------------
# coerce_json_list -- element="str"
# -----------------------------------------------------------------------------


def test_coerce_json_list_str_wraps_a_bare_string() -> None:
    """A bare string where a list of strings was wanted is one element."""
    assert coerce_json_list("single query", element="str", site="s") == [
        "single query"
    ]


def test_coerce_json_list_str_blank_string_is_empty() -> None:
    """A blank string is dropped, not kept as an empty element."""
    assert coerce_json_list("   ", element="str", site="s") == []


def test_coerce_json_list_str_strips_and_drops_blank_elements() -> None:
    """String elements are stripped; blank ones are dropped."""
    result = coerce_json_list([" a ", "", "b"], element="str", site="s")
    assert result == ["a", "b"]


# -----------------------------------------------------------------------------
# Coercion warning
# -----------------------------------------------------------------------------


def test_coerce_json_list_warns_with_the_site_when_coerced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A shape that needed coercion logs a warning naming the call site."""
    caplog.set_level(logging.WARNING)
    coerce_json_list({"a": 1}, element="dict", site="draft phase")
    assert "draft phase" in caplog.text


def test_coerce_json_list_no_warning_for_an_already_valid_list(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A list already in the right shape needs no warning."""
    caplog.set_level(logging.WARNING)
    coerce_json_list([{"a": 1}], element="dict", site="draft phase")
    assert caplog.text == ""


def test_coerce_json_list_no_warning_for_a_genuinely_empty_list(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """None (a genuinely absent value) needs no warning either."""
    caplog.set_level(logging.WARNING)
    coerce_json_list(None, element="dict", site="draft phase")
    assert caplog.text == ""


# -----------------------------------------------------------------------------
# Overload contract -- runtime evidence for what the type overloads promise
# -----------------------------------------------------------------------------


def test_coerce_json_list_str_element_returns_only_str_instances() -> None:
    """element="str" really yields str instances, not the mixed input types.

    The three @overload stubs on coerce_json_list promise list[str] for
    element="str" and list[dict[str, Any]] for element="dict"; mypy checks
    the promise against the declared return types, not against what the
    function actually does at runtime. This pins the runtime side: a
    mixed-type input still comes back as nothing but the promised type.
    """
    result = coerce_json_list(
        ["a query", 42, None, {"nested": "dict"}, "another query"],
        element="str",
        site="s",
    )
    assert result == ["a query", "another query"]
    assert all(isinstance(item, str) for item in result)


def test_coerce_json_list_dict_element_returns_only_dict_instances() -> None:
    """element="dict" really yields dict instances, not mixed input types."""
    result = coerce_json_list(
        [{"a": 1}, "a string", 42, None, {"b": 2}],
        element="dict",
        site="s",
    )
    assert result == [{"a": 1}, {"b": 2}]
    assert all(isinstance(item, dict) for item in result)


def test_extract_token_usage_reads_all_fields() -> None:
    """Reads prompt, completion, and reasoning tokens off a full response."""
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=45,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=30),
        )
    )
    assert extract_token_usage(response) == TokenUsage(120, 45, 30)


def test_extract_token_usage_defaults_missing_usage_to_zero() -> None:
    """A response with no ``usage`` attribute at all reads as all-zero.

    This is exactly the offline backend's response shape (see
    ``offline.llm._build_response``), so telemetry never raises on it.
    """
    response = SimpleNamespace(choices=[])
    assert extract_token_usage(response) == TokenUsage(0, 0, 0)


def test_extract_token_usage_defaults_missing_reasoning_to_zero() -> None:
    """A provider that omits reasoning tokens reads as zero, not None."""
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    )
    assert extract_token_usage(response) == TokenUsage(10, 5, 0)


# --- classifying an empty completion (_extract_completion_content) ---------


def _empty_response(
    finish_reason: str | None, reasoning_tokens: int
) -> SimpleNamespace:
    """A response with no content, at a given finish reason/reasoning spend."""
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
    """A mid-stream provider error is not a thinking-only response.

    OpenRouter reports an upstream failure mid-stream as
    ``finish_reason="error"``, which production hit repeatedly (reasoning
    tokens spent, no answer). The model did not choose to stop -- the
    provider errored -- so this must not disable thinking for every later
    attempt; it is answered by a plain retry instead.
    """
    response = _empty_response("error", reasoning_tokens=519)

    with pytest.raises(ValueError) as caught:
        _extract_completion_content(response, "openrouter/z-ai/glm-5.3-flash")

    assert type(caught.value) is ValueError
    assert "error" in str(caught.value).lower()


def test_finish_reason_stop_with_reasoning_still_classifies_thinking_only() -> (
    None
):
    """The genuine case is untouched: a normal stop with no answer.

    Pins that narrowing the classification to exclude provider errors did
    not also narrow out the case it exists for.
    """
    response = _empty_response("stop", reasoning_tokens=1149)

    with pytest.raises(LLMThinkingOnlyError):
        _extract_completion_content(response, "openrouter/z-ai/glm-5.3-flash")


def test_finish_reason_length_still_classifies_budget_exhausted() -> None:
    """``finish_reason="length"`` is checked, and wins, before "error" is."""
    response = _empty_response("length", reasoning_tokens=18000)

    with pytest.raises(LLMBudgetExhaustedError):
        _extract_completion_content(response, "openrouter/z-ai/glm-5.3-flash")


def _parser(
    response_format: ResponseFormat | None = None, **tool_kwargs: Any
) -> ResponseParser:
    """Build a ResponseParser around a minimal ToolConfig."""
    tc = ToolConfig(
        server="s",
        mcp_tool_name="t",
        response_format=response_format or ResponseFormat(),
        **tool_kwargs,
    )
    return ResponseParser(tc)


# --- parse_response: decoding ----------------------------------------------


def test_parse_response_valid_json_string() -> None:
    """A valid JSON string is decoded into a Python object."""
    assert _parser().parse_response('{"k": 1}') == {"k": 1}


def test_parse_response_strips_whitespace_before_decode() -> None:
    """Surrounding whitespace is stripped before decoding."""
    assert _parser().parse_response("  [1, 2]  ") == [1, 2]


def test_parse_response_invalid_json_returns_raw_string() -> None:
    """A non-JSON string is returned unchanged (the fallback path)."""
    assert _parser().parse_response("not json") == "not json"


def test_parse_response_passes_through_non_string() -> None:
    """A response that is already a dict/list is passed through untouched."""
    payload = {"already": "parsed"}
    assert _parser().parse_response(payload) is payload


def test_parse_response_boolean_string_true() -> None:
    """A ``boolean_string`` response of ``True`` decodes to the bool True."""
    p = _parser(ResponseFormat(type="boolean_string"))
    assert p.parse_response("True") is True


def test_parse_response_boolean_string_false() -> None:
    """Any non-``true`` value under ``boolean_string`` decodes to False."""
    p = _parser(ResponseFormat(type="boolean_string"))
    assert p.parse_response("nope") is False


# --- _navigate_path --------------------------------------------------------


def test_navigate_root_with_dot() -> None:
    """A ``.`` path returns the root data unchanged."""
    data = {"a": 1}
    assert _parser()._navigate_path(data, ".") is data


def test_navigate_root_with_empty_path() -> None:
    """An empty path returns the root data unchanged."""
    data = {"a": 1}
    assert _parser()._navigate_path(data, "") is data


def test_navigate_nested_key() -> None:
    """Dot-separated paths descend into nested dicts."""
    assert _parser()._navigate_path({"a": {"b": 2}}, "a.b") == 2


def test_navigate_array_index() -> None:
    """``field[index]`` notation indexes into a list."""
    assert _parser()._navigate_path({"a": [10, 20]}, "a[1]") == 20


def test_navigate_array_index_out_of_range_returns_none() -> None:
    """An out-of-range array index yields None."""
    assert _parser()._navigate_path({"a": [10]}, "a[5]") is None


def test_navigate_missing_key_returns_none() -> None:
    """A path through a missing key yields None."""
    assert _parser()._navigate_path({"a": 1}, "x.y") is None


def test_navigate_through_non_dict_returns_none() -> None:
    """Descending into a non-dict leaf yields None."""
    assert _parser()._navigate_path({"a": 5}, "a.b") is None


# --- _apply_transform ------------------------------------------------------


def test_transform_split() -> None:
    """``split:DELIM`` splits a string on the delimiter."""
    assert _parser()._apply_transform("split:/", "2023/01/02") == [
        "2023",
        "01",
        "02",
    ]


def test_transform_index() -> None:
    """``index:N`` selects the Nth element of a sequence."""
    assert _parser()._apply_transform("index:0", ["a", "b"]) == "a"


def test_transform_index_out_of_range_returns_none() -> None:
    """``index:N`` out of range yields None."""
    assert _parser()._apply_transform("index:5", ["a"]) is None


def test_transform_int_valid() -> None:
    """``int`` coerces a numeric string to an int."""
    assert _parser()._apply_transform("int", "42") == 42


def test_transform_int_invalid_returns_none() -> None:
    """``int`` on a non-numeric value yields None."""
    assert _parser()._apply_transform("int", "xx") is None


def test_transform_float_valid() -> None:
    """``float`` coerces a numeric string to a float."""
    assert _parser()._apply_transform("float", "3.5") == 3.5


def test_transform_default_on_none_coerces_int() -> None:
    """``default:0`` on None returns int 0 (the int-first coercion quirk)."""
    result = _parser()._apply_transform("default:0", None)
    assert result == 0
    assert isinstance(result, int)


def test_transform_default_on_none_keeps_non_numeric_string() -> None:
    """``default:N/A`` on None returns the string unchanged when not numeric."""
    assert _parser()._apply_transform("default:N/A", None) == "N/A"


def test_transform_wrap_list_scalar() -> None:
    """``wrap_list`` wraps a scalar in a single-element list."""
    assert _parser()._apply_transform("wrap_list", "x") == ["x"]


def test_transform_wrap_list_passes_through_list() -> None:
    """``wrap_list`` leaves an existing list unchanged."""
    assert _parser()._apply_transform("wrap_list", ["x"]) == ["x"]


def test_transform_wrap_list_none_returns_none() -> None:
    """``wrap_list`` on None returns None (the None guard runs first)."""
    assert _parser()._apply_transform("wrap_list", None) is None


def test_transform_unknown_passes_value_through() -> None:
    """An unrecognized transform returns the value untouched."""
    assert _parser()._apply_transform("zzz", "keepme") == "keepme"


# --- _evaluate_expression --------------------------------------------------


def test_evaluate_static_quoted_string() -> None:
    """A single-quoted expression evaluates to its literal contents."""
    assert _parser()._evaluate_expression("'pubmed'", {}) == "pubmed"


def test_evaluate_key_token() -> None:
    """``@key`` evaluates to the supplied dict key."""
    assert _parser()._evaluate_expression("@key", {}, dict_key="abc") == "abc"


def test_evaluate_url_from_key() -> None:
    """``@url_from_key`` builds a PubMed URL from the dict key."""
    result = _parser()._evaluate_expression("@url_from_key", {}, dict_key="123")
    assert result == "https://pubmed.ncbi.nlm.nih.gov/123/"


def test_evaluate_url_from_key_none_when_no_key() -> None:
    """``@url_from_key`` returns None when no dict key is available."""
    assert _parser()._evaluate_expression("@url_from_key", {}) is None


def test_evaluate_simple_field_access() -> None:
    """A bare field name reads that key from the item."""
    assert _parser()._evaluate_expression("title", {"title": "T"}) == "T"


def test_evaluate_transform_chain() -> None:
    """A transform chain applies each transform left to right."""
    result = _parser()._evaluate_expression(
        "date|split:/|index:0|int", {"date": "2023/01/02"}
    )
    assert result == 2023


# --- parse_to_articles ------------------------------------------------------


def test_parse_to_articles_list_search_maps_articles() -> None:
    """A list search response maps each item to an Article via field_mapping."""
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
    """Items that map to an empty title are dropped from the result."""
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
    """``is_dict`` results expose the dict key via ``@key`` mappings."""
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
    """A ``boolean_string`` tool returns the decoded bool, not articles."""
    tc = ToolConfig(
        server="s",
        mcp_tool_name="t",
        category="utility",
        response_format=ResponseFormat(type="boolean_string"),
    )
    assert ResponseParser(tc).parse_response("true") is True


def test_parse_to_articles_non_search_returns_raw() -> None:
    """A non-search, non-boolean tool returns the raw parsed response."""
    tc = ToolConfig(
        server="s",
        mcp_tool_name="t",
        category="read",
        response_format=ResponseFormat(),
    )
    assert ResponseParser(tc).parse_response('{"a": 1}') == {"a": 1}


def test_parse_to_articles_none_response_returns_empty() -> None:
    """A ``null`` JSON response parses to an empty article list."""
    rf = ResponseFormat(results_path=".", field_mapping={"title": "name"})
    tc = ToolConfig(
        server="s", mcp_tool_name="t", category="search", response_format=rf
    )
    assert ResponseParser(tc).parse_to_articles("null") == []

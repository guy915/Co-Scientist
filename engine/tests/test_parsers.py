"""Tests for the MCP tool-response parser.

These tests lock in the *current* behavior of the pure parsing helpers in
``co_scientist.tools.response_parser`` - response decoding, path navigation,
expression evaluation, transform application, and Article mapping - as a
regression net for upcoming refactors. The parser performs no LLM or network
calls, so the tests run deterministically with no mocking.
"""

from typing import Any, cast

from co_scientist.config.schema import ResponseFormat
from co_scientist.config.schema import ToolConfig
from co_scientist.models import Article
from co_scientist.tools.response_parser import parse_tool_response
from co_scientist.tools.response_parser import ResponseParser


def _parser(response_format: ResponseFormat | None = None,
            **tool_kwargs: Any) -> ResponseParser:
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
    assert _parser().parse_response('  [1, 2]  ') == [1, 2]


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
    assert _parser()._apply_transform("split:/",
                                      "2023/01/02") == ["2023", "01", "02"]


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
    """``default:0`` on None returns the int 0 (the int-first coercion quirk)."""
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
    result = _parser()._evaluate_expression("date|split:/|index:0|int",
                                            {"date": "2023/01/02"})
    assert result == 2023


# --- parse_to_articles / parse_tool_response -------------------------------


def test_parse_tool_response_list_search_maps_articles() -> None:
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
        "results": [{
            "name": "Paper One",
            "pub_year": "2021",
            "authors": ["X Y"]
        }]
    }
    articles = cast(list[Article], parse_tool_response(resp, tc))
    assert len(articles) == 1
    art = articles[0]
    assert art.title == "Paper One"
    assert art.year == 2021
    assert art.authors == ["X Y"]
    assert art.source == "preprint"
    assert art.used_in_analysis is True


def test_parse_tool_response_skips_items_without_title() -> None:
    """Items that map to an empty title are dropped from the result."""
    rf = ResponseFormat(
        type="json",
        results_path="results",
        field_mapping={"title": "name"},
    )
    tc = ToolConfig(server="s",
                    mcp_tool_name="t",
                    category="search",
                    response_format=rf)
    resp = {"results": [{"name": "Has Title"}, {"no_name": "x"}]}
    articles = cast(list[Article], parse_tool_response(resp, tc))
    assert [a.title for a in articles] == ["Has Title"]


def test_parse_tool_response_dict_results_with_key_mapping() -> None:
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
    tc = ToolConfig(server="s",
                    mcp_tool_name="t",
                    category="search",
                    response_format=rf)
    resp = {"12345": {"title": "KG paper"}}
    articles = cast(list[Article], parse_tool_response(resp, tc))
    assert len(articles) == 1
    art = articles[0]
    assert art.title == "KG paper"
    assert art.source_id == "12345"
    assert art.url == "https://pubmed.ncbi.nlm.nih.gov/12345/"


def test_parse_tool_response_boolean_category() -> None:
    """A ``boolean_string`` tool returns the decoded bool, not articles."""
    tc = ToolConfig(
        server="s",
        mcp_tool_name="t",
        category="utility",
        response_format=ResponseFormat(type="boolean_string"),
    )
    assert parse_tool_response("true", tc) is True


def test_parse_tool_response_non_search_returns_raw() -> None:
    """A non-search, non-boolean tool returns the raw parsed response."""
    tc = ToolConfig(server="s",
                    mcp_tool_name="t",
                    category="read",
                    response_format=ResponseFormat())
    assert parse_tool_response('{"a": 1}', tc) == {"a": 1}


def test_parse_to_articles_none_response_returns_empty() -> None:
    """A ``null`` JSON response parses to an empty article list."""
    rf = ResponseFormat(results_path=".", field_mapping={"title": "name"})
    tc = ToolConfig(server="s",
                    mcp_tool_name="t",
                    category="search",
                    response_format=rf)
    assert parse_tool_response("null", tc) == []

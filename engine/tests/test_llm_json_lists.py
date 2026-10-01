"""Tests for coercing an off-shape parsed LLM JSON value into a list.

DeepSeek's json_object mode does not enforce the schema it is given, so a
site reading a list out of parsed JSON without going through
``call_llm_json``'s schema validation (a tool-calling loop's final
response, or a freeform call) can be handed a bare string, a dict
carrying the list under a plausible key, a dict that is itself the single
element wanted, or a list with individually wrong-typed elements.
``coerce_json_list`` is the shared seam every such read routes through.
"""

import logging

import pytest

from co_scientist.llm import coerce_json_list, parse_tool_loop_json

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

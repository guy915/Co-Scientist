"""Tests for tool content_params placeholder substitution.

Covers ``resolve_content_params`` and its private helpers in
``co_scientist.config.content_params``: per-match substitution
(``_apply_placeholder_match``), whole-value substitution
(``_substitute_placeholders``), per-value dispatch on type
(``_resolve_content_param_value``), and the public entry point that
resolves a whole params dict.
"""

import re

from co_scientist.config.content_params import (
    _apply_placeholder_match,
    _resolve_content_param_value,
    _substitute_placeholders,
    resolve_content_params,
)

_PATTERN = re.compile(r"\{(\w+)\}")

# --- _apply_placeholder_match ------------------------------------------------


def test_apply_placeholder_match_unknown_placeholder_passthrough() -> None:
    """A placeholder absent from context leaves resolved_value unchanged."""
    result = _apply_placeholder_match(
        "{unknown}", "unknown", "{unknown}", {}, preserve_type=True
    )
    assert result == "{unknown}"


def test_apply_placeholder_match_preserves_type_for_exact_match() -> None:
    """An exact-match placeholder with preserve_type=True yields raw value."""
    context = {"goal": ["a", "b"]}
    result = _apply_placeholder_match(
        "{goal}", "goal", "{goal}", context, preserve_type=True
    )
    assert result == ["a", "b"]


def test_apply_placeholder_match_stringifies_when_embedded() -> None:
    """A placeholder embedded in a larger string is always stringified."""
    context = {"goal": ["a", "b"]}
    result = _apply_placeholder_match(
        "prefix {goal} suffix",
        "goal",
        "prefix {goal} suffix",
        context,
        preserve_type=True,
    )
    assert result == "prefix ['a', 'b'] suffix"


def test_apply_placeholder_match_no_preserve_type_always_stringifies() -> None:
    """With preserve_type=False, even an exact match is stringified."""
    context = {"count": 5}
    result = _apply_placeholder_match(
        "{count}", "count", "{count}", context, preserve_type=False
    )
    assert result == "5"


def test_apply_placeholder_match_string_context_value_not_double_quoted() -> (
    None
):
    """A string context value replaces in-place without str() wrapping."""
    context = {"name": "cancer"}
    result = _apply_placeholder_match(
        "study {name}", "name", "study {name}", context, preserve_type=True
    )
    assert result == "study cancer"


# --- _substitute_placeholders -------------------------------------------------


def test_substitute_placeholders_no_matches_returns_value_unchanged() -> None:
    """A value with no {placeholder} syntax passes through untouched."""
    result = _substitute_placeholders(
        "plain string", {}, _PATTERN, preserve_type=True
    )
    assert result == "plain string"


def test_substitute_placeholders_single_exact_match_preserves_type() -> None:
    """A lone placeholder value resolves to the raw (typed) context value."""
    context = {"research_goal": {"nested": 1}}
    result = _substitute_placeholders(
        "{research_goal}", context, _PATTERN, preserve_type=True
    )
    assert result == {"nested": 1}


def test_substitute_placeholders_multiple_placeholders_in_one_value() -> None:
    """Multiple placeholders in the same string all get substituted."""
    context = {"a": "X", "b": "Y"}
    result = _substitute_placeholders(
        "{a}-{b}", context, _PATTERN, preserve_type=True
    )
    assert result == "X-Y"


def test_substitute_placeholders_unknown_placeholder_left_untouched() -> None:
    """A placeholder absent from context is left in the output string."""
    context = {"known": "value"}
    result = _substitute_placeholders(
        "{known} and {unknown}", context, _PATTERN, preserve_type=True
    )
    assert result == "value and {unknown}"


# --- _resolve_content_param_value ---------------------------------------------


def test_resolve_content_param_value_string_dispatches_to_substitute() -> None:
    """A string value is routed through placeholder substitution."""
    context = {"research_goal": "Cure X"}
    result = _resolve_content_param_value("{research_goal}", context, _PATTERN)
    assert result == "Cure X"


def test_resolve_content_param_value_list_resolves_each_item() -> None:
    """Each string item in a list is substituted; non-strings pass through."""
    context = {"topic": "genomics"}
    result = _resolve_content_param_value(
        ["{topic}", "static", 3], context, _PATTERN
    )
    assert result == ["genomics", "static", 3]


def test_resolve_content_param_value_list_items_never_preserve_type() -> None:
    """A lone-placeholder list item still stringifies (list items != exact)."""
    context = {"nums": [1, 2, 3]}
    result = _resolve_content_param_value(["{nums}"], context, _PATTERN)
    assert result == ["[1, 2, 3]"]


def test_resolve_content_param_value_non_string_non_list_passthrough() -> None:
    """Numbers, bools, and dicts pass through unchanged (dicts unrecursed)."""
    context = {"x": "y"}
    assert _resolve_content_param_value(42, context, _PATTERN) == 42
    assert _resolve_content_param_value(True, context, _PATTERN) is True
    nested = {"inner": "{x}"}
    assert _resolve_content_param_value(nested, context, _PATTERN) is nested


# --- resolve_content_params (public entry point) ------------------------------


def test_resolve_content_params_empty_params_returns_empty_dict() -> None:
    """An empty (or falsy) params dict short-circuits to {}."""
    assert resolve_content_params({}, {"research_goal": "X"}) == {}


def test_resolve_content_params_resolves_multiple_keys() -> None:
    """Every key in params is independently resolved against context."""
    params = {
        "query": "{research_goal}",
        "tags": ["{focus_areas}", "static-tag"],
        "limit": 10,
    }
    context = {
        "research_goal": "Cure cancer",
        "focus_areas": "immunotherapy",
    }
    result = resolve_content_params(params, context)
    assert result == {
        "query": "Cure cancer",
        "tags": ["immunotherapy", "static-tag"],
        "limit": 10,
    }


def test_resolve_content_params_preserves_list_type_for_context_list() -> None:
    """A value that is exactly ``{key}`` and maps to a list stays a list."""
    params = {"areas": "{focus_areas}"}
    context = {"focus_areas": ["a", "b", "c"]}
    result = resolve_content_params(params, context)
    assert result == {"areas": ["a", "b", "c"]}


def test_resolve_content_params_leaves_unknown_placeholders_untouched() -> None:
    """Placeholders with no matching context key are left as literal text."""
    params = {"query": "{missing_key} literal"}
    result = resolve_content_params(params, {"research_goal": "X"})
    assert result == {"query": "{missing_key} literal"}

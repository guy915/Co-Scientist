"""Truncation of over-long strings for the json_object downgrade.

A fourth mirror alongside ``test_llm_capability_prune.py`` (invented keys),
``test_llm_capability_backfill.py`` (missing required fields), and
``test_llm_capability_truncate.py`` (over-long arrays): downgrading a
schema'd call to ``{"type": "json_object"}`` also loses server-side
``maxLength`` enforcement, so an answer a few characters over the limit
fails the whole response. Production run b82f9162: generation and
validation calls failed on a hypothesis ``title`` field like
"'Lacosamide-mediated Nav1.6/Nav1.7 slow inactivation as a cytostatic
mechanism in depolarized glioblastoma cells' is too long", discarding a
large prompt's worth of work over a few characters -- on a free gateway
model with a 100-requests/day cap, one such retry is 1% of the day's
budget.

``_truncate_oversized_strings`` trims the answer to fit the schema; like
its siblings it runs on a parsed response only (the "Trim the schema,
never the input" gotcha, root ``AGENTS.md``), and it never touches
``minLength``, ``pattern``, or enum membership -- those describe the
content of the answer, not an over-generous provider, and no amount of
truncation fixes a wrong answer.
"""

from typing import Any

from co_scientist.llm.structured.truncate_strings import (
    _truncate_oversized_strings,
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 20},
        "code": {"type": "string", "minLength": 3, "maxLength": 5},
        "group": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 10},
            },
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "maxLength": 8},
                },
            },
        },
        "tags": {
            "type": "array",
            "items": {"type": "string", "maxLength": 6},
        },
        "unbounded": {"type": "string"},
    },
}


def test_truncate_cuts_a_string_past_max_length() -> None:
    """A string over maxLength is cut down to fit."""
    obj: dict[str, Any] = {"title": "this is way too long a title"}

    _truncate_oversized_strings(obj, _SCHEMA)

    assert len(obj["title"]) <= 20


def test_truncate_prefers_a_word_boundary_near_the_limit() -> None:
    """A truncation cuts at the last word boundary within ~20% of the cap.

    The exact production shape: the real title still overruns after the
    cut point, so the trim lands mid-word unless a nearby space is used
    instead. maxLength=20 with a boundary window of the last 4 chars
    (20 - round(20*0.2)=16..20): "twelve chars ok!!" cut at 20 chars is
    "twelve chars ok!!" itself (17 chars, fits) -- use a string that
    actually overflows with a space inside the window.
    """
    # 24 chars; cut to 20 is "abcdefghij klmnopqr ", the last space sits at
    # index 19, inside the window [16, 20) -- so the cut lands there, not
    # mid-word at "opqr".
    obj: dict[str, Any] = {"title": "abcdefghij klmnopqr stuvwxyz"}

    _truncate_oversized_strings(obj, _SCHEMA)

    assert obj["title"] == "abcdefghij klmnopqr"
    assert len(obj["title"]) <= 20
    assert not obj["title"].endswith(" ")


def test_truncate_hard_cuts_when_no_boundary_is_near() -> None:
    """No space within the trailing window falls back to a hard cut."""
    value = "onelongwordwithnospaceatall"
    obj: dict[str, Any] = {"title": value}

    _truncate_oversized_strings(obj, _SCHEMA)

    assert obj["title"] == value[:20]
    assert len(obj["title"]) == 20


def test_truncate_leaves_minlength_and_pattern_violations_untouched() -> None:
    """minLength/pattern are real answer errors -- never patched here."""
    obj: dict[str, Any] = {"code": "ab"}  # under minLength=3, over is fine

    _truncate_oversized_strings(obj, _SCHEMA)

    assert obj["code"] == "ab"


def test_truncate_leaves_strings_within_bound_untouched() -> None:
    """A string at or under its cap is left exactly as it arrived."""
    obj: dict[str, Any] = {"title": "short"}

    _truncate_oversized_strings(obj, _SCHEMA)

    assert obj["title"] == "short"


def test_truncate_ignores_strings_without_max_length() -> None:
    """A property with no maxLength declared is never trimmed."""
    long_value = "x" * 500
    obj: dict[str, Any] = {"unbounded": long_value}

    _truncate_oversized_strings(obj, _SCHEMA)

    assert obj["unbounded"] == long_value


def test_truncate_recurses_into_nested_objects() -> None:
    """An over-long string inside a nested object is truncated too."""
    obj: dict[str, Any] = {"group": {"name": "way too long a name"}}

    _truncate_oversized_strings(obj, _SCHEMA)

    assert len(obj["group"]["name"]) <= 10


def test_truncate_recurses_into_an_array_of_objects() -> None:
    """An over-long string inside an array-of-objects item is truncated."""
    obj: dict[str, Any] = {
        "sections": [{"note": "way too long"}, {"note": "ok"}]
    }

    _truncate_oversized_strings(obj, _SCHEMA)

    assert len(obj["sections"][0]["note"]) <= 8
    assert obj["sections"][1]["note"] == "ok"


def test_truncate_recurses_into_an_array_of_strings() -> None:
    """Each over-long string in a plain string array is truncated."""
    obj: dict[str, Any] = {"tags": ["short", "waytoolongtag"]}

    _truncate_oversized_strings(obj, _SCHEMA)

    assert obj["tags"][0] == "short"
    assert len(obj["tags"][1]) <= 6


def test_truncate_noop_for_non_dict_inputs() -> None:
    """Non-dict payloads and non-dict schemas are silently ignored."""
    _truncate_oversized_strings(["not", "a", "dict"], _SCHEMA)
    _truncate_oversized_strings({"a": 1}, "not a schema")  # no exception


def test_truncate_ignores_non_string_values_under_a_string_schema() -> None:
    """A malformed non-string value at a string-typed key is left alone."""
    obj: dict[str, Any] = {"title": 12345}

    _truncate_oversized_strings(obj, _SCHEMA)

    assert obj["title"] == 12345

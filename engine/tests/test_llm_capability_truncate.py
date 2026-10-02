"""Truncation of over-long arrays for the json_object downgrade.

A third mirror alongside ``test_llm_capability_prune.py`` (invented keys)
and ``test_llm_capability_backfill.py`` (missing required fields):
downgrading a schema'd call to ``{"type": "json_object"}`` also loses
server-side ``maxItems`` enforcement, so a model can return an array one
item longer than the schema allows and fail validation over an otherwise
perfectly good answer. Production log (run 44e848fb): six experiment-plan
steps against a ``maxItems: 5`` schema discarded the whole response and
cost a full paid retry, even though the consuming node
(``agents/generation/experiment_plan.py``) already truncates to the same
cap defensively -- the sixth step was never going to survive regardless.

``reshape_json_output`` trims the answer to fit the schema; it must
never be reached for the INPUT side of anything (see the "Trim the schema,
never the input" gotcha in root ``AGENTS.md``) -- these tests exercise it
only as a shim applied to a parsed response, exactly like its two
siblings.
"""

from typing import Any

from co_scientist.llm.structured.validate import reshape_json_output

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
        },
        "group": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 2,
                }
            },
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 1,
                    }
                },
            },
        },
        "unbounded": {"type": "array", "items": {"type": "string"}},
    },
}


def test_truncate_drops_items_past_max_items() -> None:
    """The exact production failure: six steps against a maxItems: 5 cap."""
    obj: dict[str, Any] = {"steps": ["a", "b", "c", "d", "e", "f"]}

    reshape_json_output(obj, _SCHEMA)

    assert obj == {"steps": ["a", "b", "c", "d", "e"]}


def test_truncate_recurses_into_nested_objects() -> None:
    """An over-long array inside a nested object is truncated too."""
    obj: dict[str, Any] = {"group": {"tags": ["x", "y", "z"]}}

    reshape_json_output(obj, _SCHEMA)

    assert obj == {"group": {"tags": ["x", "y"]}}


def test_truncate_recurses_into_an_array_inside_an_object_inside_an_array() -> (
    None
):
    """Proves the recursion: array -> object items -> array property.

    ``sections`` is an array of objects, and each object's own ``notes``
    field is itself an over-long array. Both levels must be enforced by
    one traversal against the array's item schema.
    """
    obj: dict[str, Any] = {
        "sections": [
            {"notes": ["first", "second"]},
            {"notes": ["only one already"]},
        ]
    }

    reshape_json_output(obj, _SCHEMA)

    assert obj == {
        "sections": [
            {"notes": ["first"]},
            {"notes": ["only one already"]},
        ]
    }


def test_truncate_leaves_arrays_within_bound_untouched() -> None:
    """An array at or under its cap is left exactly as it arrived."""
    obj: dict[str, Any] = {"steps": ["a", "b"]}

    reshape_json_output(obj, _SCHEMA)

    assert obj == {"steps": ["a", "b"]}


def test_truncate_ignores_arrays_without_max_items() -> None:
    """A property with no ``maxItems`` declared is never trimmed."""
    obj: dict[str, Any] = {"unbounded": list("abcdefghij")}

    reshape_json_output(obj, _SCHEMA)

    assert obj == {"unbounded": list("abcdefghij")}


def test_truncate_noop_for_non_dict_inputs() -> None:
    """Non-dict payloads and non-dict schemas are silently ignored."""
    reshape_json_output(["not", "a", "dict"], _SCHEMA)
    reshape_json_output({"a": 1}, "not a schema")  # no exception == pass


def test_truncate_ignores_non_list_values_under_an_array_schema() -> None:
    """A malformed non-list value at an array-typed key is left alone."""
    obj: dict[str, Any] = {"steps": "not a list"}

    reshape_json_output(obj, _SCHEMA)

    assert obj == {"steps": "not a list"}

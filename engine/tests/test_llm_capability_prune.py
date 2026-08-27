"""Pruning of invented properties for the json_object downgrade.

The mirror image of ``test_llm_capability_backfill.py``. Downgrading a
schema'd call to ``{"type": "json_object"}`` loses the server-side schema
constraint in both directions: the model may omit a required field, and it
may also *add* fields nobody asked for. Every object node in this engine's
schemas is closed (``schemas/builders.obj`` sets
``additionalProperties: False``), so one invented key fails validation for
the whole response.

Retrying does not fix it. A production research_overview call answered with
the same three extra sections -- ``knowledge_base``, ``nih_specific_aims``,
``research_contacts`` -- on all five attempts, each one a full paid call
against a large prompt, and the node then fell back to empty. The invented
keys carry no information the schema asked for, so dropping them client-side
is what turns that into a first-attempt success.
"""

from typing import Any

from co_scientist.llm_json import _prune_unknown_properties

_CLOSED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "assessment": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"verdict": {"type": "string"}},
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"title": {"type": "string"}},
            },
        },
    },
}


def test_prune_drops_invented_top_level_properties() -> None:
    """The exact production failure: three invented sections are dropped."""
    obj: dict[str, Any] = {
        "summary": "ok",
        "knowledge_base": {"entries": []},
        "nih_specific_aims": "Aim 1",
        "research_contacts": ["someone"],
    }

    _prune_unknown_properties(obj, _CLOSED_SCHEMA)

    assert obj == {"summary": "ok"}


def test_prune_recurses_into_nested_objects() -> None:
    """An invented key inside a closed nested object is dropped too."""
    obj: dict[str, Any] = {
        "assessment": {"verdict": "holds", "confidence": 0.9}
    }

    _prune_unknown_properties(obj, _CLOSED_SCHEMA)

    assert obj == {"assessment": {"verdict": "holds"}}


def test_prune_recurses_into_arrays_of_objects() -> None:
    """Array items are pruned against the array's item schema."""
    obj: dict[str, Any] = {"items": [{"title": "a", "rank": 1}, {"title": "b"}]}

    _prune_unknown_properties(obj, _CLOSED_SCHEMA)

    assert obj == {"items": [{"title": "a"}, {"title": "b"}]}


def test_prune_keeps_extras_where_the_schema_allows_them() -> None:
    """An open node keeps whatever the model added: only closed nodes prune."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    }
    obj: dict[str, Any] = {"summary": "ok", "extra": 1}

    _prune_unknown_properties(obj, schema)

    assert obj == {"summary": "ok", "extra": 1}


def test_prune_keeps_declared_fields_even_when_invalid() -> None:
    """Only unknown names are pruned; a wrong value is validation's job."""
    obj: dict[str, Any] = {"summary": 42}

    _prune_unknown_properties(obj, _CLOSED_SCHEMA)

    assert obj == {"summary": 42}


def test_prune_noop_for_non_dict_inputs() -> None:
    """Non-dict payloads and non-dict schemas are silently ignored."""
    _prune_unknown_properties(["not", "a", "dict"], _CLOSED_SCHEMA)
    _prune_unknown_properties({"a": 1}, "not a schema")  # no exception == pass

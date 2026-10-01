"""Back-fill of missing required fields for the json_object downgrade.

Downgrading a schema'd call to ``{"type": "json_object"}`` loses the
server-side schema constraint, so a model may answer without a required
field. ``_backfill_required_fields`` supplies a type-appropriate empty
default before validation runs, which is what keeps the downgrade from
turning a usable answer into a schema failure.

Split from ``test_llm_capability_shim.py`` on size; that file keeps the
downgrade decision and the end-to-end ``call_llm`` / ``call_llm_json``
wiring, including the two back-fill wiring tests that need the network
fakes. Nothing here does -- the function is pure.
"""

from typing import Any

import jsonschema

from co_scientist.llm.structured.validate import _backfill_required_fields
from co_scientist.schemas.review import FULL_REVIEW_SCHEMA
from tests._llm_fake import NESTED_SCHEMA as _NESTED_SCHEMA


def test_backfill_fills_missing_required_fields_by_type() -> None:
    """Each missing required field gets a type-appropriate empty default."""
    schema = {
        "type": "object",
        "properties": {
            "s": {"type": "string"},
            "o": {"type": "object"},
            "a": {"type": "array"},
            "i": {"type": "integer"},
            "n": {"type": "number"},
            "u": {},
        },
        "required": ["s", "o", "a", "i", "n", "u"],
    }
    obj: dict[str, Any] = {}

    _backfill_required_fields(obj, schema)

    assert obj == {"s": "", "o": {}, "a": [], "i": 0, "n": 0, "u": ""}


def test_backfill_uses_first_enum_value_for_strings() -> None:
    """A missing required enum string defaults to the first enum value."""
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["holds", "weakened"]}
        },
        "required": ["verdict"],
    }
    obj: dict[str, Any] = {}

    _backfill_required_fields(obj, schema)

    assert obj == {"verdict": "holds"}


def test_backfill_recurses_into_nested_objects() -> None:
    """Missing required fields inside present nested objects are filled."""
    obj: dict[str, Any] = {"summary": "ok", "assessment": {}}

    _backfill_required_fields(obj, _NESTED_SCHEMA["schema"])

    assert obj == {
        "summary": "ok",
        "assessment": {"verdict": "holds", "notes": []},
    }


def test_backfill_leaves_present_fields_untouched() -> None:
    """Fields already present keep their values, even schema-invalid ones."""
    obj: dict[str, Any] = {
        "summary": 42,
        "assessment": {"verdict": "custom", "notes": ["kept"]},
    }

    _backfill_required_fields(obj, _NESTED_SCHEMA["schema"])

    assert obj == {
        "summary": 42,
        "assessment": {"verdict": "custom", "notes": ["kept"]},
    }


def test_backfill_ignores_required_fields_without_property_schema() -> None:
    """Required names absent from ``properties`` are not invented."""
    schema = {
        "type": "object",
        "properties": {},
        "required": ["mystery"],
    }
    obj: dict[str, Any] = {}

    _backfill_required_fields(obj, schema)

    assert obj == {}


def test_backfill_noop_for_non_dict_inputs() -> None:
    """Non-dict payloads and non-dict schemas are silently ignored."""
    _backfill_required_fields(["not", "a", "dict"], {"required": ["x"]})
    _backfill_required_fields({}, "not a schema")  # no exception == pass


_ARRAY_OF_OBJECTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "notes"],
            },
        },
    },
    "required": ["items"],
}


def test_backfill_recurses_into_array_items() -> None:
    """A required field missing from one item of an array is backfilled.

    ``_recurse_into_properties`` used to hand an array value straight to
    ``_backfill_required_fields``, which no-ops on anything that is not a
    dict -- so a required field missing from an *item* inside an array
    (as opposed to a nested object) was never filled, and the response
    failed schema validation instead of degrading. This is the array
    counterpart of ``_prune_unknown_properties``'s ``_prune_child``, which
    already walks array items the same way.
    """
    obj: dict[str, Any] = {
        "items": [
            {"title": "present", "notes": ["kept"]},
            {"title": "missing notes"},
        ]
    }

    _backfill_required_fields(obj, _ARRAY_OF_OBJECTS_SCHEMA)

    assert obj == {
        "items": [
            {"title": "present", "notes": ["kept"]},
            {"title": "missing notes", "notes": []},
        ]
    }


def test_backfill_ignores_non_dict_array_items() -> None:
    """A malformed array item (not a dict) is left alone, not crashed on."""
    obj: dict[str, Any] = {"items": ["not a dict", 42]}

    _backfill_required_fields(obj, _ARRAY_OF_OBJECTS_SCHEMA)

    assert obj == {"items": ["not a dict", 42]}


def test_backfill_rescues_a_full_review_missing_reviews_summary() -> None:
    """A required nested block a downgraded answer omits still validates.

    ``reviews_summary`` became required on ``FULL_REVIEW_SCHEMA`` so it
    would actually be filled -- but production's primary runs json_object
    mode, where nothing enforces the schema. Were the back-fill unable to
    reach a required *nested* object's own required children, a model
    that skipped the block would fail validation on every attempt and the
    whole review would be lost: a regression, not a fidelity gain.
    """
    schema = FULL_REVIEW_SCHEMA["schema"]
    answer: dict[str, Any] = {
        "correctness": "Internally consistent.",
        "assumptions": [],
        "quality_and_novelty": "A non-obvious combination.",
        "literature_grounding": "Two cohort studies agree.",
        "verdict": "sound",
        "justification": "Worth a pilot.",
    }

    _backfill_required_fields(answer, schema)

    jsonschema.validate(instance=answer, schema=schema)
    assert answer["reviews_summary"]["critical_flaws"] == []
    assert answer["reviews_summary"]["executive_verdict"] == ""
    assert answer["feasibility_steps"] == []

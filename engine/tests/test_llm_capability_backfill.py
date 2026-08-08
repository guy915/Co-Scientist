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

from co_scientist.llm_json import _backfill_required_fields
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

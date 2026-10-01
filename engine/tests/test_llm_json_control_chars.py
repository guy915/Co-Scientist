"""Tests for JSON carrying literal control characters inside strings.

A model writing prose into a JSON string field routinely presses return
inside it. Strict JSON forbids that -- a raw newline between the quotes is
a parse error, not a formatting nicety -- so the whole response is lost
however well-formed the rest of it is.

Observed live on ``openrouter/stealth/ox-alpha`` in ``json_object`` mode,
where no server-side schema constrains the shape: five ranking calls in one
express run died at "Invalid control character", each one a complete,
balanced object whose only fault was a blank line inside one field.
"""

import json

from co_scientist.llm.structured.repair import _try_minor_repairs

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

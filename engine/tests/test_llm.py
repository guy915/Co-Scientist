"""Tests for the pure JSON helpers in ``co_scientist.llm``.

These tests lock in the *current* behavior of the network-free helpers:
``attempt_json_repair`` (the JSON-repair logic), ``validate_json_schema``,
and ``get_fallback_response``. None of them touch litellm or the network, so
the tests run deterministically with no mocking. They assert the ACTUAL
behavior observed in the code, including a couple of quirks (an empty object
is returned as-is; some inputs the task brief expected to be "repaired" are
in fact not handled by this function; and an empty/whitespace input under
major repairs crashes).
"""

from typing import Any

import pytest

from co_scientist.llm import attempt_json_repair
from co_scientist.llm import get_fallback_response
from co_scientist.llm import validate_json_schema
from jsonschema.exceptions import ValidationError

# --- attempt_json_repair: clean parses (no repair) -------------------------


def test_valid_object_parsed_without_repair() -> None:
    """A valid JSON object parses directly with ``was_repaired`` False."""
    assert attempt_json_repair('{"a": 1, "b": "x"}') == ({
        "a": 1,
        "b": "x"
    }, False)


def test_valid_object_with_surrounding_whitespace() -> None:
    """Leading/trailing whitespace around a valid object is tolerated."""
    assert attempt_json_repair('  {"a": 1}  ') == ({"a": 1}, False)


def test_empty_object_returned_as_is() -> None:
    """An empty object ``{}`` is returned by the initial parse, not repaired.

    The falsy-result guard (``if result:``) only runs inside the repair
    loops, so the initial ``isinstance(result, dict)`` branch returns ``{}``
    verbatim with ``was_repaired`` False.
    """
    assert attempt_json_repair("{}") == ({}, False)


def test_empty_object_with_major_repairs_still_returned_as_is() -> None:
    """``{}`` short-circuits in the initial parse even when major is allowed."""
    assert attempt_json_repair("{}", allow_major_repairs=True) == ({}, False)


def test_valid_array_returns_list_not_dict() -> None:
    """A valid JSON array is returned as a list, despite the dict-typed hint.

    The initial parse only returns when the result is a dict, so the array
    falls through to the (trailing-comma) minor-repair strategy, which
    re-parses it and returns the truthy list with ``was_repaired`` False.
    This documents that the ``tuple[dict | None, bool]`` annotation does not
    hold for array inputs.
    """
    parsed, repaired = attempt_json_repair("[1, 2, 3]")
    assert isinstance(parsed, list)
    assert parsed == [1, 2, 3]
    assert repaired is False


def test_empty_array_returns_none() -> None:
    """An empty array is not returned: the empty list is falsy and skipped."""
    assert attempt_json_repair("[]") == (None, False)


# --- attempt_json_repair: minor repairs (trailing commas) ------------------


def test_trailing_comma_in_object_is_minor_repair() -> None:
    """A trailing comma before ``}`` is fixed and reported as NOT major.

    Trailing-comma removal is a minor repair, so ``was_repaired`` is False
    even though the input was malformed.
    """
    assert attempt_json_repair('{"a": 1,}') == ({"a": 1}, False)


def test_trailing_comma_in_nested_array_is_minor_repair() -> None:
    """A trailing comma inside a nested array is fixed as a minor repair."""
    assert attempt_json_repair('{"a": [1, 2,]}') == ({"a": [1, 2]}, False)


# --- attempt_json_repair: markdown fences are NOT handled here -------------


def test_markdown_json_fence_is_not_unwrapped() -> None:
    """A ```json fenced block is NOT stripped by ``attempt_json_repair``.

    Despite the task brief, fence stripping lives in ``call_llm_json`` (a
    network-backed caller), not in this pure function. With only minor
    repairs the fenced payload is unparseable and returns ``(None, False)``.
    Under major repairs the inner object is still recovered, but via the
    generic ``\\{.*\\}`` regex-extraction strategy (treated as a major
    repair), NOT via any fence-aware logic.
    """
    fenced = '```json\n{"a": 1}\n```'
    assert attempt_json_repair(fenced) == (None, False)
    assert attempt_json_repair(fenced, allow_major_repairs=True) == ({
        "a": 1
    }, True)


# --- attempt_json_repair: single quotes are NOT repaired ------------------


def test_single_quoted_json_is_not_repaired() -> None:
    """Single-quoted (Python-style) JSON is not repaired by this function.

    Contrary to the task brief, there is no single-quote-to-double-quote
    strategy; the input stays unparseable in both modes.
    """
    assert attempt_json_repair("{'a': 1}") == (None, False)
    assert attempt_json_repair("{'a': 1}", allow_major_repairs=True) == (None,
                                                                         False)


# --- attempt_json_repair: the major-repair gate ----------------------------


def test_truncated_object_repaired_only_with_major_repairs() -> None:
    """Unbalanced/truncated JSON is closed only when major repairs are on.

    With ``allow_major_repairs=True`` the missing ``}`` is added and the
    object parses, with ``was_repaired`` True. With the flag off the gate
    holds and nothing is returned.
    """
    truncated = '{"a": 1, "b": 2'
    assert attempt_json_repair(truncated,
                               allow_major_repairs=True) == ({
                                   "a": 1,
                                   "b": 2
                               }, True)
    assert attempt_json_repair(truncated, allow_major_repairs=False) == (None,
                                                                         False)


def test_truncated_object_default_does_not_major_repair() -> None:
    """The default (no kwarg) does not perform major repairs."""
    assert attempt_json_repair('{"a": 1, "b": 2') == (None, False)


def test_unterminated_string_value_closed_with_major_repairs() -> None:
    """An unterminated string value is closed under major repairs."""
    assert attempt_json_repair('{"a": "hello',
                               allow_major_repairs=True) == ({
                                   "a": "hello"
                               }, True)


def test_truncated_array_value_closed_with_major_repairs() -> None:
    """A truncated array value is closed (string + bracket) under major."""
    assert attempt_json_repair('{"items": ["x", "y',
                               allow_major_repairs=True) == ({
                                   "items": ["x", "y"]
                               }, True)


def test_nested_truncated_object_closed_with_major_repairs() -> None:
    """A truncated nested object gets both braces added under major repairs."""
    assert attempt_json_repair('{"a": {"b": 1',
                               allow_major_repairs=True) == ({
                                   "a": {
                                       "b": 1
                                   }
                               }, True)


def test_truncated_root_array_closed_with_major_repairs() -> None:
    """A truncated top-level array is closed and returned as a list (major)."""
    parsed, repaired = attempt_json_repair("[1, 2, 3",
                                           allow_major_repairs=True)
    assert isinstance(parsed, list)
    assert parsed == [1, 2, 3]
    assert repaired is True


def test_json_object_embedded_in_prose_extracted_only_with_major() -> None:
    """An object embedded in surrounding prose is extracted only under major.

    The regex-extraction strategy (a major repair) pulls the first ``{...}``
    out of the text; without major repairs the input is left unparsed.
    """
    text = 'Here is the answer: {"a": 1} thanks'
    assert attempt_json_repair(text,
                               allow_major_repairs=True) == ({
                                   "a": 1
                               }, True)
    assert attempt_json_repair(text, allow_major_repairs=False) == (None, False)


# --- attempt_json_repair: unrepairable input -------------------------------


def test_plain_garbage_returns_none() -> None:
    """Non-JSON prose is unrepairable and returns ``(None, False)``."""
    assert attempt_json_repair("this is not json at all") == (None, False)
    assert attempt_json_repair("this is not json at all",
                               allow_major_repairs=True) == (None, False)


def test_empty_string_without_major_repairs_returns_none() -> None:
    """An empty string with only minor repairs returns ``(None, False)``."""
    assert attempt_json_repair("") == (None, False)


def test_empty_string_with_major_repairs_returns_none() -> None:
    """Empty input under major repairs returns no value rather than crashing.

    Regression guard: ``close_truncated_json`` short-circuits on an empty (or
    whitespace-only) string instead of indexing ``stripped[-1]``, so the
    repair honors the documented ``(None, ...)`` contract.
    """
    parsed, _ = attempt_json_repair("", allow_major_repairs=True)
    assert parsed is None


def test_whitespace_only_with_major_repairs_returns_none() -> None:
    """Whitespace-only input also returns no value after the empty guard."""
    parsed, _ = attempt_json_repair("   ", allow_major_repairs=True)
    assert parsed is None


# --- validate_json_schema --------------------------------------------------

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "a": {
            "type": "integer"
        }
    },
    "required": ["a"],
}


def test_validate_json_schema_passes_for_valid_instance() -> None:
    """A conforming instance validates and returns None (no raise)."""
    validate_json_schema({"a": 1}, _SCHEMA)  # no exception == valid


def test_validate_json_schema_none_schema_skips_validation() -> None:
    """A ``None`` schema skips validation entirely (returns None)."""
    validate_json_schema({"anything": True}, None)  # no exception == valid


def test_validate_json_schema_unwraps_nested_schema_key() -> None:
    """A schema wrapped under a ``schema`` key is unwrapped before validating."""
    nested = {"name": "node", "schema": _SCHEMA}
    validate_json_schema({"a": 5}, nested)  # no exception == valid


def test_validate_json_schema_raises_on_type_mismatch() -> None:
    """A type mismatch against the schema raises ``ValidationError``."""
    with pytest.raises(ValidationError):
        validate_json_schema({"a": "not an int"}, _SCHEMA)


def test_validate_json_schema_raises_on_missing_required() -> None:
    """A missing required property raises ``ValidationError``."""
    with pytest.raises(ValidationError):
        validate_json_schema({}, _SCHEMA)


# --- get_fallback_response -------------------------------------------------


def test_fallback_none_schema_returns_none() -> None:
    """A ``None`` schema yields no fallback."""
    assert get_fallback_response(None) is None


def test_fallback_for_proximity_node() -> None:
    """The proximity node gets a concrete skip-deduplication fallback dict."""
    fallback = get_fallback_response({"name": "proximity_analysis"})
    assert fallback == {
        "similarity_clusters": [],
        "diversity_assessment": "Analysis failed - skipping deduplication",
        "redundancy_assessment": "Analysis failed - skipping deduplication",
    }


def test_fallback_for_critical_node_returns_none() -> None:
    """A critical (non-proximity) node has no fallback."""
    assert get_fallback_response({"name": "generate_hypotheses"}) is None


def test_fallback_schema_without_name_returns_none() -> None:
    """A schema with no ``name`` field has no fallback."""
    assert get_fallback_response({}) is None


# --- attempt_json_repair: invalid backslash escapes (LaTeX/math) -----------


def test_invalid_latex_escape_is_minor_repaired() -> None:
    r"""LaTeX-style ``\(...\)`` in a string value is repaired (minor).

    This is the real-world failure that aborted a run: DeepSeek emitted
    ``GFP-Ub\(^{G76V}\)`` inside a JSON string, and ``\(`` is not a valid JSON
    escape. The repair doubles the lone backslashes so the literal text
    survives, and it succeeds WITHOUT major repairs.
    """
    raw = r'{"experiment": "use GFP-Ub\(^{G76V}\) reporter"}'
    parsed, was_major = attempt_json_repair(raw)
    assert parsed == {"experiment": r"use GFP-Ub\(^{G76V}\) reporter"}
    assert was_major is False


def test_invalid_escape_with_trailing_comma_repaired() -> None:
    """Combined invalid escape + trailing comma is still a minor repair."""
    raw = r'{"a": "x\(y", "b": 1,}'
    parsed, was_major = attempt_json_repair(raw)
    assert parsed == {"a": r"x\(y", "b": 1}
    assert was_major is False


def test_valid_escapes_are_left_intact() -> None:
    """Legitimate JSON escapes are not double-escaped by the repair."""
    # Valid as-is, so it parses without any repair.
    assert attempt_json_repair(r'{"a": "line\n\t\"q\"\\done"}') == (
        {
            "a": 'line\n\t"q"\\done'
        },
        False,
    )


# --- get_fallback_response: enhancement nodes degrade, foundational fail ---


def test_enhancement_nodes_get_a_fallback() -> None:
    """Every post-generation enhancement node degrades instead of aborting."""
    for name in (
            "proximity_analysis",
            "hypothesis_evolution",
            "hypothesis_review",
            "hypothesis_batch_review",
            "reflection_observations",
            "meta_review",
            "deep_verification",
            "research_overview",
    ):
        assert get_fallback_response({"name": name}) is not None, name


def test_foundational_nodes_have_no_fallback() -> None:
    """Foundational nodes fail loud (no fallback) -- no hypotheses, no run."""
    for name in ("hypothesis_generation", "hypothesis_draft",
                 "supervisor_guidance", "ranking_judgment"):
        assert get_fallback_response({"name": name}) is None, name


def test_evolution_fallback_is_empty_dict_keeps_original() -> None:
    """Evolution's empty fallback routes the node to its keep-original path."""
    assert get_fallback_response({"name": "hypothesis_evolution"}) == {}


def test_batch_review_fallback_has_empty_reviews() -> None:
    """Batch review degrades to no rows; the node fills 'Review unavailable'."""
    assert get_fallback_response({"name": "hypothesis_batch_review"}) == {
        "reviews": []
    }


def test_fallback_returns_independent_copy() -> None:
    """Mutating a returned fallback must not corrupt the shared template."""
    first = get_fallback_response({"name": "hypothesis_batch_review"})
    assert first is not None
    first["reviews"].append("dirty")
    second = get_fallback_response({"name": "hypothesis_batch_review"})
    assert second == {"reviews": []}

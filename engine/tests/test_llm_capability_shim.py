from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest
from jsonschema.exceptions import ValidationError

from co_scientist.llm import CompletionSpec, call_llm, call_llm_json
from co_scientist.llm.request.completion import (
    _supports_json_schema_response_format,
)
from co_scientist.llm.structured.validate import reshape_json_output
from co_scientist.schemas.planning import META_REVIEW_SCHEMA
from co_scientist.schemas.review import FULL_REVIEW_SCHEMA
from tests._llm_fake import NESTED_SCHEMA, disable_llm_cache, scripted_backend
from tests._llm_fake import make_completion as _completion
from tests._llm_fake import make_message as _message

pytestmark = pytest.mark.usefixtures("clear_capability_cache")

_ANSWER_DISCIPLINE = (
    "\n\n## Answer Discipline\n\n"
    "Your reasoning is not your answer. When you have finished reasoning, "
    "you must write the JSON object described below as the content of your "
    "reply. A reply whose content is empty is discarded in full, however "
    "good the reasoning behind it was, so never end your turn without "
    "emitting the JSON."
)

_SCHEMA_PROMPT_SUFFIX = _ANSWER_DISCIPLINE + (
    "\n\n---\nRESPOND WITH VALID JSON ONLY. "
    "Your output MUST strictly match this JSON schema "
    "(all required fields must be present):\n"
)

_SCHEMA_PROMPT_TRAILER = (
    "\n\n"
    "Output a JSON object that CONFORMS TO the schema above -- the "
    "actual data. Do NOT output the schema itself: your response must "
    'not contain "type", "properties", or "required" keys unless the '
    "schema declares them as data fields. Use only the property names "
    "the schema lists; any field it does not declare will be rejected."
)

_FLAT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def _registry(monkeypatch: pytest.MonkeyPatch, supported: bool) -> None:
    _supports_json_schema_response_format.cache_clear()
    monkeypatch.setattr(
        "co_scientist.llm.litellm.supports_response_schema",
        lambda model: supported,
    )


def _serve(
    monkeypatch: pytest.MonkeyPatch, supported: bool, *contents: str
) -> list[dict[str, Any]]:
    disable_llm_cache(monkeypatch)
    _registry(monkeypatch, supported)
    return scripted_backend(
        monkeypatch, [_completion(_message(c)) for c in contents]
    ).requests


@pytest.mark.parametrize(
    "schema", [NESTED_SCHEMA, _FLAT_SCHEMA], ids=["named", "bare"]
)
async def test_an_unsupported_model_gets_json_object_mode_and_a_schema_prompt(
    monkeypatch: pytest.MonkeyPatch, schema: dict[str, Any]
) -> None:
    sent = _serve(monkeypatch, False, "{}")

    await call_llm(
        "a prompt", CompletionSpec(model_name="test-model", json_schema=schema)
    )

    assert sent[0]["response_format"] == {"type": "json_object"}
    assert sent[0]["messages"] == [
        {
            "role": "user",
            "content": (
                "a prompt"
                + _SCHEMA_PROMPT_SUFFIX
                + json.dumps(schema.get("schema", schema), indent=2)
                + _SCHEMA_PROMPT_TRAILER
            ),
        }
    ]


@pytest.mark.parametrize(
    ("schema", "envelope"),
    [
        (NESTED_SCHEMA, NESTED_SCHEMA),
        (_FLAT_SCHEMA, {"name": "response", "schema": _FLAT_SCHEMA}),
        (
            {"schema": _FLAT_SCHEMA},
            {"name": "response", "schema": _FLAT_SCHEMA},
        ),
    ],
    ids=["named", "bare", "unnamed-envelope"],
)
async def test_a_supported_model_gets_a_named_native_schema(
    monkeypatch: pytest.MonkeyPatch,
    schema: dict[str, Any],
    envelope: dict[str, Any],
) -> None:
    sent = _serve(monkeypatch, True, "{}")

    await call_llm(
        "a prompt", CompletionSpec(model_name="test-model", json_schema=schema)
    )

    assert sent[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": envelope,
    }
    assert sent[0]["messages"] == [{"role": "user", "content": "a prompt"}]
    assert "name" not in _FLAT_SCHEMA, "the caller's schema is not mutated"


_CLOSED: dict[str, Any] = {
    "name": "capability_shim_closed",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}
_MAX_LENGTH: dict[str, Any] = {
    "name": "capability_shim_max_length",
    "schema": {
        "type": "object",
        "properties": {"title": {"type": "string", "maxLength": 20}},
        "required": ["title"],
    },
}
_MAX_ITEMS: dict[str, Any] = {
    "name": "capability_shim_max_items",
    "schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            }
        },
        "required": ["steps"],
    },
}
_ENVELOPE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hypotheses": {"type": "array", "items": {"type": "string"}}
    },
}


@pytest.mark.parametrize(
    ("schema", "content", "repaired"),
    [
        (
            NESTED_SCHEMA,
            '{"summary": "ok", "assessment": {}}',
            {
                "summary": "ok",
                "assessment": {"verdict": "holds", "notes": []},
            },
        ),
        (
            _CLOSED,
            '{"summary": "ok", "nih_specific_aims": "Aim 1"}',
            {"summary": "ok"},
        ),
        (
            _MAX_ITEMS,
            '{"steps": ["a", "b", "c", "d", "e", "f"]}',
            {"steps": ["a", "b", "c", "d", "e"]},
        ),
        (
            _MAX_LENGTH,
            '{"title": "this title runs well past the cap"}',
            {"title": "this title runs well"},
        ),
        (
            _ENVELOPE,
            '{"hypotheses": {"hypotheses": ["one"]}}',
            {"hypotheses": ["one"]},
        ),
    ],
    ids=["backfill", "prune", "truncate-array", "truncate-string", "envelope"],
)
async def test_only_a_json_object_provider_is_repaired_locally(
    monkeypatch: pytest.MonkeyPatch,
    schema: dict[str, Any],
    content: str,
    repaired: dict[str, Any],
) -> None:
    """Native schema providers reject malformed output; trimming there would
    hide an anomaly, while JSON-object providers repeat the same flaw on
    every retry."""
    sent = _serve(monkeypatch, False, content)
    spec = CompletionSpec(model_name="test-model", json_schema=schema)

    assert await call_llm_json("a prompt", spec, max_attempts=2) == repaired
    assert len(sent) == 1, "no second provider call"

    _serve(monkeypatch, True, content, content)
    with pytest.raises(ValidationError):
        await call_llm_json("a prompt", spec, max_attempts=2)


async def test_a_mangled_nested_taxonomy_validates_after_the_shims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = META_REVIEW_SCHEMA["schema"]
    caps = schema["properties"]["recurring_themes"]["items"]["properties"][
        "sub_themes"
    ]
    point_cap = caps["items"]["properties"]["points"]["maxItems"]
    mangled = {
        "theme": "Primary Driver vs. Consequence",
        "points": [f"point {i}" for i in range(point_cap + 3)],
        "example_reviews": ["review 3"],
    }
    answer = {
        "meta_review_summary": "",
        "recurring_themes": [
            {
                "theme": "Core",
                "description": "How the mechanism is argued.",
                "frequency": "very common",
                "sub_themes": [mangled] * (caps["maxItems"] + 2),
            }
        ],
        "strengths": [],
        "weaknesses": [],
        "process_assessment": {
            "generation_process": "",
            "review_process": "",
            "evolution_process": "",
        },
        "strategic_recommendations": [],
        "potential_connections": [],
        "candidate_comparison": {
            "thematic_summary": "",
            "axes": [],
            "ideas": [],
        },
        "existing_solutions_comparison": {
            "summary": "",
            "axes": [],
            "rows": [],
        },
        "main_research_directions": "",
    }
    _serve(monkeypatch, False, json.dumps(answer))

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(model_name="test-model", json_schema=META_REVIEW_SCHEMA),
        max_attempts=1,
    )

    subs = result["recurring_themes"][0]["sub_themes"]
    assert len(subs) == caps["maxItems"]
    assert subs[0]["description"] == "", "a missing nested field is backfilled"
    assert "example_reviews" not in subs[0], "an invented key is pruned"
    assert len(subs[0]["points"]) == point_cap


_PRUNE_CLOSED: dict[str, Any] = {
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
_ITEMS_REQUIRED: dict[str, Any] = {
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
_BOUNDS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "unbounded": {"type": "array", "items": {"type": "string"}},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 1,
                    },
                    "note": {"type": "string", "maxLength": 8},
                },
            },
        },
        "title": {"type": "string", "maxLength": 20},
        "code": {"type": "string", "minLength": 3, "maxLength": 5},
        "free": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string", "maxLength": 6}},
    },
}


@pytest.mark.parametrize(
    ("schema", "obj", "expected"),
    [
        (
            {
                "type": "object",
                "properties": {
                    "s": {"type": "string"},
                    "o": {"type": "object"},
                    "a": {"type": "array"},
                    "i": {"type": "integer"},
                    "n": {"type": "number"},
                    "u": {},
                    "e": {"type": "string", "enum": ["holds", "weakened"]},
                    "mystery_has_no_property_schema": {},
                },
                "required": ["s", "o", "a", "i", "n", "u", "e", "unknown"],
            },
            {},
            {
                "s": "",
                "o": {},
                "a": [],
                "i": 0,
                "n": 0,
                "u": "",
                "e": "holds",
            },
        ),
        (
            NESTED_SCHEMA["schema"],
            {
                "summary": 42,
                "assessment": {"verdict": "custom", "notes": ["k"]},
            },
            {
                "summary": 42,
                "assessment": {"verdict": "custom", "notes": ["k"]},
            },
        ),
        (
            _ITEMS_REQUIRED,
            {
                "items": [
                    {"title": "present", "notes": ["kept"]},
                    {"title": "x"},
                ]
            },
            {
                "items": [
                    {"title": "present", "notes": ["kept"]},
                    {"title": "x", "notes": []},
                ]
            },
        ),
        (
            _ITEMS_REQUIRED,
            {"items": ["not a dict", 42]},
            {"items": ["not a dict", 42]},
        ),
        (
            _PRUNE_CLOSED,
            {
                "summary": "ok",
                "knowledge_base": {"entries": []},
                "assessment": {"verdict": "holds", "confidence": 0.9},
                "items": [{"title": "a", "rank": 1}, {"title": "b"}],
            },
            {
                "summary": "ok",
                "assessment": {"verdict": "holds"},
                "items": [{"title": "a"}, {"title": "b"}],
            },
        ),
        (
            {"type": "object", "properties": {"summary": {"type": "string"}}},
            {"summary": "ok", "extra": 1},
            {"summary": "ok", "extra": 1},
        ),
        (_PRUNE_CLOSED, {"summary": 42}, {"summary": 42}),
        (
            _BOUNDS,
            {
                "steps": ["a", "b", "c", "d"],
                "unbounded": list("abcdefghij"),
                "sections": [
                    {"notes": ["first", "second"], "note": "way too long"},
                    {"notes": ["only one"], "note": "ok"},
                ],
                "tags": ["short", "waytoolongtag"],
            },
            {
                "steps": ["a", "b", "c"],
                "unbounded": list("abcdefghij"),
                "sections": [
                    {"notes": ["first"], "note": "way too"},
                    {"notes": ["only one"], "note": "ok"},
                ],
                "tags": ["short", "waytoo"],
            },
        ),
        (
            _BOUNDS,
            {"title": "abcdefghij klmnopqr stuvwxyz"},
            {"title": "abcdefghij klmnopqr"},
        ),
        (
            _BOUNDS,
            {"title": "onelongwordwithnospaceatall"},
            {"title": "onelongwordwithnospa"},
        ),
        (
            _BOUNDS,
            {"code": "ab", "free": "x" * 30, "title": 12345, "steps": "none"},
            {"code": "ab", "free": "x" * 30, "title": 12345, "steps": "none"},
        ),
    ],
    ids=[
        "backfill-by-type",
        "backfill-leaves-present-fields",
        "backfill-array-items",
        "non-dict-array-items-ignored",
        "prune-nested-and-array",
        "prune-keeps-extras-the-schema-allows",
        "prune-keeps-declared-invalid",
        "truncate-arrays-and-strings",
        "truncate-at-a-word-boundary",
        "truncate-hard-cut",
        "truncate-leaves-what-it-cannot-bound",
    ],
)
def test_reshaping_repairs_only_what_the_schema_lets_it(
    schema: dict[str, Any], obj: Any, expected: Any
) -> None:
    reshape_json_output(obj, schema)

    assert obj == expected


def test_reshaping_ignores_inputs_that_are_not_objects() -> None:
    reshape_json_output(["not", "a", "dict"], {"required": ["x"]})
    reshape_json_output({"a": 1}, "not a schema")


def test_an_ambiguous_array_envelope_still_fails_validation() -> None:
    schema = {"type": "object", "properties": {"hypotheses": {"type": "array"}}}
    result: dict[str, Any] = {"hypotheses": {"a": [], "b": []}}

    reshape_json_output(result, schema)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, schema)


def test_a_full_review_missing_its_summary_blocks_is_rescued() -> None:
    """Required nested review blocks must backfill on JSON-object
    providers."""
    schema = FULL_REVIEW_SCHEMA["schema"]
    answer: dict[str, Any] = {
        "correctness": "Internally consistent.",
        "assumptions": [],
        "quality_and_novelty": "A non-obvious combination.",
        "literature_grounding": "Two cohort studies agree.",
        "verdict": "sound",
        "justification": "Worth a pilot.",
    }

    reshape_json_output(answer, schema)

    jsonschema.validate(instance=answer, schema=schema)
    assert answer["reviews_summary"]["critical_flaws"] == []
    assert answer["feasibility_steps"] == []

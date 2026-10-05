from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
from jsonschema.exceptions import ValidationError

from co_scientist.llm import CompletionSpec, call_llm, call_llm_json
from co_scientist.llm.request.completion import (
    _supports_json_schema_response_format,
)
from co_scientist.llm.structured.validate import reshape_json_output
from co_scientist.schemas.review import FULL_REVIEW_SCHEMA
from tests._llm_fake import NESTED_SCHEMA as _NESTED_SCHEMA
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_fake import scripted_backend


def _completion(content: str) -> SimpleNamespace:
    message = SimpleNamespace(
        role="assistant", content=content, tool_calls=None
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _patch_registry(
    monkeypatch: pytest.MonkeyPatch, supported: bool
) -> dict[str, int]:
    state = {"calls": 0}

    def fake_supports(model: str) -> bool:
        state["calls"] += 1
        return supported

    monkeypatch.setattr(
        "co_scientist.llm.litellm.supports_response_schema", fake_supports
    )
    return state


def _capture_acompletion(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> list[dict[str, Any]]:
    return scripted_backend(monkeypatch, responses).requests


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


_LLM_CAPABILITY_SHIM_CLOSED_SCHEMA: dict[str, Any] = {
    "name": "capability_shim_closed",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}


@pytest.mark.usefixtures("clear_capability_cache")
class TestLlmCapabilityShim:
    def test_deepseek_family_overrides_registry(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LiteLLM advertises native schema support that the DeepSeek API
        rejects."""
        state = _patch_registry(monkeypatch, supported=True)

        assert (
            _supports_json_schema_response_format("deepseek/deepseek-chat")
            is False
        )
        assert state["calls"] == 0

    def test_registry_supported_model_keeps_json_schema(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_registry(monkeypatch, supported=True)

        assert (
            _supports_json_schema_response_format("gemini/gemini-2.5-flash")
            is True
        )

    def test_registry_unsupported_model_downgrades(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_registry(monkeypatch, supported=False)

        assert (
            _supports_json_schema_response_format("some/other-model") is False
        )

    def test_registry_lookup_failure_defaults_to_supported(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        def raising_supports(model: str) -> bool:
            raise RuntimeError("registry unavailable")

        monkeypatch.setattr(
            "co_scientist.llm.litellm.supports_response_schema",
            raising_supports,
        )

        assert _supports_json_schema_response_format("some/other-model") is True

    async def test_call_llm_downgrades_request_for_unsupported_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=False)
        captured = _capture_acompletion(monkeypatch, [_completion("{}")])

        await call_llm(
            "a prompt",
            CompletionSpec(model_name="test-model", json_schema=_NESTED_SCHEMA),
        )

        assert captured[0]["response_format"] == {"type": "json_object"}
        expected_content = (
            "a prompt"
            + _SCHEMA_PROMPT_SUFFIX
            + json.dumps(_NESTED_SCHEMA["schema"], indent=2)
            + _SCHEMA_PROMPT_TRAILER
        )
        assert captured[0]["messages"] == [
            {
                "role": "user",
                "content": expected_content,
            }
        ]

    async def test_downgraded_prompt_forbids_echoing_the_schema(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """JSON-object mode enforces no schema; instructions must distinguish
        the answer from its schema."""
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=False)
        captured = _capture_acompletion(monkeypatch, [_completion("{}")])

        await call_llm(
            "a prompt",
            CompletionSpec(model_name="test-model", json_schema=_NESTED_SCHEMA),
        )

        content = captured[0]["messages"][0]["content"]
        assert "Do NOT output the schema itself" in content
        assert "any field it does not declare will be rejected" in content

    async def test_downgraded_prompt_names_the_reply_as_the_deliverable(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The answer instruction must precede the schema; placing it after
        did not reduce empty answers."""
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=False)
        captured = _capture_acompletion(monkeypatch, [_completion("{}")])

        await call_llm(
            "a prompt",
            CompletionSpec(model_name="test-model", json_schema=_NESTED_SCHEMA),
        )

        content = captured[0]["messages"][0]["content"]
        assert "Your reasoning is not your answer" in content
        assert content.index(
            "Your reasoning is not your answer"
        ) < content.index("RESPOND WITH VALID JSON ONLY")

    async def test_schema_instructions_absent_for_supported_models(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Native schema enforcement already constrains output; repeated
        prompt rules only spend tokens."""
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        captured = _capture_acompletion(monkeypatch, [_completion("{}")])

        await call_llm(
            "a prompt",
            CompletionSpec(model_name="test-model", json_schema=_NESTED_SCHEMA),
        )

        assert (
            "messages" not in captured[0]
            or "Do NOT output the schema"
            not in (captured[0]["messages"][0]["content"])
        )

    async def test_call_llm_keeps_json_schema_for_supported_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        captured = _capture_acompletion(monkeypatch, [_completion("{}")])

        await call_llm(
            "a prompt",
            CompletionSpec(model_name="test-model", json_schema=_NESTED_SCHEMA),
        )

        assert captured[0]["response_format"] == {
            "type": "json_schema",
            "json_schema": _NESTED_SCHEMA,
        }
        assert captured[0]["messages"] == [
            {"role": "user", "content": "a prompt"}
        ]

    async def test_call_llm_downgrade_unwraps_nested_schema_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=False)
        captured = _capture_acompletion(monkeypatch, [_completion("{}")])
        flat_schema: dict[str, Any] = {"type": "object", "properties": {}}

        await call_llm(
            "a prompt",
            CompletionSpec(model_name="test-model", json_schema=flat_schema),
        )

        content = captured[0]["messages"][0]["content"]
        assert json.dumps(flat_schema, indent=2) in content

    async def test_call_llm_json_backfills_before_validation_on_downgrade(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=False)
        captured = _capture_acompletion(
            monkeypatch, [_completion('{"summary": "ok", "assessment": {}}')]
        )

        result = await call_llm_json(
            "a prompt",
            CompletionSpec(model_name="test-model", json_schema=_NESTED_SCHEMA),
            max_attempts=2,
        )

        assert result == {
            "summary": "ok",
            "assessment": {"verdict": "holds", "notes": []},
        }
        assert len(captured) == 1

    async def test_call_llm_json_no_backfill_for_supported_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        incomplete = _completion('{"summary": "ok", "assessment": {}}')
        _capture_acompletion(monkeypatch, [incomplete, incomplete])

        with pytest.raises(ValidationError):
            await call_llm_json(
                "a prompt",
                CompletionSpec(
                    model_name="test-model", json_schema=_NESTED_SCHEMA
                ),
                max_attempts=2,
            )

    async def test_call_llm_json_prunes_invented_fields_on_downgrade(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=False)
        captured = _capture_acompletion(
            monkeypatch,
            [_completion('{"summary": "ok", "nih_specific_aims": "Aim 1"}')],
        )

        result = await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name="test-model",
                json_schema=_LLM_CAPABILITY_SHIM_CLOSED_SCHEMA,
            ),
            max_attempts=2,
        )

        assert result == {"summary": "ok"}
        assert len(captured) == 1

    async def test_call_llm_json_no_prune_for_supported_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        invented = _completion(
            '{"summary": "ok", "nih_specific_aims": "Aim 1"}'
        )
        _capture_acompletion(monkeypatch, [invented, invented])

        with pytest.raises(ValidationError):
            await call_llm_json(
                "a prompt",
                CompletionSpec(
                    model_name="test-model",
                    json_schema=_LLM_CAPABILITY_SHIM_CLOSED_SCHEMA,
                ),
                max_attempts=2,
            )

    @pytest.mark.parametrize("unnamed_envelope", [False, True])
    async def test_native_bare_schema_has_named_wire_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        unnamed_envelope: bool,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        captured = _capture_acompletion(
            monkeypatch, [_completion('{"label":"supports"}')]
        )
        schema = {
            "type": "object",
            "properties": {"label": {"type": "string", "enum": ["supports"]}},
            "required": ["label"],
            "additionalProperties": False,
        }
        result = await call_llm_json(
            "Classify the supplied evidence.",
            CompletionSpec(
                model_name="test-model",
                json_schema={"schema": schema} if unnamed_envelope else schema,
            ),
            max_attempts=1,
        )
        assert result == {"label": "supports"}
        assert captured[0]["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": schema},
        }
        assert "name" not in schema


def test_backfill_fills_missing_required_fields_by_type() -> None:
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

    reshape_json_output(obj, schema)

    assert obj == {"s": "", "o": {}, "a": [], "i": 0, "n": 0, "u": ""}


def test_backfill_uses_first_enum_value_for_strings() -> None:
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["holds", "weakened"]}
        },
        "required": ["verdict"],
    }
    obj: dict[str, Any] = {}

    reshape_json_output(obj, schema)

    assert obj == {"verdict": "holds"}


def test_backfill_recurses_into_nested_objects() -> None:
    obj: dict[str, Any] = {"summary": "ok", "assessment": {}}

    reshape_json_output(obj, _NESTED_SCHEMA["schema"])

    assert obj == {
        "summary": "ok",
        "assessment": {"verdict": "holds", "notes": []},
    }


def test_backfill_leaves_present_fields_untouched() -> None:
    obj: dict[str, Any] = {
        "summary": 42,
        "assessment": {"verdict": "custom", "notes": ["kept"]},
    }

    reshape_json_output(obj, _NESTED_SCHEMA["schema"])

    assert obj == {
        "summary": 42,
        "assessment": {"verdict": "custom", "notes": ["kept"]},
    }


def test_backfill_ignores_required_fields_without_property_schema() -> None:
    schema = {
        "type": "object",
        "properties": {},
        "required": ["mystery"],
    }
    obj: dict[str, Any] = {}

    reshape_json_output(obj, schema)

    assert obj == {}


def test_backfill_noop_for_non_dict_inputs() -> None:
    reshape_json_output(["not", "a", "dict"], {"required": ["x"]})
    reshape_json_output({}, "not a schema")


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
    obj: dict[str, Any] = {
        "items": [
            {"title": "present", "notes": ["kept"]},
            {"title": "missing notes"},
        ]
    }

    reshape_json_output(obj, _ARRAY_OF_OBJECTS_SCHEMA)

    assert obj == {
        "items": [
            {"title": "present", "notes": ["kept"]},
            {"title": "missing notes", "notes": []},
        ]
    }


def test_backfill_ignores_non_dict_array_items() -> None:
    obj: dict[str, Any] = {"items": ["not a dict", 42]}

    reshape_json_output(obj, _ARRAY_OF_OBJECTS_SCHEMA)

    assert obj == {"items": ["not a dict", 42]}


def test_backfill_rescues_a_full_review_missing_reviews_summary() -> None:
    """Required nested review blocks must backfill too on JSON-object
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
    assert answer["reviews_summary"]["executive_verdict"] == ""
    assert answer["feasibility_steps"] == []


_LLM_CAPABILITY_PRUNE_CLOSED_SCHEMA: dict[str, Any] = {
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
    obj: dict[str, Any] = {
        "summary": "ok",
        "knowledge_base": {"entries": []},
        "nih_specific_aims": "Aim 1",
        "research_contacts": ["someone"],
    }

    reshape_json_output(obj, _LLM_CAPABILITY_PRUNE_CLOSED_SCHEMA)

    assert obj == {"summary": "ok"}


def test_prune_recurses_into_nested_objects() -> None:
    obj: dict[str, Any] = {
        "assessment": {"verdict": "holds", "confidence": 0.9}
    }

    reshape_json_output(obj, _LLM_CAPABILITY_PRUNE_CLOSED_SCHEMA)

    assert obj == {"assessment": {"verdict": "holds"}}


def test_prune_recurses_into_arrays_of_objects() -> None:
    obj: dict[str, Any] = {"items": [{"title": "a", "rank": 1}, {"title": "b"}]}

    reshape_json_output(obj, _LLM_CAPABILITY_PRUNE_CLOSED_SCHEMA)

    assert obj == {"items": [{"title": "a"}, {"title": "b"}]}


def test_prune_keeps_extras_where_the_schema_allows_them() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    }
    obj: dict[str, Any] = {"summary": "ok", "extra": 1}

    reshape_json_output(obj, schema)

    assert obj == {"summary": "ok", "extra": 1}


def test_prune_keeps_declared_fields_even_when_invalid() -> None:
    obj: dict[str, Any] = {"summary": 42}

    reshape_json_output(obj, _LLM_CAPABILITY_PRUNE_CLOSED_SCHEMA)

    assert obj == {"summary": 42}


def test_prune_noop_for_non_dict_inputs() -> None:
    reshape_json_output(
        ["not", "a", "dict"], _LLM_CAPABILITY_PRUNE_CLOSED_SCHEMA
    )
    reshape_json_output({"a": 1}, "not a schema")


@pytest.mark.parametrize("envelope", [{"hypotheses": ["one"]}, {"items": []}])
def test_downgraded_nested_array_envelope_is_unwrapped(
    envelope: dict[str, Any],
) -> None:
    schema = {
        "type": "object",
        "properties": {
            "hypotheses": {"type": "array", "items": {"type": "string"}}
        },
    }
    result = {"hypotheses": envelope}
    reshape_json_output(result, schema)
    assert result["hypotheses"] == next(iter(envelope.values()))


def test_ambiguous_array_envelope_still_fails_validation() -> None:
    schema = {"type": "object", "properties": {"hypotheses": {"type": "array"}}}
    result: dict[str, Any] = {"hypotheses": {"a": [], "b": []}}
    reshape_json_output(result, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, schema)


@pytest.mark.asyncio
async def test_wrapped_array_succeeds_without_a_second_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=False)
    captured = _capture_acompletion(
        monkeypatch, [_completion('{"hypotheses": {"hypotheses": ["one"]}}')]
    )
    result = await call_llm_json(
        "generate",
        CompletionSpec(
            model_name="test-model",
            json_schema={
                "type": "object",
                "properties": {
                    "hypotheses": {"type": "array", "items": {"type": "string"}}
                },
            },
        ),
    )
    assert result == {"hypotheses": ["one"]}
    assert len(captured) == 1

"""Tests for the provider-capability shim in ``co_scientist.llm``.

Some providers (DeepSeek) reject ``response_format={"type": "json_schema"}``.
For those models the engine downgrades each schema'd call to
``{"type": "json_object"}``, restates the schema as prompt text, and
back-fills missing required fields with empty defaults before schema
validation. These tests pin down the downgrade decision
(``_supports_json_schema_response_format``), the back-fill behavior
(``_backfill_required_fields``), and the end-to-end wiring through
``call_llm`` / ``call_llm_json``.

Following ``test_llm_wrappers.py``, every network seam is mocked:
``litellm.acompletion`` is replaced with an async fake returning
litellm-shaped ``SimpleNamespace`` objects, ``litellm.supports_response_schema``
is replaced to force each capability branch, and caching is disabled by
patching ``co_scientist.llm.get_cache``.
"""

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from co_scientist import llm
from co_scientist.cache import LLMCache
from co_scientist.llm import (
    _supports_json_schema_response_format,
    call_llm,
    call_llm_json,
)
from co_scientist.llm_json import _backfill_required_fields

# --- helpers ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_capability_cache() -> Iterator[None]:
    """Reset the memoized capability probe around each test.

    ``_supports_json_schema_response_format`` is ``lru_cache``-memoized, so its
    per-model result would otherwise leak across tests that patch the registry
    to different answers for the same model name.
    """
    _supports_json_schema_response_format.cache_clear()
    yield
    _supports_json_schema_response_format.cache_clear()


def _completion(content: str) -> SimpleNamespace:
    """Build a litellm-shaped completion carrying a single text message.

    Args:
        content: The assistant message text.

    Returns:
        A response namespace exposing ``choices[0].message.content``.
    """
    message = SimpleNamespace(
        role="assistant", content=content, tool_calls=None
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _disable_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``llm.get_cache`` to hand back a disabled cache.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(llm, "get_cache", lambda: LLMCache(enabled=False))


def _patch_registry(
    monkeypatch: pytest.MonkeyPatch, supported: bool
) -> dict[str, int]:
    """Patch ``litellm.supports_response_schema`` to a fixed answer.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        supported: The capability answer the fake registry returns.

    Returns:
        A mutable dict whose ``"calls"`` key counts registry lookups.
    """
    state = {"calls": 0}

    def fake_supports(model: str) -> bool:  # pylint: disable=unused-argument
        state["calls"] += 1
        return supported

    monkeypatch.setattr(
        "co_scientist.llm.litellm.supports_response_schema", fake_supports
    )
    return state


def _capture_acompletion(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> list[dict[str, Any]]:
    """Patch ``litellm.acompletion`` and record the kwargs of every call.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        responses: Completion namespaces to return on successive calls.

    Returns:
        A list that accumulates the kwargs dict of each completion call.
    """
    captured: list[dict[str, Any]] = []
    queue = iter(responses)

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.append(kwargs)
        return next(queue)

    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion", fake_acompletion
    )
    return captured


_NESTED_SCHEMA: dict[str, Any] = {
    "name": "capability_shim_test",
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "assessment": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["holds", "weakened"],
                    },
                    "notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["verdict", "notes"],
            },
        },
        "required": ["summary", "assessment"],
    },
}

_SCHEMA_PROMPT_SUFFIX = (
    "\n\n---\nRESPOND WITH VALID JSON ONLY. "
    "Your output MUST strictly match this JSON schema "
    "(all required fields must be present):\n"
)

# --- downgrade decision ------------------------------------------------------


def test_deepseek_family_overrides_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeepSeek models are json_object-only even if the registry says True.

    litellm's cost map marks deepseek/* as supporting response schema while
    the DeepSeek API rejects it, so the family list must win: the registry is
    never even consulted.
    """
    state = _patch_registry(monkeypatch, supported=True)

    assert (
        _supports_json_schema_response_format("deepseek/deepseek-chat") is False
    )
    assert state["calls"] == 0


def test_registry_supported_model_keeps_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registry-supported model keeps the json_schema response format."""
    _patch_registry(monkeypatch, supported=True)

    assert (
        _supports_json_schema_response_format("gemini/gemini-2.5-flash") is True
    )


def test_registry_unsupported_model_downgrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registry-unsupported model is downgraded to json_object."""
    _patch_registry(monkeypatch, supported=False)

    assert _supports_json_schema_response_format("some/other-model") is False


def test_registry_lookup_failure_defaults_to_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing registry lookup leaves the default json_schema path intact."""

    def raising_supports(model: str) -> bool:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(
        "co_scientist.llm.litellm.supports_response_schema", raising_supports
    )

    assert _supports_json_schema_response_format("some/other-model") is True


# --- back-fill ---------------------------------------------------------------


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


# --- call_llm request shaping ------------------------------------------------


async def test_call_llm_downgrades_request_for_unsupported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported model gets json_object plus the schema in the prompt."""
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=False)
    captured = _capture_acompletion(monkeypatch, [_completion("{}")])

    await call_llm("a prompt", "test-model", json_schema=_NESTED_SCHEMA)

    assert captured[0]["response_format"] == {"type": "json_object"}
    expected_content = (
        "a prompt"
        + _SCHEMA_PROMPT_SUFFIX
        + json.dumps(_NESTED_SCHEMA["schema"], indent=2)
    )
    assert captured[0]["messages"] == [
        {
            "role": "user",
            "content": expected_content,
        }
    ]


async def test_call_llm_keeps_json_schema_for_supported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supported model keeps json_schema and an unmodified prompt."""
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=True)
    captured = _capture_acompletion(monkeypatch, [_completion("{}")])

    await call_llm("a prompt", "test-model", json_schema=_NESTED_SCHEMA)

    assert captured[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": _NESTED_SCHEMA,
    }
    assert captured[0]["messages"] == [{"role": "user", "content": "a prompt"}]


async def test_call_llm_downgrade_unwraps_nested_schema_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schema without a nested "schema" key is injected verbatim."""
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=False)
    captured = _capture_acompletion(monkeypatch, [_completion("{}")])
    flat_schema: dict[str, Any] = {"type": "object", "properties": {}}

    await call_llm("a prompt", "test-model", json_schema=flat_schema)

    content = captured[0]["messages"][0]["content"]
    assert content.endswith(json.dumps(flat_schema, indent=2))


# --- call_llm_json back-fill wiring -------------------------------------------


async def test_call_llm_json_backfills_before_validation_on_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the downgrade path, omitted required fields are back-filled.

    The response is missing ``assessment.verdict`` and ``assessment.notes``;
    without the back-fill, schema validation would fail and retry. With it,
    the first attempt validates and the returned dict carries the defaults.
    """
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=False)
    captured = _capture_acompletion(
        monkeypatch, [_completion('{"summary": "ok", "assessment": {}}')]
    )

    result = await call_llm_json(
        "a prompt", "test-model", json_schema=_NESTED_SCHEMA, max_attempts=2
    )

    assert result == {
        "summary": "ok",
        "assessment": {"verdict": "holds", "notes": []},
    }
    assert len(captured) == 1  # validated on the first attempt, no retry


async def test_call_llm_json_no_backfill_for_supported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default json_schema path never back-fills; validation still fails.

    The same incomplete response that succeeds on the downgrade path raises
    ``ValidationError`` for a supported model, proving the back-fill is keyed
    on the downgrade condition rather than applied globally.
    """
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=True)
    incomplete = _completion('{"summary": "ok", "assessment": {}}')
    _capture_acompletion(monkeypatch, [incomplete, incomplete])

    with pytest.raises(ValidationError):
        await call_llm_json(
            "a prompt", "test-model", json_schema=_NESTED_SCHEMA, max_attempts=2
        )

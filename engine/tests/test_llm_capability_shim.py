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
patching ``co_scientist.llm.tools.loop.get_cache``.
"""

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from co_scientist.llm import CompletionSpec, call_llm, call_llm_json
from co_scientist.llm.request.completion import (
    _supports_json_schema_response_format,
)
from tests._llm_fake import NESTED_SCHEMA as _NESTED_SCHEMA
from tests._llm_fake import disable_llm_cache as _disable_cache

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


# Precedes the schema, and the order is load-bearing -- see the position
# note in _inject_schema_into_prompt's docstring.
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

# Follows the schema. Nothing enforces the schema server-side on this route,
# so this wording is the whole constraint; see _inject_schema_into_prompt.
_SCHEMA_PROMPT_TRAILER = (
    "\n\n"
    "Output a JSON object that CONFORMS TO the schema above -- the "
    "actual data. Do NOT output the schema itself: your response must "
    'not contain "type", "properties", or "required" keys unless the '
    "schema declares them as data fields. Use only the property names "
    "the schema lists; any field it does not declare will be rejected."
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


# --- call_llm request shaping ------------------------------------------------


async def test_call_llm_downgrades_request_for_unsupported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported model gets json_object plus the schema in the prompt."""
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shim tells the model to emit data, not the schema it was shown.

    Both production failures on this route were ``additionalProperties``
    violations: a response carrying the schema's own ``type``/``properties``
    keys, and a response inventing an undeclared field. Nothing rejects
    either server-side once json_schema has been downgraded to json_object,
    so the instruction is the only thing standing between them and a
    wasted retry.
    """
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shim tells the model that its reasoning is not the answer.

    A restated schema is something a thinking model can satisfy inside its
    chain of thought and then treat as done, which is the answerless
    completion behind ``LLMThinkingOnlyError``. Measured against the real
    ranking-matchup prompt: thinking alone produced none in 20 calls, the
    schema alone none in 20, the two together 12 in 65 -- and this
    instruction took that to 2 in 65 with thinking left on. It belongs on
    this route because this route is what creates the condition.

    The position is asserted, not just the presence: the identical text
    *after* the schema measured as no fix at all (3 in 40 against a
    control's 3 in 40), so a tidy-up that folds it into the trailing
    instruction block would revert this while still containing the words.
    """
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=False)
    captured = _capture_acompletion(monkeypatch, [_completion("{}")])

    await call_llm(
        "a prompt",
        CompletionSpec(model_name="test-model", json_schema=_NESTED_SCHEMA),
    )

    content = captured[0]["messages"][0]["content"]
    assert "Your reasoning is not your answer" in content
    assert content.index("Your reasoning is not your answer") < content.index(
        "RESPOND WITH VALID JSON ONLY"
    )


async def test_schema_instructions_absent_for_supported_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A json_schema-capable model has the constraint enforced, not narrated.

    The prompt stays clean there: the provider rejects a non-conforming
    response outright, so restating the rules would only spend tokens.
    """
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supported model keeps json_schema and an unmodified prompt."""
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
    assert captured[0]["messages"] == [{"role": "user", "content": "a prompt"}]


async def test_call_llm_downgrade_unwraps_nested_schema_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schema without a nested "schema" key is injected verbatim."""
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
        "a prompt",
        CompletionSpec(model_name="test-model", json_schema=_NESTED_SCHEMA),
        max_attempts=2,
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
            "a prompt",
            CompletionSpec(model_name="test-model", json_schema=_NESTED_SCHEMA),
            max_attempts=2,
        )


# --- call_llm_json prune wiring ----------------------------------------------

_CLOSED_SCHEMA: dict[str, Any] = {
    "name": "capability_shim_closed",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}


async def test_call_llm_json_prunes_invented_fields_on_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the downgrade path, properties the schema forbids are dropped.

    The response carries an invented ``nih_specific_aims`` section. Without
    the prune, the closed schema rejects it and every retry rejects the same
    answer again; with it, the first attempt validates.
    """
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=False)
    captured = _capture_acompletion(
        monkeypatch,
        [_completion('{"summary": "ok", "nih_specific_aims": "Aim 1"}')],
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(model_name="test-model", json_schema=_CLOSED_SCHEMA),
        max_attempts=2,
    )

    assert result == {"summary": "ok"}
    assert len(captured) == 1  # validated on the first attempt, no retry


async def test_call_llm_json_no_prune_for_supported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schema-enforcing provider is trusted: the same answer still fails.

    Proves the prune is keyed on the downgrade condition rather than applied
    globally -- where the provider enforces the schema itself, an extra field
    is a real anomaly and stays a validation failure.
    """
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=True)
    invented = _completion('{"summary": "ok", "nih_specific_aims": "Aim 1"}')
    _capture_acompletion(monkeypatch, [invented, invented])

    with pytest.raises(ValidationError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name="test-model", json_schema=_CLOSED_SCHEMA),
            max_attempts=2,
        )


@pytest.mark.parametrize("unnamed_envelope", [False, True])
async def test_native_bare_schema_has_named_wire_envelope(
    monkeypatch: pytest.MonkeyPatch,
    unnamed_envelope: bool,
) -> None:
    """Bare schemas work through native providers requiring a named envelope."""
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

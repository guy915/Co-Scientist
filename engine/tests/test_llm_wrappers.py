from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError
from litellm.exceptions import BadRequestError

from co_scientist import cache as cache_mod
from co_scientist.cache import LLMCache
from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm,
    call_llm_json,
    precall,
)
from tests._llm_fake import (
    disable_llm_cache,
    install_fake_backend,
    make_completion,
    make_message,
    patch_acompletion,
    scripted_backend,
)

_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}


async def test_call_llm_returns_the_message_and_rejects_an_empty_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_llm_cache(monkeypatch)
    patch_acompletion(
        monkeypatch,
        [
            make_completion(make_message("the answer text")),
            make_completion(make_message("   ")),
        ],
    )
    spec = CompletionSpec(model_name="test-model")

    assert await call_llm("a prompt", spec) == "the answer text"
    with pytest.raises(ValueError, match="None or empty content"):
        await call_llm("a prompt", spec, max_attempts=1)


@pytest.mark.parametrize(
    ("content", "schema", "expected"),
    [
        ('{"a": 1, "b": "x"}', None, {"a": 1, "b": "x"}),
        ('```json\n{"a": 7}\n```', None, {"a": 7}),
        ('{"a": 1,}', _INT_SCHEMA, {"a": 1}),
        ("this is not json at all", None, json.JSONDecodeError),
        ('{"a": "not an int"}', _INT_SCHEMA, ValidationError),
    ],
    ids=["clean", "fenced", "trailing-comma", "unparseable", "wrong-type"],
)
async def test_call_llm_json_repairs_what_it_can_and_raises_what_it_cannot(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    schema: dict[str, Any] | None,
    expected: Any,
) -> None:
    disable_llm_cache(monkeypatch)
    patch_acompletion(monkeypatch, [make_completion(make_message(content))] * 2)
    spec = CompletionSpec(model_name="test-model", json_schema=schema)

    if isinstance(expected, type):
        with pytest.raises(expected):
            await call_llm_json("a prompt", spec, max_attempts=2)
    else:
        assert await call_llm_json("a prompt", spec, max_attempts=2) == expected


async def test_a_scoped_override_bypasses_a_cache_that_would_otherwise_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = LLMCache(cache_dir=str(tmp_path), enabled=True)
    monkeypatch.setattr(precall, "get_cache", lambda: cache)
    backend = scripted_backend(
        monkeypatch, [make_completion(make_message("fresh"))], repeat_last=True
    )
    spec = CompletionSpec(model_name="test-model")
    cached = LLMCallOptions(use_cache=True)

    await call_llm("a prompt", spec, options=cached)
    await call_llm("a prompt", spec, options=cached)
    assert len(backend.requests) == 1

    with cache_mod.scoped_cache_override(False):
        await call_llm("a prompt", spec, options=cached)
    assert len(backend.requests) == 2


async def test_a_rejected_reasoning_cap_falls_back_to_the_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported bounds degrade to a reasoning tier instead of failing."""
    disable_llm_cache(monkeypatch)
    model = "openrouter/minimax/minimax-m3:free"
    backend = scripted_backend(
        monkeypatch,
        [
            BadRequestError(
                message=(
                    "reasoning.max_tokens is not supported for this model."
                ),
                model=model,
                llm_provider="openrouter",
            ),
            make_completion(make_message('{"a": 1}')),
        ],
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=model, max_tokens=12000, json_schema=_INT_SCHEMA
        ),
        max_attempts=3,
        options=LLMCallOptions(enable_thinking=False),
    )

    assert result == {"a": 1}
    first, second = (r["extra_body"]["reasoning"] for r in backend.requests)
    assert first["max_tokens"] > 0
    assert second == {"enabled": True, "effort": "low"}


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-opus-5-5",
        "anthropic/claude-sonnet-5-5",
        "openai/gpt-6.1-sol",
        "openai/gpt-6-astra",
        "gemini/gemini-3.8-flash",
    ],
)
@pytest.mark.parametrize("enable_thinking", [True, False])
async def test_direct_reasoning_models_think_by_default_within_the_floor(
    monkeypatch: pytest.MonkeyPatch, model: str, enable_thinking: bool
) -> None:
    """Their thinking spends the output cap, so even calls that ask for no
    thinking get the floor, and no thinking knob is sent."""
    disable_llm_cache(monkeypatch)
    backend = install_fake_backend(monkeypatch, _answer)

    await call_llm(
        "prompt",
        CompletionSpec(model_name=model, max_tokens=4000),
        options=LLMCallOptions(enable_thinking=enable_thinking),
    )

    request = backend.requests[0]
    assert (
        not {"output_config", "reasoning_effort", "thinking"} & request.keys()
    )
    cap = request.get("max_completion_tokens") or request["max_tokens"]
    assert cap >= THINKING_FLOOR_MAX_TOKENS
    if model.startswith("openai/"):
        assert "max_tokens" not in request


async def _answer(**_kwargs: Any) -> Any:
    return make_completion(make_message("ok"))


@pytest.mark.parametrize(
    "model", ["anthropic/claude-opus-5-5", "openai/gpt-6-astra"]
)
async def test_models_that_reject_sampling_knobs_never_get_them(
    monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    disable_llm_cache(monkeypatch)
    backend = install_fake_backend(monkeypatch, _answer)

    await call_llm("prompt", CompletionSpec(model_name=model))

    assert "temperature" not in backend.requests[0]


async def test_claude_structured_calls_carry_the_schema_in_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LiteLLM turns a native schema into a forced tool call, which Claude
    refuses while thinking."""
    disable_llm_cache(monkeypatch)
    backend = install_fake_backend(monkeypatch, _answer)

    await call_llm(
        "prompt",
        CompletionSpec(
            model_name="anthropic/claude-opus-5-5",
            json_schema={"type": "object"},
        ),
    )

    assert backend.requests[0]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("model", ["openai/gpt-6.1-sol", "openai/gpt-6-astra"])
async def test_gpt6_calls_go_through_the_responses_api_once_per_retry(
    monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    """Chat Completions refuses function calling on these models."""
    disable_llm_cache(monkeypatch)
    backend = scripted_backend(
        monkeypatch, [RuntimeError("blip"), make_completion(make_message("ok"))]
    )

    await call_llm("prompt", CompletionSpec(model_name=model), max_attempts=2)

    assert [r["model"] for r in backend.requests] == [
        model.replace("openai/", "openai/responses/", 1)
    ] * 2

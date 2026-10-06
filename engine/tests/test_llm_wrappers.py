from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError
from litellm.exceptions import BadRequestError

from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm,
    call_llm_json,
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

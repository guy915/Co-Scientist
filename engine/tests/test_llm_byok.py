"""Bring-your-own-key threading through the engine's LLM entry points.

A caller may supply a per-run provider ``api_key`` two ways: explicitly on
``CompletionSpec`` (the call being made) or scoped around a block of work
via ``scoped_api_key`` (how a run's key reaches every agent call without
entering the checkpointed workflow state). Either way the key must arrive
at ``litellm.acompletion`` as its ``api_key`` keyword and must never leak
into the cache or the workflow state.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.cache import LLMCacheRequest
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    current_api_key,
    scoped_api_key,
)

# These tests assert on the completion kwargs, so every call must reach
# the patched acompletion rather than a cache entry.
_NO_CACHE = LLMCallOptions(use_cache=False)


def _response(content: str = "ok") -> SimpleNamespace:
    """Shape a litellm completion response with one text choice."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _capturing_acompletion(captured: dict[str, Any]) -> Any:
    """A fake ``acompletion`` recording its kwargs into ``captured``."""

    async def acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.clear()
        captured.update(kwargs)
        return _response()

    return acompletion


def _message(content: str = "final") -> SimpleNamespace:
    """Shape an assistant message for the tool-loop path."""
    return SimpleNamespace(role="assistant", content=content)


async def test_call_llm_passes_spec_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion",
        _capturing_acompletion(captured),
    )
    await call_llm(
        "prompt",
        CompletionSpec(model_name="openai/gpt-x", api_key="sk-byok-123"),
        options=_NO_CACHE,
    )
    assert captured["api_key"] == "sk-byok-123"


async def test_call_llm_passes_scoped_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion",
        _capturing_acompletion(captured),
    )
    with scoped_api_key("sk-byok-scoped"):
        await call_llm(
            "prompt scoped",
            CompletionSpec(model_name="openai/gpt-x"),
            options=_NO_CACHE,
        )
    assert captured["api_key"] == "sk-byok-scoped"


async def test_call_llm_omits_api_key_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion",
        _capturing_acompletion(captured),
    )
    await call_llm(
        "prompt bare",
        CompletionSpec(model_name="openai/gpt-x"),
        options=_NO_CACHE,
    )
    assert "api_key" not in captured


async def test_call_llm_json_passes_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.clear()
        captured.update(kwargs)
        return _response('{"answer": 1}')

    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", acompletion)
    result = await call_llm_json(
        "prompt",
        CompletionSpec(
            model_name="openai/gpt-x",
            force_json=True,
            api_key="sk-byok-json",
        ),
        options=_NO_CACHE,
    )
    assert result == {"answer": 1}
    assert captured["api_key"] == "sk-byok-json"


async def test_call_llm_with_tools_passes_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.clear()
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=_message("final"))]
        )

    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", acompletion)

    async def executor(tool_call: Any) -> dict[str, Any]:
        return {}

    loop = ToolLoop(tools=[], executor=executor, max_iterations=1)
    with scoped_api_key("sk-byok-tools"):
        text, _history = await call_llm_with_tools(
            "prompt",
            CompletionSpec(model_name="openai/gpt-x"),
            loop,
            options=_NO_CACHE,
        )
    assert text == "final"
    assert captured["api_key"] == "sk-byok-tools"


def test_scoped_api_key_resets_on_exit() -> None:
    assert current_api_key() is None
    with scoped_api_key("sk-byok"):
        assert current_api_key() == "sk-byok"
        with scoped_api_key(None):
            # None is a no-op scope: the outer key stays in effect.
            assert current_api_key() == "sk-byok"
    assert current_api_key() is None


def test_api_key_not_in_cache_request() -> None:
    """The cache-key object must never carry the credential."""
    request = LLMCacheRequest(
        prompt="p",
        model_name="m",
        temperature=0.7,
        max_tokens=100,
    )
    assert not hasattr(request, "api_key")


def test_generator_constructor_forces_cache_off_with_api_key() -> None:
    from co_scientist.generator.core import HypothesisGenerator
    from co_scientist.generator.options import GeneratorOptions

    generator = HypothesisGenerator(
        model_name="openai/gpt-x",
        options=GeneratorOptions(api_key="sk-byok"),
    )
    assert generator.api_key == "sk-byok"
    assert generator.enable_cache is False


def test_generator_api_key_stays_out_of_initial_state() -> None:
    """A BYOK generator's config fields must not carry the key.

    The workflow state is checkpointed wholesale; the key may only ever
    travel through the generator attribute and the scoped context.
    """
    from co_scientist.generator.core import HypothesisGenerator
    from co_scientist.generator.options import GeneratorOptions

    generator = HypothesisGenerator(
        model_name="openai/gpt-x",
        options=GeneratorOptions(api_key="sk-byok-secret"),
    )
    fields = generator._initial_config_fields()
    assert "sk-byok-secret" not in str(fields)
    assert "api_key" not in fields

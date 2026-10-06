from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.constants import MODEL_PRICING
from co_scientist.generator.core import HypothesisGenerator
from co_scientist.generator.run_setup import GeneratorOptions
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    model_profile,
    scoped_api_key,
)
from co_scientist.llm.profile import (
    ROUTES,
    Thinking,
    gateway_routes,
    priced_routes,
)
from tests._llm_fake import install_fake_backend

_NO_CACHE = LLMCallOptions(use_cache=False)


def _reply(content: str = "ok") -> SimpleNamespace:
    message = SimpleNamespace(role="assistant", content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.mark.parametrize("kind", ["text", "json", "tools"])
@pytest.mark.parametrize("source", ["spec", "scoped", "none"])
async def test_a_byok_key_reaches_the_provider_and_is_never_invented(
    monkeypatch: pytest.MonkeyPatch, kind: str, source: str
) -> None:
    sent: list[dict[str, Any]] = []

    async def acompletion(**kwargs: Any) -> SimpleNamespace:
        sent.append(kwargs)
        return _reply('{"answer": 1}')

    async def executor(tool_call: Any) -> dict[str, Any]:
        return {}

    install_fake_backend(monkeypatch, acompletion)
    spec = CompletionSpec(
        model_name="openai/gpt-x",
        api_key="sk-byok-spec" if source == "spec" else None,
    )

    with scoped_api_key("sk-byok-scoped" if source == "scoped" else None):
        if kind == "text":
            await call_llm("prompt", spec, options=_NO_CACHE)
        elif kind == "json":
            await call_llm_json("prompt", spec, options=_NO_CACHE)
        else:
            await call_llm_with_tools(
                "prompt",
                spec,
                ToolLoop(tools=[], executor=executor, max_iterations=1),
                options=_NO_CACHE,
            )

    assert (
        sent[0].get("api_key")
        == {
            "spec": "sk-byok-spec",
            "scoped": "sk-byok-scoped",
            "none": None,
        }[source]
    )
    assert ("api_key" in sent[0]) is (source != "none")


def test_a_byok_key_forces_the_cache_off_and_stays_out_of_state() -> None:
    """Workflow state is checkpointed wholesale; BYOK credentials must stay
    out."""
    generator = HypothesisGenerator(
        model_name="openai/gpt-x",
        options=GeneratorOptions(api_key="sk-byok-secret"),
    )

    assert generator.api_key == "sk-byok-secret"
    assert generator.enable_cache is False
    fields = generator._initial_config_fields()
    assert "sk-byok-secret" not in str(fields)
    assert "api_key" not in fields


_ULTRA = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"


def test_capabilities_resolve_without_regard_to_case() -> None:
    assert model_profile("DeepSeek/DeepSeek-V4-Flash") == model_profile(
        "deepseek/deepseek-v4-flash"
    )
    assert model_profile(_ULTRA.upper()) == model_profile(_ULTRA)


def test_the_thinking_knob_and_the_gateway_agree() -> None:
    probes = ["deepseek/x", "openrouter/deepseek/x", "openrouter/a/b"]
    for name in [*ROUTES, *probes]:
        profile = model_profile(name)
        if profile.thinking is Thinking.GATEWAY:
            assert profile.gateway, name
        if profile.thinking is Thinking.NATIVE:
            assert not profile.gateway, name


def test_every_declared_gateway_route_is_priced_and_funded() -> None:
    routes = gateway_routes()
    assert routes
    for name in routes:
        profile = model_profile(name)
        assert profile.price is not None, name
        assert profile.reasons, name


def test_the_price_table_is_the_profile_prices() -> None:
    assert priced_routes() == MODEL_PRICING
    for name, price in MODEL_PRICING.items():
        assert model_profile(name).price == price, name

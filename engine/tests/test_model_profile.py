from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.constants import MODEL_PRICING, estimate_cost_usd
from co_scientist.generator.core import HypothesisGenerator
from co_scientist.generator.run_setup import GeneratorOptions
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ModelProfile,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    current_api_key,
    model_profile,
    scoped_api_key,
)
from co_scientist.llm.profile import (
    FAMILIES,
    ROUTES,
    Facts,
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


def test_a_scoped_api_key_resets_on_exit_and_none_keeps_the_outer_one() -> None:
    assert current_api_key() is None
    with scoped_api_key("sk-byok"), scoped_api_key(None):
        assert current_api_key() == "sk-byok"
    assert current_api_key() is None


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


@pytest.mark.parametrize(
    "model",
    ["gpt-4o", "ollama/llama3", "openrouter/x/y", "openrouter/x/y:free"],
)
def test_an_unknown_route_gets_the_defaults(model: str) -> None:
    assert model_profile(model) == ModelProfile()


def test_capabilities_resolve_without_regard_to_case() -> None:
    assert model_profile("DeepSeek/DeepSeek-V4-Flash") == model_profile(
        "deepseek/deepseek-v4-flash"
    )
    assert model_profile(_ULTRA.upper()) == model_profile(_ULTRA)


@pytest.mark.parametrize(
    ("model", "thinking", "gateway"),
    [
        ("deepseek/deepseek-v5-x", Thinking.NATIVE, False),
        ("vendor/mydeepseek-r9", Thinking.NATIVE, False),
        ("openrouter/deepseek/deepseek-v5-x", Thinking.GATEWAY, True),
        (_ULTRA, Thinking.GATEWAY, True),
        ("openrouter/vendor/gemini-3-x", Thinking.NONE, False),
    ],
)
def test_how_a_route_is_asked_to_think_follows_its_family(
    model: str, thinking: Thinking, gateway: bool
) -> None:
    profile = model_profile(model)
    assert (profile.thinking, profile.gateway) == (thinking, gateway)


def test_a_family_can_reach_a_route_it_shares_with_another() -> None:
    profile = model_profile("openrouter/vendor/gemini-3-deepseek-hybrid")
    assert profile.min_temperature == 1.0
    assert profile.thinking is Thinking.GATEWAY
    assert profile.json_schema is False


def test_an_exact_entry_overrides_its_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = "openrouter/deepseek/pinned"
    own: Facts = {"reasons": False, "json_schema": True}
    monkeypatch.setitem(ROUTES, route, own)

    profile = model_profile(route)

    assert profile.reasons is False
    assert profile.json_schema is True
    assert profile.thinking is Thinking.GATEWAY, (
        "unstated fields stay the family's"
    )


def test_no_exact_route_overrules_a_family_on_json_schema() -> None:
    for route, facts in ROUTES.items():
        for family in FAMILIES:
            stated = family.facts.get("json_schema")
            if family.matches(route) and stated is not None:
                assert facts.get("json_schema", stated) == stated, route


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


def test_cost_is_billed_by_tokens_with_cached_prefixes_at_the_cache_rate() -> (
    None
):
    """Tool turns resend cached prefixes; full input pricing overstates their
    cost, and an unknown cache-read price must not be treated as free."""
    million = 1_000_000
    assert estimate_cost_usd("offline/does-not-exist", million, million) == 0.0
    assert estimate_cost_usd("deepseek/deepseek-v4-pro", 0, 0) == 0.0
    flash = MODEL_PRICING["deepseek/deepseek-v4-flash"]
    assert estimate_cost_usd(
        "deepseek/deepseek-v4-flash", million, million
    ) == (flash.prompt_usd_per_million + flash.completion_usd_per_million)

    model = "openrouter/deepseek/deepseek-v4-flash"
    price = MODEL_PRICING[model]
    assert price.cached_prompt_usd_per_million < price.prompt_usd_per_million
    assert estimate_cost_usd(model, million, 0, million) == (
        price.cached_prompt_usd_per_million
    )
    assert estimate_cost_usd(model, 1_000, 0, 10_000) == (
        1_000 / million * price.cached_prompt_usd_per_million
    ), "a cached count never exceeds the prompt it slices"
    assert estimate_cost_usd(model, 1_000, 0, -5) == (
        1_000 / million * price.prompt_usd_per_million
    )

    unmeasured = "openai/gpt-4o"
    assert MODEL_PRICING[unmeasured].cached_prompt_usd_per_million == 0.0
    assert estimate_cost_usd(unmeasured, million, 0, million) == (
        estimate_cost_usd(unmeasured, million, 0)
    )

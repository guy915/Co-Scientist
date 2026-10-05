from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest import mock

import litellm
import pytest

from co_scientist.cache import LLMCacheRequest
from co_scientist.constants import MODEL_PRICING, estimate_cost_usd
from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ModelProfile,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    current_api_key,
    deepseek_thinking_extra_body,
    model_profile,
    model_reasons,
    reasoning_effort_args,
    scoped_api_key,
)
from co_scientist.llm.admission.free_policy import _requires_free, verify_model
from co_scientist.llm.profile import (
    FAMILIES,
    ROUTES,
    Facts,
    Thinking,
    gateway_routes,
    priced_routes,
)
from co_scientist.llm.request.completion import (
    CompletionShape,
    _build_completion_args,
    _clamp_temperature,
    _supports_json_schema_response_format,
)
from co_scientist.llm.request.thinking import (
    _gateway_provider,
    effective_max_tokens,
    effective_thinking_enabled,
    scoped_minimal_reasoning,
)
from tests._llm_fake import CAPABILITIES, MONEY, install_fake_backend

# These tests assert on the completion kwargs, so every call must reach
# the patched acompletion rather than a cache entry.
_NO_CACHE = LLMCallOptions(use_cache=False)


def _response(content: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _capturing_acompletion(captured: dict[str, Any]) -> Any:

    async def acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.clear()
        captured.update(kwargs)
        return _response()

    return acompletion


def _message(content: str = "final") -> SimpleNamespace:
    return SimpleNamespace(role="assistant", content=content)


async def test_call_llm_passes_spec_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    install_fake_backend(monkeypatch, _capturing_acompletion(captured))
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
    install_fake_backend(monkeypatch, _capturing_acompletion(captured))
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
    install_fake_backend(monkeypatch, _capturing_acompletion(captured))
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

    install_fake_backend(monkeypatch, acompletion)
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

    install_fake_backend(monkeypatch, acompletion)

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
            assert current_api_key() == "sk-byok"
    assert current_api_key() is None


def test_api_key_not_in_cache_request() -> None:
    request = LLMCacheRequest(
        prompt="p",
        model_name="m",
        temperature=0.7,
        max_tokens=100,
    )
    assert not hasattr(request, "api_key")


def test_generator_constructor_forces_cache_off_with_api_key() -> None:
    from co_scientist.generator.core import HypothesisGenerator
    from co_scientist.generator.run_setup import GeneratorOptions

    generator = HypothesisGenerator(
        model_name="openai/gpt-x",
        options=GeneratorOptions(api_key="sk-byok"),
    )
    assert generator.api_key == "sk-byok"
    assert generator.enable_cache is False


def test_generator_api_key_stays_out_of_initial_state() -> None:
    """Workflow state is checkpointed wholesale; BYOK credentials must stay
    out."""
    from co_scientist.generator.core import HypothesisGenerator
    from co_scientist.generator.run_setup import GeneratorOptions

    generator = HypothesisGenerator(
        model_name="openai/gpt-x",
        options=GeneratorOptions(api_key="sk-byok-secret"),
    )
    fields = generator._initial_config_fields()
    assert "sk-byok-secret" not in str(fields)
    assert "api_key" not in fields


_ULTRA = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"


def test_a_table_entry_and_a_profile_list_the_same_fields() -> None:
    assert set(Facts.__annotations__) == {
        field.name for field in dataclasses.fields(ModelProfile)
    }


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


def _resolved_profiles() -> list[tuple[str, ModelProfile]]:
    probes = ["deepseek/x", "openrouter/deepseek/x", "openrouter/a/b"]
    return [(name, model_profile(name)) for name in [*ROUTES, *probes]]


def test_the_thinking_knob_and_the_gateway_agree() -> None:
    for name, profile in _resolved_profiles():
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


_SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}
_FREE_ROW = {
    "pricing": {"prompt": "0", "completion": "0"},
    "architecture": {
        "input_modalities": ["text"],
        "output_modalities": ["text"],
    },
}
_KNOB_KEYS = ("reasoning", "thinking")
_BASE_PROVIDER: dict[str, Any] = {
    "require_parameters": True,
    "allow_fallbacks": True,
    "preferred_min_throughput": 25,
    "order": ["z-ai", "deepinfra", "novita", "gmicloud"],
}


@contextlib.contextmanager
def _registry(answer: bool | type[Exception]) -> Iterator[None]:

    def stub(model: str) -> bool:
        if isinstance(answer, bool):
            return answer
        raise answer("no registry entry")

    patch = mock.patch.object(litellm, "supports_response_schema", stub)
    _supports_json_schema_response_format.cache_clear()
    try:
        with patch:
            yield
    finally:
        _supports_json_schema_response_format.cache_clear()


def _schema_route(model: str) -> bool | str:
    answers = []
    for stub in (True, False, RuntimeError):
        with _registry(stub):
            answers.append(_supports_json_schema_response_format(model))
    if answers == [True, False, True]:
        return "registry"
    assert len(set(answers)) == 1, (model, answers)
    return answers[0]


def _free_row(model: str) -> str:
    route = model.removeprefix("openrouter/")
    try:
        verify_model(route, {route: _FREE_ROW})
    except FreeModelEligibilityError as exc:
        return str(exc)
    return "ok"


def _bodies(model: str) -> list[dict[str, Any]]:
    with scoped_minimal_reasoning():
        recovering = deepseek_thinking_extra_body(model, enabled=False)
    return [
        deepseek_thinking_extra_body(model),
        deepseek_thinking_extra_body(model, enabled=False),
        recovering,
    ]


def _routing(model: str, body: dict[str, Any]) -> dict[str, Any]:
    routing = {k: v for k, v in body.items() if k not in _KNOB_KEYS}
    if routing.get("provider") == _gateway_provider(model.lower()):
        routing["provider"] = "gateway provider"
    return routing


def _split_body(model: str) -> tuple[list[Any], dict[str, Any]]:
    bodies = _bodies(model)
    routings = [_routing(model, body) for body in bodies]
    assert routings[0] == routings[1] == routings[2], model
    knobs = [
        next((body[key] for key in _KNOB_KEYS if key in body), None)
        for body in bodies
    ]
    return knobs, routings[0]


def _request(model: str, shape: CompletionShape) -> list[Any]:
    args = _build_completion_args("prompt", model, 4000, 0.5, shape)
    wired = args.get("extra_body", {}) == deepseek_thinking_extra_body(
        model, enabled=shape.enable_thinking
    ) and args.get("reasoning_effort") == reasoning_effort_args(
        model, enabled=shape.enable_thinking
    ).get("reasoning_effort")
    return [
        args.get("response_format", {}).get("type"),
        args["messages"] != [{"role": "user", "content": "prompt"}],
        args["max_tokens"],
        wired,
    ]


def _requests(model: str) -> list[list[Any]]:
    with _registry(True):
        schema = _request(model, CompletionShape(json_schema=_SCHEMA))
        plain = _request(
            model, CompletionShape(force_json=True, enable_thinking=False)
        )
    return [schema, plain]


def _thinks(model: str) -> list[bool]:
    with scoped_minimal_reasoning():
        recovering = effective_thinking_enabled(model, False)
    return [effective_thinking_enabled(model, False), recovering]


def _capabilities(model: str) -> dict[str, Any]:
    knobs, routing = _split_body(model)
    return {
        "reasons": model_reasons(model),
        "effort": [
            reasoning_effort_args(model),
            reasoning_effort_args(model, enabled=False),
        ],
        "knobs": knobs,
        "routing": routing,
        "thinks": _thinks(model),
        "floor": [
            effective_max_tokens(model, 4000, True),
            effective_max_tokens(model, 4000, False),
        ],
        "schema": _schema_route(model),
        "temperature": [_clamp_temperature(model, t) for t in (0.0, 0.7, 1.0)],
        "free": [
            _requires_free({"model": model}, byok=False),
            _requires_free({"model": model}, byok=True),
        ],
        "free_row": _free_row(model),
        "requests": _requests(model),
    }


def _provider_delta(provider: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(provider.keys() | _BASE_PROVIDER.keys())
    return {
        key: provider.get(key)
        for key in keys
        if provider.get(key) != _BASE_PROVIDER.get(key)
    }


def _money(model: str) -> list[Any]:
    price = MODEL_PRICING.get(model)
    return [
        None
        if price is None
        else [
            price.prompt_usd_per_million,
            price.completion_usd_per_million,
            price.cached_prompt_usd_per_million,
        ],
        estimate_cost_usd(model, 1_000_000, 1_000_000, 500_000),
        _provider_delta(_gateway_provider(model.lower())),
    ]


_CAPABILITY_ROWS = [
    (model, row) for models, row in CAPABILITIES for model in models
]


@pytest.fixture
def _hermetic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    monkeypatch.setenv("COSCIENTIST_LLM_TIMEOUT_SECONDS", "0")


@pytest.mark.usefixtures("_hermetic_environment")
class TestModelProfileSnapshot:
    @pytest.mark.parametrize(("model", "row"), _CAPABILITY_ROWS)
    def test_every_capability_of_the_model_is_unchanged(
        self, model: str, row: dict[str, Any]
    ) -> None:
        observed = _capabilities(model)
        for fact, expected in row.items():
            assert observed[fact] == expected, (model, fact)
        assert observed.keys() == row.keys(), model

    @pytest.mark.parametrize(("model", "row"), sorted(MONEY.items()))
    def test_the_price_and_routing_cap_of_the_model_are_unchanged(
        self, model: str, row: list[Any]
    ) -> None:
        assert _money(model) == row

    def test_every_model_has_both_rows(self) -> None:
        capability_models = {model for model, _ in _CAPABILITY_ROWS}
        assert capability_models == set(MONEY)
        assert set(MODEL_PRICING) <= capability_models


def test_unlisted_model_prices_at_zero() -> None:
    assert (
        estimate_cost_usd("offline/does-not-exist", 1_000_000, 1_000_000) == 0.0
    )


def test_known_model_prices_proportional_to_tokens() -> None:
    """Provider prices are outside facts; this tests arithmetic from their
    table."""
    model = "deepseek/deepseek-v4-flash"
    price = MODEL_PRICING[model]

    million = estimate_cost_usd(model, 1_000_000, 1_000_000)
    half = estimate_cost_usd(model, 500_000, 500_000)

    assert million == (
        price.prompt_usd_per_million + price.completion_usd_per_million
    )
    assert half == million / 2


def test_zero_tokens_costs_nothing() -> None:
    assert estimate_cost_usd("deepseek/deepseek-v4-pro", 0, 0) == 0.0


def test_a_cached_prefix_is_billed_at_the_cache_rate() -> None:
    """Tool turns resend cached prefixes; full input pricing overstates their
    cost."""
    model = "openrouter/deepseek/deepseek-v4-flash"
    price = MODEL_PRICING[model]
    assert price.cached_prompt_usd_per_million < price.prompt_usd_per_million

    uncached = estimate_cost_usd(model, 1_000_000, 0)
    fully_cached = estimate_cost_usd(model, 1_000_000, 0, 1_000_000)

    assert uncached == price.prompt_usd_per_million
    assert fully_cached == price.cached_prompt_usd_per_million
    assert (
        estimate_cost_usd(model, 1_000_000, 0, 500_000)
        == (uncached + fully_cached) / 2
    )


def test_a_model_with_no_measured_cache_rate_prices_as_before() -> None:
    """An unknown cache-read price must not be treated as free."""
    model = "openai/gpt-4o"
    assert MODEL_PRICING[model].cached_prompt_usd_per_million == 0.0

    assert estimate_cost_usd(model, 1_000_000, 0, 1_000_000) == (
        estimate_cost_usd(model, 1_000_000, 0)
    )


def test_a_cached_count_never_exceeds_the_prompt_it_slices() -> None:
    model = "openrouter/deepseek/deepseek-v4-flash"
    price = MODEL_PRICING[model]

    assert estimate_cost_usd(model, 1_000, 0, 10_000) == (
        1_000 / 1_000_000 * price.cached_prompt_usd_per_million
    )
    assert estimate_cost_usd(model, 1_000, 0, -5) == (
        1_000 / 1_000_000 * price.prompt_usd_per_million
    )

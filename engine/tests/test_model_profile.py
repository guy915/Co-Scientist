from __future__ import annotations

import contextlib
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest import mock

import litellm
import pytest

from co_scientist.constants import MODEL_PRICING, estimate_cost_usd
from co_scientist.exceptions import FreeModelEligibilityError
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


_INCOMPLETE = "zero-cost pricing is incomplete"
_GATEWAY = {"provider": "gateway provider"}
_KNOBS_1: Any = [
    {"enabled": True, "effort": "high"},
    {"enabled": True, "max_tokens": 2048},
    {"enabled": True, "effort": "low"},
]
_KNOBS_2: Any = [
    {"enabled": True, "effort": "high"},
    {"enabled": False},
    {"enabled": True, "effort": "low"},
]
_JSON_OBJECT_THINKING = [
    ["json_object", True, 18000, True],
    ["json_object", False, 18000, True],
]
_NATIVE_THEN_OBJECT = [
    ["json_schema", False, 18000, True],
    ["json_object", False, 18000, True],
]
_FOUR_THOUSAND = [
    ["json_schema", False, 4000, True],
    ["json_object", False, 4000, True],
]


def _row(*layers: dict[str, Any], **facts: Any) -> dict[str, Any]:
    """A plain non-reasoning route unless the layers or facts say otherwise."""
    row = {
        "reasons": False,
        "effort": [{}, {}],
        "knobs": [None, None, None],
        "routing": {},
        "thinks": [False, True],
        "floor": [4000, 4000],
        "schema": "registry",
        "temperature": [0.0, 0.7, 1.0],
        "free": [False, False],
        "free_row": _INCOMPLETE,
        "requests": _FOUR_THOUSAND,
    }
    for layer in (*layers, facts):
        row.update(layer)
    return row


_FREE_REASONING: dict[str, Any] = {
    "reasons": True,
    "knobs": _KNOBS_1,
    "routing": _GATEWAY,
    "thinks": [True, True],
    "floor": [18000, 18000],
    "schema": False,
    "free": [True, False],
    "free_row": "ok",
    "requests": _JSON_OBJECT_THINKING,
}
_DEEPSEEK_GATEWAY: dict[str, Any] = {
    "reasons": True,
    "knobs": _KNOBS_2,
    "routing": _GATEWAY,
    "floor": [18000, 4000],
    "schema": False,
    "requests": [
        ["json_object", True, 18000, True],
        ["json_object", False, 4000, True],
    ],
}
_ALWAYS_THINKS: dict[str, Any] = {
    "reasons": True,
    "thinks": [True, True],
    "floor": [18000, 18000],
    "requests": _NATIVE_THEN_OBJECT,
}


def _chain(*models: str) -> dict[str, Any]:
    return {"provider": "gateway provider", "models": list(models)}


CAPABILITIES: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (
        (
            "openrouter/nex-agi/nex-n2.5-pro:free",
            "openrouter/minimax/minimax-m2.7:free",
        ),
        _row(_FREE_REASONING),
    ),
    (
        ("openrouter/qwen/qwen3.8-27b:free",),
        _row(_FREE_REASONING, schema=True, requests=_NATIVE_THEN_OBJECT),
    ),
    (
        ("openrouter/z-ai/glm-5.2:free",),
        _row(
            _FREE_REASONING,
            routing=_chain(
                "minimax/minimax-m3:free",
                "nvidia/nemotron-3-super-120b-a12b:free",
                "nvidia/nemotron-3.5-lightning:free",
            ),
        ),
    ),
    (
        ("openrouter/minimax/minimax-m3:free",),
        _row(
            _FREE_REASONING,
            routing=_chain(
                "nvidia/nemotron-3-super-120b-a12b:free",
                "google/gemma-4-31b-it:free",
                "minimax/minimax-m2.7:free",
            ),
        ),
    ),
    (
        (_ULTRA,),
        _row(
            _FREE_REASONING,
            routing=_chain(
                "dots-studio/dots-3-note-preview:free",
                "nvidia/nemotron-3-super-120b-a12b:free",
            ),
            requests=[
                [None, True, 18000, True],
                [None, False, 18000, True],
            ],
        ),
    ),
    (
        ("openrouter/z-ai/glm-5.3-flash",),
        _row(
            _FREE_REASONING,
            free=[False, False],
            free_row=_INCOMPLETE,
            routing=_chain(
                "minimax/minimax-m3:free",
                "nvidia/nemotron-3.5-lightning:free",
            ),
        ),
    ),
    (
        (
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v5-x",
            "vendor/mydeepseek-r9",
            "DeepSeek/DeepSeek-V4-Flash",
        ),
        _row(
            reasons=True,
            effort=[{"reasoning_effort": "high"}, {}],
            knobs=[
                {"type": "enabled"},
                {"type": "disabled"},
                {"type": "disabled"},
            ],
            floor=[18000, 4000],
            schema=False,
            requests=_DEEPSEEK_GATEWAY["requests"],
        ),
    ),
    (
        (
            "gemini/gemini-2.5-flash",
            "openai/gpt-4o",
            "ollama/llama3",
            "openrouter/qwen/qwen3.8-27b",
        ),
        _row(),
    ),
    (
        ("openrouter/google/gemini-3-x",),
        _row(temperature=[1.0, 1.0, 1.0]),
    ),
    (
        (
            "openrouter/deepseek/deepseek-v4-flash",
            "openrouter/deepseek/deepseek-v5-x",
        ),
        _row(_DEEPSEEK_GATEWAY),
    ),
    (
        ("openrouter/google/gemma-4-26b-a4b-it:free",),
        _row(
            schema=False,
            free=[True, False],
            free_row="ok",
            requests=[
                ["json_object", True, 4000, True],
                ["json_object", False, 4000, True],
            ],
        ),
    ),
    (
        ("openrouter/x/y:free",),
        _row(free=[True, False], free_row="ok"),
    ),
    (
        ("openrouter/deepseek/deepseek-v4-flash:free",),
        _row(_DEEPSEEK_GATEWAY, free=[True, False], free_row="ok"),
    ),
    (
        ("openrouter/vendor/gemini-3-deepseek-hybrid",),
        _row(_DEEPSEEK_GATEWAY, temperature=[1.0, 1.0, 1.0]),
    ),
    (
        ("OpenRouter/NEX-AGI/NEX-N2.5-PRO:FREE",),
        _row(_FREE_REASONING, free=[False, False], free_row=_INCOMPLETE),
    ),
    (
        ("openai/gpt-6.1-sol", "openai/gpt-6-astra"),
        _row(_ALWAYS_THINKS),
    ),
    (
        (
            "gemini/gemini-3.1-flash-lite",
            "gemini/gemini-3.5-flash",
            "Gemini/Gemini-3.1-Flash-Lite",
        ),
        _row(_ALWAYS_THINKS, temperature=[1.0, 1.0, 1.0]),
    ),
    (
        ("anthropic/claude-sonnet-5-5", "anthropic/claude-fable-5-1"),
        _row(_ALWAYS_THINKS, schema=False, requests=_JSON_OBJECT_THINKING),
    ),
]


def _direct_money(prompt: float, completion: float) -> list[Any]:
    cap = {"prompt": prompt * 1.05, "completion": completion * 1.05}
    return [[prompt, completion, 0.0], prompt + completion, {"max_price": cap}]


_FREE: Any = [
    [0.0, 0.0, 0.0],
    0.0,
    {"max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0}},
]
_UNPRICED: Any = [None, 0.0, {}]
_CAP_1: Any = {"max_price": {"prompt": 0.462, "completion": 1.3860000000000001}}
_CAP_3: Any = {
    "max_price": {"prompt": 0.2625, "completion": 1.5750000000000002}
}

MONEY: dict[str, Any] = {
    "openrouter/nex-agi/nex-n2.5-pro:free": _FREE,
    "openrouter/minimax/minimax-m2.7:free": _FREE,
    "openrouter/qwen/qwen3.8-27b:free": [
        [0.0, 0.0, 0.0],
        0.0,
        {
            "data_collection": "deny",
            "max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0},
            "only": ["modelrun"],
            "order": None,
            "zdr": True,
        },
    ],
    "openrouter/z-ai/glm-5.2:free": _FREE,
    "openrouter/minimax/minimax-m3:free": _FREE,
    _ULTRA: _FREE,
    "openrouter/z-ai/glm-5.3-flash": [
        [0.15, 0.5, 0.015],
        0.5825,
        {"max_price": {"prompt": 0.1575, "completion": 0.525}},
    ],
    "deepseek/deepseek-v4-flash": [[0.44, 1.32, 0.0], 1.76, _CAP_1],
    "gemini/gemini-2.5-flash": [
        [0.3, 2.5, 0.0],
        2.8,
        {"max_price": {"prompt": 0.315, "completion": 2.625}},
    ],
    "gemini/gemini-3.1-flash-lite": [[0.25, 1.5, 0.0], 1.75, _CAP_3],
    "openrouter/deepseek/deepseek-v4-flash": [
        [0.083, 0.165, 0.017],
        0.21500000000000002,
        {"max_price": {"prompt": 0.08715, "completion": 0.17325000000000002}},
    ],
    "openai/gpt-4o": [
        [2.5, 10.0, 0.0],
        12.5,
        {"max_price": {"prompt": 2.625, "completion": 10.5}},
    ],
    **{
        name: _direct_money(prompt, completion)
        for name, (prompt, completion) in {
            "anthropic/claude-sonnet-5-5": (2.0, 10.0),
            "anthropic/claude-fable-5-1": (10.0, 50.0),
            "openai/gpt-6.1-sol": (2.0, 10.0),
            "openai/gpt-6-astra": (10.0, 50.0),
        }.items()
    },
    **dict.fromkeys(
        (
            "openrouter/google/gemma-4-26b-a4b-it:free",
            "ollama/llama3",
            "openrouter/x/y:free",
            "openrouter/qwen/qwen3.8-27b",
            "deepseek/deepseek-v5-x",
            "openrouter/deepseek/deepseek-v5-x",
            "openrouter/deepseek/deepseek-v4-flash:free",
            "vendor/mydeepseek-r9",
            "gemini/gemini-3.5-flash",
            "openrouter/google/gemini-3-x",
            "openrouter/vendor/gemini-3-deepseek-hybrid",
        ),
        _UNPRICED,
    ),
    "DeepSeek/DeepSeek-V4-Flash": [None, 0.0, _CAP_1],
    "OpenRouter/NEX-AGI/NEX-N2.5-PRO:FREE": [
        None,
        0.0,
        {"max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0}},
    ],
    "Gemini/Gemini-3.1-Flash-Lite": [None, 0.0, _CAP_3],
}

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
        assert {model for model, _ in _CAPABILITY_ROWS} == set(MONEY)


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

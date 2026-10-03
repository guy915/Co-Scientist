from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.constants import (
    MINIMAL_REASONING_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm,
    call_llm_json,
    deepseek_thinking_extra_body,
    model_reasons,
)
from co_scientist.llm.request.completion import (
    CompletionShape,
    _build_completion_args,
    _supports_json_schema_response_format,
)
from tests._llm_fake import NESTED_SCHEMA as _NESTED_SCHEMA
from tests._llm_fake import _catalog, _mock_catalog
from tests._llm_fake import _free_catalog as _isolated_catalog
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_fake import make_completion as _completion
from tests._llm_fake import make_message as _message
from tests._llm_fake import patch_acompletion as _patch_acompletion

__all__ = ["_isolated_catalog"]

_PRIMARY = "openrouter/z-ai/glm-5.3-flash"
_FREE_PRIMARY = "openrouter/z-ai/glm-5.2:free"
_GLM = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
_MINIMAX = "openrouter/minimax/minimax-m3:free"
_NEX_PRO = "openrouter/nex-agi/nex-n2.5-pro:free"
_QWEN_CANDIDATE = "openrouter/qwen/qwen3.8-27b:free"


def test_the_primary_model_carries_its_fallback_chain() -> None:
    """Free model-pool throttling needs a provider fallback, not another
    transport retry."""
    body = deepseek_thinking_extra_body(_PRIMARY)

    assert body["models"] == [
        "minimax/minimax-m3:free",
        "nvidia/nemotron-3.5-lightning:free",
    ]


def test_the_non_default_free_chain_head_still_carries_its_chain() -> None:
    body = deepseek_thinking_extra_body(_FREE_PRIMARY)

    assert body["models"] == [
        "minimax/minimax-m3:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3.5-lightning:free",
    ]


def test_the_legacy_minimax_default_carries_the_all_free_chain() -> None:
    """OpenRouter limits fallback chains to three models with separate free
    allowances."""
    body = deepseek_thinking_extra_body(_MINIMAX)
    chain = [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "google/gemma-4-31b-it:free",
        "minimax/minimax-m2.7:free",
    ]
    assert body["models"] == chain

    from co_scientist.constants import MODEL_PRICING

    for gateway_relative in (_MINIMAX.removeprefix("openrouter/"), *chain):
        price = MODEL_PRICING[f"openrouter/{gateway_relative}"]
        assert (
            price.prompt_usd_per_million,
            price.completion_usd_per_million,
        ) == (
            0.0,
            0.0,
        ), gateway_relative


def test_the_fallback_models_do_not_themselves_carry_a_chain() -> None:
    """Recursive chains would revisit a model whose allowance was already
    spent."""
    from co_scientist.llm.profile import model_profile

    for gateway_relative in (
        "nvidia/nemotron-3-super-120b-a12b:free",
        "google/gemma-4-31b-it:free",
        "minimax/minimax-m2.7:free",
        "dots-studio/dots-3-note-preview:free",
        "nvidia/nemotron-3.5-lightning:free",
    ):
        model_name = f"openrouter/{gateway_relative}"
        assert "models" not in deepseek_thinking_extra_body(model_name)
        profile = model_profile(model_name)
        assert profile.gateway
        assert not profile.fallbacks


def test_selected_nex_pro_default_has_no_model_fallback() -> None:
    from co_scientist.llm.profile import model_profile

    assert model_profile(_NEX_PRO).gateway
    assert not model_profile(_NEX_PRO).fallbacks
    body = deepseek_thinking_extra_body(_NEX_PRO)
    assert "models" not in body
    assert body["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }


def test_qwen_candidate_uses_only_its_verified_zero_retention_host() -> None:
    """Provider admission depends on the verified zero-retention host."""
    body = deepseek_thinking_extra_body(_QWEN_CANDIDATE, enabled=False)

    assert "models" not in body
    assert body["reasoning"] == {
        "enabled": True,
        "max_tokens": MINIMAL_REASONING_MAX_TOKENS,
    }
    assert body["provider"]["only"] == ["modelrun"]
    assert body["provider"]["zdr"] is True
    assert body["provider"]["data_collection"] == "deny"
    assert "order" not in body["provider"]
    assert body["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }


def test_qwen_candidate_uses_native_schema() -> None:
    assert _supports_json_schema_response_format(_QWEN_CANDIDATE) is True
    args = _build_completion_args(
        "Return JSON",
        _QWEN_CANDIDATE,
        6000,
        0,
        CompletionShape(json_schema={"type": "object", "properties": {}}),
    )
    assert args["response_format"]["type"] == "json_schema"


def test_a_reasoning_model_in_the_chain_still_gets_the_knob() -> None:
    body = deepseek_thinking_extra_body(_GLM)

    assert body["reasoning"] == {"enabled": True, "effort": "high"}


def test_a_disable_request_gets_capped_reasoning_when_mandatory() -> None:
    """Mandatory reasoning cannot honor disable; bound its spend instead."""
    body = deepseek_thinking_extra_body(_MINIMAX, enabled=False)

    assert body["reasoning"] == {
        "enabled": True,
        "max_tokens": MINIMAL_REASONING_MAX_TOKENS,
    }


def test_the_reasoning_cap_leaves_room_for_the_answer() -> None:
    """Reasoning and answer tokens share one completion budget."""
    smallest_entailment_budget = 6000

    assert MINIMAL_REASONING_MAX_TOKENS >= 1024
    assert smallest_entailment_budget // 2 > MINIMAL_REASONING_MAX_TOKENS


def test_the_minimal_reasoning_redirect_keeps_the_ordinary_floor() -> None:
    """A higher floor can buy longer thought instead of an answer."""
    from co_scientist.llm.request.thinking import effective_max_tokens

    assert (
        effective_max_tokens(_MINIMAX, 12000, enable_thinking=False)
        == THINKING_FLOOR_MAX_TOKENS
    )


def test_a_call_that_actually_asked_for_thinking_keeps_the_ordinary_floor() -> (
    None
):
    from co_scientist.llm.request.thinking import effective_max_tokens

    assert (
        effective_max_tokens(_MINIMAX, 12000, enable_thinking=True)
        == THINKING_FLOOR_MAX_TOKENS
    )


def test_a_non_reasoning_call_is_untouched_by_the_floor() -> None:
    from co_scientist.llm.request.thinking import effective_max_tokens

    assert (
        effective_max_tokens(
            "openrouter/some/plain-model", 6000, enable_thinking=False
        )
        == 6000
    )


def test_every_gateway_call_is_pinned_to_hosts_that_honour_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parameter support must be binding, not an advisory routing preference."""
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    for model in (_PRIMARY, _GLM, _MINIMAX):
        provider = deepseek_thinking_extra_body(model)["provider"]
        assert provider["require_parameters"] is True
        assert provider["allow_fallbacks"] is True
        assert provider["preferred_min_throughput"] == 25


def test_every_gateway_call_prefers_the_default_upstream_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-robin routing loses cache locality on repeated transcripts."""
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    from co_scientist.llm.request.thinking import _DEFAULT_UPSTREAM_ORDER

    for model in (_PRIMARY, _GLM, _MINIMAX):
        provider = deepseek_thinking_extra_body(model)["provider"]
        assert provider["order"] == list(_DEFAULT_UPSTREAM_ORDER)
        assert "sort" not in provider


def test_the_upstream_order_is_overridable_without_a_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Routing overrides are read live rather than cached at process startup."""
    monkeypatch.setenv(
        "COSCIENTIST_GATEWAY_PROVIDER_ORDER", "friendli, together"
    )
    provider = deepseek_thinking_extra_body(_PRIMARY)["provider"]
    assert provider["order"] == ["friendli", "together"]


def test_an_empty_upstream_order_env_var_opts_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty means opt out, unlike unset; admission caps still apply."""
    monkeypatch.setenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", "")
    provider = deepseek_thinking_extra_body(_PRIMARY)["provider"]
    assert "order" not in provider
    assert provider["require_parameters"] is True
    assert "max_price" in provider


def test_a_direct_non_gateway_route_carries_no_provider_block() -> None:
    """Gateway routing fields must not leak to direct providers."""
    body = deepseek_thinking_extra_body("deepseek/deepseek-chat")
    assert "provider" not in body


def test_gateway_models_without_native_schema_use_json_object() -> None:
    """Registry capability can change; requiring an unsupported parameter
    yields 404."""
    from co_scientist.llm.profile import gateway_routes

    for model in gateway_routes():
        if model == _QWEN_CANDIDATE:
            continue
        assert _supports_json_schema_response_format(model) is False, model


def test_the_primary_still_gets_the_thinking_token_floor() -> None:
    """Zero reported reasoning tokens do not prove zero reasoning spend."""
    args = _build_completion_args(
        "prompt", _PRIMARY, 4000, 0.5, CompletionShape()
    )

    assert args["max_tokens"] == THINKING_FLOOR_MAX_TOKENS


def test_the_two_reasoning_facts_stay_separable() -> None:
    """Knob support and actual reasoning spend are independent provider
    facts."""
    from co_scientist.llm.profile import ModelProfile, Thinking

    knob_only = ModelProfile(thinking=Thinking.NONE, reasons=True)

    assert knob_only.thinking is Thinking.NONE
    assert knob_only.reasons is True
    assert model_reasons(_PRIMARY) is True


def test_no_fallback_costs_more_than_the_model_above_it() -> None:
    """Routine fallback from a free primary must not admit paid models."""
    from co_scientist.constants import MODEL_PRICING
    from co_scientist.llm.profile import gateway_routes, model_profile

    def rate(gateway_relative: str) -> tuple[float, float]:
        price = MODEL_PRICING[f"openrouter/{gateway_relative}"]
        return (
            price.prompt_usd_per_million,
            price.completion_usd_per_million,
        )

    for primary in gateway_routes():
        fallbacks = model_profile(primary).fallbacks
        if not fallbacks:
            continue
        above = (
            MODEL_PRICING[primary].prompt_usd_per_million,
            MODEL_PRICING[primary].completion_usd_per_million,
        )
        for name in fallbacks:
            below = rate(name)
            assert below <= above, (
                f"{name} costs more than {primary} it falls back from"
            )
            above = below


def test_no_declared_chain_exceeds_openrouters_fallback_cap() -> None:
    """OpenRouter accepts at most three models in a fallback chain."""
    from co_scientist.llm.profile import gateway_routes, model_profile
    from co_scientist.llm.request.thinking import _GATEWAY_MAX_FALLBACKS

    for primary in gateway_routes():
        fallbacks = model_profile(primary).fallbacks
        assert len(fallbacks) <= _GATEWAY_MAX_FALLBACKS, primary


def test_no_chain_head_claims_disable_support_a_fallback_lacks() -> None:
    """Every fallback sees the same request and must honor its reasoning
    policy."""
    from co_scientist.llm.profile import gateway_routes, model_profile

    for primary in gateway_routes():
        declared = model_profile(primary)
        if not declared.reasoning_can_disable:
            continue
        for name in declared.fallbacks:
            fallback = model_profile(f"openrouter/{name}")
            assert fallback.gateway and fallback.reasoning_can_disable, (
                f"{primary} claims reasoning_can_disable=True but its "
                f"fallback {name} does not"
            )


def test_the_routing_body_never_sends_more_than_the_cap() -> None:
    from co_scientist.llm.profile import gateway_routes
    from co_scientist.llm.request.thinking import _GATEWAY_MAX_FALLBACKS

    for model in gateway_routes():
        body = deepseek_thinking_extra_body(model)
        assert len(body.get("models", [])) <= _GATEWAY_MAX_FALLBACKS, model


def test_every_catalogued_route_arms_the_routing_ceiling() -> None:
    from co_scientist.constants import MODEL_PRICING
    from co_scientist.llm.profile import gateway_routes
    from co_scientist.llm.request.thinking import _gateway_provider

    for primary in gateway_routes():
        price = MODEL_PRICING[primary]
        provider = _gateway_provider(primary)
        assert "max_price" in provider, primary
        if (
            price.prompt_usd_per_million
            == price.completion_usd_per_million
            == 0
        ):
            assert provider["max_price"] == {
                "prompt": 0,
                "completion": 0,
                "request": 0,
            }


def test_the_price_cap_excludes_the_2x_tier() -> None:
    """The routing ceiling must exclude the premium tier above the headline
    rate."""
    from co_scientist.llm.request.thinking import _MAX_PRICE_MULTIPLE

    assert 1.0 <= _MAX_PRICE_MULTIPLE < 1.29


def test_the_price_cap_admits_the_headline_rate() -> None:
    """Gateway price rounding needs a small admission epsilon."""
    from co_scientist.constants import MODEL_PRICING
    from co_scientist.llm.request.thinking import (
        _MAX_PRICE_MULTIPLE,
        _gateway_provider,
    )

    primary = "openrouter/z-ai/glm-5.3-flash"
    price = MODEL_PRICING[primary]
    provider = _gateway_provider(primary)

    assert provider["max_price"] == {
        "prompt": price.prompt_usd_per_million * _MAX_PRICE_MULTIPLE,
        "completion": price.completion_usd_per_million * _MAX_PRICE_MULTIPLE,
    }
    assert provider["max_price"]["prompt"] >= price.prompt_usd_per_million


_MODEL = "openrouter/google/gemma-4-26b-a4b-it:free"


@pytest.fixture
def _clear_capability_cache() -> Iterator[None]:
    """Clear process-cached capabilities to isolate provider fixtures."""
    _supports_json_schema_response_format.cache_clear()
    yield
    _supports_json_schema_response_format.cache_clear()


def _patch_registry(monkeypatch: pytest.MonkeyPatch, supported: bool) -> None:

    def fake_supports(model: str) -> bool:
        del model
        return supported

    monkeypatch.setattr(
        "co_scientist.llm.litellm.supports_response_schema", fake_supports
    )


def _capture_acompletion(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    _patch_acompletion(monkeypatch, responses, captured)
    return captured


@pytest.mark.usefixtures("_clear_capability_cache", "_isolated_catalog")
class TestLlmGemmaRoute:
    async def test_exact_route_injects_schema_at_request_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        captured = _capture_acompletion(
            monkeypatch, [_completion(_message("{}"))]
        )

        await call_llm(
            "a prompt",
            CompletionSpec(
                model_name=_MODEL,
                api_key="test-byok-key",
                json_schema=_NESTED_SCHEMA,
            ),
        )

        assert captured[0]["response_format"] == {"type": "json_object"}
        content = captured[0]["messages"][0]["content"]
        assert json.dumps(_NESTED_SCHEMA["schema"], indent=2) in content

    async def test_unqualified_gemma_route_keeps_native_schema(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        captured = _capture_acompletion(
            monkeypatch, [_completion(_message("{}"))]
        )

        await call_llm(
            "a prompt",
            CompletionSpec(
                model_name="google/gemma-4-26b-a4b-it",
                api_key="test-byok-key",
                json_schema=_NESTED_SCHEMA,
            ),
        )

        assert captured[0]["response_format"] == {
            "type": "json_schema",
            "json_schema": _NESTED_SCHEMA,
        }
        assert captured[0]["messages"] == [
            {"role": "user", "content": "a prompt"}
        ]

    async def test_exact_route_keeps_local_schema_backfill_and_validation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        captured = _capture_acompletion(
            monkeypatch,
            [_completion(_message('{"summary": "ok", "assessment": {}}'))],
        )

        result = await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_MODEL,
                api_key="test-byok-key",
                json_schema=_NESTED_SCHEMA,
            ),
            max_attempts=2,
        )

        assert result == {
            "summary": "ok",
            "assessment": {"verdict": "holds", "notes": []},
        }
        assert captured[0]["response_format"] == {"type": "json_object"}
        assert len(captured) == 1

    async def test_exact_route_rejects_invalid_enum_then_retries(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        captured = _capture_acompletion(
            monkeypatch,
            [
                _completion(
                    _message(
                        '{"summary": "ok", "assessment": '
                        '{"verdict": "invalid", "notes": []}}'
                    )
                ),
                _completion(
                    _message(
                        '{"summary": "ok", "assessment": '
                        '{"verdict": "holds", "notes": []}}'
                    )
                ),
            ],
        )

        result = await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_MODEL,
                api_key="test-byok-key",
                json_schema=_NESTED_SCHEMA,
            ),
            max_attempts=2,
        )

        assert result == {
            "summary": "ok",
            "assessment": {"verdict": "holds", "notes": []},
        }
        assert len(captured) == 2
        assert all(
            request["response_format"] == {"type": "json_object"}
            for request in captured
        )

    async def test_exact_free_route_keeps_caps_and_require_parameters(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_registry(monkeypatch, supported=True)
        catalog = _catalog({"prompt": "0", "completion": "0"})
        catalog["data"][0]["id"] = _MODEL.removeprefix("openrouter/")
        _mock_catalog(monkeypatch, catalog)
        requests: list[dict[str, Any]] = []
        _patch_acompletion(
            monkeypatch,
            [_completion(_message('{"answer": "ok"}'))],
            requests,
        )

        await call_llm_json(
            "probe",
            CompletionSpec(
                model_name=_MODEL,
                json_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
            ),
            options=LLMCallOptions(use_cache=False),
            max_attempts=1,
        )

        assert requests[0]["response_format"] == {"type": "json_object"}
        provider = requests[0]["extra_body"]["provider"]
        assert provider["max_price"] == {
            "prompt": 0,
            "completion": 0,
            "request": 0,
        }
        assert provider["require_parameters"] is True
        assert requests[0]["api_base"] == "https://openrouter.ai/api/v1"

from __future__ import annotations

import json
from typing import Any

import pytest

from co_scientist.constants import MODEL_PRICING
from co_scientist.llm import (
    CompletionSpec,
    call_llm,
    deepseek_thinking_extra_body,
)
from co_scientist.llm.profile import gateway_routes, model_profile
from co_scientist.llm.request.thinking import (
    _GATEWAY_MAX_FALLBACKS,
    _gateway_provider,
)
from tests._llm_fake import NESTED_SCHEMA, disable_llm_cache, scripted_backend
from tests._llm_fake import make_completion as _completion
from tests._llm_fake import make_message as _message

_PRIMARY = "openrouter/z-ai/glm-5.3-flash"


def _price(model: str) -> tuple[float, float]:
    price = MODEL_PRICING[model]
    return price.prompt_usd_per_million, price.completion_usd_per_million


def test_no_fallback_costs_more_than_the_model_above_it() -> None:
    """Routine fallback from a free primary must not admit paid models."""
    for primary in gateway_routes():
        above = _price(primary)
        for name in model_profile(primary).fallbacks:
            below = _price(f"openrouter/{name}")
            assert below <= above, f"{name} falls back from {primary}"
            above = below


def test_no_declared_chain_exceeds_openrouters_fallback_cap() -> None:
    """OpenRouter accepts at most three models in a fallback chain."""
    for primary in gateway_routes():
        body = deepseek_thinking_extra_body(primary)
        fallbacks = model_profile(primary).fallbacks
        assert len(fallbacks) <= _GATEWAY_MAX_FALLBACKS, primary
        assert len(body.get("models", [])) <= _GATEWAY_MAX_FALLBACKS, primary


def test_no_chain_head_claims_disable_support_a_fallback_lacks() -> None:
    """Every fallback sees the same request and must honor its reasoning
    policy."""
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


def test_every_catalogued_route_arms_the_routing_ceiling() -> None:
    for primary in gateway_routes():
        provider = _gateway_provider(primary)
        assert "max_price" in provider, primary
        if _price(primary) == (0, 0):
            assert provider["max_price"] == {
                "prompt": 0,
                "completion": 0,
                "request": 0,
            }


@pytest.mark.parametrize(
    ("order", "expected"),
    [("friendly, together", ["friendly", "together"]), ("", None)],
    ids=["override", "empty-opts-out"],
)
def test_the_upstream_order_is_read_live_and_empty_opts_out(
    monkeypatch: pytest.MonkeyPatch, order: str, expected: list[str] | None
) -> None:
    monkeypatch.setenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", order)

    provider = deepseek_thinking_extra_body(_PRIMARY)["provider"]

    assert provider.get("order") == expected
    assert provider["require_parameters"] is True, "admission caps still apply"
    assert "max_price" in provider


@pytest.mark.parametrize(
    ("model", "native"),
    [
        ("openrouter/google/gemma-4-26b-a4b-it:free", False),
        ("google/gemma-4-26b-a4b-it", True),
    ],
    ids=["exact-free-route", "unqualified-route"],
)
async def test_the_gemma_route_alone_takes_its_schema_in_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
    clear_capability_cache: None,
    model: str,
    native: bool,
) -> None:
    disable_llm_cache(monkeypatch)
    monkeypatch.setattr(
        "co_scientist.llm.litellm.supports_response_schema", lambda m: True
    )
    sent: list[dict[str, Any]] = scripted_backend(
        monkeypatch, [_completion(_message("{}"))]
    ).requests

    await call_llm(
        "a prompt",
        CompletionSpec(
            model_name=model, api_key="test-byok-key", json_schema=NESTED_SCHEMA
        ),
    )

    if native:
        assert sent[0]["response_format"]["type"] == "json_schema"
        assert sent[0]["messages"] == [{"role": "user", "content": "a prompt"}]
    else:
        assert sent[0]["response_format"] == {"type": "json_object"}
        schema_text = json.dumps(NESTED_SCHEMA["schema"], indent=2)
        assert schema_text in sent[0]["messages"][0]["content"]

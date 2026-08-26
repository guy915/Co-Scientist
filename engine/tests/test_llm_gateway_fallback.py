"""Tests for the gateway model chain and per-model routing capabilities.

The deployment reaches one gateway (OpenRouter) and names a primary model
plus the chain to try when it is unavailable. Three properties are pinned
here because each one failed silently when it was wrong: a model that does
not reason must not be told to, a model whose host cannot serve
``json_schema`` must be downgraded before the request goes out, and the
fallback chain must actually ride on the request rather than existing only
in a constant.
"""

from co_scientist.llm_request import (
    CompletionShape,
    _build_completion_args,
    _supports_json_schema_response_format,
    deepseek_thinking_extra_body,
)

_OX = "openrouter/stealth/ox-alpha"
_GLM = "openrouter/z-ai/glm-5.2:free"
_MUSE = "openrouter/meta/muse-spark-1.2"


def test_the_primary_model_carries_its_fallback_chain() -> None:
    """A call names the models to try after the primary, in order.

    The gateway accepts a ``models`` array and moves down it when the
    primary is unavailable, which is the only place this can be handled
    without a retry: a 429 from a free pool is not a transport error the
    engine's own retry ladder can fix by asking the same host again.
    """
    body = deepseek_thinking_extra_body(_OX)

    assert body["models"] == ["z-ai/glm-5.2:free", "meta/muse-spark-1.2"]


def test_the_fallback_models_do_not_themselves_carry_a_chain() -> None:
    """Only the primary names the chain; a member of it must not recurse.

    A fallback that re-listed the chain would let the gateway walk back up
    to a model the caller had already moved past, and the paid last resort
    is the one it would reach.
    """
    assert "models" not in deepseek_thinking_extra_body(_GLM)
    assert "models" not in deepseek_thinking_extra_body(_MUSE)


def test_ox_alpha_is_not_asked_to_reason() -> None:
    """The primary spends no reasoning tokens, so it is not told to.

    Measured over four live calls: ``reasoning_tokens`` came back 0 with
    the reasoning parameter set. Asking anyway costs nothing in tokens but
    lifts ``max_tokens`` to the thinking floor, which misreports the call's
    budget everywhere the floor is read back as evidence a call reasoned.
    """
    body = deepseek_thinking_extra_body(_OX)

    assert "reasoning" not in body


def test_a_reasoning_model_in_the_chain_still_gets_the_knob() -> None:
    """Not reasoning is a property of the model, never of the route."""
    body = deepseek_thinking_extra_body(_GLM)

    assert body["reasoning"] == {"enabled": True, "effort": "high"}


def test_every_gateway_call_is_pinned_to_hosts_that_honour_it() -> None:
    """The routing constraint is the route's, so it applies to all of them.

    ``require_parameters`` is what makes every other parameter binding
    rather than advisory, and a gateway spreads one model over hosts that
    differ by an order of magnitude in speed.
    """
    for model in (_OX, _GLM, _MUSE):
        provider = deepseek_thinking_extra_body(model)["provider"]
        assert provider["require_parameters"] is True
        assert provider["sort"] == "throughput"


def test_ox_alpha_is_downgraded_to_json_object() -> None:
    """No host serving the primary accepts ``json_schema``.

    Sending it is not a soft degradation: the gateway pairs it with
    ``require_parameters`` and finds no eligible host at all, so the call
    fails outright with a 404 rather than answering unconstrained. Measured
    live -- ``json_schema`` plus the routing constraint returns "No
    endpoints found that can handle the requested parameters", while
    ``json_object`` with the same constraint answers.
    """
    assert _supports_json_schema_response_format(_OX) is False


def test_the_primary_does_not_get_the_thinking_token_floor() -> None:
    """A call that will not reason keeps the budget its call site chose."""
    args = _build_completion_args("prompt", _OX, 4000, 0.5, CompletionShape())

    assert args["max_tokens"] == 4000

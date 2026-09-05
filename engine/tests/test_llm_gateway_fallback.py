"""Tests for the gateway model chain and per-model routing capabilities.

The deployment reaches one gateway (OpenRouter) and names a primary model
plus the chain to try when it is unavailable. Three properties are pinned
here because each one failed silently when it was wrong: a model that does
not reason must not be told to, a model whose host cannot serve
``json_schema`` must be downgraded before the request goes out, and the
fallback chain must actually ride on the request rather than existing only
in a constant.
"""

import pytest

from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
from co_scientist.llm_request import (
    CompletionShape,
    _build_completion_args,
    _supports_json_schema_response_format,
    deepseek_thinking_extra_body,
    model_reasons,
)

_PRIMARY = "openrouter/z-ai/glm-5.3-flash"
_FREE_PRIMARY = "openrouter/z-ai/glm-5.2:free"
_GLM = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
_NEMO = "openrouter/minimax/minimax-m3:free"


def test_the_primary_model_carries_its_fallback_chain() -> None:
    """A call names the models to try after the primary, in order.

    The gateway accepts a ``models`` array and moves down it when the
    primary is unavailable, which is the only place this can be handled
    without a retry: a 429 from a free pool is not a transport error the
    engine's own retry ladder can fix by asking the same host again.
    """
    body = deepseek_thinking_extra_body(_PRIMARY)

    assert body["models"] == [
        "minimax/minimax-m3:free",
        "nvidia/nemotron-3.5-lightning:free",
    ]


def test_the_non_default_free_chain_head_still_carries_its_chain() -> None:
    """``glm-5.2:free`` is no longer ``app.config``'s default but stays wired.

    Its single host answered 1 of 11 live probes on 2026-09-05 -- the
    saturated-pool shape noted 2026-08-26, and the reason the 2026-09-06
    switch moved the default straight to this chain's own first rung,
    ``minimax/minimax-m3:free``, with nothing behind it. This entry is kept
    for a deployment that opts back into the chain.
    """
    body = deepseek_thinking_extra_body(_FREE_PRIMARY)

    assert body["models"] == [
        "minimax/minimax-m3:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3.5-lightning:free",
    ]


def test_the_deployed_default_carries_no_fallback_chain() -> None:
    """``minimax-m3:free`` is the sole primary: no chain behind it.

    The 2026-09-06 owner decision was a single free model, not another
    chain to fall through -- a real express run had already shown this
    model, not ``glm-5.2:free`` above it, serving nearly all the traffic.
    """
    assert "models" not in deepseek_thinking_extra_body(_NEMO)


def test_the_fallback_models_do_not_themselves_carry_a_chain() -> None:
    """Only a primary names a chain; a member of one must not recurse.

    A fallback that re-listed a chain would let the gateway walk back up
    to a model the caller had already moved past, and the paid last resort
    is the one it would reach.
    """
    assert "models" not in deepseek_thinking_extra_body(_GLM)
    assert "models" not in deepseek_thinking_extra_body(_NEMO)


def test_a_reasoning_model_in_the_chain_still_gets_the_knob() -> None:
    """Not reasoning is a property of the model, never of the route."""
    body = deepseek_thinking_extra_body(_GLM)

    assert body["reasoning"] == {"enabled": True, "effort": "high"}


def test_every_gateway_call_is_pinned_to_hosts_that_honour_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The routing constraint is the route's, so it applies to all of them.

    ``require_parameters`` is what makes every other parameter binding
    rather than advisory. Hosts differ by an order of magnitude in speed,
    so ``preferred_min_throughput`` -- the floor that replaced
    ``sort: throughput`` -- is route-wide too, not just the primary's.
    """
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    for model in (_PRIMARY, _GLM, _NEMO):
        provider = deepseek_thinking_extra_body(model)["provider"]
        assert provider["require_parameters"] is True
        assert provider["allow_fallbacks"] is True
        assert provider["preferred_min_throughput"] == 25


def test_every_gateway_call_prefers_the_default_upstream_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache locality needs a preference, not a per-call throughput pick.

    Sorting by throughput -- the previous mechanism -- round robins across
    whichever upstream is fastest at that instant, which is exactly what
    made a prompt prefix cached on one upstream worthless on the next
    call. ``order`` is a preference list, not a hard pin: OpenRouter tries
    it in sequence and only falls through to its own default selection
    when every listed upstream is unavailable.

    The order itself changed 2026-09-05: the throughput-derived
    Modal/Friendli/Together chain all price at 2x `z-ai/glm-5.3-flash`'s
    listed rate, which a production run paid for directly ($4.70 against
    $2.50 at the headline rate). The replacement -- Z.AI (first-party),
    DeepInfra, Novita, GMICloud -- all bill the listed rate; their
    throughput is unmeasured, which is exactly what
    ``preferred_min_throughput`` and the env override below exist to
    cover without needing a re-pin.
    """
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    from co_scientist.llm_thinking import _DEFAULT_UPSTREAM_ORDER

    for model in (_PRIMARY, _GLM, _NEMO):
        provider = deepseek_thinking_extra_body(model)["provider"]
        assert provider["order"] == list(_DEFAULT_UPSTREAM_ORDER)
        assert "sort" not in provider


def test_the_upstream_order_is_overridable_without_a_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator can retune cache locality live, per the task's design.

    Read per call rather than cached at import, mirroring
    ``parse_timeout_env``'s own rationale: a regression discovered in
    production should not need a restart to fix.
    """
    monkeypatch.setenv(
        "COSCIENTIST_GATEWAY_PROVIDER_ORDER", "friendli, together"
    )
    provider = deepseek_thinking_extra_body(_PRIMARY)["provider"]
    assert provider["order"] == ["friendli", "together"]


def test_an_empty_upstream_order_env_var_opts_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit empty value disables ordering, distinct from unset.

    ``max_price`` and ``require_parameters`` must survive the opt-out --
    only the cache-locality preference is what turns off.
    """
    monkeypatch.setenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", "")
    provider = deepseek_thinking_extra_body(_PRIMARY)["provider"]
    assert "order" not in provider
    assert provider["require_parameters"] is True
    assert "max_price" in provider


def test_a_direct_non_gateway_route_carries_no_provider_block() -> None:
    """The routing block is gateway-specific; a direct route sends none.

    Guards against ``order``/``allow_fallbacks`` leaking onto a call that
    never goes through OpenRouter, where they would be meaningless extra
    body fields sent straight to the provider's own API.
    """
    body = deepseek_thinking_extra_body("deepseek/deepseek-chat")
    assert "provider" not in body


def test_every_gateway_model_is_downgraded_to_json_object() -> None:
    """Every declared gateway model gets the safe format, not just the primary.

    ``json_object`` is served by every host in this chain; ``json_schema``
    is not, and paired with ``require_parameters`` an unsupported format
    is a hard 404 rather than a soft degradation to an unconstrained
    answer. Free models turn over faster than litellm's registry does, so
    if a future registry bump ever flips one of these to ``True``, this is
    what would catch it rather than a live 404.
    """
    from co_scientist.llm_thinking import _GATEWAY_MODELS

    for model in _GATEWAY_MODELS:
        assert _supports_json_schema_response_format(model) is False, model


def test_the_primary_still_gets_the_thinking_token_floor() -> None:
    """Reporting no reasoning tokens is not the same as spending none.

    Ox Alpha returns ``reasoning_tokens=0`` on every call, which is what
    first put ``reasons=False`` on it -- and denying it the floor was
    wrong. Measured on a live express run: 24 calls went out at their call
    sites' own 8000-token budget, came back with ``finish_reason="length"``
    and empty content, and each one climbed the escalation ladder and was
    re-sent. The budget is spent on something the API does not itemise, so
    the only observable is the empty answer.

    A ceiling is not a spend: raising it costs nothing on the calls that
    answer briefly, and removes 24 wasted round-trips from the ones that
    do not.
    """
    args = _build_completion_args(
        "prompt", _PRIMARY, 4000, 0.5, CompletionShape()
    )

    assert args["max_tokens"] == THINKING_FLOOR_MAX_TOKENS


def test_the_two_reasoning_facts_stay_separable() -> None:
    """Taking the knob and spending the budget remain distinct questions.

    This pinned a model that answered no to the first and yes to the
    second; its provider withdrew it mid-session, and the model replacing
    it answers yes to both. The distinction is what matters and is kept
    under test, because collapsing the two is what withheld the token
    floor and cost 24 answerless round-trips.
    """
    from co_scientist.llm_thinking import GatewayModel

    knob_only = GatewayModel(
        takes_reasoning_knob=False, spends_budget_thinking=True
    )

    assert knob_only.takes_reasoning_knob is False
    assert knob_only.spends_budget_thinking is True
    assert model_reasons(_PRIMARY) is True


def test_no_fallback_costs_more_than_the_model_above_it() -> None:
    """A chain may only ever descend in price.

    This is the test that would have caught the incident this chain was
    rebuilt after: a free primary with a $1.25/$4.25 "last resort" behind
    it, where 429 is the normal state of a shared free pool, so the
    expensive rung was the routine destination rather than the emergency
    one. It served 3.17M tokens and billed $5.23 in an afternoon.

    Asserted over the declared table rather than one hand-picked pair, so
    a rung added later cannot reintroduce the shape.
    """
    from co_scientist.constants_pricing import MODEL_PRICING
    from co_scientist.llm_thinking import _GATEWAY_MODELS

    def rate(gateway_relative: str) -> tuple[float, float]:
        price = MODEL_PRICING[f"openrouter/{gateway_relative}"]
        return (
            price.prompt_usd_per_million,
            price.completion_usd_per_million,
        )

    for primary, declared in _GATEWAY_MODELS.items():
        if not declared.fallbacks:
            continue
        above = (
            MODEL_PRICING[primary].prompt_usd_per_million,
            MODEL_PRICING[primary].completion_usd_per_million,
        )
        for name in declared.fallbacks:
            below = rate(name)
            assert below <= above, (
                f"{name} costs more than {primary} it falls back from"
            )
            above = below


def test_a_priced_primary_arms_the_routing_ceiling() -> None:
    """The cap exists only when the primary has a rate to be a multiple of.

    A priced primary must send ``max_price``: that is the ceiling that
    would have refused the $5.23 incident's fallback. A *free* primary
    correctly sends none -- there is no meaningful multiple of nothing --
    but that is safe only because every rung under it is also free
    (asserted by ``test_no_fallback_costs_more_than_the_model_above_it``),
    so an uncapped route still has nothing to overspend on.
    """
    from co_scientist.constants_pricing import MODEL_PRICING
    from co_scientist.llm_thinking import _GATEWAY_MODELS, _gateway_provider

    for primary, declared in _GATEWAY_MODELS.items():
        if not declared.fallbacks:
            continue
        price = MODEL_PRICING[primary]
        has_cap = "max_price" in _gateway_provider(primary)
        if price.prompt_usd_per_million:
            assert has_cap, (
                f"{primary} heads a chain but sends no price ceiling"
            )
        else:
            assert not has_cap, (
                f"{primary} is free but sends a price ceiling anyway"
            )


def test_the_price_cap_excludes_the_2x_tier() -> None:
    """The multiple must stay tight enough to shut out the 2x hosts.

    OpenRouter's endpoint list for `z-ai/glm-5.3-flash` on 2026-09-05
    splits into a headline tier (Z.AI, DeepInfra, Novita, GMICloud at
    $0.075/$0.25), a middle band strictly between 1x and 2x (Morph at
    1.29x, up to Modal at 1.9998x), and a tier at exactly 2x
    ($0.15/$0.50, Friendli and Together among them). A multiple of 2.0
    admitted the whole middle band plus the 2x tier -- Modal, at
    1.9998x, is what a production run was routed to, billed $4.70 for
    work priced at $2.50 headline. Pinned so a later "loosen it for
    throughput" change cannot silently reopen either band without
    someone reading this: the next host above the headline rate is
    Morph at 1.29x, well clear of the current cap.
    """
    from co_scientist.llm_thinking import _MAX_PRICE_MULTIPLE

    assert 1.0 <= _MAX_PRICE_MULTIPLE < 1.29


def test_the_price_cap_admits_the_headline_rate() -> None:
    """The ceiling OpenRouter actually enforces is inclusive of the cap.

    Per OpenRouter's provider-routing docs, ``max_price`` reads "<= $x/m
    ... or less" -- a host billing exactly the listed rate still
    qualifies. The cap sits a few percent above that rate rather than
    exactly on it, since the gateway's own price comparison may not
    represent the listed rate with the same rounding this process does.
    """
    from co_scientist.constants_pricing import MODEL_PRICING
    from co_scientist.llm_thinking import _MAX_PRICE_MULTIPLE, _gateway_provider

    primary = "openrouter/z-ai/glm-5.3-flash"
    price = MODEL_PRICING[primary]
    provider = _gateway_provider(primary)

    assert provider["max_price"] == {
        "prompt": price.prompt_usd_per_million * _MAX_PRICE_MULTIPLE,
        "completion": price.completion_usd_per_million * _MAX_PRICE_MULTIPLE,
    }
    assert provider["max_price"]["prompt"] >= price.prompt_usd_per_million

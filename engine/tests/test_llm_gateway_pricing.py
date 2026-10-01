"""Tests for the gateway chain's price ceiling and per-rung cost ordering.

Split from ``test_llm_gateway_fallback.py`` on the same grounds as
``test_llm_reasoning_mandatory.py``: these pin the price cap that stops a
free primary's fallback chain from ever routing to a rung more expensive
than the primary above it (including an explicit zero ceiling for free
primaries) -- distinct concerns from that
file's routing-shape and reasoning-knob tests.
"""

from co_scientist.llm import deepseek_thinking_extra_body


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
    """Every declared chain stays at or under OpenRouter's own 3-item cap.

    Production run b82f9162 (2026-09-06 00:19 UTC) sent a six-rung
    ``minimax-m3:free`` chain as the ``models`` array and every gateway
    call 400'd: ``"'models' array must have 3 items or fewer."`` Checked
    over the declared table, not one hand-picked chain, so a rung added
    later cannot reintroduce the shape.
    """
    from co_scientist.llm.profile import gateway_routes, model_profile
    from co_scientist.llm.request.gateway_routing import _GATEWAY_MAX_FALLBACKS

    for primary in gateway_routes():
        fallbacks = model_profile(primary).fallbacks
        assert len(fallbacks) <= _GATEWAY_MAX_FALLBACKS, primary


def test_no_chain_head_claims_disable_support_a_fallback_lacks() -> None:
    """A disabled-reasoning request can land on any rung ``models`` lists.

    ``reasoning`` is built once, from the primary's own declaration, but
    OpenRouter's ``models`` fallback array lets the gateway serve the
    request from *any* host on the list -- the incident this guards
    against (minimax-m3:free's "Reasoning is mandatory... cannot be
    disabled") never fell through to a fallback host either; both of its
    attempts died on the primary's own message. So a chain head that
    claims ``reasoning_can_disable=True`` while a rung behind it does not
    would silently 400 the instant the gateway picked that rung. Checked
    over the whole declared table, not one hand-picked chain, so a rung
    added later cannot reintroduce the shape.
    """
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
    """The same cap holds on the actual request body, not just the table.

    ``test_no_declared_chain_exceeds_openrouters_fallback_cap`` pins the
    source data; this pins what a call actually sends, so a future bug in
    ``_gateway_body`` that appended to a chain would be caught
    here even if the table itself stayed correct.
    """
    from co_scientist.llm.profile import gateway_routes
    from co_scientist.llm.request.gateway_routing import _GATEWAY_MAX_FALLBACKS

    for model in gateway_routes():
        body = deepseek_thinking_extra_body(model)
        assert len(body.get("models", [])) <= _GATEWAY_MAX_FALLBACKS, model


def test_every_catalogued_route_arms_the_routing_ceiling() -> None:
    """A zero-priced primary must keep the provider ceiling armed too."""
    from co_scientist.constants_pricing import MODEL_PRICING
    from co_scientist.llm.profile import gateway_routes
    from co_scientist.llm.request.gateway_routing import _gateway_provider

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
    from co_scientist.llm.request.gateway_routing import _MAX_PRICE_MULTIPLE

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
    from co_scientist.llm.request.gateway_routing import (
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

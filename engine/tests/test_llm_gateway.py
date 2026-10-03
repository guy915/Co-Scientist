"""Offline contracts for llm gateway."""

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


def test_the_legacy_minimax_default_carries_the_all_free_chain() -> None:
    """The former Minimax default retains its chain for explicit selection.

    The chain was measured 2026-09-06, when Minimax was the system default.
    Each ``:free`` variant caps at roughly 100 requests/day per model, not
    "one saturated shared pool" -- the shape the 2026-09-06 single-model
    switch had assumed. A chain lets a run keep going once the primary's
    own daily cap is spent, in the order the live probe measured -- capped
    at three rungs (``_GATEWAY_MAX_FALLBACKS``): a six-rung version of this
    chain 400'd every gateway call in production (run b82f9162, 2026-09-06
    00:19 UTC), since OpenRouter caps the ``models`` array at 3 items.
    """
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
    """Only a primary names a chain; a member of one must not recurse.

    A fallback that re-listed a chain would let the gateway walk back up
    to a model the caller had already moved past. ``glm-5.2:free`` is the
    one deliberate exception -- it heads its own non-default chain -- so
    it is checked separately, not against this invariant.
    """
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
    """The selected default stays on Nex Pro when its route is unavailable."""
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
    """A provisional route must not drift to a provider with unknown terms."""
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
    """Its sole endpoint advertises structured outputs, not JSON object mode."""
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
    """Not reasoning is a property of the model, never of the route."""
    body = deepseek_thinking_extra_body(_GLM)

    assert body["reasoning"] == {"enabled": True, "effort": "high"}


def test_a_disable_request_gets_capped_reasoning_when_mandatory() -> None:
    """``enabled=False`` never reaches a model that rejects disabling.

    Production run b82f9162 (2026-09-06 04:39:30 UTC): every batched
    entailment call against ``minimax/minimax-m3:free`` failed on both
    attempts with "Reasoning is mandatory for this endpoint and cannot be
    disabled", because ``enable_thinking=False`` reached the wire as a
    literal ``reasoning: {"enabled": False}``. The model's own declaration
    (``reasoning_can_disable=False``) redirects that to reasoning the
    gateway is asked to *bound*, rather than a tier name: run 6760ce63
    then measured 24547 reasoning tokens against a 24000-token budget on
    the minimal tier, i.e. the tier alone bounds nothing.
    """
    body = deepseek_thinking_extra_body(_MINIMAX, enabled=False)

    assert body["reasoning"] == {
        "enabled": True,
        "max_tokens": MINIMAL_REASONING_MAX_TOKENS,
    }


def test_the_reasoning_cap_leaves_room_for_the_answer() -> None:
    """The cap must fit inside the smallest entailment caller's budget.

    ``app.claims.verifier`` sizes its per-claim call at 6000, and the cap
    is spent before a single answer token is written, so a cap anywhere
    near that budget reproduces the answerless completion it exists to
    prevent -- on a provider that does not apply the thinking floor at
    all.
    """
    smallest_entailment_budget = 6000

    assert MINIMAL_REASONING_MAX_TOKENS >= 1024
    assert smallest_entailment_budget // 2 > MINIMAL_REASONING_MAX_TOKENS


def test_the_minimal_reasoning_redirect_keeps_the_ordinary_floor() -> None:
    """Bounding the reasoning replaces funding it at a premium.

    The premium floor (24000) was tried first and failed on its own
    terms: run 6760ce63 measured 24547 reasoning tokens against it, so
    each raise simply bought a longer chain of thought. Worse, at that
    floor a 12000-token caller sent an identical 24000-token request on
    all three ladder rungs, since ``escalated_max_tokens`` also floors at
    24000 -- the "retry that resends the identical request" bug the
    ladder exists to avoid. With the reasoning itself capped, the
    ordinary floor is enough room and the rungs differ again.
    """
    from co_scientist.llm.request.thinking import effective_max_tokens

    assert (
        effective_max_tokens(_MINIMAX, 12000, enable_thinking=False)
        == THINKING_FLOOR_MAX_TOKENS
    )


def test_a_call_that_actually_asked_for_thinking_keeps_the_ordinary_floor() -> (
    None
):
    """A caller that asked for thinking gets the floor proven for it.

    The forced-reasoning redirect changes what the ``reasoning`` object
    carries, never the budget an ordinary thinking call is funded at.
    """
    from co_scientist.llm.request.thinking import effective_max_tokens

    assert (
        effective_max_tokens(_MINIMAX, 12000, enable_thinking=True)
        == THINKING_FLOOR_MAX_TOKENS
    )


def test_a_non_reasoning_call_is_untouched_by_the_floor() -> None:
    """A model with no thinking mode gets no floor.

    ``max_tokens`` passes through exactly as the call site sized it.
    """
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
    """The routing constraint is the route's, so it applies to all of them.

    ``require_parameters`` is what makes every other parameter binding
    rather than advisory. Hosts differ by an order of magnitude in speed,
    so ``preferred_min_throughput`` -- the floor that replaced
    ``sort: throughput`` -- is route-wide too, not just the primary's.
    """
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    for model in (_PRIMARY, _GLM, _MINIMAX):
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
    from co_scientist.llm.request.thinking import _DEFAULT_UPSTREAM_ORDER

    for model in (_PRIMARY, _GLM, _MINIMAX):
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


def test_gateway_models_without_native_schema_use_json_object() -> None:
    """Declared routes use the format supported by their pinned endpoints.

    ``json_object`` is served by every host in this chain; ``json_schema``
    is not, and paired with ``require_parameters`` an unsupported format
    is a hard 404 rather than a soft degradation to an unconstrained
    answer.

    Qwen's pinned endpoint supports native structured outputs, so it is
    checked separately above. This asserts the other routes' downgrade
    decision, not litellm's
    registry: every declared gateway route now states ``json_schema`` in its
    profile rather than falling through to
    ``litellm.supports_response_schema``. That fallback made the test
    non-hermetic in practice -- the registry's answer for
    ``openrouter/z-ai/glm-5.2:free`` flipped from False to True between
    two runs on the same day with no code change, because free/stealth
    listings on these gateways are volatile in a way litellm's static
    capability table cannot track. A declared override was chosen over
    patching the registry lookup in the test: the whole point of the
    downgrade is that gateway chains cannot trust the registry's answer
    for these models in production either (``require_parameters`` makes a
    wrong "yes" a hard 404, not a soft degradation), so the fix belongs in
    the engine's own logic, and this test now pins that logic rather than
    a mocked stand-in for it.
    """
    from co_scientist.llm.profile import gateway_routes

    for model in gateway_routes():
        if model == _QWEN_CANDIDATE:
            continue
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
    from co_scientist.llm.profile import ModelProfile, Thinking

    knob_only = ModelProfile(thinking=Thinking.NONE, reasons=True)

    assert knob_only.thinking is Thinking.NONE
    assert knob_only.reasons is True
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
    """Every declared chain stays at or under OpenRouter's own 3-item cap.

    Production run b82f9162 (2026-09-06 00:19 UTC) sent a six-rung
    ``minimax-m3:free`` chain as the ``models`` array and every gateway
    call 400'd: ``"'models' array must have 3 items or fewer."`` Checked
    over the declared table, not one hand-picked chain, so a rung added
    later cannot reintroduce the shape.
    """
    from co_scientist.llm.profile import gateway_routes, model_profile
    from co_scientist.llm.request.thinking import _GATEWAY_MAX_FALLBACKS

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
    from co_scientist.llm.request.thinking import _GATEWAY_MAX_FALLBACKS

    for model in gateway_routes():
        body = deepseek_thinking_extra_body(model)
        assert len(body.get("models", [])) <= _GATEWAY_MAX_FALLBACKS, model


def test_every_catalogued_route_arms_the_routing_ceiling() -> None:
    """A zero-priced primary must keep the provider ceiling armed too."""
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
    from co_scientist.llm.request.thinking import _MAX_PRICE_MULTIPLE

    assert 1.0 <= _MAX_PRICE_MULTIPLE < 1.29


def test_the_price_cap_admits_the_headline_rate() -> None:
    """The ceiling OpenRouter actually enforces is inclusive of the cap.

    Per OpenRouter's provider-routing docs, ``max_price`` reads "<= $x/m
    ... or less" -- a host billing exactly the listed rate still
    qualifies. The cap sits a few percent above that rate rather than
    exactly on it, since the gateway's own price comparison may not
    represent the listed rate with the same rounding this process does.
    """
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
    """Reset the memoized capability decision around each test."""
    _supports_json_schema_response_format.cache_clear()
    yield
    _supports_json_schema_response_format.cache_clear()


def _patch_registry(monkeypatch: pytest.MonkeyPatch, supported: bool) -> None:
    """Make the registry answer deterministic for this route test."""

    def fake_supports(model: str) -> bool:
        del model
        return supported

    monkeypatch.setattr(
        "co_scientist.llm.litellm.supports_response_schema", fake_supports
    )


def _capture_acompletion(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> list[dict[str, Any]]:
    """Capture completion kwargs while returning queued fake responses."""
    captured: list[dict[str, Any]] = []
    _patch_acompletion(monkeypatch, responses, captured)
    return captured


@pytest.mark.usefixtures("_clear_capability_cache", "_isolated_catalog")
class TestLlmGemmaRoute:
    async def test_exact_route_injects_schema_at_request_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The exact route reuses the existing json_object request shim."""
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
        """The route exception does not broaden to unqualified Gemma models."""
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
        """The shimmed route still backfills and validates locally."""
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
        """Local validation rejects an invalid enum before accepting a retry."""
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
        """The Gemma route keeps the normal zero-price admission policy."""
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

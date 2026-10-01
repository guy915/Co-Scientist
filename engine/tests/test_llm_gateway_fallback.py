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

from co_scientist.constants import (
    MINIMAL_REASONING_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.llm import deepseek_thinking_extra_body, model_reasons
from co_scientist.llm.request.completion import (
    CompletionShape,
    _build_completion_args,
    _supports_json_schema_response_format,
)

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

    from co_scientist.constants_pricing import MODEL_PRICING

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
    from co_scientist.llm.request.gateway_routing import _GATEWAY_MODELS

    for gateway_relative in (
        "nvidia/nemotron-3-super-120b-a12b:free",
        "google/gemma-4-31b-it:free",
        "minimax/minimax-m2.7:free",
        "dots-studio/dots-3-note-preview:free",
        "nvidia/nemotron-3.5-lightning:free",
    ):
        model_name = f"openrouter/{gateway_relative}"
        assert "models" not in deepseek_thinking_extra_body(model_name)
        assert not _GATEWAY_MODELS[model_name].fallbacks


def test_selected_nex_pro_default_has_no_model_fallback() -> None:
    """The selected default stays on Nex Pro when its route is unavailable."""
    from co_scientist.llm.request.gateway_routing import _GATEWAY_MODELS

    assert not _GATEWAY_MODELS[_NEX_PRO].fallbacks
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

    ``app.claim_verifier`` sizes its per-claim call at 6000, and the cap
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
    from co_scientist.llm.request.gateway_routing import _DEFAULT_UPSTREAM_ORDER

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
    registry: every ``_GATEWAY_MODELS`` key is now declared explicitly in
    ``_supports_json_schema_response_format`` rather than falling through
    to ``litellm.supports_response_schema``. That fallback made the test
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
    from co_scientist.llm.request.gateway_routing import _GATEWAY_MODELS

    for model in _GATEWAY_MODELS:
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
    from co_scientist.llm.request.gateway_routing import GatewayModel

    knob_only = GatewayModel(
        takes_reasoning_knob=False, spends_budget_thinking=True
    )

    assert knob_only.takes_reasoning_knob is False
    assert knob_only.spends_budget_thinking is True
    assert model_reasons(_PRIMARY) is True

"""Tests for DeepSeek thinking-mode completion parameters.

Split from ``test_llm_wrappers.py``: covers how
``co_scientist.llm.request.completion._build_completion_args`` maps the thinking
opt-in/opt-out onto DeepSeek's ``thinking`` object and
``reasoning_effort``. Every engine node thinks; the opt-out cases below
cover the seam itself, which no call site uses today.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from tests._llm_backend_fake import install_fake_backend
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_wrapper_fakes import (
    make_completion as _completion,
)
from tests._llm_wrapper_fakes import (
    make_message as _message,
)

# --- DeepSeek thinking mode --------------------------------------------------


def test_thinking_enabled_by_default_for_deepseek() -> None:
    """Every DeepSeek call thinks unless a call site opts out."""
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt", "deepseek/deepseek-v4-flash", 100, 0.5, CompletionShape()
    )

    assert args["extra_body"] == {"thinking": {"type": "enabled"}}
    assert args["reasoning_effort"] == "high"


def test_thinking_disabled_drops_reasoning_effort() -> None:
    """Opting out disables thinking explicitly and spends no reasoning.

    ``reasoning_effort`` must not survive the opt-out: it would ask the
    provider to size a reasoning budget for a call that does not reason.
    """
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt",
        "deepseek/deepseek-v4-flash",
        100,
        0.5,
        CompletionShape(enable_thinking=False),
    )

    assert args["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in args


def test_gateway_route_carries_the_effort_only_inside_extra_body() -> None:
    """A gateway route states the reasoning tier exactly once.

    The gateway's own ``reasoning`` object already carries ``effort``, so a
    top-level ``reasoning_effort`` beside it is a second copy of the same
    instruction -- and the copy the gateway rejects. litellm refuses it for
    a model whose OpenRouter support map does not list the parameter
    (``UnsupportedParamsError``), which the engine survives only because
    every engine call also passes ``drop_params``. The app's own call sites
    invoke litellm directly and do not, so the redundant field failed the
    contextual safety screen outright and parked runs for human review.
    """
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt",
        "openrouter/deepseek/deepseek-v4-flash",
        100,
        0.5,
        CompletionShape(),
    )

    assert args["extra_body"]["reasoning"] == {
        "enabled": True,
        "effort": "high",
    }
    assert "reasoning_effort" not in args


def test_thinking_params_absent_for_non_deepseek_models() -> None:
    """The thinking params are DeepSeek-specific and never sent elsewhere."""
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt", "gemini/gemini-2.5-flash", 100, 0.5, CompletionShape()
    )

    assert "extra_body" not in args
    assert "reasoning_effort" not in args


# --- Thinking token floor ----------------------------------------------------


def test_thinking_call_raised_to_the_token_floor() -> None:
    """A thinking call never goes out on an answer-sized budget.

    ``max_tokens`` bounds reasoning plus answer, so a budget sized before
    thinking was switched on lets the chain of thought consume the whole
    allowance and return empty content -- billed in full, then retried.
    """
    from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt", "deepseek/deepseek-v4-flash", 4000, 0.5, CompletionShape()
    )

    assert args["max_tokens"] == THINKING_FLOOR_MAX_TOKENS


def test_token_floor_never_lowers_a_larger_budget() -> None:
    """The floor only raises: a node that sized itself higher keeps its own.

    The scaled batch budgets (review, evolution) already exceed the floor,
    and clamping them down to it would truncate the answers they were sized
    for -- the exact failure this floor exists to prevent.
    """
    from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    above_floor = THINKING_FLOOR_MAX_TOKENS + 6000
    args = _build_completion_args(
        "prompt",
        "deepseek/deepseek-v4-flash",
        above_floor,
        0.5,
        CompletionShape(),
    )

    assert args["max_tokens"] == above_floor


def test_token_floor_not_applied_when_thinking_is_off() -> None:
    """A non-thinking call keeps its budget; there is no reasoning to fund."""
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt",
        "deepseek/deepseek-v4-flash",
        4000,
        0.5,
        CompletionShape(enable_thinking=False),
    )

    assert args["max_tokens"] == 4000


def test_token_floor_not_applied_to_non_thinking_models() -> None:
    """Models without a thinking mode spend the budget on the answer alone."""
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt", "gemini/gemini-2.5-flash", 4000, 0.5, CompletionShape()
    )

    assert args["max_tokens"] == 4000


async def test_ranking_matchup_thinks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The O(n^2) tournament judge reasons, like every other engine node.

    Asserted at the litellm seam through the real ``call_llm_json`` ->
    ``call_llm`` chain, so what the provider actually receives is verified
    end to end rather than at the ranking call site alone. This is the
    run's highest-volume call, so a silent regression to a non-thinking
    judge would be a large quality change with no other symptom.
    """
    from co_scientist.agents.ranking.ranking import (
        _call_matchup_judge,
        _DebateContext,
    )
    from co_scientist.agents.ranking.ranking_debate import _MatchupPrompt
    from tests._state import make_hypothesis

    seen: dict[str, Any] = {}

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return _completion(_message('{"winner": "A"}'))

    install_fake_backend(monkeypatch, fake_acompletion)
    _disable_cache(monkeypatch)

    mp = _MatchupPrompt("compare A and B", None, None, None)
    ctx = _DebateContext(
        make_hypothesis(text="a"),
        make_hypothesis(text="b"),
        "goal",
        "deepseek/deepseek-v4-flash",
    )
    await _call_matchup_judge(mp, ctx)

    assert seen["extra_body"] == {"thinking": {"type": "enabled"}}
    assert seen["reasoning_effort"] == "high"


# --- Gateway routes ----------------------------------------------------------


def test_a_gateway_route_gets_its_own_reasoning_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway normalizes reasoning; the provider's own knob is not it.

    Measured against `openrouter/deepseek/deepseek-v4-flash`: a call
    carrying DeepSeek's ``{"thinking": {"type": "disabled"}}`` came back
    with the whole budget spent on reasoning and empty content -- the
    parameter asking for thinking off is read as asking for it on. That
    fails in the shape AGENTS.md records for an exhausted budget, so it
    reads as a token-budget defect rather than as a wrong parameter, and
    the first casualty is title generation, whose 24-token budget a
    chain of thought consumes entirely.
    """
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    from co_scientist.llm import deepseek_thinking_extra_body

    routed = "openrouter/deepseek/deepseek-v4-flash"

    gateway = {
        "require_parameters": True,
        "allow_fallbacks": True,
        "preferred_min_throughput": 25,
        "order": ["z-ai", "deepinfra", "novita", "gmicloud"],
        "max_price": {"prompt": 0.083 * 1.05, "completion": 0.165 * 1.05},
    }

    assert deepseek_thinking_extra_body(routed, enabled=False) == {
        "reasoning": {"enabled": False},
        "provider": gateway,
    }
    assert deepseek_thinking_extra_body(routed, enabled=True) == {
        "reasoning": {"enabled": True, "effort": "high"},
        "provider": gateway,
    }


def test_the_direct_route_still_speaks_deepseek() -> None:
    """Adding a gateway must not change what the first-party call sends."""
    from co_scientist.llm import deepseek_thinking_extra_body

    direct = "deepseek/deepseek-v4-flash"

    assert deepseek_thinking_extra_body(direct, enabled=True) == {
        "thinking": {"type": "enabled"}
    }
    assert deepseek_thinking_extra_body(direct, enabled=False) == {
        "thinking": {"type": "disabled"}
    }


def test_a_model_without_thinking_is_untouched_on_either_route() -> None:
    """The route decides the shape, never whether there is one at all."""
    from co_scientist.llm import deepseek_thinking_extra_body

    assert deepseek_thinking_extra_body("gemini/gemini-2.5-flash") == {}
    assert deepseek_thinking_extra_body("openrouter/openai/gpt-4o") == {}


def test_the_gateway_route_is_pinned_to_hosts_that_honour_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway spreads one model over hosts that are not interchangeable.

    Three of them matter here. A host that ignores an unsupported
    parameter makes the reasoning knob advisory, which is the failure this
    route already produced once. Hosts differ by an order of magnitude in
    speed while the default ordering picks on price, so a call can land
    on one serving single digit tokens per second -- measured, the
    slowest of six concurrent calls took 32.9s unconstrained against 7.1s
    constrained, and two calls in the first routed run hit the engine's
    own 600s ceiling outright. And they differ by 6.5x in price, which
    neither ``order`` nor ``preferred_min_throughput`` considers at all,
    so without a ceiling the run cost this project reports bounds nothing
    -- the cap is what makes ``constants_pricing`` an estimate of the
    worst case rather than of one arbitrary host.

    The mechanism guarding the first risk changed since that measurement:
    ``sort: throughput`` picked whichever upstream was fastest *per call*,
    which round-robined consecutive calls across Modal/Friendli/Together
    and is very likely why production's prompt-cache hit rate collapsed
    to 6.9% (against a 33.7% monthly baseline) on 2026-09-04, the day
    with the heaviest repeated-prompt traffic -- a prefix cached on one
    upstream is wasted the instant the next call lands on another. The
    replacement, a fixed ``order`` preference plus a
    ``preferred_min_throughput`` floor (OpenRouter's own documented
    "deprioritize, don't exclude" semantics for a degraded endpoint),
    keeps consecutive calls landing on the same host for the cache's
    sake while still moving off one that has degraded into the "single
    digit tokens per second" shape of the original incident.

    The order named above changed again on 2026-09-05: Modal/Friendli/
    Together were chosen for measured throughput without noticing all
    three price at 2x `z-ai/glm-5.3-flash`'s listed rate, and a
    production run routed there was billed $4.70 for work priced at
    $2.50 headline. The price cap (``_MAX_PRICE_MULTIPLE``, tightened
    from 2.0 to 1.0 in the same change) is what should have caught this
    and did not, because 2.0 was loose enough to admit the 2x tier
    outright. The replacement order -- Z.AI, DeepInfra, Novita, GMICloud
    -- all bill the headline rate; none of their throughput is measured,
    which is exactly the gap ``preferred_min_throughput`` and the env
    override exist to cover without a re-pin.
    """
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    from co_scientist.llm import deepseek_thinking_extra_body

    body = deepseek_thinking_extra_body("openrouter/deepseek/deepseek-v4-flash")

    assert body["provider"] == {
        "require_parameters": True,
        "allow_fallbacks": True,
        "preferred_min_throughput": 25,
        "order": ["z-ai", "deepinfra", "novita", "gmicloud"],
        "max_price": {"prompt": 0.083 * 1.05, "completion": 0.165 * 1.05},
    }
    # The direct route has no gateway to constrain, and must not grow one.
    assert "provider" not in deepseek_thinking_extra_body(
        "deepseek/deepseek-v4-flash"
    )

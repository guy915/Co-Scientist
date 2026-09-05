"""Tests for the DeepSeek thinking-mode helpers in ``app.config``.

The two helpers translate the thinking toggle into DeepSeek's request
params: a ``thinking`` object plus ``reasoning_effort``. Getting the
format wrong is silent rather than an error, so the shape is pinned here.
Every app call site thinks now, titling included; the opt-out
(``deepseek_non_thinking_extra_body``) has no live caller but stays
covered here as a tested seam -- see its docstring.
"""

from __future__ import annotations

from app.config import (
    deepseek_non_thinking_extra_body,
    deepseek_thinking_kwargs,
)


def test_thinking_kwargs_native_deepseek() -> None:
    """Native DeepSeek gets the thinking object at low reasoning effort."""
    kwargs = deepseek_thinking_kwargs("deepseek/deepseek-v4-pro")

    assert kwargs == {
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "high",
    }


def test_thinking_kwargs_empty_for_other_models() -> None:
    """Non-DeepSeek models carry no thinking params at all."""
    assert deepseek_thinking_kwargs("gemini/gemini-2.5-flash") == {}


def test_non_thinking_body_native_deepseek() -> None:
    """The opt-out disables thinking explicitly on the native API."""
    body = deepseek_non_thinking_extra_body("deepseek/deepseek-v4-flash")

    assert body == {"thinking": {"type": "disabled"}}


def test_non_thinking_body_empty_for_other_models() -> None:
    """Non-DeepSeek models carry no thinking params at all."""
    assert deepseek_non_thinking_extra_body("gpt-4o-mini") == {}


# --- thinking token floor ----------------------------------------------------


def test_thinking_floor_raises_an_answer_sized_budget() -> None:
    """A DeepSeek budget sized for the answer alone is lifted to the floor.

    The provider counts reasoning against ``max_tokens``, so an answer-sized
    budget lets a long chain of thought return empty content -- billed in
    full, and for the claim verifier indistinguishable from "the LLM
    assessor never wins".
    """
    from app.config import THINKING_FLOOR_MAX_TOKENS, thinking_safe_max_tokens

    assert (
        thinking_safe_max_tokens("deepseek/deepseek-v4-flash", 3_000)
        == THINKING_FLOOR_MAX_TOKENS
    )


def test_thinking_floor_never_lowers_a_larger_budget() -> None:
    """The floor only raises; a call site asking for more keeps its number."""
    from app.config import THINKING_FLOOR_MAX_TOKENS, thinking_safe_max_tokens

    above = THINKING_FLOOR_MAX_TOKENS + 5_000

    assert thinking_safe_max_tokens("deepseek/deepseek-v4-pro", above) == above


def test_thinking_floor_leaves_non_deepseek_budgets_alone() -> None:
    """Models without a thinking mode spend the whole budget on the answer."""
    from app.config import thinking_safe_max_tokens

    assert thinking_safe_max_tokens("gemini/gemini-2.5-flash", 3_000) == 3_000


# --- thinking timeout floor --------------------------------------------------


def test_thinking_timeout_floor_raises_an_answer_sized_deadline() -> None:
    """A deadline sized for the answer alone is lifted to the floor.

    Funding the chain of thought without extending the clock only moves the
    failure: the call is cut off mid-reasoning instead of returning empty,
    and both land in the same silent fallback.
    """
    from app.config import THINKING_FLOOR_TIMEOUT_SECONDS, thinking_safe_timeout

    assert (
        thinking_safe_timeout("deepseek/deepseek-v4-flash", 20.0)
        == THINKING_FLOOR_TIMEOUT_SECONDS
    )


def test_thinking_timeout_floor_never_lowers_a_longer_deadline() -> None:
    """The floor only raises; a call site allowing more keeps its number."""
    from app.config import THINKING_FLOOR_TIMEOUT_SECONDS, thinking_safe_timeout

    above = THINKING_FLOOR_TIMEOUT_SECONDS + 120.0

    assert thinking_safe_timeout("deepseek/deepseek-v4-pro", above) == above


def test_thinking_timeout_floor_leaves_non_deepseek_deadlines_alone() -> None:
    """Models without a thinking mode keep their own, tighter deadline."""
    from app.config import thinking_safe_timeout

    assert thinking_safe_timeout("gemini/gemini-2.5-flash", 20.0) == 20.0


def test_thinking_timeout_floor_admits_the_token_floor() -> None:
    """The clock must allow the token budget it is paired with to arrive.

    The two ceilings are one setting in two places. Pinning the relationship
    here is what stops a later tightening of the deadline from silently
    re-breaking every call the token floor was raised to fix.
    """
    from app.config import (
        THINKING_FLOOR_MAX_TOKENS,
        THINKING_FLOOR_TIMEOUT_SECONDS,
    )

    pessimistic_tokens_per_second = 75.0

    assert (
        THINKING_FLOOR_MAX_TOKENS / pessimistic_tokens_per_second
        <= THINKING_FLOOR_TIMEOUT_SECONDS
    )


def test_the_thinking_knob_is_the_engine_s_to_choose() -> None:
    """One place decides how a route expresses thinking, not two.

    The app and the engine both send thinking parameters, and the shape
    depends on the route rather than on the model: a gateway normalizes
    reasoning into its own parameter and ignores DeepSeek's. Two copies
    of that rule is one more thing to keep in step, and the copy that
    gets forgotten sends a disable that reads as an enable -- which
    costs a whole token budget and returns nothing.
    """
    from app.config import (
        deepseek_non_thinking_extra_body,
        deepseek_thinking_kwargs,
    )

    routed = "openrouter/deepseek/deepseek-v4-flash"
    direct = "deepseek/deepseek-v4-flash"

    # The price ceiling is the engine's too: a gateway spreads one model
    # over hosts differing 6.5x in price, and neither the host ordering
    # nor the throughput floor considers price at all. Restating any of
    # it here would be the second copy this test exists to prevent.
    #
    # `order` replaced `sort: throughput` after the latter was measured
    # scattering consecutive calls across upstreams and collapsing the
    # prompt-cache hit rate to 6.9% (against 33.7% for the month) on the
    # run of 2026-09-04; `preferred_min_throughput` keeps the slow-host
    # protection `sort` used to provide. Full rationale lives with the
    # engine's own copy in test_llm_wrappers_thinking.py.
    gateway = {
        "require_parameters": True,
        "allow_fallbacks": True,
        "preferred_min_throughput": 25,
        "order": ["modal", "friendli", "together"],
        "max_price": {"prompt": 0.166, "completion": 0.33},
    }

    assert deepseek_non_thinking_extra_body(routed) == {
        "reasoning": {"enabled": False},
        "provider": gateway,
    }
    assert deepseek_non_thinking_extra_body(direct) == {
        "thinking": {"type": "disabled"}
    }
    assert deepseek_thinking_kwargs(routed)["extra_body"] == {
        "reasoning": {"enabled": True, "effort": "high"},
        "provider": gateway,
    }
    assert deepseek_non_thinking_extra_body("gemini/gemini-2.5-flash") == {}
    assert deepseek_thinking_kwargs("gemini/gemini-2.5-flash") == {}

    # The tier is stated once, in the shape the route understands. A
    # top-level ``reasoning_effort`` beside the gateway's own ``reasoning``
    # object is the copy litellm refuses (``UnsupportedParamsError``) for a
    # model its OpenRouter support map does not list -- and these app call
    # sites reach litellm directly, without the ``drop_params`` every engine
    # call carries. It parked runs at the contextual safety screen.
    assert "reasoning_effort" not in deepseek_thinking_kwargs(routed)
    assert deepseek_thinking_kwargs(direct)["reasoning_effort"] == "high"

"""Tests for the DeepSeek thinking-mode helpers in ``app.config``.

The two helpers translate the thinking toggle into provider-specific
request params: DeepSeek's native API takes a ``thinking`` object plus
``reasoning_effort``, while the same models on Alibaba Cloud DashScope
take ``enable_thinking`` (bool) and are sent no effort tier. Getting the
format wrong is silent -- the two APIs disagree on the default, so the
wrong shape leaves reasoning to chance rather than erroring. Titling is
the one caller of the opt-out; everything else thinks.
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


def test_thinking_kwargs_dashscope_deepseek() -> None:
    """DeepSeek-on-DashScope thinks via enable_thinking, no effort tiers."""
    kwargs = deepseek_thinking_kwargs("dashscope/deepseek-v4-pro")

    assert kwargs == {"extra_body": {"enable_thinking": True}}


def test_thinking_kwargs_empty_for_other_models() -> None:
    """Non-DeepSeek models carry no thinking params at all."""
    assert deepseek_thinking_kwargs("gemini/gemini-2.5-flash") == {}


def test_non_thinking_body_native_deepseek() -> None:
    """The opt-out disables thinking explicitly on the native API."""
    body = deepseek_non_thinking_extra_body("deepseek/deepseek-v4-flash")

    assert body == {"thinking": {"type": "disabled"}}


def test_non_thinking_body_dashscope_deepseek() -> None:
    """The opt-out maps to enable_thinking=False on DashScope."""
    body = deepseek_non_thinking_extra_body("dashscope/deepseek-v4-flash")

    assert body == {"enable_thinking": False}


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
        thinking_safe_max_tokens("dashscope/deepseek-v4-flash", 3_000)
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

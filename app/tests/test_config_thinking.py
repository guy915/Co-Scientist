"""Tests for the DeepSeek thinking-mode helpers in ``app.config``.

The two helpers translate the thinking toggle into provider-specific
request params: DeepSeek's native API takes a ``thinking`` object plus
``reasoning_effort``, while the same models on Alibaba Cloud DashScope
take ``enable_thinking`` (bool) and are sent no effort tier. Getting the
format wrong is silent -- the two APIs disagree on the default, so the
wrong shape leaves reasoning to chance rather than erroring. Only the
thinking variant has call sites today; the opt-out remains as a seam.
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

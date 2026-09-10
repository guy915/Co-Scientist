"""Tests for narrative goal-restatement generation (GOAL-RESTATEMENT-001)."""

from __future__ import annotations

import types
from typing import Any

import pytest

from app.config import settings
from app.goal_restatement import clean_restatement, generate_goal_restatement


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A clean restatement.", "A clean restatement."),
        ('  "Wrapped in quotes."  ', "Wrapped in quotes."),
        ("Collapses\n  messy\twhitespace", "Collapses messy whitespace"),
    ],
)
def test_clean_restatement_normalizes(raw: str, expected: str) -> None:
    """Whitespace is collapsed to one paragraph and wrapping quotes stripped."""
    assert clean_restatement(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "x" * 801])
def test_clean_restatement_rejects_empty_or_overlong(raw: str) -> None:
    """An empty or essay-length reply is discarded, so the report omits it."""
    assert clean_restatement(raw) is None


async def test_generation_failure_returns_none(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """Any provider failure yields None so the report simply omits it."""
    import litellm

    async def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(litellm, "acompletion", _boom)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")

    assert await generate_goal_restatement("Map the feedback loop.") is None


async def test_reasoned_with_no_answer_retries_without_thinking(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """A reasoned-but-empty completion is retried with thinking off.

    Mirrors ``title_gen``: a completion that spends its whole reasoning
    budget and writes nothing is not a provider failure, so it earns one
    retry with thinking disabled rather than silently omitting the paragraph.
    """
    import litellm

    calls: list[dict[str, Any]] = []

    def _thinking_only() -> Any:
        message = types.SimpleNamespace(content="")
        details = types.SimpleNamespace(reasoning_tokens=900)
        usage = types.SimpleNamespace(completion_tokens_details=details)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)], usage=usage
        )

    def _answered() -> Any:
        message = types.SimpleNamespace(
            content="This investigation seeks the loop's control point."
        )
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    async def _acompletion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return _thinking_only() if len(calls) == 1 else _answered()

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")

    restatement = await generate_goal_restatement("Map the feedback loop.")

    assert restatement == "This investigation seeks the loop's control point."
    assert len(calls) == 2
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}

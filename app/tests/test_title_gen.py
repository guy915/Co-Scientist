"""Tests for run session-title generation and persistence."""

from __future__ import annotations

import types
from typing import Any

import pytest

from app import store
from app.config import settings
from app.title_gen import clean_title, generate_run_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Ferroptosis Regulators in Pancreatic Cancer",
            "Ferroptosis Regulators in Pancreatic Cancer",
        ),
        (
            '  "Antibiotic Resistance in Biofilms"  ',
            "Antibiotic Resistance in Biofilms",
        ),
        ("Synaptic Pruning and Cognition.", "Synaptic Pruning and Cognition"),
        ("Title\n  with   messy\twhitespace", "Title with messy whitespace"),
    ],
)
def test_clean_title_normalizes(raw: str, expected: str) -> None:
    assert clean_title(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", '""', "A" * 200])
def test_clean_title_rejects_empty_or_overlong(raw: str) -> None:
    assert clean_title(raw) is None


def test_set_run_title_persists_and_serializes(isolated_db: str) -> None:
    run = store.create_run(
        "Map senescence escape mechanisms",
        "default",
        "mock",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    # Created without a title; the API shape carries it as None.
    assert run.title is None
    assert run.to_dict()["title"] is None

    store.set_run_title(run.id, "Senescence Escape Mechanisms", isolated_db)

    reloaded = store.get_run(run.id, db_path=isolated_db)
    assert reloaded is not None
    assert reloaded.title == "Senescence Escape Mechanisms"
    assert reloaded.to_dict()["title"] == "Senescence Escape Mechanisms"


def test_set_run_title_missing_run_is_noop(isolated_db: str) -> None:
    # No row for this id: the update touches nothing and does not raise.
    store.set_run_title("does-not-exist", "Ghost Title", isolated_db)
    assert store.get_run("does-not-exist", db_path=isolated_db) is None


async def test_title_call_thinks_and_its_budget_assumes_that(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """Titling thinks like every app call site now, its budget assumes that.

    These two facts are one decision. Reasoning tokens come out of the same
    ``max_tokens`` and are emitted first, so a thinking title call sent with
    the answer-sized budget alone would spend the whole thing on its chain
    of thought and return empty content -- which surfaces only as runs that
    are silently untitled, never as an error, because ``generate_run_title``
    swallows every failure. Asserting both together means a future edit
    cannot flip one without the other.
    """
    import litellm

    from app.config_thinking import THINKING_FLOOR_MAX_TOKENS

    seen: dict[str, Any] = {}

    async def _capturing_acompletion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        message = types.SimpleNamespace(content="Ferroptosis In Glioma")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    monkeypatch.setattr(litellm, "acompletion", _capturing_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")

    title = await generate_run_title("Find ferroptosis regulators in glioma")

    assert title == "Ferroptosis In Glioma"
    assert seen["extra_body"] == {"thinking": {"type": "enabled"}}
    assert seen["reasoning_effort"] == "high"
    # The budget lifted to the reasoning floor, since 24 alone would be
    # spent entirely on the chain of thought.
    assert seen["max_tokens"] == THINKING_FLOOR_MAX_TOKENS


async def test_title_call_timeout_is_lifted_for_a_thinking_model(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """The token budget and the deadline are one setting in two places.

    A thinking call funded to reason for up to four minutes must not still
    be abandoned at the old 15s answer-only deadline.
    """
    import asyncio

    import litellm

    from app.config import THINKING_FLOOR_TIMEOUT_SECONDS

    seen_timeout: dict[str, float] = {}
    real_wait_for = asyncio.wait_for

    async def _capturing_wait_for(aw: Any, timeout: float) -> Any:
        seen_timeout["value"] = timeout
        return await real_wait_for(aw, timeout=timeout)

    async def _acompletion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content="Ferroptosis In Glioma")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")
    monkeypatch.setattr(asyncio, "wait_for", _capturing_wait_for)

    await generate_run_title("Find ferroptosis regulators in glioma")

    assert seen_timeout["value"] >= THINKING_FLOOR_TIMEOUT_SECONDS


async def test_title_call_reasoned_with_no_answer_retries_without_thinking(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """A completion that reasoned and wrote nothing is retried, not lost.

    A non-streaming completion can end normally having spent its whole
    reasoning budget and answered with nothing at all -- the same shape
    the engine's ``LLMThinkingOnlyError`` names for its own call sites.
    Titling used to read this as "no usable title" and fall back to the
    goal-clause title silently; it now gets one retry with thinking off.
    """
    import litellm

    calls: list[dict[str, Any]] = []

    def _thinking_only_response() -> Any:
        message = types.SimpleNamespace(content="")
        details = types.SimpleNamespace(reasoning_tokens=900)
        usage = types.SimpleNamespace(completion_tokens_details=details)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)], usage=usage
        )

    def _answered_response() -> Any:
        message = types.SimpleNamespace(content="Ferroptosis In Glioma")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    async def _acompletion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if len(calls) == 1:
            return _thinking_only_response()
        return _answered_response()

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")

    title = await generate_run_title("Find ferroptosis regulators in glioma")

    assert title == "Ferroptosis In Glioma"
    assert len(calls) == 2
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in calls[1]

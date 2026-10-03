"""Tests for run text."""

from __future__ import annotations

import logging
import types
from typing import Any

import pytest

from app import elo, store
from app.config import settings
from app.elo import INITIAL_ELO
from app.goal_text import (
    clean_restatement,
    clean_title,
    generate_goal_restatement,
    generate_run_title,
)
from app.text_utils import readable_experiment_summary
from tests._llm_fake_backend import install_completion_backend

# Elo defaults and ordering agree with the engine.


def test_initial_elo_is_1200() -> None:
    assert INITIAL_ELO == 1200


def test_leaderboard_ranks_played_ideas_above_unplayed_ones() -> None:
    """Never having competed must not outrank having competed and lost.

    Every hypothesis starts at INITIAL_ELO, so a pure Elo sort promotes the
    ideas the tournament never reached. A production run led its standings
    with six unplayed ideas at 1200 and put the genuine runner-up, which had
    actually lost a match at 1136, beneath all of them.
    """
    from app.elo import live_leaderboard

    rows = live_leaderboard(
        [
            {"id": "unplayed", "title": "Never matched", "elo_rating": 1200},
            {
                "id": "loser",
                "title": "Lost a match",
                "elo_rating": 1136,
                "loss_count": 1,
            },
            {
                "id": "winner",
                "title": "Won a match",
                "elo_rating": 1259,
                "win_count": 1,
            },
        ]
    )

    assert [row["id"] for row in rows] == ["winner", "loser", "unplayed"]


constants = pytest.importorskip("co_scientist.constants")


def test_elo_constants_match_engine() -> None:
    """The app's default Elo tuning mirrors the engine's constants."""
    assert elo.INITIAL_ELO == constants.INITIAL_ELO_RATING
    assert elo.DEFAULT_K_FACTOR == constants.ELO_K_FACTOR


# Tests for narrative goal-restatement generation (GOAL-RESTATEMENT-001).


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

    async def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    install_completion_backend(monkeypatch, _boom)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")

    assert await generate_goal_restatement("Map the feedback loop.") is None


async def test_reasoned_with_no_answer_retries_without_thinking(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """A reasoned-but-empty completion is retried with thinking off.

    Mirrors ``goal_text``: a completion that spends its whole reasoning
    budget and writes nothing is not a provider failure, so it earns one
    retry with thinking disabled rather than silently omitting the paragraph.
    """
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

    install_completion_backend(monkeypatch, _acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")

    restatement = await generate_goal_restatement("Map the feedback loop.")

    assert restatement == "This investigation seeks the loop's control point."
    assert len(calls) == 2
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}


async def test_goal_text_retries_keep_separate_operation_budgets(
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retries share one operation cap; the next operation starts fresh."""

    async def reasoning_only(**_kwargs: Any) -> Any:
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(message=types.SimpleNamespace(content=""))
            ],
            usage=types.SimpleNamespace(
                completion_tokens_details=types.SimpleNamespace(
                    reasoning_tokens=900
                )
            ),
        )

    fake = install_completion_backend(monkeypatch, reasoning_only)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")
    monkeypatch.setattr(settings, "app_llm_max_calls", 1)
    with caplog.at_level(logging.INFO, logger="app.llm_scope"):
        assert await generate_run_title("Map the feedback loop.") is None
        assert await generate_goal_restatement("Map the feedback loop.") is None

    assert len(fake.requests) == 2
    assert "surface=title calls=1" in caplog.text
    assert "surface=goal_restatement calls=1" in caplog.text


# Tests for app.text_utils.readable_experiment_summary (R14-20).


def test_collapses_numbered_steps_and_bolded_criteria_to_one_line() -> None:
    text = (
        "1. Script the pipeline.\n"
        "2. Calibrate against ground truth.\n"
        "**Go:** AUC >= 0.8.\n"
        "**No-Go:** AUC < 0.6."
    )
    assert readable_experiment_summary(text) == (
        "Script the pipeline. Calibrate against ground truth."
        " Go: AUC >= 0.8. No-Go: AUC < 0.6."
    )


def test_plain_paragraph_passes_through_unchanged() -> None:
    assert (
        readable_experiment_summary("A single free-text paragraph.")
        == "A single free-text paragraph."
    )


def test_empty_string_returns_empty() -> None:
    assert readable_experiment_summary("") == ""


def test_whitespace_only_returns_empty() -> None:
    assert readable_experiment_summary("   \n  \n") == ""


def test_leaves_bold_text_other_than_go_no_go_markers_untouched() -> None:
    """Only the two known Go/No-Go markers are unbolded, nothing else."""
    text = "1. Use the **primary** readout.\n**Go:** it clears threshold."
    assert readable_experiment_summary(text) == (
        "Use the **primary** readout. Go: it clears threshold."
    )


# Tests for run session-title generation and persistence.


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
    from app.config import THINKING_FLOOR_MAX_TOKENS

    seen: dict[str, Any] = {}

    async def _capturing_acompletion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        message = types.SimpleNamespace(content="Ferroptosis In Glioma")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    install_completion_backend(monkeypatch, _capturing_acompletion)
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

    install_completion_backend(monkeypatch, _acompletion)
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

    install_completion_backend(monkeypatch, _acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")

    title = await generate_run_title("Find ferroptosis regulators in glioma")

    assert title == "Ferroptosis In Glioma"
    assert len(calls) == 2
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in calls[1]

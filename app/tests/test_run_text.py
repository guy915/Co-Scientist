from __future__ import annotations

import logging
import types
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.config import settings
from app.elo import live_leaderboard
from app.goal_text import (
    clean_restatement,
    clean_title,
    generate_goal_restatement,
    generate_run_title,
)
from app.store import runs
from app.text_utils import readable_experiment_summary
from tests._llm_fake_backend import install_completion_backend
from tests._store_helpers import seed_run

_GENERATORS = [
    pytest.param(
        generate_goal_restatement,
        "This investigation seeks the loop's control point.",
        id="restatement",
    ),
    pytest.param(generate_run_title, "Ferroptosis In Glioma", id="title"),
]


def test_leaderboard_ranks_played_ideas_above_unplayed_ones() -> None:
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A clean restatement.", "A clean restatement."),
        ('  "Wrapped in quotes."  ', "Wrapped in quotes."),
        ("Collapses\n  messy\twhitespace", "Collapses messy whitespace"),
        ("", None),
        ("   ", None),
        ("x" * 801, None),
    ],
)
def test_clean_restatement(raw: str, expected: str | None) -> None:
    assert clean_restatement(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            '  "Antibiotic Resistance in Biofilms"  ',
            "Antibiotic Resistance in Biofilms",
        ),
        ("Synaptic Pruning and Cognition.", "Synaptic Pruning and Cognition"),
        ("Title\n  with   messy\twhitespace", "Title with messy whitespace"),
        ("", None),
        ("   ", None),
        ('""', None),
        ("A" * 200, None),
    ],
)
def test_clean_title(raw: str, expected: str | None) -> None:
    assert clean_title(raw) == expected


@pytest.mark.parametrize(
    ("text", "summary"),
    [
        (
            "1. Script the pipeline.\n"
            "2. Calibrate against ground truth.\n"
            "**Go:** AUC >= 0.8.\n"
            "**No-Go:** AUC < 0.6.",
            "Script the pipeline. Calibrate against ground truth."
            " Go: AUC >= 0.8. No-Go: AUC < 0.6.",
        ),
        (
            "1. Use the **primary** readout.\n**Go:** it clears threshold.",
            "Use the **primary** readout. Go: it clears threshold.",
        ),
        ("   \n  \n", ""),
    ],
)
def test_experiment_summary_reads_as_one_line(text: str, summary: str) -> None:
    assert readable_experiment_summary(text) == summary


def test_set_run_title_persists_and_serializes(isolated_db: str) -> None:
    run = seed_run(
        "Map senescence escape mechanisms",
        profile="default",
        provider="mock",
        client_id="c1",
        db_path=isolated_db,
    )
    assert run.to_dict()["title"] is None

    runs.set_run_title(run.id, "Senescence Escape Mechanisms", isolated_db)

    reloaded = runs.get_run(run.id, db_path=isolated_db)
    assert reloaded is not None
    assert reloaded.to_dict()["title"] == "Senescence Escape Mechanisms"


def _thinking_only() -> Any:
    message = types.SimpleNamespace(content="")
    details = types.SimpleNamespace(reasoning_tokens=900)
    usage = types.SimpleNamespace(completion_tokens_details=details)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=message)], usage=usage
    )


def _answered(text: str) -> Any:
    message = types.SimpleNamespace(content=text)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=message)]
    )


@pytest.mark.parametrize(("generate", "answer"), _GENERATORS)
async def test_generation_failure_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
    generate: Callable[[str], Awaitable[str | None]],
    answer: str,
) -> None:
    async def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    install_completion_backend(monkeypatch, _boom)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")

    assert await generate("Map the feedback loop.") is None


@pytest.mark.parametrize(("generate", "answer"), _GENERATORS)
async def test_reasoned_with_no_answer_retries_without_thinking(
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
    generate: Callable[[str], Awaitable[str | None]],
    answer: str,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _acompletion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return _thinking_only() if len(calls) == 1 else _answered(answer)

    install_completion_backend(monkeypatch, _acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")

    assert await generate("Map the feedback loop.") == answer
    assert len(calls) == 2
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in calls[1]


async def test_goal_text_retries_keep_separate_operation_budgets(
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def reasoning_only(**_kwargs: Any) -> Any:
        return _thinking_only()

    fake = install_completion_backend(monkeypatch, reasoning_only)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")
    monkeypatch.setattr(settings, "app_llm_max_calls", 1)
    with caplog.at_level(logging.INFO, logger="app.llm_scope"):
        assert await generate_run_title("Map the feedback loop.") is None
        assert await generate_goal_restatement("Map the feedback loop.") is None

    assert len(fake.requests) == 2
    assert "surface=title calls=1" in caplog.text
    assert "surface=goal_restatement calls=1" in caplog.text


async def test_title_call_thinks_with_a_budget_and_deadline_that_assume_it(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    # Reasoning consumes the output budget and can leave an untitled answer.
    import asyncio

    from app.config import (
        THINKING_FLOOR_MAX_TOKENS,
        THINKING_FLOOR_TIMEOUT_SECONDS,
    )

    seen: dict[str, Any] = {}
    real_wait_for = asyncio.wait_for

    async def _capturing_wait_for(aw: Any, timeout: float) -> Any:
        seen["timeout"] = timeout
        return await real_wait_for(aw, timeout=timeout)

    async def _capturing_acompletion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return _answered("Ferroptosis In Glioma")

    install_completion_backend(monkeypatch, _capturing_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")
    monkeypatch.setattr(asyncio, "wait_for", _capturing_wait_for)

    title = await generate_run_title("Find ferroptosis regulators in glioma")

    assert title == "Ferroptosis In Glioma"
    assert seen["extra_body"] == {"thinking": {"type": "enabled"}}
    assert seen["reasoning_effort"] == "high"
    assert seen["max_tokens"] == THINKING_FLOOR_MAX_TOKENS
    assert seen["timeout"] >= THINKING_FLOOR_TIMEOUT_SECONDS

"""Tests for run session-title generation and persistence."""

from __future__ import annotations

import types
from typing import Any

import pytest

from app import store
from app.config import settings
from app.title_gen import _clean_title, generate_run_title


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
    assert _clean_title(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", '""', "A" * 200])
def test_clean_title_rejects_empty_or_overlong(raw: str) -> None:
    assert _clean_title(raw) is None


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


async def test_title_call_does_not_think_and_stays_within_its_budget(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """Titling opts out of thinking, and its token budget assumes that.

    These two facts are one decision. Reasoning tokens come out of the same
    ``max_tokens`` and are emitted first, so a thinking title call spends
    the whole budget on its chain of thought and returns empty content --
    which surfaces only as runs that are silently untitled, never as an
    error, because ``generate_run_title`` swallows every failure. Asserting
    both together means a future edit cannot flip one without the other.
    """
    import litellm

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
    assert seen["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in seen
    # The budget that only works without a reasoning spend.
    assert seen["max_tokens"] == 24

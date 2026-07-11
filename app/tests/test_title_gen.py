"""Tests for run session-title generation and persistence."""

from __future__ import annotations

import pytest

from app import store
from app.title_gen import _clean_title


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
        research_goal="Map senescence escape mechanisms",
        profile="default",
        provider="mock",
        config={},
        client_id="c1",
        db_path=isolated_db,
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

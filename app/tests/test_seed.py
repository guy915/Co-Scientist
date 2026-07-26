"""Tests for the startup demo-run seeder in ``app.seed``.

Exercises the full seed-then-reseed lifecycle directly (not through the app's
lifespan), including the already-seeded no-op branch, the reseed-on-missing-
report branch, and the per-goal failure isolation.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app import seed, store
from app.demo_seed_data import DEMO_SEED_VERSION
from app.store import DEMO_CLIENT_ID, RunRow


def _seed(db_path: str) -> None:
    asyncio.run(seed.seed_demo_runs(db_path=db_path))


def test_seed_demo_runs_creates_three_runs_with_reports(
    isolated_db: str,
) -> None:
    _seed(isolated_db)

    runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    goals = {r.research_goal for r in runs}
    assert goals == set(seed._DEMO_GOALS)
    for run in runs:
        # Each default demo is a complete browseable, offline-backed example.
        assert run.status == "completed"
        assert run.llm_backend == "offline"
        assert store.run_used_offline(run)
        md = store.read_report_markdown(run.id, db_path=isolated_db)
        assert md is not None and "Research Report" in md
        assert len(store.list_hypotheses(run.id, db_path=isolated_db)) == 3
        assert len(store.list_evidence(run.id, db_path=isolated_db)) == 2
        assert len(store.list_reviews(run.id, db_path=isolated_db)) == 3
        assert len(store.list_matches(run.id, db_path=isolated_db)) == 2
        assert "Curated demonstration only" in md
        report = store.get_latest_report(run.id, db_path=isolated_db)
        assert report is not None
        assert report["payload"]["demo_seed_version"] == DEMO_SEED_VERSION


def test_seed_demo_runs_is_idempotent_when_reports_exist(
    isolated_db: str,
) -> None:
    _seed(isolated_db)
    before = {
        r.id: store.get_latest_report(r.id, db_path=isolated_db)
        for r in store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    }

    _seed(isolated_db)

    after_runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(after_runs) == 3
    assert {r.id for r in after_runs} == set(before)
    # No report was regenerated: created_at timestamps are unchanged.
    for run in after_runs:
        report = store.get_latest_report(run.id, db_path=isolated_db)
        assert report is not None
        seeded_at = before[run.id]["created_at"]  # type: ignore[index]
        assert report["created_at"] == seeded_at


def test_seed_demo_runs_reseeds_run_missing_report(isolated_db: str) -> None:
    goal = seed._DEMO_GOALS[0]
    run = store.create_run(
        goal,
        "default",
        "mock",
        {},
        store.RunCreateOptions(client_id=DEMO_CLIENT_ID, db_path=isolated_db),
    )
    assert store.read_report_markdown(run.id, db_path=isolated_db) is None

    _seed(isolated_db)

    runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    reseeded = next(r for r in runs if r.research_goal == goal)
    # The existing row is reused (re-seeded in place), not duplicated.
    assert reseeded.id == run.id
    assert (
        store.read_report_markdown(reseeded.id, db_path=isolated_db) is not None
    )


def test_seed_demo_runs_replaces_legacy_demo_content(isolated_db: str) -> None:
    """An older persisted report is upgraded to the curated scenario."""
    goal = seed._DEMO_GOALS[0]
    run = store.create_run(
        goal,
        "express",
        "engine",
        {},
        store.RunCreateOptions(client_id=DEMO_CLIENT_ID, db_path=isolated_db),
    )
    store.save_report(run.id, {"legacy": True}, "# Legacy", db_path=isolated_db)

    _seed(isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["demo_seed_version"] == DEMO_SEED_VERSION
    assert "Curated demonstration only" in report["markdown_text"]


def test_seed_demo_run_failure_is_swallowed(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed per-goal seed is logged and does not abort the others."""

    async def _boom(goal: str, run: RunRow | None, db_path: str | None) -> None:
        raise RuntimeError("seed failure")

    monkeypatch.setattr(seed, "_seed_demo_run", _boom)

    with caplog.at_level(logging.ERROR, logger="app.seed"):
        _seed(isolated_db)

    assert "Failed to seed demo run" in caplog.text
    assert store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db) == []


def test_seed_demo_run_creates_new_run_when_none_given(
    isolated_db: str,
) -> None:
    """``_seed_demo_run`` creates a run itself when passed ``run=None``."""
    # This exercises the seeding primitive directly, bypassing
    # ``seed_demo_runs`` (which installs the router itself), so install the
    # offline router first -- otherwise the engine run's offline/ model calls
    # have no handler and the run fails. Idempotent; a passthrough for real
    # models.
    from co_scientist.offline_llm import install_offline_router

    install_offline_router()
    goal = "A standalone seeding goal"
    asyncio.run(seed._seed_demo_run(goal, None, isolated_db))

    runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    created = [r for r in runs if r.research_goal == goal]
    assert len(created) == 1
    assert created[0].status == "completed"
    assert created[0].llm_backend == "offline"
    assert store.read_report_markdown(created[0].id, db_path=isolated_db)


def test_has_readable_report_reflects_report_presence(
    isolated_db: str,
) -> None:
    run = store.create_run(
        "goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    assert seed._has_readable_report(run, isolated_db) is False

    store.save_report(run.id, {"k": "v"}, "# md", db_path=isolated_db)
    assert seed._has_readable_report(run, isolated_db) is True


def _demo_run_row(id_: str, goal: str) -> RunRow:
    return RunRow(
        id=id_,
        research_goal=goal,
        profile="default",
        status="completed",
        provider="mock",
        config={},
        client_id=DEMO_CLIENT_ID,
        created_at=0.0,
        updated_at=0.0,
        completed_at=0.0,
        error=None,
    )


def test_runs_by_goal_indexes_by_research_goal() -> None:
    a = _demo_run_row("a", "goal-a")
    b = _demo_run_row("b", "goal-b")
    indexed = seed._runs_by_goal([a, b])
    assert indexed == {"goal-a": a, "goal-b": b}

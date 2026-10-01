"""Tests for the startup demo-run seeder in ``app.seed``.

Exercises the full seed-then-reseed lifecycle directly (not through the app's
lifespan), including the already-seeded no-op branch, the reseed-on-missing-
report branch, and the per-goal failure isolation.
"""

from __future__ import annotations

import asyncio
import logging
import re

import pytest

from app import seed, store
from app.demo_seed_data import (
    DEMO_SCENARIOS,
    DEMO_SEED_VERSION,
    scenario_hypotheses,
    scenario_key,
)
from app.seed.review_detail import full_review_count, simulation_review_count
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
        scenario = DEMO_SCENARIOS[run.research_goal]
        expected_ideas = len(scenario_hypotheses(scenario))
        hypotheses = store.list_hypotheses(run.id, db_path=isolated_db)
        assert len(hypotheses) == expected_ideas
        evidence = store.list_evidence(run.id, db_path=isolated_db)
        assert len(evidence) == 6
        # R12-12: the demo's real curated sources carry a PubMed id
        # wired through from their own url, so the run-wide bibliography
        # is populated with real identifiers rather than empty.
        assert all(item["pmid"] for item in evidence)
        assert "\n## References\n" in md
        assert md.count("\n- [") == 6
        key = scenario_key(scenario)
        # Every idea carries reflection + deep_verification; only the
        # highest-ranked ideas additionally carry a curated full/simulation
        # review row (see app.seed.review_detail).
        expected_reviews = (
            expected_ideas * 2
            + full_review_count(key)
            + simulation_review_count(key)
        )
        assert (
            len(store.list_reviews(run.id, db_path=isolated_db))
            == expected_reviews
        )
        assert len(store.list_matches(run.id, db_path=isolated_db)) == (
            expected_ideas - 1 + expected_ideas // 2
        )
        # Every example idea has a tournament record; none is shown unranked.
        assert all(
            hypothesis["win_count"] + hypothesis["loss_count"]
            for hypothesis in hypotheses
        )
        assert "Curated demonstration only" in md
        report = store.get_latest_report(run.id, db_path=isolated_db)
        assert report is not None
        assert report["payload"]["demo_seed_version"] == DEMO_SEED_VERSION
        assert len(report["payload"]["knowledge_base"]) == 6
        overview = report["payload"]["research_overview"]
        aims = overview["nih_specific_aims"]["aims"]
        assert len(aims) == 3
        metrics = store.get_run_metrics(run.id, db_path=isolated_db)
        assert metrics is not None
        assert metrics["total_time"] == scenario.duration_seconds
        assert max(hypothesis["elo_rating"] for hypothesis in hypotheses) == (
            scenario.elo_ceiling
        )

    assert sorted(
        len(scenario_hypotheses(scenario))
        for scenario in DEMO_SCENARIOS.values()
    ) == [15, 19, 21]


def test_seed_demo_runs_render_criteria_and_unexpected_directions(
    isolated_db: str,
) -> None:
    """Both R12-18/R12-23 report sections are populated, not merely wired.

    A report is stored, frozen ``reports.markdown_text``; nothing
    re-renders it, so a demo only shows a new section once it is re-seeded
    with curated data that supplies it. This pins that the curated
    ``critical_criteria`` (``seed/config_synthesis.py``) fill the report's
    prose "Evaluation Criteria" section (``_render_evaluation_criteria_
    markdown``) and that the curated ``unexpected_research_directions``
    fill the "Unexpected research directions" bullets
    (``_render_unexpected_directions_section``) on all three demos.
    """
    _seed(isolated_db)

    runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    for run in runs:
        md = store.read_report_markdown(run.id, db_path=isolated_db)
        assert md is not None
        assert "\n## Evaluation Criteria\n" in md
        section = md.split("## Evaluation Criteria", 1)[1]
        next_heading = re.search(r"\n## ", section)
        body = section[: next_heading.start()] if next_heading else section
        entries = [line for line in body.splitlines() if line.startswith("**")]
        assert entries
        for entry in entries:
            assert entry.startswith("**")
            assert ":** " in entry

        assert "\n### Unexpected research directions\n" in md
        directions_section = md.split("### Unexpected research directions", 1)[
            1
        ]
        next_directions_heading = re.search(r"\n#{1,3} ", directions_section)
        directions_body = (
            directions_section[: next_directions_heading.start()]
            if next_directions_heading
            else directions_section
        )
        bullets = [
            line
            for line in directions_body.splitlines()
            if line.startswith("- ")
        ]
        assert len(bullets) == 3
        for bullet in bullets:
            assert bullet.startswith("- **")
            assert bullet.count("**") >= 2


def test_seed_demo_runs_render_main_research_directions(
    isolated_db: str,
) -> None:
    """R14-27: all three demos show the report's own narrative directions.

    Pins that the curated ``main_research_directions``
    (``seed/meta_review_directions.py``) fills the report's "## Main
    Research Directions" section, sitting immediately before Top
    hypotheses (R14-27's own published "before Candidate Ideas"
    placement), with two genuinely populated paragraphs -- not a bare
    heading.
    """
    _seed(isolated_db)

    runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    for run in runs:
        md = store.read_report_markdown(run.id, db_path=isolated_db)
        assert md is not None
        assert "\n## Main Research Directions\n" in md

        directions_index = md.index("## Main Research Directions")
        candidates_index = md.index("## Top hypotheses")
        assert directions_index < candidates_index

        section = md.split("## Main Research Directions", 1)[1]
        next_heading = re.search(r"\n#{1,2} ", section)
        body = section[: next_heading.start()] if next_heading else section
        paragraphs = [
            p.strip() for p in body.strip().split("\n\n") if p.strip()
        ]
        assert len(paragraphs) == 2
        for paragraph in paragraphs:
            assert paragraph
            assert "**" in paragraph


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


def test_seed_demo_runs_backfills_goal_detail_config(isolated_db: str) -> None:
    """A current report cannot leave an old demo row's details empty."""
    goal = seed._DEMO_GOALS[0]
    run = store.create_run(
        goal,
        "standard",
        "engine",
        {},
        store.RunCreateOptions(client_id=DEMO_CLIENT_ID, db_path=isolated_db),
    )
    store.save_report(
        run.id,
        {"demo_seed_version": DEMO_SEED_VERSION},
        "# Current-looking report",
        db_path=isolated_db,
    )

    _seed(isolated_db)

    upgraded = store.get_run(run.id, db_path=isolated_db)
    assert upgraded is not None
    setup = upgraded.config["setup"]
    assert len(setup["requirements"]) == 6
    assert len(setup["attributes"]) == 5


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

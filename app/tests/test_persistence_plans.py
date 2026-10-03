"""Tests for persistence 2."""

from __future__ import annotations

import logging
import pathlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app import store
from app.store import db
from app.store import db as store_db
from tests._drain_helpers import (
    _final_state_with_features,
    _persist,
    _persist_and_finalize,
)

# Store tests for per-run execution metrics persistence.


_METRICS = {
    "total_time": 12.5,
    "hypothesis_count": 8,
    "reviews_count": 8,
    "tournaments_count": 6,
    "evolutions_count": 2,
    "llm_calls": 24,
    "phase_times": {"generate": 4.0, "ranking": 2.5},
}


def _make_run(db_path: str) -> str:
    run = store.create_run(
        "Metrics goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=db_path),
    )
    return run.id


def test_metrics_roundtrip(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    store.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    assert store.get_run_metrics(run_id, db_path=isolated_db) == _METRICS


def test_metrics_absent_returns_none(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    assert store.get_run_metrics(run_id, db_path=isolated_db) is None


def test_metrics_upsert_replaces_previous_row(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    store.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    replacement = {**_METRICS, "llm_calls": 99}
    store.save_run_metrics(run_id, replacement, db_path=isolated_db)
    saved = store.get_run_metrics(run_id, db_path=isolated_db)
    assert saved is not None
    assert saved["llm_calls"] == 99


def test_clear_run_derived_data_removes_metrics(isolated_db: str) -> None:
    """A resume's derived-data wipe drops metrics; re-finalize rewrites them."""
    run_id = _make_run(isolated_db)
    store.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    store.clear_run_derived_data(run_id, db_path=isolated_db)
    assert store.get_run_metrics(run_id, db_path=isolated_db) is None


# Tests for the upgrade path against databases created by older builds.
#
# The rest of the suite runs against freshly created databases, where every
# table is built from the current ``_SCHEMA`` and so already carries the
# columns the migrations add. That shape cannot catch ordering bugs between
# ``_SCHEMA`` and ``_run_migrations``. These tests start from an *old-shape*
# database instead, which is what a deployed volume actually holds.


# The app_logs table exactly as builds before the client-isolation change
# created it: no client_id column, and no index over it.
_OLD_APP_LOGS = """
CREATE TABLE app_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    level TEXT NOT NULL,
    levelno INTEGER NOT NULL,
    logger TEXT NOT NULL,
    message TEXT NOT NULL,
    run_id TEXT,
    exc_text TEXT
);
CREATE INDEX idx_app_logs_run ON app_logs(run_id, id);
"""


def _old_shape_db(tmp_path: object) -> str:
    """Create a database holding a pre-client-isolation app_logs table."""
    path = str(tmp_path / "old.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_APP_LOGS)
    conn.commit()
    conn.close()
    return path


def _columns(path: str, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _indexes(path: str, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}
    finally:
        conn.close()


def test_connect_upgrades_an_old_app_logs_table(tmp_path: object) -> None:
    """Opening a pre-client-isolation database migrates it instead of raising.

    A schema-level index over a migration-added column would abort
    ``executescript`` here, leaving the path uninitialized and every later
    connect failing the same way -- i.e. the server would not start.
    """
    path = _old_shape_db(tmp_path)

    with db.connect(path) as conn:
        conn.execute("SELECT client_id FROM app_logs").fetchall()

    assert "client_id" in _columns(path, "app_logs")
    # The index must still end up present, not merely be dropped to dodge
    # the ordering problem.
    assert "idx_app_logs_client" in _indexes(path, "app_logs")


def test_connect_is_idempotent_over_an_upgraded_database(
    tmp_path: object,
) -> None:
    """A second process opening the same file re-runs migrations cleanly."""
    path = _old_shape_db(tmp_path)
    with db.connect(path):
        pass
    # Drop the module-level cache so this connect redoes the init work a
    # fresh process would, rather than skipping it.
    db._initialized.discard(path)

    with db.connect(path) as conn:
        conn.execute("SELECT client_id FROM app_logs").fetchall()

    assert "idx_app_logs_client" in _indexes(path, "app_logs")


# The interview_turns table exactly as builds before the fallback-provenance
# change created it: no fallback column.
_OLD_INTERVIEW_TURNS = """
CREATE TABLE interview_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    reasoning TEXT,
    created_at REAL NOT NULL
);
"""


def test_connect_upgrades_old_interview_turns_table(
    tmp_path: object,
) -> None:
    """Turns written before the fallback marker open unmarked, not broken.

    A deployed volume holds transcripts whose turns predate the marker; the
    upgrade must add the column and read those rows as model-driven (the
    default), since a missing marker can only mean "written before the
    signal existed", never "known to be scripted".
    """
    path = str(tmp_path / "old_turns.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_INTERVIEW_TURNS)
    conn.execute(
        "INSERT INTO interview_turns (interview_id, role, content, "
        "created_at) VALUES ('iv-1', 'agent', 'Which focus area?', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute("SELECT fallback FROM interview_turns").fetchall()

    assert "fallback" in _columns(path, "interview_turns")
    assert [row[0] for row in rows] == [0]


# The hypotheses table exactly as builds before the multi-parent lineage
# change created it: no parent_ids column.
_OLD_HYPOTHESES = """
CREATE TABLE hypotheses (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_id TEXT,
    generation INTEGER NOT NULL DEFAULT 0,
    category TEXT,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    mechanism TEXT,
    expected_effect TEXT,
    experimental_context TEXT,
    created_by_agent TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def test_connect_upgrades_old_hypotheses_table(tmp_path: object) -> None:
    """Hypotheses written before multi-parent lineage open with NULL parents.

    A deployed volume holds hypotheses predating the combination operator;
    the upgrade adds the column and those rows read back as NULL parent_ids,
    since a missing column can only mean single-parent lineage.
    """
    path = str(tmp_path / "old_hyps.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_HYPOTHESES)
    conn.execute(
        "INSERT INTO hypotheses (id, run_id, title, statement, "
        "created_by_agent, created_at) "
        "VALUES ('h1', 'r1', 'T', 'S', 'generation', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute("SELECT parent_ids FROM hypotheses").fetchall()

    assert "parent_ids" in _columns(path, "hypotheses")
    assert [row[0] for row in rows] == [None]


def test_connect_adds_scene_setting_columns_to_old_hypotheses(
    tmp_path: object,
) -> None:
    """A pre-MO-6 hypotheses table gains introduction/recent_findings.

    A deployed volume holds hypotheses written before the published
    proposal's scene-setting sections were carried at all; those rows
    read back with NULL in both new columns rather than failing the
    upgrade.
    """
    path = str(tmp_path / "old_hyps_scene.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_HYPOTHESES)
    conn.execute(
        "INSERT INTO hypotheses (id, run_id, title, statement, "
        "created_by_agent, created_at) "
        "VALUES ('h1', 'r1', 'T', 'S', 'generation', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT introduction, recent_findings FROM hypotheses"
        ).fetchall()

    columns = _columns(path, "hypotheses")
    assert {"introduction", "recent_findings"} <= columns
    assert [tuple(row) for row in rows] == [(None, None)]


def test_connect_adds_safety_and_toxicity_column_to_old_hypotheses(
    tmp_path: object,
) -> None:
    """A pre-MO-10 hypotheses table gains safety_and_toxicity.

    A deployed volume holds hypotheses written before the proposer's own
    safety-and-toxicity assessment was carried at all; those rows read
    back with NULL rather than failing the upgrade.
    """
    path = str(tmp_path / "old_hyps_safety.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_HYPOTHESES)
    conn.execute(
        "INSERT INTO hypotheses (id, run_id, title, statement, "
        "created_by_agent, created_at) "
        "VALUES ('h1', 'r1', 'T', 'S', 'generation', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT safety_and_toxicity FROM hypotheses"
        ).fetchall()

    assert "safety_and_toxicity" in _columns(path, "hypotheses")
    assert [row[0] for row in rows] == [None]


# The evidence table exactly as builds before retrieval provenance created
# it: scoring columns present, but nothing naming the search behind a row.
_OLD_EVIDENCE = """
CREATE TABLE evidence (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT,
    url TEXT,
    authors_json TEXT,
    year INTEGER,
    abstract TEXT,
    available INTEGER NOT NULL DEFAULT 1,
    mime_type TEXT,
    sha256 TEXT,
    byte_size INTEGER,
    document_version TEXT,
    extraction_tool TEXT,
    doi TEXT,
    pmid TEXT,
    passage_text TEXT,
    retrieved_at REAL,
    retrieval_score REAL,
    retrieval_rationale TEXT,
    retriever_version TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX idx_ev_run ON evidence(run_id);
"""


def test_connect_upgrades_evidence_for_retrieval_provenance(
    tmp_path: object,
) -> None:
    """Evidence written before provenance opens with a NULL search link.

    The column is added by migration rather than by ``_SCHEMA``, whose
    ``CREATE TABLE IF NOT EXISTS`` is a no-op against the table a deployed
    volume already holds. Existing rows read back NULL, which is the only
    state they could represent: nothing recorded what was asked.
    """
    path = str(tmp_path / "old_evidence.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_EVIDENCE)
    conn.execute(
        "INSERT INTO evidence (id, run_id, title, created_at) "
        "VALUES ('e1', 'r1', 'A paper', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute("SELECT retrieval_call_id FROM evidence").fetchall()
        # The new table arrives on the same open, from _SCHEMA.
        conn.execute("SELECT COUNT(*) FROM retrieval_calls").fetchone()

    assert "retrieval_call_id" in _columns(path, "evidence")
    assert [row[0] for row in rows] == [None]


def test_connect_upgrades_evidence_for_retraction(tmp_path: object) -> None:
    """Evidence written before the retraction column opens with it NULL.

    A row drained before this wave has no way to know whether its
    unavailable evidence was retracted -- the column is additive, so it
    reads back NULL, which ``store.list_evidence`` then coerces to False
    (the same as a row that was never flagged retracted).
    """
    path = str(tmp_path / "old_evidence.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_EVIDENCE)
    conn.execute(
        "INSERT INTO evidence (id, run_id, title, created_at) "
        "VALUES ('e1', 'r1', 'A paper', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute("SELECT retracted FROM evidence").fetchall()

    assert "retracted" in _columns(path, "evidence")
    assert [row[0] for row in rows] == [None]


# The matches table as builds before the debate-transcript column created
# it -- itself already the post-``tier``/``debate_turns`` shape, since both
# of those are migration-added too.
_OLD_MATCHES = """
CREATE TABLE matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    winner_id TEXT NOT NULL,
    loser_id TEXT NOT NULL,
    winner_elo_before INTEGER NOT NULL,
    winner_elo_after INTEGER NOT NULL,
    loser_elo_before INTEGER NOT NULL,
    loser_elo_after INTEGER NOT NULL,
    rationale TEXT,
    tier TEXT,
    debate_turns INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
"""


def test_connect_upgrades_matches_for_the_debate_transcript(
    tmp_path: object,
) -> None:
    """A match judged before the transcript column keeps its row and reads NULL.

    The column is additive: ``ALTER TABLE ... ADD COLUMN`` rewrites the
    schema header, never the rows, so a deployed single-replica volume
    upgrades without a table rebuild or a VACUUM. The pre-existing row
    survives with its rationale intact and a NULL transcript, which is
    the only state it could represent -- the turns were never stored.
    """
    path = str(tmp_path / "old_matches.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_MATCHES)
    conn.execute(
        "INSERT INTO matches (run_id, iteration, winner_id, loser_id, "
        "winner_elo_before, winner_elo_after, loser_elo_before, "
        "loser_elo_after, rationale, tier, debate_turns, created_at) "
        "VALUES ('r1', 0, 'h1', 'h2', 1200, 1212, 1200, 1188, "
        "'Idea 1 wins.', 'decisive', 3, 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT rationale, debate_transcript FROM matches"
        ).fetchall()

    assert "debate_transcript" in _columns(path, "matches")
    assert [tuple(row) for row in rows] == [("Idea 1 wins.", None)]


# Tests for report persistence in ``app.store.reports``.
#
# Covers ``save_report``'s happy path (moved here from ``test_store.py`` to
# keep that file under the 500-line ceiling), the disk-write failure branch,
# the on-disk fallback used for report rows that predate the ``markdown_text``
# column, and the read-side fallback for a row saved during the R14-11
# two-document split window (reversed 2026-09-04).


def _insert_legacy_report_row(
    db_path: str,
    run_id: str,
    report_id: str,
    markdown_path: str | None,
    markdown_text_ranking: str | None = None,
) -> None:
    """Insert a report row with no ``markdown_text`` (pre-column schema)."""
    with store.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO reports (id, run_id, payload_json, markdown_path, "
            "markdown_text, markdown_text_ranking, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                report_id,
                run_id,
                "{}",
                markdown_path,
                None,
                markdown_text_ranking,
                0.0,
            ),
        )


def test_reports_round_trip_markdown_to_disk(isolated_db: str) -> None:
    """The report round-trips through both DB text and disk."""
    run = store.create_run(
        "report rt",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    saved = store.save_report(
        run.id, {"k": "v"}, "# Hello\nbody", db_path=isolated_db
    )
    assert saved["markdown_path"].endswith(".md")
    md = store.read_report_markdown(run.id, db_path=isolated_db)
    assert md and "Hello" in md
    rep = store.get_latest_report(run.id, db_path=isolated_db)
    assert rep and rep["payload"] == {"k": "v"}


def test_save_report_logs_warning_on_disk_write_failure(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A disk write failure is logged, but the DB row is still persisted."""
    run = store.create_run(
        "disk failure goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )

    def _boom(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", _boom)

    with caplog.at_level(logging.WARNING, logger="app.store.reports"):
        saved = store.save_report(
            run.id, {"k": "v"}, "# md body", db_path=isolated_db
        )

    assert "Could not write report markdown to disk" in caplog.text
    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["id"] == saved["id"]
    assert report["markdown_text"] == "# md body"


def test_read_report_markdown_falls_back_to_disk_when_db_text_missing(
    isolated_db: str, tmp_path: pathlib.Path
) -> None:
    """Rows written before markdown_text existed fall back to the disk file."""
    run = store.create_run(
        "disk fallback goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    md_file = tmp_path / "on_disk.md"
    md_file.write_text("# From disk", encoding="utf-8")

    _insert_legacy_report_row(
        isolated_db, run.id, "report-disk-1", str(md_file)
    )

    text = store.read_report_markdown(run.id, db_path=isolated_db)
    assert text == "# From disk"


def test_read_report_markdown_none_without_db_text_or_path(
    isolated_db: str,
) -> None:
    """No markdown_text and no markdown_path yields None, not a crash."""
    run = store.create_run(
        "no source goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    _insert_legacy_report_row(isolated_db, run.id, "report-disk-2", None)

    assert store.read_report_markdown(run.id, db_path=isolated_db) is None


def test_get_latest_report_and_read_markdown_none_without_any_report(
    isolated_db: str,
) -> None:
    """A run with no report row at all yields None from both readers."""
    run = store.create_run(
        "no report goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    assert store.get_latest_report(run.id, db_path=isolated_db) is None
    assert store.read_report_markdown(run.id, db_path=isolated_db) is None


def test_read_report_markdown_none_when_disk_file_missing(
    isolated_db: str, tmp_path: pathlib.Path
) -> None:
    """A markdown_path pointing at a deleted file yields None, not a crash."""
    run = store.create_run(
        "missing file goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    missing_path = tmp_path / "does_not_exist.md"

    _insert_legacy_report_row(
        isolated_db, run.id, "report-disk-3", str(missing_path)
    )

    assert store.read_report_markdown(run.id, db_path=isolated_db) is None


def test_save_report_never_writes_the_legacy_ranking_column(
    isolated_db: str,
) -> None:
    """Every write since the reversal leaves markdown_text_ranking NULL."""
    run = store.create_run(
        "no ranking write goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    store.save_report(run.id, {"k": "v"}, "# Goal Report", db_path=isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["markdown_text_ranking"] is None


def test_read_report_markdown_appends_a_legacy_split_window_row(
    isolated_db: str,
) -> None:
    """A row saved during the R14-11 split window keeps its full content.

    Such a row's ``markdown_text`` is the overview-only half and its "Top
    hypotheses" write-up sits only in ``markdown_text_ranking`` -- the
    reader must not silently drop that half now that nothing else reads
    the column.
    """
    run = store.create_run(
        "split window goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    _insert_legacy_report_row(
        isolated_db,
        run.id,
        "report-split-window",
        None,
        markdown_text_ranking="# ranking half",
    )
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE reports SET markdown_text=? WHERE id=?",
            ("# overview half", "report-split-window"),
        )

    text = store.read_report_markdown(run.id, db_path=isolated_db)
    assert text == "# overview half\n\n# ranking half"


# Store round-trip, drain wiring, and migration coverage for E19.
#
# Covers the durable Supervisor plan/allocation-ledger store I/O
# (``save_supervisor_plan``/``get_supervisor_plan``,
# ``replace_supervisor_allocations``/``list_supervisor_allocations``), the
# real drain wiring (a finalized run's checkpoint state actually reaches the
# store), the collections endpoint, and -- per AGENTS.md's recorded trap --
# that the new tables/index come up cleanly against a database built from a
# schema that predates them, the way a populated production volume would be
# migrated.


def _plan_final_state() -> dict[str, object]:
    """A grounded engine final state carrying a full Supervisor record.

    Layers the Supervisor fields onto the shared ``_final_state_with_
    features`` fixture rather than a minimal hand-built state: its
    hypotheses are grounded against matching articles, so the run actually
    clears the rank-and-publish gate and finalizes (see
    ``test_engine_drain_safety.py`` for what happens when it does not).
    """
    state = _final_state_with_features()
    state["supervisor_guidance"] = {
        "research_goal_analysis": {"key_areas": ["oncology"]},
        "workflow_plan": {"iterations": 2},
        "config_synthesis": {"tone": "concise"},
        "performance_assessment": {},
        "adjustment_recommendations": [],
        "output_preparation": {},
    }
    state["orchestrator_state"] = {"previous_top_elo": 1320, "pool_size": 4}
    state["supervisor_decision_provenance"] = "model"
    state["termination_reason"] = "satisfied_completion"
    state["task_history"] = [
        {
            "task_type": "generate",
            "status": "queued",
            "reason": "Supervisor selected generate from live state: "
            "0 hypotheses, 0 reviewed, 0 committed matches, "
            "iteration 1.",
            "iteration": 1,
            "termination_reason": None,
            "priority": 50,
            "planner_reason": "Seed the initial hypothesis pool.",
        },
        {
            "task_type": "rank",
            "status": "queued",
            "reason": "Supervisor selected rank from live state: "
            "2 hypotheses, 2 reviewed, 0 committed matches, "
            "iteration 1.",
            "iteration": 1,
            "termination_reason": None,
            "priority": 40,
            "planner_reason": "Establish an initial ordering.",
        },
        {
            "task_type": "terminate",
            "status": "completed",
            "reason": "Supervisor selected terminate from live state: "
            "2 hypotheses, 2 reviewed, 1 committed matches, "
            "iteration 1.",
            "iteration": 1,
            "termination_reason": "satisfied_completion",
            "priority": 0,
            "planner_reason": "Budget exhausted with a stable ranking.",
        },
    ]
    return state


# --- store round-trip --------------------------------------------------


def test_save_and_get_plan_round_trip(isolated_db: str) -> None:
    run = store.create_run("sp goal", "standard", "mock", {})
    guidance = {"workflow_plan": {"iterations": 2}}

    store.save_supervisor_plan(
        store.NewSupervisorPlan(
            run_id=run.id,
            guidance=guidance,
            termination_reason="satisfied_completion",
            decision_provenance="model",
            orchestrator_state={"pool_size": 4},
        ),
        db_path=isolated_db,
    )
    plan = store.get_supervisor_plan(run.id, db_path=isolated_db)

    assert plan is not None
    assert plan["plan"] == guidance
    assert plan["orchestrator_state"] == {"pool_size": 4}
    assert plan["termination_reason"] == "satisfied_completion"
    assert plan["decision_provenance"] == "model"


def test_save_plan_upserts_rather_than_duplicates(isolated_db: str) -> None:
    run = store.create_run("sp goal", "standard", "mock", {})
    store.save_supervisor_plan(
        store.NewSupervisorPlan(
            run_id=run.id,
            guidance={"workflow_plan": {}},
            termination_reason=None,
            decision_provenance="model",
            orchestrator_state={},
        ),
        db_path=isolated_db,
    )
    store.save_supervisor_plan(
        store.NewSupervisorPlan(
            run_id=run.id,
            guidance={"workflow_plan": {"iterations": 3}},
            termination_reason="satisfied_completion",
            decision_provenance="hard_invariant",
            orchestrator_state={"pool_size": 8},
        ),
        db_path=isolated_db,
    )

    with store_db.connect(isolated_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM supervisor_plan WHERE run_id=?", (run.id,)
        ).fetchone()[0]
    assert count == 1
    plan = store.get_supervisor_plan(run.id, db_path=isolated_db)
    assert plan is not None
    assert plan["plan"] == {"workflow_plan": {"iterations": 3}}
    assert plan["decision_provenance"] == "hard_invariant"


def test_get_plan_returns_none_before_finalize(isolated_db: str) -> None:
    run = store.create_run("sp goal", "standard", "mock", {})
    assert store.get_supervisor_plan(run.id, db_path=isolated_db) is None


def test_replace_and_list_allocations_round_trip(isolated_db: str) -> None:
    run = store.create_run("sp goal", "standard", "mock", {})
    allocations = [
        {
            "task_type": "generate",
            "status": "queued",
            "reason": "first",
            "iteration": 1,
        },
        {
            "task_type": "rank",
            "status": "queued",
            "reason": "second",
            "iteration": 1,
            "priority": 40,
            "planner_reason": "raw model rationale",
        },
    ]

    store.replace_supervisor_allocations(
        run.id, allocations, db_path=isolated_db
    )
    rows = store.list_supervisor_allocations(run.id, db_path=isolated_db)

    assert [r["task_type"] for r in rows] == ["generate", "rank"]
    assert [r["seq"] for r in rows] == [0, 1]
    assert rows[1]["priority"] == 40
    assert rows[1]["planner_reason"] == "raw model rationale"


def test_replace_allocations_clears_prior_rows(isolated_db: str) -> None:
    """A second replace fully supersedes the first -- no accumulation."""
    run = store.create_run("sp goal", "standard", "mock", {})
    store.replace_supervisor_allocations(
        run.id,
        [
            {
                "task_type": "generate",
                "status": "queued",
                "reason": "first",
                "iteration": 1,
            }
        ],
        db_path=isolated_db,
    )
    store.replace_supervisor_allocations(
        run.id,
        [
            {
                "task_type": "terminate",
                "status": "completed",
                "reason": "done",
                "iteration": 1,
            }
        ],
        db_path=isolated_db,
    )

    rows = store.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [r["task_type"] for r in rows] == ["terminate"]


def test_allocations_are_scoped_per_run(isolated_db: str) -> None:
    run_a = store.create_run("goal a", "standard", "mock", {})
    run_b = store.create_run("goal b", "standard", "mock", {})
    store.replace_supervisor_allocations(
        run_a.id,
        [
            {
                "task_type": "generate",
                "status": "queued",
                "reason": "only a",
                "iteration": 1,
            }
        ],
        db_path=isolated_db,
    )

    assert (
        store.list_supervisor_allocations(run_b.id, db_path=isolated_db) == []
    )
    assert (
        len(store.list_supervisor_allocations(run_a.id, db_path=isolated_db))
        == 1
    )


def test_run_deletion_cascades_to_supervisor_tables(isolated_db: str) -> None:
    run = store.create_run("sp goal", "standard", "mock", {})
    store.save_supervisor_plan(
        store.NewSupervisorPlan(
            run_id=run.id,
            guidance={"workflow_plan": {}},
            termination_reason=None,
            decision_provenance="model",
            orchestrator_state={},
        ),
        db_path=isolated_db,
    )
    store.replace_supervisor_allocations(
        run.id,
        [
            {
                "task_type": "generate",
                "status": "queued",
                "reason": "r",
                "iteration": 1,
            }
        ],
        db_path=isolated_db,
    )

    with store.connect(isolated_db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM runs WHERE id = ?", (run.id,))

    assert store.get_supervisor_plan(run.id, db_path=isolated_db) is None
    assert store.list_supervisor_allocations(run.id, db_path=isolated_db) == []


# --- real drain wiring ---------------------------------------------------


def test_finalize_persists_supervisor_plan_and_allocations(
    isolated_db: str,
) -> None:
    """A real finalize drain persists the plan durably.

    This must hold independent of the checkpoint blob.
    """
    run = store.create_run("sp e2e goal", "standard", "mock", {})
    final_state = _plan_final_state()

    _persist_and_finalize(run, final_state, isolated_db)

    plan = store.get_supervisor_plan(run.id, db_path=isolated_db)
    assert plan is not None
    assert plan["plan"]["workflow_plan"] == {"iterations": 2}
    assert plan["decision_provenance"] == "model"
    assert plan["termination_reason"] == "satisfied_completion"
    assert plan["orchestrator_state"] == {
        "previous_top_elo": 1320,
        "pool_size": 4,
    }

    allocations = store.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == [
        "generate",
        "rank",
        "terminate",
    ]
    assert allocations[-1]["termination_reason"] == "satisfied_completion"
    assert "2 hypotheses" in allocations[-1]["reason"]


def test_re_finalize_replaces_rather_than_accumulates(
    isolated_db: str,
) -> None:
    run = store.create_run("sp goal", "standard", "mock", {})
    final_state = _plan_final_state()

    _persist_and_finalize(run, final_state, isolated_db)
    first = store.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert len(first) == 3

    # A resumed run's re-finalize is exercised at the persistence layer
    # directly, the way test_store_knowledge_facts does for the same reason
    # (finalize_report itself no-ops on an already-published run).

    _persist(run_id=run.id, final_state=final_state, db_path=isolated_db)
    second = store.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert len(second) == 3


async def test_supervisor_plan_endpoint_returns_persisted_rows(
    isolated_db: str,
) -> None:
    from app.runs.collections import get_supervisor_plan

    run = store.create_run("sp goal", "standard", "mock", {})
    store.save_supervisor_plan(
        store.NewSupervisorPlan(
            run_id=run.id,
            guidance={"workflow_plan": {"iterations": 1}},
            termination_reason="satisfied_completion",
            decision_provenance="model",
            orchestrator_state={},
        ),
        db_path=isolated_db,
    )
    store.replace_supervisor_allocations(
        run.id,
        [
            {
                "task_type": "generate",
                "status": "queued",
                "reason": "r",
                "iteration": 1,
            }
        ],
        db_path=isolated_db,
    )

    result = await get_supervisor_plan(run.id)

    assert result["plan"]["plan"] == {"workflow_plan": {"iterations": 1}}
    assert len(result["allocations"]) == 1
    assert result["allocations"][0]["task_type"] == "generate"


# --- migration against an old-schema database ----------------------------


def test_new_tables_come_up_against_a_pre_existing_database(
    isolated_db: str,
) -> None:
    """Connecting to a database that predates these tables creates them.

    Mirrors ``test_db_migration_on_volume.py``: builds a minimal "ancient"
    database (just the ``runs`` table, no ``supervisor_plan``/
    ``supervisor_allocations``) the way a populated production volume would
    look before this change, then asserts the ordinary store connection path
    creates both tables and the allocation-ledger index cleanly -- new
    ``CREATE TABLE``/``CREATE INDEX ... IF NOT EXISTS`` statements, not an
    ``ALTER`` a stale index could race.
    """
    raw = sqlite3.connect(isolated_db)
    try:
        raw.execute(
            "CREATE TABLE runs ("
            "id TEXT PRIMARY KEY, research_goal TEXT NOT NULL, "
            "profile TEXT NOT NULL, status TEXT NOT NULL, "
            "provider TEXT NOT NULL, config_json TEXT NOT NULL, "
            "client_id TEXT NOT NULL DEFAULT '', "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL, "
            "completed_at REAL, error TEXT, llm_backend TEXT)"
        )
        raw.execute(
            "INSERT INTO runs (id, research_goal, profile, status, "
            "provider, config_json, client_id, created_at, updated_at) "
            "VALUES ('legacy-run', 'legacy goal', 'standard', 'completed', "
            "'engine', '{}', 'legacy-client', 1, 1)"
        )
        raw.commit()
    finally:
        raw.close()

    # Any store call establishes the connection and runs _init_schema.
    run = store.get_run("legacy-run", db_path=isolated_db)
    assert run is not None

    with store_db.connect(isolated_db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "supervisor_plan" in tables
        assert "supervisor_allocations" in tables
        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(supervisor_allocations)")
        }
        assert "idx_sup_alloc_run" in indexes

    # And the new tables are actually writable against the migrated file.
    store.save_supervisor_plan(
        store.NewSupervisorPlan(
            run_id="legacy-run",
            guidance={"workflow_plan": {}},
            termination_reason=None,
            decision_provenance="model",
            orchestrator_state={},
        ),
        db_path=isolated_db,
    )
    plan = store.get_supervisor_plan("legacy-run", db_path=isolated_db)
    assert plan is not None


# Incremental Supervisor-ledger persistence at checkpoint boundaries (E19).
#
# ``test_store_supervisor_plan.py`` covers the finalize-time drain -- the
# happy path where a run completes. This module covers the gap finalize alone
# leaves open: a run that fails, is cancelled, or is safety-blocked never
# reaches finalize, so ``store.save_checkpoint`` itself must carry the ledger
# forward at every node-task commit boundary (see
# ``app.store.supervisor_plan.sync_supervisor_ledger_from_checkpoint``, called
# from ``app.store.checkpoints.save_checkpoint``).


def _checkpoint_state(
    *,
    task_history: list[dict[str, Any]] | None = None,
    guidance: dict[str, Any] | None = None,
    orchestrator_state: dict[str, Any] | None = None,
    decision_provenance: str | None = None,
    termination_reason: str | None = None,
) -> dict[str, Any]:
    """Build a ``NewCheckpoint.state`` envelope shaped like the real one.

    Mirrors ``engine_tasks/support.py``'s ``{"provider": ..., **envelope}``
    shape, where ``envelope["state"]`` holds the plain ``WorkflowState``
    fields (see ``co_scientist.checkpoint.serialize_workflow_state``).
    """
    return {
        "provider": "engine",
        "version": 1,
        "last_event_seq": 0,
        "state": {
            "task_history": task_history or [],
            "supervisor_guidance": guidance or {},
            "orchestrator_state": orchestrator_state or {},
            "supervisor_decision_provenance": decision_provenance,
            "termination_reason": termination_reason,
        },
    }


def _task(
    task_type: str, iteration: int = 1, **overrides: Any
) -> dict[str, Any]:
    return {
        "task_type": task_type,
        "status": "queued",
        "reason": f"Supervisor selected {task_type} from live state.",
        "iteration": iteration,
        **overrides,
    }


_GUIDANCE = {"workflow_plan": {"iterations": 2}}


def test_save_checkpoint_persists_ledger_without_finalize(
    isolated_db: str,
) -> None:
    """A checkpoint alone -- no finalize, no drain -- populates the ledger."""
    run = store.create_run("goal", "standard", "mock", {})
    assert store.get_supervisor_plan(run.id, db_path=isolated_db) is None

    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="engine_task:t1",
            schema_version=1,
            last_event_seq=3,
            state=_checkpoint_state(
                task_history=[_task("generate")],
                guidance=_GUIDANCE,
                orchestrator_state={"pool_size": 4},
                decision_provenance="model",
            ),
        ),
        db_path=isolated_db,
    )

    allocations = store.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == ["generate"]

    plan = store.get_supervisor_plan(run.id, db_path=isolated_db)
    assert plan is not None
    assert plan["plan"] == _GUIDANCE
    assert plan["termination_reason"] is None  # run has not ended


def test_ledger_grows_across_successive_checkpoints(isolated_db: str) -> None:
    """Each later checkpoint's larger task_history extends the ledger."""
    run = store.create_run("goal", "standard", "mock", {})

    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="engine_task:t1",
            schema_version=1,
            last_event_seq=1,
            state=_checkpoint_state(
                task_history=[_task("generate")], guidance=_GUIDANCE
            ),
        ),
        db_path=isolated_db,
    )
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="engine_task:t2",
            schema_version=1,
            last_event_seq=2,
            state=_checkpoint_state(
                task_history=[_task("generate"), _task("rank")],
                guidance=_GUIDANCE,
                decision_provenance="model",
            ),
        ),
        db_path=isolated_db,
    )

    allocations = store.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == ["generate", "rank"]


def test_shorter_later_checkpoint_never_shrinks_the_ledger(
    isolated_db: str,
) -> None:
    """A checkpoint with less history than already stored is a no-op.

    Guards against a superseded or out-of-order commit erasing what a
    previous, further-along checkpoint had already recorded.
    """
    run = store.create_run("goal", "standard", "mock", {})
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="engine_task:t1",
            schema_version=1,
            last_event_seq=1,
            state=_checkpoint_state(
                task_history=[_task("generate"), _task("rank")],
                guidance=_GUIDANCE,
            ),
        ),
        db_path=isolated_db,
    )

    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="engine_task:stale",
            schema_version=1,
            last_event_seq=1,
            state=_checkpoint_state(
                task_history=[_task("generate")], guidance=_GUIDANCE
            ),
        ),
        db_path=isolated_db,
    )

    allocations = store.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == ["generate", "rank"]


def test_equal_length_checkpoint_is_a_no_op(isolated_db: str) -> None:
    """A checkpoint repeating the same task_history writes nothing new.

    This is the common case: item-level checkpoints (fan-out items, ranking
    matches) carry the same task_history as the last orchestrator decision,
    so the ledger's write frequency tracks orchestrator decisions, not
    checkpoint count.
    """
    run = store.create_run("goal", "standard", "mock", {})
    state = _checkpoint_state(
        task_history=[_task("generate")], guidance=_GUIDANCE
    )
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="t1", schema_version=1, last_event_seq=1, state=state
        ),
        db_path=isolated_db,
    )
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="t2", schema_version=1, last_event_seq=2, state=state
        ),
        db_path=isolated_db,
    )

    with store_db.connect(isolated_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM supervisor_allocations WHERE run_id=?",
            (run.id,),
        ).fetchone()[0]
    assert count == 1


def test_no_guidance_yet_persists_nothing(isolated_db: str) -> None:
    """A checkpoint before the Supervisor has run leaves no plan row."""
    run = store.create_run("goal", "standard", "mock", {})
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="engine.bootstrap",
            schema_version=1,
            last_event_seq=0,
            state=_checkpoint_state(),
        ),
        db_path=isolated_db,
    )

    assert store.get_supervisor_plan(run.id, db_path=isolated_db) is None
    assert store.list_supervisor_allocations(run.id, db_path=isolated_db) == []


def test_legacy_checkpoint_shape_is_a_no_op(isolated_db: str) -> None:
    """A checkpoint state without a nested WorkflowState is safely ignored.

    Some checkpoint call sites (and every test in test_store_checkpoints.py)
    pass a synthetic ``state`` dict with no ``"state"`` sub-key at all --
    the sync must not raise on that shape.
    """
    run = store.create_run("goal", "standard", "mock", {})
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="s", schema_version=1, last_event_seq=1, state={"round": 1}
        ),
        db_path=isolated_db,
    )

    assert store.get_supervisor_plan(run.id, db_path=isolated_db) is None
    assert store.list_supervisor_allocations(run.id, db_path=isolated_db) == []


def test_finalize_remains_authoritative_after_incremental_writes(
    isolated_db: str,
) -> None:
    """Finalize's terminal write still lands cleanly over incremental ones."""
    from tests._drain_helpers import _persist

    run = store.create_run("goal", "standard", "mock", {})
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="engine_task:t1",
            schema_version=1,
            last_event_seq=1,
            state=_checkpoint_state(
                task_history=[_task("generate")],
                guidance=_GUIDANCE,
                decision_provenance="model",
            ),
        ),
        db_path=isolated_db,
    )
    assert store.get_supervisor_plan(run.id, db_path=isolated_db) is not None

    final_state: dict[str, Any] = {
        "hypotheses": [],
        "articles": [],
        "tournament_matchups": [],
        "proximity_graph": {},
        "meta_review": {},
        "evolution_details": [],
        "supervisor_guidance": _GUIDANCE,
        "orchestrator_state": {"pool_size": 4},
        "supervisor_decision_provenance": "hard_invariant",
        "termination_reason": "satisfied_completion",
        "task_history": [
            _task("generate"),
            _task("terminate", status="completed"),
        ],
    }
    _persist(run_id=run.id, final_state=final_state, db_path=isolated_db)

    plan = store.get_supervisor_plan(run.id, db_path=isolated_db)
    assert plan is not None
    assert plan["termination_reason"] == "satisfied_completion"
    assert plan["decision_provenance"] == "hard_invariant"
    allocations = store.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == ["generate", "terminate"]

from __future__ import annotations

import pathlib
import sqlite3
from typing import Any

import pytest

from app.store import checkpoints, db, reports, runs
from app.store import db as _store_db
from app.store import db as store_db
from app.store import retrieval_calls as retrieval
from app.store import runs_views as views
from app.store import supervisor_plan as plans
from app.store.checkpoints import NewCheckpoint
from app.store.runs import RunCreateOptions
from app.store.supervisor_plan import NewSupervisorPlan
from tests._drain_helpers import (
    _final_state_with_features,
    _persist,
    _persist_and_finalize,
)

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
    run = runs.create_run(
        "Metrics goal",
        "default",
        "mock",
        {},
        RunCreateOptions(db_path=db_path),
    )
    return run.id


def test_metrics_roundtrip(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    retrieval.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    assert retrieval.get_run_metrics(run_id, db_path=isolated_db) == _METRICS


def test_metrics_absent_returns_none(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    assert retrieval.get_run_metrics(run_id, db_path=isolated_db) is None


def test_metrics_upsert_replaces_previous_row(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    retrieval.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    replacement = {**_METRICS, "llm_calls": 99}
    retrieval.save_run_metrics(run_id, replacement, db_path=isolated_db)
    saved = retrieval.get_run_metrics(run_id, db_path=isolated_db)
    assert saved is not None
    assert saved["llm_calls"] == 99


def test_clear_run_derived_data_removes_metrics(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    retrieval.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    views.clear_run_derived_data(run_id, db_path=isolated_db)
    assert retrieval.get_run_metrics(run_id, db_path=isolated_db) is None


# Fresh schemas hide migration ordering bugs; populated legacy fixtures exercise
# the actual upgrade path.


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
    # Schema indexes cannot reference columns until legacy migration adds them.
    path = _old_shape_db(tmp_path)

    with db.connect(path) as conn:
        conn.execute("SELECT client_id FROM app_logs").fetchall()

    assert "client_id" in _columns(path, "app_logs")
    assert "idx_app_logs_client" in _indexes(path, "app_logs")


def test_connect_is_idempotent_over_an_upgraded_database(
    tmp_path: object,
) -> None:
    path = _old_shape_db(tmp_path)
    with db.connect(path):
        pass
    db._initialized.discard(path)

    with db.connect(path) as conn:
        conn.execute("SELECT client_id FROM app_logs").fetchall()

    assert "idx_app_logs_client" in _indexes(path, "app_logs")


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
    # Missing legacy fallback markers mean unknown pre-marker provenance, not
    # known scripted output.
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
    # Legacy tables need ALTER for search links; CREATE IF NOT EXISTS does not
    # add columns.
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
        conn.execute("SELECT COUNT(*) FROM retrieval_calls").fetchone()

    assert "retrieval_call_id" in _columns(path, "evidence")
    assert [row[0] for row in rows] == [None]


def test_connect_upgrades_evidence_for_retraction(tmp_path: object) -> None:
    # Legacy evidence cannot establish historical retraction; additive columns
    # initially remain unknown.
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
    # Additive transcript columns preserve existing rationale without table
    # rebuild or VACUUM.
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


def _insert_legacy_report_row(
    db_path: str,
    run_id: str,
    report_id: str,
    markdown_path: str | None,
    markdown_text_ranking: str | None = None,
) -> None:
    with _store_db.connect(db_path) as conn:
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


def test_reports_round_trip_full_markdown_through_database(
    isolated_db: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    run = runs.create_run(
        "report rt",
        "default",
        "mock",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    saved = reports.save_report(
        run.id, {"k": "v"}, "# Hello\nbody", db_path=isolated_db
    )
    md = reports.read_report_markdown(run.id, db_path=isolated_db)
    assert md == "# Hello\nbody"
    rep = reports.get_latest_report(run.id, db_path=isolated_db)
    assert rep and rep["payload"] == {"k": "v"}
    assert rep["id"] == saved["id"]
    assert rep["markdown_text"] == "# Hello\nbody"
    assert rep["markdown_path"] == ""
    assert not (tmp_path / "reports").exists()


def test_read_report_markdown_falls_back_to_disk_when_db_text_missing(
    isolated_db: str, tmp_path: pathlib.Path
) -> None:
    run = runs.create_run(
        "disk fallback goal",
        "default",
        "mock",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    md_file = tmp_path / "on_disk.md"
    md_file.write_text("# From disk", encoding="utf-8")

    _insert_legacy_report_row(
        isolated_db, run.id, "report-disk-1", str(md_file)
    )

    text = reports.read_report_markdown(run.id, db_path=isolated_db)
    assert text == "# From disk"


def test_read_report_markdown_none_without_db_text_or_path(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "no source goal",
        "default",
        "mock",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    _insert_legacy_report_row(isolated_db, run.id, "report-disk-2", None)

    assert reports.read_report_markdown(run.id, db_path=isolated_db) is None


def test_get_latest_report_and_read_markdown_none_without_any_report(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "no report goal",
        "default",
        "mock",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    assert reports.get_latest_report(run.id, db_path=isolated_db) is None
    assert reports.read_report_markdown(run.id, db_path=isolated_db) is None


def test_read_report_markdown_none_when_disk_file_missing(
    isolated_db: str, tmp_path: pathlib.Path
) -> None:
    run = runs.create_run(
        "missing file goal",
        "default",
        "mock",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    missing_path = tmp_path / "does_not_exist.md"

    _insert_legacy_report_row(
        isolated_db, run.id, "report-disk-3", str(missing_path)
    )

    assert reports.read_report_markdown(run.id, db_path=isolated_db) is None


def test_save_report_never_writes_the_legacy_ranking_column(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "no ranking write goal",
        "default",
        "mock",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    reports.save_report(
        run.id, {"k": "v"}, "# Goal Report", db_path=isolated_db
    )

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["markdown_text_ranking"] is None


def test_read_report_markdown_appends_a_legacy_split_window_row(
    isolated_db: str,
) -> None:
    # Legacy split reports carry ranking text in another column; merging must
    # preserve both halves.
    run = runs.create_run(
        "split window goal",
        "default",
        "mock",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    _insert_legacy_report_row(
        isolated_db,
        run.id,
        "report-split-window",
        None,
        markdown_text_ranking="# ranking half",
    )
    with _store_db.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE reports SET markdown_text=? WHERE id=?",
            ("# overview half", "report-split-window"),
        )

    text = reports.read_report_markdown(run.id, db_path=isolated_db)
    assert text == "# overview half\n\n# ranking half"


def _plan_final_state() -> dict[str, object]:
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


def test_save_and_get_plan_round_trip(isolated_db: str) -> None:
    run = runs.create_run("sp goal", "standard", "mock", {})
    guidance = {"workflow_plan": {"iterations": 2}}

    plans.save_supervisor_plan(
        NewSupervisorPlan(
            run_id=run.id,
            guidance=guidance,
            termination_reason="satisfied_completion",
            decision_provenance="model",
            orchestrator_state={"pool_size": 4},
        ),
        db_path=isolated_db,
    )
    plan = plans.get_supervisor_plan(run.id, db_path=isolated_db)

    assert plan is not None
    assert plan["plan"] == guidance
    assert plan["orchestrator_state"] == {"pool_size": 4}
    assert plan["termination_reason"] == "satisfied_completion"
    assert plan["decision_provenance"] == "model"


def test_save_plan_upserts_rather_than_duplicates(isolated_db: str) -> None:
    run = runs.create_run("sp goal", "standard", "mock", {})
    plans.save_supervisor_plan(
        NewSupervisorPlan(
            run_id=run.id,
            guidance={"workflow_plan": {}},
            termination_reason=None,
            decision_provenance="model",
            orchestrator_state={},
        ),
        db_path=isolated_db,
    )
    plans.save_supervisor_plan(
        NewSupervisorPlan(
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
    plan = plans.get_supervisor_plan(run.id, db_path=isolated_db)
    assert plan is not None
    assert plan["plan"] == {"workflow_plan": {"iterations": 3}}
    assert plan["decision_provenance"] == "hard_invariant"


def test_get_plan_returns_none_before_finalize(isolated_db: str) -> None:
    run = runs.create_run("sp goal", "standard", "mock", {})
    assert plans.get_supervisor_plan(run.id, db_path=isolated_db) is None


def test_replace_and_list_allocations_round_trip(isolated_db: str) -> None:
    run = runs.create_run("sp goal", "standard", "mock", {})
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

    plans.replace_supervisor_allocations(
        run.id, allocations, db_path=isolated_db
    )
    rows = plans.list_supervisor_allocations(run.id, db_path=isolated_db)

    assert [r["task_type"] for r in rows] == ["generate", "rank"]
    assert [r["seq"] for r in rows] == [0, 1]
    assert rows[1]["priority"] == 40
    assert rows[1]["planner_reason"] == "raw model rationale"


def test_replace_allocations_clears_prior_rows(isolated_db: str) -> None:
    run = runs.create_run("sp goal", "standard", "mock", {})
    plans.replace_supervisor_allocations(
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
    plans.replace_supervisor_allocations(
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

    rows = plans.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [r["task_type"] for r in rows] == ["terminate"]


def test_allocations_are_scoped_per_run(isolated_db: str) -> None:
    run_a = runs.create_run("goal a", "standard", "mock", {})
    run_b = runs.create_run("goal b", "standard", "mock", {})
    plans.replace_supervisor_allocations(
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
        plans.list_supervisor_allocations(run_b.id, db_path=isolated_db) == []
    )
    assert (
        len(plans.list_supervisor_allocations(run_a.id, db_path=isolated_db))
        == 1
    )


def test_run_deletion_cascades_to_supervisor_tables(isolated_db: str) -> None:
    run = runs.create_run("sp goal", "standard", "mock", {})
    plans.save_supervisor_plan(
        NewSupervisorPlan(
            run_id=run.id,
            guidance={"workflow_plan": {}},
            termination_reason=None,
            decision_provenance="model",
            orchestrator_state={},
        ),
        db_path=isolated_db,
    )
    plans.replace_supervisor_allocations(
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

    with _store_db.connect(isolated_db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM runs WHERE id = ?", (run.id,))

    assert plans.get_supervisor_plan(run.id, db_path=isolated_db) is None
    assert plans.list_supervisor_allocations(run.id, db_path=isolated_db) == []


def test_finalize_persists_supervisor_plan_and_allocations(
    isolated_db: str,
) -> None:
    run = runs.create_run("sp e2e goal", "standard", "mock", {})
    final_state = _plan_final_state()

    _persist_and_finalize(run, final_state, isolated_db)

    plan = plans.get_supervisor_plan(run.id, db_path=isolated_db)
    assert plan is not None
    assert plan["plan"]["workflow_plan"] == {"iterations": 2}
    assert plan["decision_provenance"] == "model"
    assert plan["termination_reason"] == "satisfied_completion"
    assert plan["orchestrator_state"] == {
        "previous_top_elo": 1320,
        "pool_size": 4,
    }

    allocations = plans.list_supervisor_allocations(run.id, db_path=isolated_db)
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
    run = runs.create_run("sp goal", "standard", "mock", {})
    final_state = _plan_final_state()

    _persist_and_finalize(run, final_state, isolated_db)
    first = plans.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert len(first) == 3

    _persist(run_id=run.id, final_state=final_state, db_path=isolated_db)
    second = plans.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert len(second) == 3


async def test_supervisor_plan_endpoint_returns_persisted_rows(
    isolated_db: str,
) -> None:
    from app.runs.collections import get_supervisor_plan

    run = runs.create_run("sp goal", "standard", "mock", {})
    plans.save_supervisor_plan(
        NewSupervisorPlan(
            run_id=run.id,
            guidance={"workflow_plan": {"iterations": 1}},
            termination_reason="satisfied_completion",
            decision_provenance="model",
            orchestrator_state={},
        ),
        db_path=isolated_db,
    )
    plans.replace_supervisor_allocations(
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


def test_new_tables_come_up_against_a_pre_existing_database(
    isolated_db: str,
) -> None:
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

    run = runs.get_run("legacy-run", db_path=isolated_db)
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

    plans.save_supervisor_plan(
        NewSupervisorPlan(
            run_id="legacy-run",
            guidance={"workflow_plan": {}},
            termination_reason=None,
            decision_provenance="model",
            orchestrator_state={},
        ),
        db_path=isolated_db,
    )
    plan = plans.get_supervisor_plan("legacy-run", db_path=isolated_db)
    assert plan is not None


# Failure/cancellation can skip finalize, so checkpoint commits must persist
# supervisor provenance too.


def _checkpoint_state(
    *,
    task_history: list[dict[str, Any]] | None = None,
    guidance: dict[str, Any] | None = None,
    orchestrator_state: dict[str, Any] | None = None,
    decision_provenance: str | None = None,
    termination_reason: str | None = None,
) -> dict[str, Any]:
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
    run = runs.create_run("goal", "standard", "mock", {})
    assert plans.get_supervisor_plan(run.id, db_path=isolated_db) is None

    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
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

    allocations = plans.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == ["generate"]

    plan = plans.get_supervisor_plan(run.id, db_path=isolated_db)
    assert plan is not None
    assert plan["plan"] == _GUIDANCE
    assert plan["termination_reason"] is None


def test_ledger_grows_across_successive_checkpoints(isolated_db: str) -> None:
    run = runs.create_run("goal", "standard", "mock", {})

    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="engine_task:t1",
            schema_version=1,
            last_event_seq=1,
            state=_checkpoint_state(
                task_history=[_task("generate")], guidance=_GUIDANCE
            ),
        ),
        db_path=isolated_db,
    )
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
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

    allocations = plans.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == ["generate", "rank"]


def test_shorter_later_checkpoint_never_shrinks_the_ledger(
    isolated_db: str,
) -> None:
    # Older out-of-order checkpoints must not erase a more complete stored
    # ledger.
    run = runs.create_run("goal", "standard", "mock", {})
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
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

    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="engine_task:stale",
            schema_version=1,
            last_event_seq=1,
            state=_checkpoint_state(
                task_history=[_task("generate")], guidance=_GUIDANCE
            ),
        ),
        db_path=isolated_db,
    )

    allocations = plans.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == ["generate", "rank"]


def test_equal_length_checkpoint_is_a_no_op(isolated_db: str) -> None:
    # Repeated item checkpoints carry unchanged history; ledger writes track
    # decisions rather than every commit.
    run = runs.create_run("goal", "standard", "mock", {})
    state = _checkpoint_state(
        task_history=[_task("generate")], guidance=_GUIDANCE
    )
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="t1", schema_version=1, last_event_seq=1, state=state
        ),
        db_path=isolated_db,
    )
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
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
    run = runs.create_run("goal", "standard", "mock", {})
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="engine.bootstrap",
            schema_version=1,
            last_event_seq=0,
            state=_checkpoint_state(),
        ),
        db_path=isolated_db,
    )

    assert plans.get_supervisor_plan(run.id, db_path=isolated_db) is None
    assert plans.list_supervisor_allocations(run.id, db_path=isolated_db) == []


def test_legacy_checkpoint_shape_is_a_no_op(isolated_db: str) -> None:
    run = runs.create_run("goal", "standard", "mock", {})
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="s", schema_version=1, last_event_seq=1, state={"round": 1}
        ),
        db_path=isolated_db,
    )

    assert plans.get_supervisor_plan(run.id, db_path=isolated_db) is None
    assert plans.list_supervisor_allocations(run.id, db_path=isolated_db) == []


def test_finalize_remains_authoritative_after_incremental_writes(
    isolated_db: str,
) -> None:
    from tests._drain_helpers import _persist

    run = runs.create_run("goal", "standard", "mock", {})
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
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
    assert plans.get_supervisor_plan(run.id, db_path=isolated_db) is not None

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

    plan = plans.get_supervisor_plan(run.id, db_path=isolated_db)
    assert plan is not None
    assert plan["termination_reason"] == "satisfied_completion"
    assert plan["decision_provenance"] == "hard_invariant"
    allocations = plans.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == ["generate", "terminate"]

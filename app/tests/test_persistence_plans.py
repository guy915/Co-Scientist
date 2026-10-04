from __future__ import annotations

import pathlib
import sqlite3
import subprocess
import sys
from typing import Any

import pytest

from app.store import checkpoints, db, hypotheses, records, reports, runs
from app.store import db as _store_db
from app.store import db as store_db
from app.store import retrieval_calls as retrieval
from app.store import runs_views as views
from app.store import supervisor_plan as plans
from app.store.checkpoints import NewCheckpoint
from app.store.hypotheses import NewHypothesis
from app.store.records import (
    NewEvidence,
    NewMatch,
    NewReview,
    NewSafetyDecision,
)
from app.store.runs import RunCreateOptions
from app.store.schema import SCHEMA
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


def _columns(path: str, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_current_schema_supports_scientific_records_without_migrations() -> (
    None
):
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO runs(id,research_goal,profile,status,provider,"
            "config_json,created_at,updated_at) "
            "VALUES('run','goal','default','completed','mock','{}',1,1)"
        )
        hypothesis_id = hypotheses.add_hypothesis(
            NewHypothesis(
                run_id="run",
                title="Current idea",
                statement="Mechanism",
                author="Scientist",
                introduction="Context",
                recent_findings="Finding",
                safety_and_toxicity="Safety",
            ),
            conn=conn,
        )
        hypothesis = hypotheses.get_hypothesis(hypothesis_id, conn=conn)
        assert hypothesis is not None
        assert (
            hypothesis["author"],
            hypothesis["introduction"],
            hypothesis["recent_findings"],
            hypothesis["safety_and_toxicity"],
        ) == ("Scientist", "Context", "Finding", "Safety")
        records.add_review(
            NewReview(
                run_id="run",
                hypothesis_id=hypothesis_id,
                reviewer_agent="scientist",
                summary="Assessment",
                critique="Detail",
                author="Reviewer",
                verdict="supported",
                detail_json='{"depth":2}',
            ),
            conn=conn,
        )
        review = records.list_reviews("run", conn=conn)[0]
        assert (review["author"], review["verdict"], review["detail_json"]) == (
            "Reviewer",
            "supported",
            '{"depth":2}',
        )
        records.add_evidence(
            NewEvidence(run_id="run", title="Retracted source", retracted=True),
            conn=conn,
        )
        assert records.list_evidence("run", conn=conn)[0]["retracted"] is True
        records.add_match(
            NewMatch(
                run_id="run",
                iteration=1,
                winner_id=hypothesis_id,
                loser_id="other",
                winner_before=1200,
                winner_after=1212,
                loser_before=1200,
                loser_after=1188,
                rationale="Decision",
                debate_turns=3,
                debate_transcript="Discussion",
            ),
            conn=conn,
        )
        match = records.list_matches("run", conn=conn)[0]
        assert (match["debate_turns"], match["debate_transcript"]) == (
            3,
            "Discussion",
        )
        records.add_safety_decision(
            NewSafetyDecision(
                run_id="run",
                stage="review",
                decision="needs_review",
                reason="Check",
                matches=[],
                category="dual_use",
                policy_version="current",
                risk_domains=["biological"],
                requires_review=True,
                assessor="researcher",
            ),
            conn=conn,
        )
        assert tuple(
            conn.execute(
                "SELECT category,policy_version,risk_domains_json,"
                "requires_review,"
                "assessor FROM safety_decisions"
            ).fetchone()
        ) == ("dual_use", "current", '["biological"]', 1, "researcher")
        assert {"resolution", "resolved_by", "resolved_at"} <= {
            row["name"]
            for row in conn.execute("PRAGMA table_xinfo(safety_decisions)")
        }
        for table, column, default in [
            ("matches", "debate_turns", "1"),
            ("safety_decisions", "requires_review", "0"),
        ]:
            info = {
                row["name"]: row
                for row in conn.execute(f"PRAGMA table_xinfo({table})")
            }[column]
            assert (info["type"], info["notnull"], info["dflt_value"]) == (
                "INTEGER",
                1,
                default,
            )


def test_current_schema_preserves_usage_and_log_ownership_on_restart(
    tmp_path: pathlib.Path,
) -> None:
    path = str(tmp_path / "current-store.db")
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert {"idx_free_run_usage_client", "idx_app_logs_client"} <= indexes
        assert [
            row[2]
            for row in conn.execute(
                "PRAGMA index_info(idx_free_run_usage_client)"
            )
        ] == ["client_id", "created_at"]
        assert [
            row[2]
            for row in conn.execute("PRAGMA index_info(idx_app_logs_client)")
        ] == ["client_id", "id"]
        conn.execute("INSERT INTO free_run_usage VALUES('spent-run','owner',1)")
        conn.execute(
            "INSERT INTO app_logs(created_at,level,levelno,logger,message,"
            "client_id) VALUES(1,'INFO',20,'test','retained','owner')"
        )
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.store.db import connect; import sys; "
            "ctx=connect(sys.argv[1]); c=ctx.__enter__(); "
            "assert c.isolation_level is None; "
            "assert c.execute('PRAGMA journal_mode').fetchone()[0]=='wal'; "
            "assert c.execute('PRAGMA foreign_keys').fetchone()[0]==1; "
            "ctx.__exit__(None,None,None)",
            path,
        ],
        check=True,
    )
    with db.connect(path) as conn:
        assert tuple(
            conn.execute(
                "SELECT run_id,client_id,created_at FROM free_run_usage"
            ).fetchone()
        ) == ("spent-run", "owner", 1.0)
        assert tuple(
            conn.execute("SELECT message,client_id FROM app_logs").fetchone()
        ) == ("retained", "owner")
        assert not conn.execute(
            "PRAGMA foreign_key_list(free_run_usage)"
        ).fetchall()


def test_report_preserves_empty_markdown_and_uses_current_schema(
    isolated_db: str,
) -> None:
    run_id = _make_run(isolated_db)
    reports.save_report(run_id, {}, "", db_path=isolated_db)
    assert reports.read_report_markdown(run_id, db_path=isolated_db) == ""
    assert not {"markdown_path", "markdown_text_ranking"} & _columns(
        isolated_db, "reports"
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

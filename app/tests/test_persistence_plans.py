from __future__ import annotations

import pathlib
from typing import Any

import pytest

from app.store import db as _store_db
from app.store import db as store_db
from app.store import reports
from app.store import retrieval_calls as retrieval
from app.store import runs_views as views
from app.store import supervisor_plan as plans
from app.store.supervisor_plan import NewSupervisorPlan
from tests._drain_helpers import (
    _final_state_with_features,
    _persist,
    _persist_and_finalize,
)
from tests._store_helpers import seed_checkpoint, seed_run

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
    run = seed_run(
        "Metrics goal", profile="default", provider="mock", db_path=db_path
    )
    return run.id


def test_metrics_roundtrip_and_upsert(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    assert retrieval.get_run_metrics(run_id, db_path=isolated_db) is None

    retrieval.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    assert retrieval.get_run_metrics(run_id, db_path=isolated_db) == _METRICS

    retrieval.save_run_metrics(
        run_id, {**_METRICS, "llm_calls": 99}, db_path=isolated_db
    )
    saved = retrieval.get_run_metrics(run_id, db_path=isolated_db)
    assert saved is not None
    assert saved["llm_calls"] == 99


def test_clear_run_derived_data_removes_metrics(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    retrieval.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    views.clear_run_derived_data(run_id, db_path=isolated_db)
    assert retrieval.get_run_metrics(run_id, db_path=isolated_db) is None


def test_reports_round_trip_full_markdown_through_database(
    isolated_db: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    run = seed_run(
        "report rt", profile="default", provider="mock", db_path=isolated_db
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


def test_save_plan_upserts_rather_than_duplicates(isolated_db: str) -> None:
    run = seed_run("sp goal", provider="mock")
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


def test_replace_allocations_clears_prior_rows(isolated_db: str) -> None:
    run = seed_run("sp goal", provider="mock")
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


def test_run_deletion_cascades_to_supervisor_tables(isolated_db: str) -> None:
    run = seed_run("sp goal", provider="mock")
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
    run = seed_run("sp e2e goal", provider="mock")
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
    run = seed_run("goal", provider="mock")
    assert plans.get_supervisor_plan(run.id, db_path=isolated_db) is None

    seed_checkpoint(
        run.id,
        _checkpoint_state(
            task_history=[_task("generate")],
            guidance=_GUIDANCE,
            orchestrator_state={"pool_size": 4},
            decision_provenance="model",
        ),
        stage="engine_task:t1",
        last_event_seq=3,
        db_path=isolated_db,
    )

    allocations = plans.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == ["generate"]

    plan = plans.get_supervisor_plan(run.id, db_path=isolated_db)
    assert plan is not None
    assert plan["plan"] == _GUIDANCE
    assert plan["termination_reason"] is None


def test_shorter_later_checkpoint_never_shrinks_the_ledger(
    isolated_db: str,
) -> None:
    # Older out-of-order checkpoints must not erase a more complete stored
    # ledger.
    run = seed_run("goal", provider="mock")
    seed_checkpoint(
        run.id,
        _checkpoint_state(
            task_history=[_task("generate"), _task("rank")],
            guidance=_GUIDANCE,
        ),
        stage="engine_task:t1",
        last_event_seq=1,
        db_path=isolated_db,
    )

    seed_checkpoint(
        run.id,
        _checkpoint_state(task_history=[_task("generate")], guidance=_GUIDANCE),
        stage="engine_task:stale",
        last_event_seq=1,
        db_path=isolated_db,
    )

    allocations = plans.list_supervisor_allocations(run.id, db_path=isolated_db)
    assert [a["task_type"] for a in allocations] == ["generate", "rank"]


def test_equal_length_checkpoint_is_a_no_op(isolated_db: str) -> None:
    # Repeated item checkpoints carry unchanged history; ledger writes track
    # decisions rather than every commit.
    run = seed_run("goal", provider="mock")
    state = _checkpoint_state(
        task_history=[_task("generate")], guidance=_GUIDANCE
    )
    seed_checkpoint(
        run.id, state, stage="t1", last_event_seq=1, db_path=isolated_db
    )
    seed_checkpoint(
        run.id, state, stage="t2", last_event_seq=2, db_path=isolated_db
    )

    with store_db.connect(isolated_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM supervisor_allocations WHERE run_id=?",
            (run.id,),
        ).fetchone()[0]
    assert count == 1


def test_finalize_remains_authoritative_after_incremental_writes(
    isolated_db: str,
) -> None:

    run = seed_run("goal", provider="mock")
    seed_checkpoint(
        run.id,
        _checkpoint_state(
            task_history=[_task("generate")],
            guidance=_GUIDANCE,
            decision_provenance="model",
        ),
        stage="engine_task:t1",
        last_event_seq=1,
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

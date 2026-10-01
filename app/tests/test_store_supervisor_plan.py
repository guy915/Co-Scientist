"""Store round-trip, drain wiring, and migration coverage for E19.

Covers the durable Supervisor plan/allocation-ledger store I/O
(``save_supervisor_plan``/``get_supervisor_plan``,
``replace_supervisor_allocations``/``list_supervisor_allocations``), the
real drain wiring (a finalized run's checkpoint state actually reaches the
store), the collections endpoint, and -- per AGENTS.md's recorded trap --
that the new tables/index come up cleanly against a database built from a
schema that predates them, the way a populated production volume would be
migrated.
"""

from __future__ import annotations

import sqlite3

from app import store
from app.store import db as store_db
from tests._drain_helpers import (
    _final_state_with_features,
    _persist,
    _persist_and_finalize,
)


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

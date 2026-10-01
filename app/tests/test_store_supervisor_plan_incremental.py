"""Incremental Supervisor-ledger persistence at checkpoint boundaries (E19).

``test_store_supervisor_plan.py`` covers the finalize-time drain -- the
happy path where a run completes. This module covers the gap finalize alone
leaves open: a run that fails, is cancelled, or is safety-blocked never
reaches finalize, so ``store.save_checkpoint`` itself must carry the ledger
forward at every node-task commit boundary (see
``app.store.supervisor_plan.sync_supervisor_ledger_from_checkpoint``, called
from ``app.store.checkpoints.save_checkpoint``).
"""

from __future__ import annotations

from typing import Any

from app import store
from app.store import db as store_db


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

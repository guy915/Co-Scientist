"""Durable Supervisor plan and per-cycle allocation ledger (audit E19).

Store I/O for the ``supervisor_plan``/``supervisor_allocations`` tables
(schema in ``schema_supervisor_plan.py``): the Supervisor's research plan,
its terminal decision provenance and termination rationale (one row per
run), and the append-only ledger of every task the adaptive orchestrator
scheduled, with the observed statistics behind each decision (one row per
scheduled task). See ``app.engine_adapter.drain`` for how a run's final
checkpoint state is turned into these rows -- both write helpers here take
already-shaped plain dicts, the same way ``replace_knowledge_facts`` does,
so this module stays agnostic of the engine's ``WorkflowState`` shape.

Both tables are replaced wholesale at finalize, matching the
``knowledge_facts``/``matches`` idiom: a resumed run that finalizes again
reconstructs identical rows rather than accumulating duplicates.

A run that fails, is cancelled, or is safety-blocked never reaches
finalize, so ``sync_supervisor_ledger_from_checkpoint`` gives the ledger a
second, earlier way in: ``app.store.checkpoints.save_checkpoint`` calls it
on every checkpoint it writes -- node commits, fan-out planning commits,
paused-task commits -- so the ledger accumulates across the run's whole
life, not only at its end. It reuses the same replace-wholesale primitives
above, guarded so a checkpoint carrying less history than what is already
stored (a superseded or out-of-order commit) can never shrink the ledger.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn


@dataclass(frozen=True)
class NewSupervisorPlan:
    """A run's Supervisor plan and terminal scheduling state (audit E19).

    ``guidance`` is the Supervisor's ``supervisor_guidance`` dict -- the six
    planning blocks (research_goal_analysis, workflow_plan,
    config_synthesis, performance_assessment, adjustment_recommendations,
    output_preparation) serialized wholesale. ``termination_reason`` is why
    the workflow stopped (None if it has not -- a defensive case, since
    finalize only runs once the run has). ``decision_provenance`` is the
    latest allocation's source (model, hard invariant, or fallback).
    ``orchestrator_state`` is the final scheduler bookkeeping snapshot.
    """

    run_id: str
    guidance: dict[str, Any]
    termination_reason: str | None
    decision_provenance: str | None
    orchestrator_state: dict[str, Any]


def save_supervisor_plan(
    plan: NewSupervisorPlan,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Persist (or replace) a run's Supervisor plan and terminal state.

    Args:
        plan: The plan to persist (see :class:`NewSupervisorPlan`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    now = _now()
    with _use_conn(conn, db_path) as active:
        active.execute(
            "INSERT INTO supervisor_plan (run_id, plan_json, "
            "orchestrator_state_json, decision_provenance, "
            "termination_reason, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET "
            "plan_json=excluded.plan_json, "
            "orchestrator_state_json=excluded.orchestrator_state_json, "
            "decision_provenance=excluded.decision_provenance, "
            "termination_reason=excluded.termination_reason, "
            "updated_at=excluded.updated_at",
            (
                plan.run_id,
                json.dumps(plan.guidance),
                json.dumps(plan.orchestrator_state),
                plan.decision_provenance,
                plan.termination_reason,
                now,
                now,
            ),
        )


def get_supervisor_plan(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Return a run's persisted Supervisor plan, or None if not finalized.

    Args:
        run_id: Owning run.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        A dict with ``plan`` and ``orchestrator_state`` decoded from JSON,
        plus ``decision_provenance``/``termination_reason``, or None.
    """
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT * FROM supervisor_plan WHERE run_id=?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["plan"] = json.loads(result.pop("plan_json"))
    result["orchestrator_state"] = json.loads(
        result.pop("orchestrator_state_json")
    )
    return result


def replace_supervisor_allocations(
    run_id: str,
    allocations: list[dict[str, Any]],
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Replace a run's allocation-ledger rows wholesale.

    Args:
        run_id: Owning run.
        allocations: The engine's ``task_history`` list -- each entry a
            serialized ``scheduling.TaskRecord`` (task_type, status, reason,
            iteration, termination_reason) plus the orchestrator's
            ``priority``/``planner_reason`` extras. Ledger order is taken
            from list order, not any timestamp.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as active:
        active.execute(
            "DELETE FROM supervisor_allocations WHERE run_id = ?", (run_id,)
        )
        now = _now()
        active.executemany(
            "INSERT INTO supervisor_allocations (run_id, seq, iteration, "
            "task_type, status, reason, planner_reason, priority, "
            "termination_reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    run_id,
                    seq,
                    int(entry.get("iteration", 0)),
                    entry["task_type"],
                    entry["status"],
                    entry["reason"],
                    entry.get("planner_reason"),
                    entry.get("priority"),
                    entry.get("termination_reason"),
                    now,
                )
                for seq, entry in enumerate(allocations)
            ],
        )


def list_supervisor_allocations(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's allocation ledger, in scheduling order.

    Args:
        run_id: Owning run.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        Rows in the order the orchestrator scheduled them (``seq`` ASC) --
        every row from one drain shares a ``created_at``, so timestamp order
        alone cannot recover the sequence.
    """
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            "SELECT * FROM supervisor_allocations WHERE run_id=? "
            "ORDER BY seq ASC",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def _count_supervisor_allocations(run_id: str, conn: sqlite3.Connection) -> int:
    """Return how many allocation-ledger rows a run already has."""
    row = conn.execute(
        "SELECT COUNT(*) FROM supervisor_allocations WHERE run_id=?",
        (run_id,),
    ).fetchone()
    return int(row[0])


def _has_supervisor_plan(run_id: str, conn: sqlite3.Connection) -> bool:
    """Return whether a run already has a persisted Supervisor plan row."""
    row = conn.execute(
        "SELECT 1 FROM supervisor_plan WHERE run_id=? LIMIT 1", (run_id,)
    ).fetchone()
    return row is not None


def _sync_allocations_from_checkpoint(
    run_id: str,
    task_history: list[dict[str, Any]],
    conn: sqlite3.Connection,
) -> bool:
    """Replace the ledger from a checkpoint's task_history, guarded.

    Every entry in ``task_history`` is appended once by the orchestrator and
    never mutated afterward (see ``orchestrator._appended_task_record``), so
    within one run's checkpoint lineage the list only ever grows or repeats
    -- it never changes at an already-recorded length. Comparing lengths is
    therefore enough to guarantee a later, partial write (a superseded
    checkpoint, an out-of-order commit) can never shrink a ledger a previous
    write already recorded more of, and to skip the many checkpoints (fan-out
    items, ranking matches) whose task_history is unchanged since the last
    orchestrator decision -- so the ledger's write frequency tracks
    orchestrator decisions, not checkpoint count.

    Returns:
        True if the ledger was (re)written, False if skipped.
    """
    if len(task_history) <= _count_supervisor_allocations(run_id, conn):
        return False
    replace_supervisor_allocations(run_id, task_history, conn=conn)
    return True


def _sync_plan_from_checkpoint(
    run_id: str,
    ledger_grew: bool,
    workflow_state: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist the plan snapshot when it is new or the ledger just grew.

    ``ledger_grew`` ties this write's frequency to
    ``_sync_allocations_from_checkpoint``'s (bounded by orchestrator
    decisions), except for the one earlier case that matters most here: the
    very first checkpoint carrying a non-empty ``supervisor_guidance`` (right
    after the Supervisor's single planning call, before any orchestrator
    decision exists) writes once regardless, so a run that dies during
    generation still leaves its research plan behind.
    """
    guidance = workflow_state.get("supervisor_guidance") or {}
    if not guidance:
        return
    if not ledger_grew and _has_supervisor_plan(run_id, conn):
        return
    save_supervisor_plan(
        NewSupervisorPlan(
            run_id=run_id,
            guidance=guidance,
            termination_reason=workflow_state.get("termination_reason"),
            decision_provenance=workflow_state.get(
                "supervisor_decision_provenance"
            ),
            orchestrator_state=workflow_state.get("orchestrator_state") or {},
        ),
        conn=conn,
    )


def sync_supervisor_ledger_from_checkpoint(
    run_id: str,
    checkpoint_state: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist the allocation ledger and plan snapshot from a checkpoint.

    Called from ``app.store.checkpoints.save_checkpoint`` on every
    checkpoint it writes, inside that same transaction -- pure DB work
    computed from state already in memory, no network I/O, no new
    transaction. This is what makes the ledger durable for a run that
    fails, is cancelled, or is safety-blocked before ever reaching
    finalize: finalize's own write (``app.engine_adapter.drain``) still
    runs unchanged and remains authoritative for the terminal
    ``termination_reason``/``decision_provenance``.

    Args:
        run_id: Run the checkpoint belongs to.
        checkpoint_state: The ``NewCheckpoint.state`` envelope -- may or may
            not carry a nested ``state`` key with the plain ``WorkflowState``
            fields (test/legacy envelopes may not), so absence is treated as
            "nothing to sync" rather than an error.
        conn: Open connection of the caller's transaction.
    """
    workflow_state = checkpoint_state.get("state") or {}
    task_history = workflow_state.get("task_history") or []
    ledger_grew = _sync_allocations_from_checkpoint(run_id, task_history, conn)
    _sync_plan_from_checkpoint(run_id, ledger_grew, workflow_state, conn)

"""Transactional recovery for durable-task provider boundaries.

The task queue re-exports these private seams from ``app.store.tasks`` so
claim-time and startup recovery keep one implementation and one transaction.
"""

from __future__ import annotations

import sqlite3

from app.store.tasks_attempts import _record_failed_attempt
from app.store.tasks_lifecycle import cancel_run_tasks
from app.store.tasks_model import (
    UNKNOWN_PROVIDER_OUTCOME_ERROR,
    ScientificTask,
    TaskFailure,
    _decode,
)
from app.store.tasks_probes import _ENGINE_RUN_STATUS_GUARD


def _stop_run_after_unknown_provider_outcome(
    conn: sqlite3.Connection,
    run_id: str,
    task_type: str,
    failure: TaskFailure,
) -> None:
    """Revoke sibling work and publish one terminal unknown-outcome event."""
    cancel_run_tasks(run_id, conn=conn)
    from app.store.runs_reconcile import _settle_run_for_failed_task

    _settle_run_for_failed_task(
        conn, run_id, task_type, failure, retryable=False
    )


def _ambiguous_expired_engine_leases(
    conn: sqlite3.Connection, now: float
) -> list[sqlite3.Row]:
    """Read active engine leases whose original request outcome is unknown."""
    return conn.execute(
        "SELECT * FROM scientific_tasks WHERE status='leased' "
        "AND lease_expires_at IS NOT NULL AND lease_expires_at<=? "
        f"AND ({_ENGINE_RUN_STATUS_GUARD}) "
        "AND substr(task_type,1,7)='engine.' "
        "AND EXISTS (SELECT 1 FROM runs WHERE runs.id=scientific_tasks.run_id "
        "            AND runs.status IN ('queued','running','synthesizing'))",
        (now,),
    ).fetchall()


def _fail_ambiguous_engine_lease(
    conn: sqlite3.Connection,
    task: ScientificTask,
    failure: TaskFailure,
    now: float,
) -> bool:
    """Fail one expired lease and stop its run in the caller's transaction."""
    attempts_json = _record_failed_attempt(
        task,
        task.lease_owner or "unknown-worker",
        failure.error,
        False,
        now,
    )
    changed = conn.execute(
        "UPDATE scientific_tasks SET status='failed', error=?, "
        "attempts_json=?, lease_owner=NULL, lease_expires_at=NULL, "
        "completed_at=?, updated_at=? WHERE id=? AND status='leased'",
        (failure.error, attempts_json, now, now, task.id),
    ).rowcount
    if not changed:
        return False
    _stop_run_after_unknown_provider_outcome(
        conn, task.run_id, task.task_type, failure
    )
    return True


def _fail_ambiguous_expired_leases(conn: sqlite3.Connection, now: float) -> int:
    """Fail each active run's first expired engine lease, transactionally."""
    failure = TaskFailure(UNKNOWN_PROVIDER_OUTCOME_ERROR, "llm_timeout_unknown")
    failed_runs: set[str] = set()
    failed_count = 0
    for row in _ambiguous_expired_engine_leases(conn, now):
        task = _decode(row)
        if task.run_id in failed_runs:
            continue
        if _fail_ambiguous_engine_lease(conn, task, failure, now):
            failed_runs.add(task.run_id)
            failed_count += 1
    return failed_count

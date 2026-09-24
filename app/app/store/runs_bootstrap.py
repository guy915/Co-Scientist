"""Lease-fenced status transitions at the durable bootstrap boundary."""

from __future__ import annotations

import sqlite3

from app.store.db import _now, transaction
from app.store.models import RunStatus


def _bootstrap_lease_matches(
    row: sqlite3.Row, worker_id: str | None, attempt: int
) -> bool:
    return all(
        (
            row["task_status"] == "leased",
            row["lease_owner"] == worker_id,
            row["attempt"] == attempt,
            row["task_type"] == "engine.bootstrap",
            row["lease_expires_at"] is not None,
            float(row["lease_expires_at"] or 0) > _now(),
        )
    )


def bootstrap_task_lease_matches(
    conn: sqlite3.Connection,
    run_id: str,
    task_id: str,
    worker_id: str | None,
    attempt: int,
) -> bool:
    """Check that the intake decision still belongs to the live bootstrap."""
    row = conn.execute(
        "SELECT status AS task_status, lease_owner, attempt, task_type, "
        "lease_expires_at FROM scientific_tasks WHERE id=? AND run_id=?",
        (task_id, run_id),
    ).fetchone()
    return row is not None and _bootstrap_lease_matches(row, worker_id, attempt)


def _allowed_terminal_bootstrap_status(
    status: str,
    row: sqlite3.Row,
    worker_id: str | None,
    attempt: int,
) -> str | None:
    if status == RunStatus.PAUSED.value and not _bootstrap_lease_matches(
        row, worker_id, attempt
    ):
        return None
    terminal_or_paused = {
        RunStatus.COMPLETED.value,
        RunStatus.CANCELLED.value,
        RunStatus.FAILED.value,
        RunStatus.BLOCKED.value,
        RunStatus.PAUSED.value,
    }
    return status if status in terminal_or_paused else None


def _advance_bootstrap_status(
    conn: sqlite3.Connection, run_id: str, status: str
) -> bool:
    if status not in {
        RunStatus.RUNNING.value,
        RunStatus.DRAFT.value,
        RunStatus.QUEUED.value,
    }:
        return False
    if status != RunStatus.RUNNING.value:
        now = _now()
        conn.execute(
            "UPDATE runs SET status=?, error=NULL, updated_at=?, "
            "completed_at=NULL WHERE id=? AND status=?",
            (RunStatus.RUNNING.value, now, run_id, status),
        )
    return True


def mark_bootstrap_running(
    run_id: str,
    task_id: str,
    worker_id: str | None,
    attempt: int,
    db_path: str | None = None,
) -> str | None:
    """Start only a live run whose bootstrap lease still belongs to caller.

    Args:
        run_id: Run whose lifecycle is being advanced.
        task_id: Bootstrap task whose lease authorizes the transition.
        worker_id: Worker expected to own the task lease.
        attempt: Attempt number expected for the claimed task.
        db_path: Optional override for the SQLite database path.

    Returns:
        The terminal or paused status when no transition is allowed, the
        current running status on success, or None if the run/lease vanished.
    """
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT runs.status AS run_status, task.status AS task_status, "
            "task.lease_owner, task.attempt, task.task_type, "
            "task.lease_expires_at "
            "FROM runs LEFT JOIN scientific_tasks AS task "
            "ON task.id=? AND task.run_id=runs.id WHERE runs.id=?",
            (task_id, run_id),
        ).fetchone()
        if row is None:
            return None
        status = str(row["run_status"])
        terminal_status = _allowed_terminal_bootstrap_status(
            status, row, worker_id, attempt
        )
        if terminal_status is not None:
            return terminal_status
        if not _bootstrap_lease_matches(row, worker_id, attempt):
            return None
        if not _advance_bootstrap_status(conn, run_id, status):
            return None
    return RunStatus.RUNNING.value

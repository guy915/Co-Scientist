"""Startup reconciliation of runs interrupted by a crash or restart.

Split out of ``app.store.runs`` to keep that module within the size cap.
Holds the active-status vocabulary and the startup sweep that either
marks an interrupted run resumable (a durable checkpoint exists) or
fails it with a clear reason. Every name is re-exported from
``app.store.runs``, so callers and monkeypatching tests are unaffected.
"""

from __future__ import annotations

import sqlite3

from app.store.checkpoints import has_checkpoint
from app.store.db import _now, connect
from app.store.events import _append_event
from app.store.models import RunStatus

# Statuses that mark a run as occupying a concurrency slot / still in flight.
_ACTIVE_RUN_STATUSES: tuple[str, str, str] = (
    RunStatus.QUEUED.value,
    RunStatus.RUNNING.value,
    RunStatus.SYNTHESIZING.value,
)


def _fail_interrupted_run(
    conn: sqlite3.Connection,
    run_id: str,
    now: float,
    reason: str,
) -> None:
    """Transition one interrupted run to failed and log a status event.

    Args:
        conn: Open connection to run the update and event append on.
        run_id: Identifier of the run to fail.
        now: Timestamp to record as the update and completion time.
        reason: Human-readable interruption reason to store and log.
    """
    conn.execute(
        "UPDATE runs SET status=?, error=?, updated_at=?, "
        "completed_at=? WHERE id=?",
        (RunStatus.FAILED.value, reason, now, now, run_id),
    )
    _append_event(
        conn, run_id, "status", {"status": "failed", "error": reason}, now
    )


def _reconcile_one_run(
    conn: sqlite3.Connection, run_id: str, now: float, reason: str
) -> str:
    """Reconcile one interrupted run and return its outcome.

    Args:
        conn: Open connection to run the checkpoint check and update on.
        run_id: Identifier of the interrupted run.
        now: Timestamp to record for any status change.
        reason: Human-readable interruption reason for a failed outcome.

    Returns:
        ``"resumable"`` when a checkpoint exists, else ``"failed"``.
    """
    if has_checkpoint(run_id, conn=conn):
        _append_event(
            conn,
            run_id,
            "status",
            {"status": "resumable", "detail": "checkpoint available"},
            now,
        )
        return "resumable"
    _fail_interrupted_run(conn, run_id, now, reason)
    return "failed"


def reconcile_interrupted_runs(
    db_path: str | None = None,
) -> dict[str, list[str]]:
    """Reconcile runs left non-terminal by a previous process (crash/restart).

    On startup no workflow tasks are running, so any run still marked queued,
    running, or synthesizing was interrupted. A run that has a durable
    checkpoint is *resumable* (Milestone 4): it is left for the resume path
    rather than failed, and a ``resumable`` status event is logged. A run with
    no checkpoint cannot be resumed and is transitioned to ``failed`` with a
    clear reason and a status event so the stream/UI reflect the interruption.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        ``{"failed": [...], "resumable": [...]}`` — the ids in each outcome.
    """
    now = _now()
    reason = "Run interrupted by a server restart."
    failed: list[str] = []
    resumable: list[str] = []
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id FROM runs WHERE status IN (?,?,?)",
            _ACTIVE_RUN_STATUSES,
        ).fetchall()
        for row in rows:
            rid = row["id"]
            outcome = _reconcile_one_run(conn, rid, now, reason)
            (resumable if outcome == "resumable" else failed).append(rid)
    return {"failed": failed, "resumable": resumable}

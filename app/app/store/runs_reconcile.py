"""Startup reconciliation of runs interrupted by a crash or restart.

Split out of ``app.store.runs`` to keep that module within the size cap.
Holds the active-status vocabulary, the one predicate every gate asks to
decide whether a run can resume, the startup sweep that either marks an
interrupted run resumable or fails it with a clear reason, and the
in-process settlement that fails a run the moment its last claimable
work dies. Both failure paths write the same run-row transition and the
same terminal ``status`` event shape, so the SSE stream closes on
either. The pre-existing names callers use are re-exported from
``app.store.runs``, so callers and monkeypatching tests are unaffected.
"""

from __future__ import annotations

import logging
import sqlite3

from app.store.checkpoints import has_checkpoint
from app.store.db import _now, connect, transaction
from app.store.events import _append_event
from app.store.models import RunStatus
from app.store.tasks_model import TaskFailure

logger = logging.getLogger(__name__)

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


def _settle_run_out_of_work(
    conn: sqlite3.Connection,
    run_id: str,
    error: str,
    now: float,
    failure_kind: str | None = None,
) -> bool:
    """Fail an active run durably because no claimable work remains.

    The in-process mirror of the startup sweep's fail outcome, called
    inside the same transaction that just failed a task past its retry
    budget (or permanently), so the probe sees exactly the state the run
    is left in. Any queued or leased task blocks settlement: a queued
    task is claimable, and a live lease may still fan out more work. The
    run update is conditional on an active status, so two workers failing
    one run's last tasks concurrently cannot both settle it -- only the
    first UPDATE lands, and only its transaction appends the terminal
    status event the SSE stream closes on. Unlike
    :func:`_fail_interrupted_run` the transition is guarded: at startup
    nothing executes, while in-process another writer may be mid-flight.

    Args:
        conn: Connection carrying the failing task's transaction.
        run_id: Identifier of the run the failed task belongs to.
        error: Failure reason to persist on the run and its status event.
        now: Timestamp recorded for the transition and the event.
        failure_kind: Optional exact provider failure type to persist.

    Returns:
        True when this call transitioned the run to failed.
    """
    row = conn.execute(
        "SELECT 1 FROM scientific_tasks WHERE run_id=? "
        "AND status IN ('queued','leased') LIMIT 1",
        (run_id,),
    ).fetchone()
    if row is not None:
        return False
    placeholders = ",".join("?" for _ in _ACTIVE_RUN_STATUSES)
    changed = conn.execute(
        "UPDATE runs SET status=?, error=?, updated_at=?, completed_at=? "
        f"WHERE id=? AND status IN ({placeholders})",
        (
            RunStatus.FAILED.value,
            error,
            now,
            now,
            run_id,
            *_ACTIVE_RUN_STATUSES,
        ),
    ).rowcount
    if not changed:
        return False
    payload = {"status": "failed", "error": error}
    if failure_kind is not None:
        payload["failure_kind"] = failure_kind
    _append_event(conn, run_id, "status", payload, now)
    return True


def _settle_run_for_failed_task(
    conn: sqlite3.Connection,
    run_id: str,
    task_type: str,
    error: str | TaskFailure,
    *,
    retryable: bool,
) -> None:
    """Settle a run whose task just failed terminally, if no work remains.

    Builds the run-level failure reason from the task outcome and
    delegates to :func:`_settle_run_out_of_work`; called inside the
    failing task's own transaction so settlement is atomic with it.

    Args:
        conn: Connection carrying the failing task's transaction.
        run_id: Identifier of the run the failed task belongs to.
        task_type: Task type name used in the persisted failure reason.
        error: The task's raw failure, optionally with its exact kind.
        retryable: False for a permanent failure, True when the retry
            budget was just exhausted.
    """
    failure = error if isinstance(error, TaskFailure) else TaskFailure(error)
    reason = (
        f"Task {task_type} failed permanently: {failure.error}"
        if not retryable
        else f"Task {task_type} exhausted its retry budget: {failure.error}"
    )
    if _settle_run_out_of_work(
        conn,
        run_id,
        reason,
        _now(),
        failure_kind=failure.failure_kind,
    ):
        logger.info(
            "Run %s failed: no claimable work remains (%s)", run_id, reason
        )


def _reconcile_one_run(
    conn: sqlite3.Connection, run_id: str, now: float, reason: str
) -> str:
    """Reconcile one interrupted run and return its outcome.

    Args:
        conn: Open connection to run the resumability checks and update
            on.
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


def _fail_ambiguous_expired_provider_leases(
    db_path: str | None, now: float
) -> None:
    """Commit unknown lease outcomes before a generic restart event."""
    from app.store.tasks import _fail_ambiguous_expired_leases

    with transaction(db_path) as conn:
        _fail_ambiguous_expired_leases(conn, now)


def reconcile_interrupted_runs(
    db_path: str | None = None,
) -> dict[str, list[str]]:
    """Reconcile runs left non-terminal by a previous process (crash/restart).

    On startup no workflow tasks are running, so any run still marked queued,
    running, or synthesizing was interrupted. A run that has a durable
    checkpoint is *resumable* (Milestone 4): it is left for the resume path
    rather than failed, and a ``resumable`` status event is logged. A run
    without one cannot be resumed and is transitioned to ``failed`` with a
    clear reason and a status event so the stream/UI reflect the
    interruption.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        ``{"failed": [...], "resumable": [...]}`` — the ids in each outcome.
    """
    now = _now()
    reason = "Run interrupted by a server restart."
    failed: list[str] = []
    resumable: list[str] = []
    _fail_ambiguous_expired_provider_leases(db_path, now)
    with connect(db_path) as conn:
        # A finalize task can commit its report and then lose the process
        # before the worker records task success. At startup all prior
        # process leases are orphaned, so settle only that already-published
        # boundary; no active run or other task type is eligible here.
        recovered = conn.execute(
            "UPDATE scientific_tasks SET status='completed', "
            "result_json=COALESCE(result_json, '{}'), error=NULL, "
            "lease_owner=NULL, lease_expires_at=NULL, completed_at=?, "
            "updated_at=? WHERE task_type='engine.finalize' "
            "AND status='leased' "
            "AND EXISTS (SELECT 1 FROM runs WHERE "
            "runs.id=scientific_tasks.run_id AND runs.status=?) "
            "AND EXISTS (SELECT 1 FROM reports WHERE "
            "reports.run_id=scientific_tasks.run_id)",
            (now, now, RunStatus.COMPLETED.value),
        ).rowcount
        if recovered:
            logger.info(
                "Reconciled %d finalize task(s) whose reports were already "
                "published before restart.",
                recovered,
            )
        rows = conn.execute(
            "SELECT id FROM runs WHERE status IN (?,?,?)",
            _ACTIVE_RUN_STATUSES,
        ).fetchall()
        for row in rows:
            rid = row["id"]
            outcome = _reconcile_one_run(conn, rid, now, reason)
            (resumable if outcome == "resumable" else failed).append(rid)
    return {"failed": failed, "resumable": resumable}

"""Startup reconciliation of runs interrupted by a crash or restart.

Split out of ``app.store.runs`` to keep that module within the size cap.
Holds the active-status vocabulary, the one predicate every gate asks to
decide whether a run can resume, the startup sweep that either marks an
interrupted run resumable or fails it with a clear reason, and the
in-process settlement that fails a run the moment its last claimable
work dies. Both failure paths write the same run-row transition and the
same terminal ``status`` event shape, so the SSE stream closes on
either. Every pre-existing name is re-exported from ``app.store.runs``,
so callers and monkeypatching tests are unaffected.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from app.store.checkpoints import has_checkpoint
from app.store.code_variants import DISCOVERY_CONFIG_KEY
from app.store.db import _now, _use_conn, connect
from app.store.events import _append_event
from app.store.models import RunStatus

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
    _append_event(
        conn, run_id, "status", {"status": "failed", "error": error}, now
    )
    return True


def _settle_run_for_failed_task(
    conn: sqlite3.Connection,
    run_id: str,
    task_type: str,
    error: str,
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
        error: The task's failure error text.
        retryable: False for a permanent failure, True when the retry
            budget was just exhausted.
    """
    reason = (
        f"Task {task_type} failed permanently: {error}"
        if not retryable
        else f"Task {task_type} exhausted its retry budget: {error}"
    )
    if _settle_run_out_of_work(conn, run_id, reason, _now()):
        logger.info(
            "Run %s failed: no claimable work remains (%s)", run_id, reason
        )


# Task states that still represent work: claimable now, claimable once a
# stale lease expires, or claimable once the run is resumed.
_UNFINISHED_TASK_STATUSES = ("queued", "leased", "paused")


def has_resumable_discovery_work(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Reports whether a discovery run still has work a worker could take.

    The single answer to "can this run resume without a checkpoint",
    asked by startup reconciliation, the resume endpoint's guard, the
    resume-mode choice and the resume enqueue. Written once because
    those four surfaces answering it separately is how they come to
    disagree.

    A discovery run never writes a workflow checkpoint -- it has no
    Supervisor and no graph state to restore, and its progress lives in
    ``code_variants`` plus its own task rows. Judging it by the
    checkpoint test alone therefore fails the one kind of run whose
    state is *entirely* durable, while resuming a hypothesis run whose
    engine state is gone. What makes this run resumable is that the
    queue still holds something: the generation keys are deterministic,
    so nothing is duplicated by continuing.

    Note what it deliberately excludes. A discovery run with no
    unfinished task has nothing claimable, and calling it resumable
    would produce a run that announces a resume on every restart and
    then sits silent -- the failure ``_queue_resume_workflow``'s log
    line exists to expose. That run is genuinely stuck and is failed.

    Args:
        run_id: The run to test.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        True when the run carries a discovery block and at least one
        unfinished task.
    """
    placeholders = ",".join("?" for _ in _UNFINISHED_TASK_STATUSES)
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT config_json FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            return False
        try:
            config = json.loads(row["config_json"] or "{}")
        except (TypeError, ValueError):
            return False
        if not isinstance(config.get(DISCOVERY_CONFIG_KEY), dict):
            return False
        pending = active.execute(
            "SELECT 1 FROM scientific_tasks WHERE run_id=? "
            f"AND status IN ({placeholders}) LIMIT 1",
            (run_id, *_UNFINISHED_TASK_STATUSES),
        ).fetchone()
    return pending is not None


def _resumable_detail(run_id: str, conn: sqlite3.Connection) -> str:
    """Names what a resumable run will actually resume from."""
    if has_checkpoint(run_id, conn=conn):
        return "checkpoint available"
    return "durable task queue"


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
        ``"resumable"`` when a checkpoint exists or the run is a
        discovery run with claimable work left, else ``"failed"``.
    """
    if has_checkpoint(run_id, conn=conn) or has_resumable_discovery_work(
        run_id, conn=conn
    ):
        _append_event(
            conn,
            run_id,
            "status",
            {"status": "resumable", "detail": _resumable_detail(run_id, conn)},
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
    rather than failed, and a ``resumable`` status event is logged. So is a
    discovery run whose queue still holds work, which has no checkpoint by
    design -- see :func:`has_resumable_discovery_work`. A run that is neither
    cannot be resumed and is transitioned to ``failed`` with a clear reason and
    a status event so the stream/UI reflect the interruption.

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

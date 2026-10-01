"""Resume-state inspection and atomic queue admission for durable runs."""

from __future__ import annotations

import logging
import sqlite3

from fastapi import HTTPException

from app import engine_adapter, engine_tasks, store, task_worker
from app.runs_support import _run_or_404
from app.store import RunRow, RunStatus, ScientificTask
from app.task_worker_enqueue import is_abandoned_spent_bootstrap

# Keep the lifecycle log channel stable across this extraction.
logger = logging.getLogger("app.runs_lifecycle")


def _has_paused_engine_task(
    run_id: str, *, conn: sqlite3.Connection | None = None
) -> bool:
    """Return whether the run has a paused engine-provider task queued."""
    return store.has_task_of_type(
        run_id, engine_tasks.ENGINE_TASK_PREFIX, status="paused", conn=conn
    )


def _has_leased_precheckpoint_bootstrap(
    run_id: str, *, conn: sqlite3.Connection | None = None
) -> bool:
    """A bootstrap lease is a resumable boundary before its first checkpoint."""
    return not store.has_checkpoint(
        run_id, conn=conn
    ) and store.has_task_of_type(
        run_id, engine_tasks.BOOTSTRAP_TASK, status="leased", conn=conn
    )


def _has_failed_precheckpoint_bootstrap_while_paused(
    run_id: str, *, conn: sqlite3.Connection | None = None
) -> bool:
    """Allow retry only when abandonment failed a bootstrap in a paused run."""
    if store.has_checkpoint(run_id, conn=conn):
        return False
    run = store.get_run(run_id, conn=conn)
    if run is None or run.status != RunStatus.PAUSED.value:
        return False
    return any(
        is_abandoned_spent_bootstrap(task)
        for task in store.list_tasks(run_id, conn=conn)
    )


def lifecycle_revision(run_id: str, *, conn: sqlite3.Connection) -> int:
    """Return the monotonic sequence of the latest lifecycle transition."""
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM run_events "
        "WHERE run_id=? AND type IN ('status', 'lifecycle')",
        (run_id,),
    ).fetchone()
    return int(row[0])


def resume_admission_snapshot(run_id: str) -> tuple[RunRow, int]:
    """Read the run status and lifecycle revision from one SQLite snapshot."""
    with store.connect() as conn:
        conn.execute("BEGIN")
        run = _run_or_404(run_id, conn=conn)
        revision = lifecycle_revision(run_id, conn=conn)
        conn.execute("COMMIT")
    return run, revision


def _is_resumable(run_id: str) -> bool:
    """Report whether anything durable exists for this run to resume from.

    A checkpoint restores engine state; a paused engine task resumes its
    boundary; a leased or abandoned bootstrap survives pause before either
    exists.
    """
    return (
        store.has_checkpoint(run_id)
        or _has_paused_engine_task(run_id)
        or _has_leased_precheckpoint_bootstrap(run_id)
        or _has_failed_precheckpoint_bootstrap_while_paused(run_id)
    )


def _prepare_resume_state(
    run_id: str, *, conn: sqlite3.Connection | None = None
) -> bool:
    """Clear stale derived data for a legacy resume and return true_resume.

    Two resume modes, chosen by the kind of checkpoint on disk:

    - Engine checkpoint (a serialized WorkflowState), an already-queued
      paused engine task, or a leased/abandoned pre-checkpoint bootstrap: a
      *true* resume. The engine restores or continues that state
      and re-enters at the orchestrator, so completed LLM/tool work is not
      repeated. Derived data is NOT cleared — the engine persists artifacts
      only at the final drain, so a mid-run interruption left only events +
      the checkpoint, and clearing would discard the pre-orchestrator events
      that resume never re-emits.
    - Legacy (pre-flip) envelope checkpoint: there is no persisted engine
      state to restore, so the durable worker re-bootstraps the run from its
      goal/config instead of a true resume. Derived data AND the stale
      envelope checkpoint are cleared so the fresh run neither duplicates rows
      or events nor trips the durable bootstrap's empty-checkpoint guard
      (``engine_tasks.execute_bootstrap`` asserts an empty checkpoint
      history).
    """
    checkpoint = store.get_latest_checkpoint(run_id, conn=conn)
    true_resume = (
        engine_adapter.is_engine_checkpoint(checkpoint)
        or _has_paused_engine_task(run_id, conn=conn)
        or _has_leased_precheckpoint_bootstrap(run_id, conn=conn)
        or _has_failed_precheckpoint_bootstrap_while_paused(run_id, conn=conn)
    )
    if not true_resume:
        # Preserve a sequence above every event being discarded, even when
        # the checkpoint floor is older than trailing generated log rows.
        store.append_event(
            run_id,
            "lifecycle",
            {"event": "legacy_resume_cleanup"},
            conn=conn,
        )
        store.clear_run_derived_data(run_id, conn=conn)
        store.clear_checkpoints(run_id, conn=conn)
    return true_resume


def _resume_detail(true_resume: bool) -> str:
    """Name what the resume is actually re-entering from."""
    return "from specialist checkpoint" if true_resume else "from checkpoint"


def _check_resume_admission(
    run_id: str,
    expected_status: str,
    expected_lifecycle_revision: int,
    *,
    conn: sqlite3.Connection,
) -> None:
    """Reject a stale resume request before it changes durable state."""
    run = _run_or_404(run_id, conn=conn)
    if (
        run.status != expected_status
        or lifecycle_revision(run_id, conn=conn) != expected_lifecycle_revision
    ):
        raise HTTPException(
            status_code=409, detail="run status changed while resuming"
        )


def _record_resume_transition(
    run_id: str, true_resume: bool, *, conn: sqlite3.Connection
) -> None:
    store.update_run_status(run_id, RunStatus.QUEUED, conn=conn)
    store.append_event(
        run_id,
        "status",
        {"status": "resuming", "detail": _resume_detail(true_resume)},
        conn=conn,
    )


def _log_resume_queue_result(run_id: str, queued: ScientificTask) -> None:
    """Record whether resume admission left a claimable task."""
    logger.info(
        "Resume for run %s landed on %s task %s (status=%s)",
        run_id,
        queued.task_type,
        queued.id[:8],
        queued.status,
    )


def _queue_resume_workflow(
    run_id: str,
    *,
    expected_status: str,
    expected_lifecycle_revision: int,
) -> ScientificTask:
    """Atomically admit only the run state observed by the resume caller."""
    with store.transaction() as conn:
        _check_resume_admission(
            run_id,
            expected_status,
            expected_lifecycle_revision,
            conn=conn,
        )
        revive_failed_bootstrap = (
            _has_failed_precheckpoint_bootstrap_while_paused(run_id, conn=conn)
        )
        true_resume = _prepare_resume_state(run_id, conn=conn)
        _record_resume_transition(run_id, true_resume, conn=conn)
        queued = task_worker.enqueue_run_workflow(
            run_id,
            resume=true_resume,
            revive_failed_precheckpoint_bootstrap=revive_failed_bootstrap,
            conn=conn,
        )
    _log_resume_queue_result(run_id, queued)
    return queued

"""Run lifecycle endpoints: start, cancel, pause, and resume."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

import app.engine_adapter as engine_adapter
import app.engine_tasks as engine_tasks
import app.store as store
import app.task_worker as task_worker
from app.auth import client_id
from app.config import settings
from app.runs.models import SafetyAdjudicationRequest, StartRunRequest
from app.runs.support import _run_or_404
from app.store import TERMINAL_STATUSES, RunRow, RunStatus, ScientificTask
from app.task_worker.enqueue import is_abandoned_spent_bootstrap

logger = logging.getLogger(__name__)

# Keep the lifecycle log channel stable across this extraction.


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


async def _apply_adjudication_lifecycle(
    run: store.RunRow,
    decision: dict[str, Any],
    resolution: str,
    *,
    expected_lifecycle_revision: int,
) -> None:
    """Apply the run-lifecycle consequence of one adjudicated decision.

    Intake/final holds gate the run's whole goal or report, so a rejection
    blocks the run and an approval releases it. A hypothesis-stage hold
    concerns one idea the engine already kept out of the pool and the
    report; rejecting it confirms the exclusion, and the recorded
    resolution is the verdict -- the run's lifecycle is untouched.

    Args:
        run: The run whose decision was adjudicated.
        decision: The resolved decision row (carries its ``stage``).
        resolution: ``"approved"`` or ``"rejected"``.
        expected_lifecycle_revision: Transition revision observed at admission.
    """
    if decision["stage"] == "hypothesis":
        return
    if resolution == "rejected":
        _block_rejected_run_if_current(
            run, expected_lifecycle_revision=expected_lifecycle_revision
        )
    elif run.status == RunStatus.PAUSED.value:
        await _release_approved_hold(
            run.id,
            expected_status=run.status,
            expected_lifecycle_revision=expected_lifecycle_revision,
        )


def _block_rejected_run_if_current(
    run: store.RunRow, *, expected_lifecycle_revision: int
) -> None:
    """Block a rejected run only while its admission state is unchanged."""
    with store.transaction() as conn:
        current = store.get_run(run.id, conn=conn)
        if current is None:
            raise HTTPException(status_code=404, detail="run not found")
        if (
            current.status != run.status
            or lifecycle_revision(run.id, conn=conn)
            != expected_lifecycle_revision
        ):
            raise HTTPException(
                status_code=409, detail="run status changed during adjudication"
            )
        store.update_run_status(
            run.id,
            RunStatus.BLOCKED,
            error="Safety reviewer rejected held content.",
            conn=conn,
        )


async def _release_approved_hold(
    run_id: str,
    *,
    expected_status: str,
    expected_lifecycle_revision: int,
) -> None:
    """Relaunch a run whose intake or final hold a reviewer just approved.

    The gate that held the run parked its task rather than completing it
    (``engine_tasks.SafetyHoldError``), so the boundary the run stopped at
    is still on the queue waiting to be released -- which is exactly what
    the resume path does. Approval used to only rewrite the run's status,
    which left the queue untouched: the holding task had already succeeded,
    re-enqueueing its boundary hit the same idempotency key and created
    nothing, and the run sat with no claimable work forever.

    The stage is not re-screened on the way back through: the escalation
    wrapper skips a stage a reviewer approved (``screen_with_escalation``),
    so a fresh contextual verdict cannot re-hold what a person released.
    """
    await _launch_resume(
        run_id,
        expected_status=expected_status,
        expected_lifecycle_revision=expected_lifecycle_revision,
    )


async def adjudicate_safety(
    run_id: str,
    decision_id: int,
    body: SafetyAdjudicationRequest,
    request: Request,
) -> dict[str, Any]:
    """Resolve one held safety decision and update the run lifecycle."""
    run, revision = resume_admission_snapshot(run_id)
    reviewer = client_id(request)
    if not reviewer:
        raise HTTPException(
            status_code=403, detail="an identified reviewer is required"
        )
    resolved = store.resolve_safety_decision(
        run_id, decision_id, body.resolution, reviewer
    )
    if not resolved:
        raise HTTPException(
            status_code=409,
            detail="decision is not reviewable or was already resolved",
        )
    decisions = store.list_safety_decisions(run_id)
    decision = next(item for item in decisions if item["id"] == decision_id)
    await _apply_adjudication_lifecycle(
        run,
        decision,
        body.resolution,
        expected_lifecycle_revision=revision,
    )
    return {"resolution": body.resolution, "decision_id": decision_id}


# Strong references to detached resume tasks so they are not garbage-collected
# mid-run; each removes itself on completion (see _launch_resume).
_resume_tasks: set[asyncio.Task[None]] = set()
router = APIRouter()


def _check_startable(run: RunRow) -> None:
    """Raise 409 if `run` cannot be (re)started in its current status.

    Only draft/failed/blocked/cancelled runs may (re)start; in-progress and
    completed runs 409 rather than double-running.
    """
    if run.status in (
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.SYNTHESIZING,
    ):
        raise HTTPException(status_code=409, detail="run already in progress")
    if run.status == RunStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="run already completed")


def _reserve_capacity_or_409(run: RunRow, conn: Any) -> None:
    """Reserve the client's concurrent-run slot, raising 409 if it is full.

    One ceiling for every tier, and one ceiling *across* them. Heavier
    tiers were previously capped harder (ultra at 1), which stopped a
    researcher from investigating two questions at once -- precisely what
    the deep tiers are for. The correction went too far the other way: the
    reservation counted each tier's runs separately, so one caller held a
    full allowance per tier and the real ceiling was four times the
    advertised one. Bounding provider spend is the tier budget's job
    (max_llm_calls); this only has to stop one client queueing unboundedly,
    which it can only do if every tier draws on the same slots.
    """
    limit = settings.max_concurrent_runs
    if not store.reserve_run_capacity_in_transaction(
        conn,
        run.id,
        run.client_id,
        limit,
        run.status,
    ):
        current = store.get_run(run.id, conn=conn)
        if current is None:
            raise HTTPException(status_code=404, detail="run not found")
        if current.status != run.status:
            raise HTTPException(
                status_code=409, detail="run status changed while starting"
            )
        raise HTTPException(
            status_code=409,
            detail=f"concurrent run limit reached ({limit})",
        )


def _enqueue_workflow_and_maybe_launch_worker(
    run: RunRow, background: BackgroundTasks
) -> ScientificTask:
    """Reserve quota and admit work atomically, then launch if embedded.

    Every run is delivered through the durable worker queue -- the engine is
    the only provider now, so there is no in-process alternative to select.
    """
    with store.transaction() as conn:
        _reserve_capacity_or_409(run, conn)
        store.revive_task_for_retry(
            run.id,
            "engine:bootstrap:v1",
            conn=conn,
        )
        task = engine_tasks.enqueue_bootstrap(run.id, conn=conn)
        store.append_event(
            run.id,
            "lifecycle",
            {"event": "queued"},
            conn=conn,
        )
    if settings.coscientist_embedded_worker:
        # Local compatibility mode consumes the same durable lease. A
        # production worker service runs ``python -m app.task_worker`` and
        # sets COSCIENTIST_EMBEDDED_WORKER=0 on the API service.
        background.add_task(
            task_worker.run_run_worker_pool_sync,
            run.id,
            f"embedded-api:{os.getpid()}",
        )
    return task


@router.post("/{run_id}/start")
async def start_run(
    run_id: str, req: StartRunRequest, background: BackgroundTasks
) -> dict[str, Any]:
    """Queue a run and launch its workflow through the durable worker.

    Args:
        run_id: Path identifier of the run to start.
        req: Request body (empty; kept to preserve the endpoint's body
            contract for existing clients).
        background: FastAPI background task registry for the embedded-worker
            compatibility mode.

    Returns:
        A dict with the run 'id', its new 'status', and the enqueued task id.

    Raises:
        HTTPException: If the run is missing, already in progress, already
            completed, or the client's concurrent-run limit is reached.
    """
    run = _run_or_404(run_id)
    _check_startable(run)
    if run.status in {
        RunStatus.CANCELLED.value,
        RunStatus.FAILED.value,
    } and store.has_checkpoint(run_id):
        raise HTTPException(
            status_code=409,
            detail="run has a checkpoint; use /resume to continue it",
        )
    if run.status == RunStatus.BLOCKED.value:
        raise HTTPException(
            status_code=409,
            detail="run was blocked; create a new run",
        )
    task = _enqueue_workflow_and_maybe_launch_worker(run, background)
    return {"id": run_id, "status": "queued", "task_id": task.id}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    """Cancel a run by revoking its durable tasks and marking it CANCELLED.

    Cancellation is durable, not in-process: revoking the run's queued and
    leased tasks is what stops the workers (their lease heartbeat observes
    the revocation and cancels in-flight work), so any non-terminal run is
    transitioned to CANCELLED here directly and a terminal ``cancelled``
    status event is emitted (mirroring the failed-run path) so open SSE
    streams close. An already-terminal run cannot be cancelled, returns 409.
    """
    with store.transaction() as conn:
        run = store.get_run(run_id, conn=conn)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if RunStatus(run.status) in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="run already finished")
        store.cancel_run_tasks(run_id, conn=conn)
        store.update_run_status(run_id, RunStatus.CANCELLED, conn=conn)
        store.append_event(run_id, "status", {"status": "cancelled"}, conn=conn)
    return {"id": run_id, "status": "cancelled"}


@router.post("/{run_id}/pause")
async def pause_run(run_id: str) -> dict[str, Any]:
    """Cooperatively pause a durably-queued/running engine run.

    Parks queued engine tasks and marks the run PAUSED. Already-leased work
    may finish its durable checkpoint, but no engine successor can be claimed
    until explicit resume; no extra checkpoint needs to be created here.
    """
    with store.transaction() as conn:
        run = store.get_run(run_id, conn=conn)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        has_engine_task = store.has_task_of_type(
            run_id, engine_tasks.ENGINE_TASK_PREFIX, conn=conn
        )
        if has_engine_task and run.status in {
            RunStatus.QUEUED.value,
            RunStatus.RUNNING.value,
        }:
            store.pause_run_tasks(run_id, conn=conn)
            store.update_run_status(run_id, RunStatus.PAUSED, conn=conn)
            store.append_event(
                run_id,
                "lifecycle",
                {"event": "pause_requested"},
                conn=conn,
            )
            return {"id": run_id, "status": "paused"}
    raise HTTPException(status_code=404, detail="run is not active")


@router.post("/{run_id}/resume")
async def resume_run(run_id: str) -> dict[str, Any]:
    """Resume a paused or interrupted run from its last checkpoint.

    Requires something durable to resume from (see ``_is_resumable``). A
    true engine resume restores the persisted WorkflowState; a legacy
    (pre-flip) envelope checkpoint instead clears derived artifacts and
    re-bootstraps the run from its goal/config (see ``_launch_resume``). A
    completed, blocked, or actively-running runs cannot be resumed; a
    *failed* one can, which makes this the recovery path for a run an earlier
    restart gave up on: failing a run never touched its task rows, so their
    retry budgets are intact.
    """
    run, lifecycle_revision = resume_admission_snapshot(run_id)
    if run.status == RunStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="run already completed")
    if run.status == RunStatus.BLOCKED.value:
        raise HTTPException(
            status_code=409,
            detail="run was blocked; create a new run",
        )
    if run.status in (RunStatus.RUNNING.value, RunStatus.SYNTHESIZING.value):
        raise HTTPException(status_code=409, detail="run already in progress")
    if not _is_resumable(run_id):
        raise HTTPException(status_code=409, detail="run has no checkpoint")
    await _launch_resume(
        run_id,
        expected_status=run.status,
        expected_lifecycle_revision=lifecycle_revision,
    )
    return {"id": run_id, "status": "queued"}


def _log_resume_task_result(task: asyncio.Task[None]) -> None:
    """Drop the finished resume worker, reporting a crash rather than hiding it.

    The detached task's reference used to be discarded without touching its
    result, so an exception inside the worker was never retrieved and never
    logged: the run just stopped.

    Args:
        task: The completed detached worker task.
    """
    _resume_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("Resume worker crashed", exc_info=task.exception())


def _launch_embedded_resume_worker(run_id: str) -> None:
    """Drive the resumed run's worker cohort in embedded-worker mode.

    Same cohort, and the same thread hand-off, that starting a run gets.
    Driving the worker with ``create_task`` ran its synchronous SQLite
    writes and WorkflowState serialization on the API's event loop, so a
    resumed run starved request handling -- a boot carrying interrupted
    runs stopped answering /health and was killed mid-run, leaving one more
    interrupted run for the next boot to inherit. Consuming the queue
    serially also gave a resumed run a quarter of the parallelism of a
    fresh one, which is backwards: an interrupted run is precisely the one
    with work already queued up to overlap.
    """
    task = asyncio.create_task(
        asyncio.to_thread(
            task_worker.run_run_worker_pool_sync,
            run_id,
            f"embedded-resume:{os.getpid()}",
        )
    )
    _resume_tasks.add(task)
    # Surface a crash in the detached worker instead of discarding it with
    # the reference: without this the task's exception is never retrieved
    # and the run simply stops, silently.
    task.add_done_callback(_log_resume_task_result)


async def _launch_resume(
    run_id: str,
    *,
    expected_status: str | None = None,
    expected_lifecycle_revision: int | None = None,
) -> None:
    """Relaunch a run through the durable worker, on a detached task.

    Shared by the resume endpoint and the startup auto-resume launcher.
    Resume runs outside a request scope (also used at startup), so this
    drives the worker on a detached asyncio task rather than FastAPI
    BackgroundTasks; a strong reference is kept until it finishes so it is
    not garbage-collected. A completed run is never relaunched by callers.
    """
    if expected_status is None or expected_lifecycle_revision is None:
        # Retain the internal helper's direct-call contract; request, hold,
        # and startup paths pass the state they observed at admission.
        run, revision = resume_admission_snapshot(run_id)
        if expected_status is None:
            expected_status = run.status
        if expected_lifecycle_revision is None:
            expected_lifecycle_revision = revision
    _queue_resume_workflow(
        run_id,
        expected_status=expected_status,
        expected_lifecycle_revision=expected_lifecycle_revision,
    )
    if settings.coscientist_embedded_worker:
        _launch_embedded_resume_worker(run_id)


async def _resume_interrupted_run(run_id: str) -> None:
    """Resume one startup candidate only if it is still active."""
    try:
        run, lifecycle_revision = resume_admission_snapshot(run_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return
        raise
    if run.status not in {
        RunStatus.QUEUED.value,
        RunStatus.RUNNING.value,
        RunStatus.SYNTHESIZING.value,
    }:
        return
    try:
        await _launch_resume(
            run_id,
            expected_status=run.status,
            expected_lifecycle_revision=lifecycle_revision,
        )
    except HTTPException:
        logger.warning("Could not auto-resume run %s", run_id)


async def resume_interrupted_runs(run_ids: list[str]) -> None:
    """Relaunch each resumable interrupted run at startup (Milestone 4).

    Called from the app lifespan after ``reconcile_interrupted_runs`` finds
    runs left non-terminal by a restart with a checkpoint to resume from.
    Skips any run that has since completed.
    """
    for run_id in run_ids:
        await _resume_interrupted_run(run_id)


__all__ = ["_is_resumable", "_queue_resume_workflow"]

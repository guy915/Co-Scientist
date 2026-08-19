"""Run lifecycle endpoints: start, cancel, pause, and resume.

Split out of ``app.runs`` (which re-exports every name here and mounts
``router`` on its own, so the served route set is unchanged). Also home
to the resume launcher shared by the resume endpoint and the startup
auto-resume path (``resume_interrupted_runs``, called from the app
lifespan in ``app.main``).

Cancellation and pause are durable: they revoke the run's queued/leased
tasks and update the run row, which the workers observe.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app import engine_adapter, engine_tasks, store, task_worker
from app.config import settings
from app.runs_models import StartRunRequest
from app.runs_support import _run_or_404
from app.store import TERMINAL_STATUSES, RunRow, RunStatus, ScientificTask

logger = logging.getLogger(__name__)

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


def _reserve_capacity_or_409(run: RunRow) -> None:
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
    if not store.reserve_run_capacity(
        run.id,
        client_id=run.client_id,
        limit=limit,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"concurrent run limit reached ({limit})",
        )


def _enqueue_workflow_and_maybe_launch_worker(
    run_id: str, background: BackgroundTasks
) -> ScientificTask:
    """Queue the run's workflow task and, in embedded mode, launch a worker.

    Every run is delivered through the durable worker queue -- the engine is
    the only provider now, so there is no in-process alternative to select.
    """
    store.append_event(run_id, "lifecycle", {"event": "queued"})
    task = task_worker.enqueue_run_workflow(run_id, force_provider="engine")
    if settings.coscientist_embedded_worker:
        # Local compatibility mode consumes the same durable lease. A
        # production worker service runs ``python -m app.task_worker`` and
        # sets COSCIENTIST_EMBEDDED_WORKER=0 on the API service.
        background.add_task(
            task_worker.run_run_worker_pool_sync,
            run_id,
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
    _reserve_capacity_or_409(run)
    task = _enqueue_workflow_and_maybe_launch_worker(run_id, background)
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
    run = _run_or_404(run_id)
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="run already finished")
    store.cancel_run_tasks(run_id)
    store.update_run_status(run_id, RunStatus.CANCELLED)
    store.append_event(run_id, "status", {"status": "cancelled"})
    return {"id": run_id, "status": "cancelled"}


@router.post("/{run_id}/pause")
async def pause_run(run_id: str) -> dict[str, Any]:
    """Cooperatively pause a durably-queued/running engine run.

    Marks the run's queued/leased engine tasks paused and the run PAUSED; the
    durable worker's own per-task checkpoint (``engine_tasks.py``) is what
    makes the run resumable, so no extra checkpoint needs to be created here.
    """
    run = _run_or_404(run_id)
    has_engine_task = store.has_task_of_type(
        run_id, engine_tasks.ENGINE_TASK_PREFIX
    )
    if has_engine_task and run.status in {
        RunStatus.QUEUED.value,
        RunStatus.RUNNING.value,
    }:
        store.pause_run_tasks(run_id)
        store.update_run_status(run_id, RunStatus.PAUSED)
        store.append_event(run_id, "lifecycle", {"event": "pause_requested"})
        return {"id": run_id, "status": "paused"}
    raise HTTPException(status_code=404, detail="run is not active")


def _has_paused_engine_task(run_id: str) -> bool:
    """Return whether the run has a paused engine-provider task queued."""
    return store.has_task_of_type(
        run_id, engine_tasks.ENGINE_TASK_PREFIX, status="paused"
    )


def _is_resumable(run_id: str) -> bool:
    """Report whether anything durable exists for this run to resume from.

    Three shapes, one question. A checkpoint restores a hypothesis run's
    engine state; a paused engine task is a run the user stopped; and a
    discovery run's progress lives in its variants and task rows rather
    than in a checkpoint it never writes. Asking only the first two
    refused a resume for the one kind of run whose state is entirely
    durable -- and, because startup reconciliation asked the same
    narrowed question, failed it on every restart.
    """
    return (
        store.has_checkpoint(run_id)
        or _has_paused_engine_task(run_id)
        or store.has_resumable_discovery_work(run_id)
    )


@router.post("/{run_id}/resume")
async def resume_run(run_id: str) -> dict[str, Any]:
    """Resume a paused or interrupted run from its last checkpoint.

    Requires something durable to resume from (see ``_is_resumable``). A
    true engine resume restores the persisted WorkflowState; a legacy
    (pre-flip) envelope checkpoint instead clears derived artifacts and
    re-bootstraps the run from its goal/config (see ``_launch_resume``); a
    discovery run re-enters its own task queue. A completed or
    actively-running run cannot be resumed -- a *failed* one can, which is
    what makes this the recovery path for a run an earlier restart gave up
    on: failing a run never touched its task rows, so their retry budgets
    are intact.
    """
    run = _run_or_404(run_id)
    if run.status == RunStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="run already completed")
    if run.status in (RunStatus.RUNNING.value, RunStatus.SYNTHESIZING.value):
        raise HTTPException(status_code=409, detail="run already in progress")
    if not _is_resumable(run_id):
        raise HTTPException(status_code=409, detail="run has no checkpoint")
    await _launch_resume(run_id)
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


def _prepare_resume_state(run_id: str) -> bool:
    """Clear stale derived data for a legacy resume and return true_resume.

    Two resume modes, chosen by the kind of checkpoint on disk:

    - Engine checkpoint (a serialized WorkflowState) or an already-queued
      paused engine task: a *true* resume. The engine restores that state
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

    A discovery run is a true resume for a third reason: it never writes a
    checkpoint, so the narrow test read it as legacy and cleared its
    derived data -- which deletes ``run_events``, and with them every
    ``discovery`` event describing the variants that survive in
    ``code_variants``. The run would come back with its search intact and
    its narrative gone.
    """
    checkpoint = store.get_latest_checkpoint(run_id)
    true_resume = (
        engine_adapter.is_engine_checkpoint(checkpoint)
        or _has_paused_engine_task(run_id)
        or store.has_resumable_discovery_work(run_id)
    )
    if not true_resume:
        store.clear_run_derived_data(run_id)
        store.clear_checkpoints(run_id)
    return true_resume


def _resume_detail(run_id: str, true_resume: bool) -> str:
    """Name what the resume is actually re-entering from.

    A discovery run gets its own wording rather than borrowing the
    checkpoint one: it has no checkpoint, and an event stream that says
    it resumed from a specialist checkpoint is a stream that lies about
    the only durable thing the run has.
    """
    if store.has_resumable_discovery_work(run_id):
        return "from durable task queue"
    return "from specialist checkpoint" if true_resume else "from checkpoint"


def _queue_resume_workflow(run_id: str, true_resume: bool) -> ScientificTask:
    """Mark the run queued, emit the resuming event, and enqueue its task."""
    store.update_run_status(run_id, RunStatus.QUEUED)
    store.append_event(
        run_id,
        "status",
        {
            "status": "resuming",
            "detail": _resume_detail(run_id, true_resume),
        },
    )
    queued = task_worker.enqueue_run_workflow(run_id, resume=true_resume)
    # Say what the resume actually landed on, not just that it happened. The
    # "resuming" event above is emitted before any work is queued, so on its
    # own it cannot distinguish a resume that started work from one that
    # enqueued nothing -- which is how a wedged run could announce a resume
    # every restart and sit silent for hours with no way to tell why. A task
    # here that is not 'queued' is the tell: nothing is claimable.
    logger.info(
        "Resume for run %s landed on %s task %s (status=%s)",
        run_id,
        queued.task_type,
        queued.id[:8],
        queued.status,
    )
    return queued


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


async def _launch_resume(run_id: str) -> None:
    """Relaunch a run through the durable worker, on a detached task.

    Shared by the resume endpoint and the startup auto-resume launcher.
    Resume runs outside a request scope (also used at startup), so this
    drives the worker on a detached asyncio task rather than FastAPI
    BackgroundTasks; a strong reference is kept until it finishes so it is
    not garbage-collected. A completed run is never relaunched by callers.
    """
    _run_or_404(run_id)
    true_resume = _prepare_resume_state(run_id)
    _queue_resume_workflow(run_id, true_resume)
    if settings.coscientist_embedded_worker:
        _launch_embedded_resume_worker(run_id)


async def resume_interrupted_runs(run_ids: list[str]) -> None:
    """Relaunch each resumable interrupted run at startup (Milestone 4).

    Called from the app lifespan after ``reconcile_interrupted_runs`` finds
    runs left non-terminal by a restart with something durable to resume
    from -- a checkpoint, or, for a discovery run, work still in its own
    queue. Skips any run that has since completed.
    """
    for run_id in run_ids:
        run = store.get_run(run_id)
        if run is None or run.status == RunStatus.COMPLETED.value:
            continue
        try:
            await _launch_resume(run_id)
        except HTTPException:
            logger.warning("Could not auto-resume run %s", run_id)

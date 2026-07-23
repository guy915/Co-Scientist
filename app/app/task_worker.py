"""Standalone durable worker for queued Co-Scientist run tasks."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import socket
import time
import uuid
from collections.abc import Sequence
from typing import Any

from app import engine_adapter, engine_tasks, store
from app.config import settings
from app.logging_setup import run_log_context
from app.notifications import deliver_completion_notification
from app.store import RunStatus, ScientificTask

logger = logging.getLogger(__name__)

_WORKFLOW_TASK = "run.workflow"
_EMAIL_TASK = "notification.email"


class _LeaseLostError(RuntimeError):
    """Signals that durable ownership ended while task code was running."""


class UnsupportedTaskError(ValueError):
    """A task type no worker knows how to execute.

    The one genuinely permanent failure a worker can hit: retrying cannot
    teach it a task type it has no branch for. Everything else reaching the
    worker boundary -- above all a provider returning empty content, which
    the engine signals with a bare ValueError -- is transient and must keep
    its retry budget. Subclasses ValueError so existing callers that catch
    ValueError still see it.
    """


class _DatabaseStopSignal:
    """Event-compatible stop signal backed by durable run status."""

    def __init__(self, run_id: str, db_path: str | None) -> None:
        self._run_id = run_id
        self._db_path = db_path

    def is_set(self) -> bool:
        """Return whether the run was durably cancelled or paused."""
        run = store.get_run(self._run_id, db_path=self._db_path)
        return bool(
            run
            and run.status
            in {RunStatus.CANCELLED.value, RunStatus.PAUSED.value}
        )


def _enqueue_resume_task(
    run_id: str,
    checkpoint: dict[str, Any],
    db_path: str | None,
) -> ScientificTask:
    """Re-enqueue the task a checkpoint recorded as its own resume point."""
    checkpoint_seq = int(checkpoint["seq"])
    recorded_successor = checkpoint["state"].get("resume_successor")
    task_type = str(recorded_successor or "") or (
        f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
    )
    idempotency_key = f"{task_type}:{checkpoint_seq}"
    # Revive first, then enqueue. The key names the boundary the run
    # stopped at, and it cannot change while the run makes no progress --
    # so if that task already died, the enqueue below is a no-op against
    # the existing row and the run would be wedged forever, announcing a
    # resume it never performs. Reviving is a no-op unless there is a dead
    # task under this key.
    if store.revive_task_for_retry(run_id, idempotency_key, db_path=db_path):
        logger.info(
            "Resume revived a dead %s task for run %s", task_type, run_id
        )
    return store.enqueue_task(
        run_id,
        task_type,
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key=idempotency_key,
        priority=100,
        provenance={"scheduled_by": "resume"},
        db_path=db_path,
    )


def enqueue_run_workflow(
    run_id: str,
    *,
    force_provider: str | None = None,
    resume: bool = False,
    db_path: str | None = None,
) -> ScientificTask:
    """Enqueue one idempotent workflow attempt for a run."""
    if resume and store.resume_run_tasks(run_id, db_path=db_path):
        resumed = [
            task
            for task in store.list_tasks(run_id, db_path=db_path)
            if task.status == "queued" and task.task_type.startswith("engine.")
        ]
        if resumed:
            return resumed[0]
    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    if resume and checkpoint:
        return _enqueue_resume_task(run_id, checkpoint, db_path)
    return engine_tasks.enqueue_bootstrap(run_id, db_path=db_path)


async def _execute_workflow_task(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, str]:
    """Execute a leased workflow task from durable run state."""
    run = store.get_run(task.run_id, db_path=db_path)
    if run is None:
        raise RuntimeError(f"run {task.run_id} no longer exists")
    resume = bool(task.inputs.get("resume"))
    provider = task.inputs.get("force_provider")
    force_provider = str(provider) if provider else None
    with run_log_context(run.id):
        stop_signal = _DatabaseStopSignal(run.id, db_path)
        async for _event in engine_adapter.run_workflow(
            run_id=run.id,
            research_goal=run.research_goal,
            config=run.config,
            force_provider=force_provider,
            resume=resume,
            cancelled=stop_signal,  # type: ignore[arg-type]
            # This legacy "run.workflow" task type predates the node-level
            # durable executor (engine_tasks.py) that now drives real engine
            # runs; historically it ran unpaced because the boundary emitter
            # ignored sleep_seconds for the engine path. Pin it explicitly so
            # unifying that pacing (see workflow.py) does not newly slow this
            # path down.
            sleep_seconds=0.0,
        ):
            pass
    final = store.get_run(run.id, db_path=db_path)
    if final is None:
        raise RuntimeError(f"run {run.id} disappeared during execution")
    if final.status == RunStatus.FAILED.value:
        raise RuntimeError(final.error or "workflow failed")
    return {"run_id": run.id, "status": final.status}


async def _execute_task_payload(
    task: ScientificTask, *, db_path: str | None
) -> dict[str, Any]:
    """Execute one leased task without committing its durable outcome."""
    if task.task_type.startswith("engine."):
        return await engine_tasks.execute_engine_task(task, db_path=db_path)
    if task.task_type == _WORKFLOW_TASK:
        return await _execute_workflow_task(task, db_path=db_path)
    if task.task_type == _EMAIL_TASK:
        return await deliver_completion_notification(task.inputs)
    raise UnsupportedTaskError(f"unsupported task type: {task.task_type}")


async def _execute_until_lease_lost(
    task: ScientificTask,
    lease_lost: asyncio.Event,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Run task code while durable ownership remains valid.

    Cancellation revokes leased rows immediately. The heartbeat reports that
    revocation through ``lease_lost``; cancelling the local coroutine then
    stops in-flight provider and retrieval work instead of letting a revoked
    task consume compute until its natural return.
    """
    execution = asyncio.create_task(
        _execute_task_payload(task, db_path=db_path)
    )
    ownership = asyncio.create_task(lease_lost.wait())
    try:
        done, _ = await asyncio.wait(
            {execution, ownership}, return_when=asyncio.FIRST_COMPLETED
        )
        if execution in done:
            return await execution

        execution.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await execution
        raise _LeaseLostError(f"task {task.id} no longer owns its lease")
    finally:
        if not execution.done():
            execution.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await execution
        ownership.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ownership


def _complete_superseded_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Record a superseded task as a successful idempotent outcome.

    Competing durable branches can finish after another branch advances the
    checkpoint. Obsolescence is a successful idempotent outcome, not a
    scientific failure, and must not consume the retry budget.
    """
    result = {"superseded": True, "reason": str(exc)}
    if not store.complete_task(task.id, worker_id, result, db_path=db_path):
        logger.warning("Task %s lost its lease while superseded", task.id)
    else:
        logger.info("Task %s superseded by a newer checkpoint", task.id)


def _fail_unsupported_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Permanently fail a task type no worker branch can execute.

    The only failure retrying cannot fix. Everything else reaching the
    worker boundary -- notably a provider returning empty content, which the
    engine raises as a bare ValueError -- falls through to the retryable
    branch instead.
    """
    store.fail_task(
        task.id, worker_id, str(exc), retryable=False, db_path=db_path
    )
    logger.error("Task %s rejected: %s", task.id, exc)


def _fail_retryable_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Fail one task while preserving its retry budget.

    Worker boundary isolates one task failure from the rest of the cohort.
    """
    store.fail_task(
        task.id, worker_id, str(exc), retryable=True, db_path=db_path
    )
    logger.exception("Task %s failed", task.id)


def _handle_task_failure(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Classify one task failure and record its outcome accordingly.

    Preserves the original except-clause priority exactly: a superseded
    checkpoint is a successful idempotent outcome, an unsupported task type
    is the one permanent failure, and everything else keeps its retry
    budget.
    """
    if isinstance(exc, engine_tasks.SupersededTaskError):
        _complete_superseded_task(task, worker_id, exc, db_path)
    elif isinstance(exc, UnsupportedTaskError):
        _fail_unsupported_task(task, worker_id, exc, db_path)
    else:
        _fail_retryable_task(task, worker_id, exc, db_path)


def _record_success(
    task: ScientificTask,
    worker_id: str,
    result: dict[str, Any],
    db_path: str | None,
) -> None:
    """Persist a task's result if this worker still owns its lease."""
    if not store.complete_task(task.id, worker_id, result, db_path=db_path):
        logger.warning("Task %s lost its lease before completion", task.id)


async def _execute_and_record(
    task: ScientificTask,
    worker_id: str,
    lease_lost: asyncio.Event,
    db_path: str | None,
) -> None:
    """Execute a claimed task and durably record its outcome."""
    try:
        # Tag every record emitted while this task runs with its run id. The
        # execution coroutine is created inside this context, so the copied
        # contextvar propagates to it (and to any node task it spawns).
        with run_log_context(task.run_id):
            result = await _execute_until_lease_lost(
                task, lease_lost, db_path=db_path
            )
    except _LeaseLostError:
        # The durable row already records cancellation, pause, or competing
        # ownership; the revoked worker must not overwrite that outcome.
        logger.info("Task %s stopped after lease revocation", task.id)
        return
    except Exception as exc:  # Worker boundary isolates one task failure.
        _handle_task_failure(task, worker_id, exc, db_path)
        return
    _record_success(task, worker_id, result, db_path)


async def _run_claimed_task(
    task: ScientificTask,
    worker_id: str,
    *,
    db_path: str | None,
    lease_seconds: float,
) -> None:
    """Execute one claimed task, renewing its lease until it settles."""
    stop_heartbeat = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        _heartbeat_lease(
            task,
            worker_id,
            stop_heartbeat,
            lease_lost,
            db_path=db_path,
            lease_seconds=lease_seconds,
        )
    )
    try:
        await _execute_and_record(task, worker_id, lease_lost, db_path)
    finally:
        stop_heartbeat.set()
        await heartbeat


async def run_once(
    worker_id: str,
    *,
    run_id: str | None = None,
    db_path: str | None = None,
    lease_seconds: float = 300.0,
) -> bool:
    """Lease and execute one ready task, returning whether work was found."""
    task = store.claim_task(
        worker_id,
        lease_seconds=lease_seconds,
        run_id=run_id,
        db_path=db_path,
    )
    if task is None:
        return False
    await _run_claimed_task(
        task, worker_id, db_path=db_path, lease_seconds=lease_seconds
    )
    return True


async def run_run_until_idle(
    run_id: str,
    worker_id: str,
    *,
    db_path: str | None = None,
    lease_seconds: float = 300.0,
) -> None:
    """Consume a run's task chain until no ready task remains."""
    while True:
        worked = await run_once(
            worker_id,
            run_id=run_id,
            db_path=db_path,
            lease_seconds=lease_seconds,
        )
        if not worked:
            return


async def _cohort_worker_step(
    run_id: str,
    worker_id: str,
    *,
    db_path: str | None,
    lease_seconds: float,
    poll_seconds: float,
) -> bool:
    """Run one poll/claim/idle cycle for a cohort worker.

    One read-only snapshot answers both idle-tick questions -- claim only
    when work is visible, and exit only when neither claimable work nor a
    sibling's live lease remains. Other cohort members may still be
    executing parent tasks that will materialize new fan-out work; remain
    available until every lease is acknowledged. Queued-but-unclaimable
    work with no live lease cannot make progress and is left for
    retry/reconciliation. Existence checks rather than listings: this runs
    twenty times a second per idle worker, and decoding every row of a
    late-stage run's task table to compute one boolean is work that grows
    as the run does.

    Returns whether the worker should keep polling.
    """
    claimable, active_lease = store.cohort_poll(run_id, db_path=db_path)
    if claimable and await run_once(
        worker_id, run_id=run_id, db_path=db_path, lease_seconds=lease_seconds
    ):
        return True
    if claimable or active_lease:
        await asyncio.sleep(poll_seconds)
        return True
    return False


async def run_run_worker_pool(
    run_id: str,
    worker_prefix: str,
    *,
    worker_count: int | None = None,
    db_path: str | None = None,
    poll_seconds: float = 0.05,
    lease_seconds: float = 300.0,
) -> None:
    """Consume one run with a bounded cohort that survives dynamic fan-out."""
    if worker_count is None:
        worker_count = settings.worker_pool_size
    if worker_count < 1:
        raise ValueError("worker_count must be positive")

    async def _worker(index: int) -> None:
        """Poll and claim work for one cohort member until idle-exit."""
        worker_id = f"{worker_prefix}:{index}"
        while await _cohort_worker_step(
            run_id,
            worker_id,
            db_path=db_path,
            lease_seconds=lease_seconds,
            poll_seconds=poll_seconds,
        ):
            continue

    await asyncio.gather(*(_worker(index) for index in range(worker_count)))


def run_run_worker_pool_sync(run_id: str, worker_prefix: str) -> None:
    """Run the embedded cohort on a worker thread, outside the API loop."""
    asyncio.run(run_run_worker_pool(run_id, worker_prefix))


async def _heartbeat_lease(
    task: ScientificTask,
    worker_id: str,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
    *,
    db_path: str | None,
    lease_seconds: float,
) -> None:
    """Renew periodically until execution finishes or ownership is lost."""
    # Two different cadences. Wake at least once a second so explicit
    # cancellation interrupts expensive provider calls promptly even when
    # production leases are long -- but that check is an in-memory event.
    # Only the renewal touches the database, and it is due on the lease's
    # own schedule: a 300-second lease does not need rewriting every second.
    # Tying the two together cost one write per second per in-flight task,
    # and SQLite's single writer has no fair queuing, so a cohort of them
    # starved ordinary API writes until creating a run failed outright.
    renew_every = max(0.05, lease_seconds / 3)
    interval = min(1.0, renew_every)
    due = time.monotonic() + renew_every
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            if time.monotonic() < due:
                continue
            due = time.monotonic() + renew_every
            if not store.renew_task_lease(
                task.id,
                worker_id,
                lease_seconds,
                db_path=db_path,
            ):
                logger.warning(
                    "Task %s lease heartbeat lost ownership", task.id
                )
                lease_lost.set()
                return


async def run_forever(
    worker_id: str,
    *,
    db_path: str | None = None,
    poll_seconds: float = 0.5,
) -> None:
    """Continuously execute leased tasks until the process is cancelled."""
    # The standalone worker runs in its own process without the app lifespan,
    # so install the offline LLM router here too. Idempotent and a harmless
    # passthrough for real models (see main.lifespan).
    from co_scientist.offline_llm import install_offline_router

    install_offline_router()
    while True:
        worked = await run_once(worker_id, db_path=db_path)
        if not worked:
            await asyncio.sleep(poll_seconds)


def _worker_id() -> str:
    """Return a unique, operator-readable worker identity."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone durable worker process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-id", default=_worker_id())
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    args = parser.parse_args(argv)
    asyncio.run(run_forever(args.worker_id, poll_seconds=args.poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

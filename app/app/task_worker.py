"""Standalone durable worker for queued Co-Scientist run tasks."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import socket
import uuid
from collections.abc import Sequence
from typing import Any

from app import engine_adapter, engine_tasks, store
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
        if store.revive_task_for_retry(
            run_id, idempotency_key, db_path=db_path
        ):
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
    except engine_tasks.SupersededTaskError as exc:
        # Competing durable branches can finish after another branch advances
        # the checkpoint. Obsolescence is a successful idempotent outcome, not
        # a scientific failure and must not consume the retry budget.
        result = {"superseded": True, "reason": str(exc)}
        if not store.complete_task(task.id, worker_id, result, db_path=db_path):
            logger.warning("Task %s lost its lease while superseded", task.id)
        else:
            logger.info("Task %s superseded by a newer checkpoint", task.id)
    except UnsupportedTaskError as exc:
        # The only failure retrying cannot fix. Everything else -- notably a
        # provider returning empty content, which the engine raises as a bare
        # ValueError -- falls through to the retryable branch below.
        store.fail_task(
            task.id,
            worker_id,
            str(exc),
            retryable=False,
            db_path=db_path,
        )
        logger.error("Task %s rejected: %s", task.id, exc)
    except Exception as exc:  # Worker boundary isolates one task failure.
        store.fail_task(
            task.id,
            worker_id,
            str(exc),
            retryable=True,
            db_path=db_path,
        )
        logger.exception("Task %s failed", task.id)
    else:
        if not store.complete_task(task.id, worker_id, result, db_path=db_path):
            logger.warning("Task %s lost its lease before completion", task.id)
    finally:
        stop_heartbeat.set()
        await heartbeat
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


async def run_run_worker_pool(
    run_id: str,
    worker_prefix: str,
    *,
    worker_count: int = 4,
    db_path: str | None = None,
    poll_seconds: float = 0.05,
    lease_seconds: float = 300.0,
) -> None:
    """Consume one run with a bounded cohort that survives dynamic fan-out."""
    if worker_count < 1:
        raise ValueError("worker_count must be positive")

    async def _worker(index: int) -> None:
        worker_id = f"{worker_prefix}:{index}"
        while True:
            worked = await run_once(
                worker_id,
                run_id=run_id,
                db_path=db_path,
                lease_seconds=lease_seconds,
            )
            if worked:
                continue
            tasks = store.list_tasks(run_id, db_path=db_path)
            # Other cohort members may still be executing parent tasks that
            # will materialize new fan-out work; remain available until every
            # lease is acknowledged. Queued-but-unclaimable work with no live
            # lease cannot make progress and is left for retry/reconciliation.
            if any(task.status == "leased" for task in tasks):
                await asyncio.sleep(poll_seconds)
                continue
            return

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
    # Poll at least once per second so explicit cancellation interrupts
    # expensive provider calls promptly even when production leases are long.
    interval = min(1.0, max(0.05, lease_seconds / 3))
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
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

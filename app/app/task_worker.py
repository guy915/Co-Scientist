"""Standalone durable worker for queued Co-Scientist run tasks."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import uuid
from collections.abc import Sequence

from app import engine_adapter, store
from app.logging_setup import run_log_context
from app.notifications import deliver_completion_notification
from app.store import RunStatus, ScientificTask

logger = logging.getLogger(__name__)

_WORKFLOW_TASK = "run.workflow"
_EMAIL_TASK = "notification.email"


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
    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    checkpoint_seq = int(checkpoint["seq"]) if checkpoint else 0
    return store.enqueue_task(
        run_id,
        _WORKFLOW_TASK,
        {
            "force_provider": force_provider,
            "resume": resume,
            "checkpoint_seq": checkpoint_seq,
        },
        idempotency_key=f"workflow:{checkpoint_seq}:{int(resume)}",
        priority=100,
        provenance={
            "behavior": "reconstructed",
            "scheduler": "durable-sqlite-worker-v1",
        },
        budget={"lease_seconds": 300},
        max_attempts=3,
        db_path=db_path,
    )


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
        ):
            pass
    final = store.get_run(run.id, db_path=db_path)
    if final is None:
        raise RuntimeError(f"run {run.id} disappeared during execution")
    if final.status == RunStatus.FAILED.value:
        raise RuntimeError(final.error or "workflow failed")
    return {"run_id": run.id, "status": final.status}


async def run_once(
    worker_id: str,
    *,
    db_path: str | None = None,
    lease_seconds: float = 300.0,
) -> bool:
    """Lease and execute one ready task, returning whether work was found."""
    task = store.claim_task(
        worker_id, lease_seconds=lease_seconds, db_path=db_path
    )
    if task is None:
        return False
    try:
        if task.task_type == _WORKFLOW_TASK:
            result = await _execute_workflow_task(task, db_path=db_path)
        elif task.task_type == _EMAIL_TASK:
            result = await deliver_completion_notification(task.inputs)
        else:
            raise ValueError(f"unsupported task type: {task.task_type}")
    except ValueError as exc:
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
        if not store.complete_task(
            task.id, worker_id, result, db_path=db_path
        ):
            logger.warning("Task %s lost its lease before completion", task.id)
    return True


async def run_forever(
    worker_id: str,
    *,
    db_path: str | None = None,
    poll_seconds: float = 0.5,
) -> None:
    """Continuously execute leased tasks until the process is cancelled."""
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
    asyncio.run(
        run_forever(args.worker_id, poll_seconds=args.poll_seconds)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

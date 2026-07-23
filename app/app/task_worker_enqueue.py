"""Run-level enqueue and the legacy in-process workflow task.

Two concerns the worker needs but does not lease: putting a run's first
(or resumed) durable task on the queue, and executing the legacy
``run.workflow`` task type that predates the node-level executor. Split
from ``app.task_worker``, which re-exports every name here so its
namespace (the seam tests and callers patch against) keeps resolving.
"""

from __future__ import annotations

import logging
from typing import Any

from app import engine_adapter, engine_tasks, store
from app.logging_setup import run_log_context
from app.store import RunStatus, ScientificTask

logger = logging.getLogger(__name__)


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
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=idempotency_key,
            priority=100,
            provenance={"scheduled_by": "resume"},
        ),
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
            run.id,
            run.research_goal,
            run.config,
            engine_adapter.WorkflowOptions(
                force_provider=force_provider,
                resume=resume,
                cancelled=stop_signal,  # type: ignore[arg-type]
                # This legacy "run.workflow" task type predates the
                # node-level durable executor (engine_tasks.py) that now
                # drives real engine runs; historically it ran unpaced
                # because the boundary emitter ignored sleep_seconds for the
                # engine path. Pin it explicitly so unifying that pacing
                # (see workflow.py) does not newly slow this path down.
                sleep_seconds=0.0,
            ),
        ):
            pass
    final = store.get_run(run.id, db_path=db_path)
    if final is None:
        raise RuntimeError(f"run {run.id} disappeared during execution")
    if final.status == RunStatus.FAILED.value:
        raise RuntimeError(final.error or "workflow failed")
    return {"run_id": run.id, "status": final.status}

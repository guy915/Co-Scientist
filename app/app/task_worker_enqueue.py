"""Run-level enqueue helpers.

Putting a run's first (or resumed) durable task on the queue is a concern
the worker needs but does not lease. Split from ``app.task_worker``, which
re-exports every name here so its namespace (the seam tests and callers
patch against) keeps resolving.
"""

from __future__ import annotations

import logging
from typing import Any

from app import engine_tasks, store
from app.store import ScientificTask

logger = logging.getLogger(__name__)


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

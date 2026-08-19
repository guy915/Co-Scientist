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


def _resume_predecessor_id(
    checkpoint: dict[str, Any], db_path: str | None
) -> str | None:
    """Return the real task id that produced a checkpoint, if any.

    ``stage`` is ``engine_task:{id}`` (a normal commit) or
    ``engine_task_paused:{id}`` (a cooperative pause) for every checkpoint
    ``_save_node_checkpoint``/``_save_paused_state`` write -- the only
    producers of a ``resume_successor`` field in production -- so the
    trailing segment is exactly the predecessor a portfolio row would
    name in ``dependencies`` (finding F4) had this checkpoint's
    committing task run one commit later instead of crashing.

    That segment is verified against the store rather than trusted on
    format alone: a stage that merely looks like the pattern but names no
    real task (a hand-built checkpoint, in a test or otherwise) would
    anchor the resumed row to a dependency that can never complete,
    wedging it forever behind a gate nothing will ever satisfy.
    """
    stage = str(checkpoint["stage"])
    if not (
        stage.startswith("engine_task:")
        or stage.startswith("engine_task_paused:")
    ):
        return None
    candidate = stage.rsplit(":", 1)[-1]
    return candidate if store.get_task(candidate, db_path=db_path) else None


def _enqueue_resume_task(
    run_id: str,
    checkpoint: dict[str, Any],
    db_path: str | None,
) -> ScientificTask:
    """Re-enqueue the task a checkpoint recorded as its own resume point.

    A checkpoint whose stage names a real predecessor task is keyed and
    anchored exactly as ``app.engine_tasks_portfolio`` would key the same
    edge had the committing task's own worker lived to enqueue it
    (predecessor id, not checkpoint sequence): the same logical successor
    enqueued through two different formats would create two claimable
    rows for one node instead of colliding on ``ON CONFLICT DO NOTHING``,
    and ``app.engine_tasks_node._check_node_task_checkpoint`` validates a
    dependency-anchored row against the checkpoint's recorded successor.

    Every other checkpoint -- one that recorded no ``resume_successor``
    (pre-fix, before that field existed) or whose stage names no real
    task -- has nothing a predecessor-anchored row could validate against,
    so it stays on the original checkpoint-sequence scheme, unchanged
    from before this function had a predecessor-anchored branch at all.
    """
    checkpoint_seq = int(checkpoint["seq"])
    recorded_successor = checkpoint["state"].get("resume_successor")
    task_type = str(recorded_successor or "") or (
        f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
    )
    predecessor_id = _resume_predecessor_id(checkpoint, db_path)
    if recorded_successor and predecessor_id is not None:
        return _enqueue_resume_successor(
            run_id, task_type, predecessor_id, checkpoint_seq, db_path
        )
    return _enqueue_resume_fallback(run_id, task_type, checkpoint_seq, db_path)


def _enqueue_resume_successor(
    run_id: str,
    task_type: str,
    predecessor_id: str,
    checkpoint_seq: int,
    db_path: str | None,
) -> ScientificTask:
    """Resume a checkpoint whose stage names a real predecessor task."""
    idempotency_key = f"{task_type}:after:{predecessor_id}"
    _revive_dead_resume_target(run_id, task_type, idempotency_key, db_path)
    return store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=idempotency_key,
            priority=100,
            dependencies=(predecessor_id,),
            provenance={"scheduled_by": "resume"},
        ),
        db_path=db_path,
    )


def _enqueue_resume_fallback(
    run_id: str, task_type: str, checkpoint_seq: int, db_path: str | None
) -> ScientificTask:
    """Resume a checkpoint on the original checkpoint-sequence scheme."""
    idempotency_key = f"{task_type}:{checkpoint_seq}"
    _revive_dead_resume_target(run_id, task_type, idempotency_key, db_path)
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


def _revive_dead_resume_target(
    run_id: str, task_type: str, idempotency_key: str, db_path: str | None
) -> None:
    """Revive a dead task under this key before re-enqueuing over it.

    The key names the boundary the run stopped at, and it cannot change
    while the run makes no progress -- so if that task already died, an
    enqueue against the same key is a no-op against the existing row and
    the run would be wedged forever, announcing a resume it never
    performs. Reviving is a no-op unless there is a dead task under this
    key.
    """
    if store.revive_task_for_retry(run_id, idempotency_key, db_path=db_path):
        logger.info(
            "Resume revived a dead %s task for run %s", task_type, run_id
        )


def _already_claimable_task(
    run_id: str, db_path: str | None
) -> ScientificTask | None:
    """The engine task a resume should land on, if one already exists.

    Two ways there is one: the run was paused, and un-pausing returned
    its work to the queue; or it is a discovery run a restart
    interrupted, whose queue was never emptied in the first place.
    """
    if store.resume_run_tasks(run_id, db_path=db_path):
        unpaused = [
            task
            for task in store.list_tasks(run_id, db_path=db_path)
            if task.status == "queued"
            and task.task_type.startswith(engine_tasks.ENGINE_TASK_PREFIX)
        ]
        if unpaused:
            return unpaused[0]
    return _interrupted_discovery_task(run_id, db_path)


def _interrupted_discovery_task(
    run_id: str, db_path: str | None
) -> ScientificTask | None:
    """The discovery work a restart left in the queue, if any.

    A discovery run writes no checkpoint, so without this a resume falls
    through to ``enqueue_bootstrap``. That is inert rather than harmful
    -- generation zero's idempotency key already exists, so the enqueue
    hands back the succeeded bootstrap row and creates nothing -- but it
    means the resume reports landing on a task nobody can claim, which
    is precisely the "wedged run" tell ``runs_lifecycle
    ._queue_resume_workflow`` logs this task to expose. The work is
    already in the queue; name it.
    """
    if not store.has_resumable_discovery_work(run_id, db_path=db_path):
        return None
    return next(
        (
            task
            for task in store.list_tasks(run_id, db_path=db_path)
            if task.status in ("queued", "leased")
            and task.task_type.startswith(engine_tasks.ENGINE_TASK_PREFIX)
        ),
        None,
    )


def enqueue_run_workflow(
    run_id: str,
    *,
    force_provider: str | None = None,
    resume: bool = False,
    db_path: str | None = None,
) -> ScientificTask:
    """Enqueue one idempotent workflow attempt for a run."""
    if resume:
        claimable = _already_claimable_task(run_id, db_path)
        if claimable is not None:
            return claimable
    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    if resume and checkpoint:
        return _enqueue_resume_task(run_id, checkpoint, db_path)
    return engine_tasks.enqueue_bootstrap(run_id, db_path=db_path)

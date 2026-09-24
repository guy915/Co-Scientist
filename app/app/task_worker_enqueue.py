"""Run-level enqueue helpers.

Putting a run's first (or resumed) durable task on the queue is a concern
the worker needs but does not lease. Split from ``app.task_worker``, which
re-exports every name here so its namespace (the seam tests and callers
patch against) keeps resolving.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from app import engine_tasks, store
from app.store import ScientificTask
from app.store.tasks_lifecycle import _DEAD_LEASE_ERROR

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ResumeDB:
    """Database handle shared by one atomic resume decision."""

    path: str | None
    conn: sqlite3.Connection | None = None


@dataclass(frozen=True)
class _CheckpointMatch:
    """The checkpoint facts used to find existing successor work."""

    seq: int
    successor: str
    predecessor_id: str | None
    fanout_source: str | None
    include_predecessor_lease: bool


# Match the persisted marker from ``store.abandon_dead_leases``; exhaustion
# alone can also describe a permanent worker failure on its final attempt.
def is_abandoned_spent_bootstrap(task: ScientificTask) -> bool:
    """Identify the dead-lease failure written by store abandonment."""
    return (
        task.task_type == engine_tasks.BOOTSTRAP_TASK
        and task.status == "failed"
        and task.attempt >= task.max_attempts
        and task.error == _DEAD_LEASE_ERROR
    )


def _resume_predecessor_id(
    checkpoint: dict[str, Any],
    db: _ResumeDB,
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
    return (
        candidate
        if store.get_task(candidate, db_path=db.path, conn=db.conn)
        else None
    )


def _enqueue_resume_task(
    run_id: str,
    checkpoint: dict[str, Any],
    db: _ResumeDB,
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
    predecessor_id = _resume_predecessor_id(checkpoint, db)
    if recorded_successor and predecessor_id is not None:
        return _enqueue_resume_successor(
            run_id, task_type, predecessor_id, checkpoint_seq, db
        )
    return _enqueue_resume_fallback(run_id, task_type, checkpoint_seq, db)


def _enqueue_resume_successor(
    run_id: str,
    task_type: str,
    predecessor_id: str,
    checkpoint_seq: int,
    db: _ResumeDB,
) -> ScientificTask:
    """Resume a checkpoint whose stage names a real predecessor task."""
    idempotency_key = f"{task_type}:after:{predecessor_id}"
    _revive_dead_resume_target(run_id, task_type, idempotency_key, db)
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
        db_path=db.path,
        conn=db.conn,
    )


def _enqueue_resume_fallback(
    run_id: str,
    task_type: str,
    checkpoint_seq: int,
    db: _ResumeDB,
) -> ScientificTask:
    """Resume a checkpoint on the original checkpoint-sequence scheme."""
    idempotency_key = f"{task_type}:{checkpoint_seq}"
    _revive_dead_resume_target(run_id, task_type, idempotency_key, db)
    return store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=idempotency_key,
            priority=100,
            provenance={"scheduled_by": "resume"},
        ),
        db_path=db.path,
        conn=db.conn,
    )


def _revive_dead_resume_target(
    run_id: str,
    task_type: str,
    idempotency_key: str,
    db: _ResumeDB,
) -> None:
    """Revive a dead task under this key before re-enqueuing over it.

    The key names the boundary the run stopped at, and it cannot change
    while the run makes no progress -- so if that task already died, an
    enqueue against the same key is a no-op against the existing row and
    the run would be wedged forever, announcing a resume it never
    performs. Reviving is a no-op unless there is a dead task under this
    key.
    """
    if store.revive_task_for_retry(
        run_id, idempotency_key, db_path=db.path, conn=db.conn
    ):
        logger.info(
            "Resume revived a dead %s task for run %s", task_type, run_id
        )


def _is_live_engine_resume_row(task: ScientificTask, now: float) -> bool:
    """Return whether an engine row is queued or can still be leased again."""
    if not task.task_type.startswith(engine_tasks.ENGINE_TASK_PREFIX):
        return False
    if task.status == "queued":
        return True
    return task.status == "leased" and (
        task.lease_expires_at is None
        or task.lease_expires_at > now
        or task.attempt < task.max_attempts
    )


def _matches_checkpoint_target(
    task: ScientificTask,
    checkpoint_seq: int,
    successor: str,
    predecessor_id: str | None,
    *,
    include_predecessor_lease: bool = True,
) -> bool:
    """Return whether a task is the checkpoint's direct queued successor."""
    if (
        include_predecessor_lease
        and task.id == predecessor_id
        and task.status == "leased"
    ):
        return True
    if not successor or task.task_type != successor:
        return False
    if predecessor_id is None:
        return task.inputs.get("checkpoint_seq") == checkpoint_seq
    return predecessor_id in task.dependencies


def _is_checkpoint_fanout_row(
    task: ScientificTask,
    checkpoint_seq: int,
    predecessor_type: str | None,
) -> bool:
    """Return whether a row belongs to the fan-out for this checkpoint."""
    return (
        predecessor_type is not None
        and task.inputs.get("checkpoint_seq") == checkpoint_seq
        and task.provenance.get("scheduled_by") == predecessor_type
    )


def _revive_spent_checkpoint_writer(
    run_id: str,
    predecessor: ScientificTask | None,
    now: float,
    db: _ResumeDB,
) -> None:
    """Replay an expired writer whose spent lease blocks its successor."""
    if (
        predecessor is None
        or predecessor.status != "leased"
        or predecessor.lease_expires_at is None
        or predecessor.lease_expires_at > now
        or predecessor.attempt < predecessor.max_attempts
    ):
        return
    if store.revive_task_for_retry(
        run_id,
        predecessor.idempotency_key,
        db_path=db.path,
        conn=db.conn,
    ):
        logger.info(
            "Resume revived spent checkpoint writer %s for run %s",
            predecessor.task_type,
            run_id,
        )


def _matching_checkpoint_rows(
    tasks: list[ScientificTask],
    match: _CheckpointMatch,
    now: float,
) -> list[ScientificTask]:
    """Collect queued or leased rows matching this checkpoint's work."""
    return [
        task
        for task in tasks
        if _is_live_engine_resume_row(task, now)
        and (
            _matches_checkpoint_target(
                task,
                match.seq,
                match.successor,
                match.predecessor_id,
                include_predecessor_lease=match.include_predecessor_lease,
            )
            or _is_checkpoint_fanout_row(task, match.seq, match.fanout_source)
        )
    ]


def _find_checkpoint_resume_task(
    run_id: str,
    tasks: list[ScientificTask],
    checkpoint: dict[str, Any],
    db: _ResumeDB,
) -> ScientificTask | None:
    """Find live work directly tied to a checkpoint or its fan-out wave."""
    checkpoint_seq = int(checkpoint["seq"])
    predecessor_id = _resume_predecessor_id(checkpoint, db)
    predecessor = (
        store.get_task(predecessor_id, db_path=db.path, conn=db.conn)
        if predecessor_id is not None
        else None
    )
    if predecessor is not None and predecessor.run_id != run_id:
        predecessor = None
        predecessor_id = None
    successor = str(checkpoint["state"].get("resume_successor") or "")
    fanout_source = successor or (
        predecessor.task_type if predecessor is not None else None
    )
    now = time.time()
    _revive_spent_checkpoint_writer(run_id, predecessor, now, db)
    paused_stage = str(checkpoint["stage"]).startswith("engine_task_paused:")
    match = _CheckpointMatch(
        checkpoint_seq,
        successor,
        predecessor_id,
        fanout_source,
        include_predecessor_lease=not paused_stage,
    )
    matching = _matching_checkpoint_rows(tasks, match, now)
    queued = next((task for task in matching if task.status == "queued"), None)
    return queued or next(iter(matching), None)


def _already_claimable_task(
    run_id: str,
    db: _ResumeDB,
) -> ScientificTask | None:
    """Find work already attached to the latest resumable checkpoint.

    A pause can race a leased task's commit: the API parks rows already in
    the queue, while that worker may enqueue checkpoint successors after
    the pause transaction. Such rows need no requeue, and using the
    checkpoint sequence plus its predecessor avoids mistaking an older
    portfolio guess for the current continuation. A live lease that wrote
    the latest checkpoint is also already doing the continuation.
    """
    unpaused = store.resume_run_tasks(run_id, db_path=db.path, conn=db.conn)
    checkpoint = store.get_latest_checkpoint(
        run_id, db_path=db.path, conn=db.conn
    )
    tasks = store.list_tasks(run_id, db_path=db.path, conn=db.conn)

    if checkpoint is None:
        # Safety holds can park an engine task before the run has a
        # checkpoint. Preserve that pre-checkpoint resume path.
        return next(
            (
                task
                for task in tasks
                if unpaused
                and task.status == "queued"
                and task.task_type.startswith(engine_tasks.ENGINE_TASK_PREFIX)
            ),
            None,
        )

    return _find_checkpoint_resume_task(run_id, tasks, checkpoint, db)


def _enqueue_resumed_workflow(
    run_id: str,
    db: _ResumeDB,
    *,
    revive_failed_precheckpoint_bootstrap: bool = False,
) -> ScientificTask:
    """Discover or enqueue resume work under the same write lock."""
    existing = _already_claimable_task(run_id, db)
    if existing is not None:
        return existing
    checkpoint = store.get_latest_checkpoint(
        run_id, db_path=db.path, conn=db.conn
    )
    if checkpoint is not None:
        return _enqueue_resume_task(run_id, checkpoint, db)
    _revive_spent_precheckpoint_bootstrap(
        run_id,
        db,
        allow_failed=revive_failed_precheckpoint_bootstrap,
    )
    return engine_tasks.enqueue_bootstrap(run_id, db_path=db.path, conn=db.conn)


def _revive_spent_precheckpoint_bootstrap(
    run_id: str,
    db: _ResumeDB,
    *,
    allow_failed: bool = False,
) -> None:
    """Revive an eligible bootstrap, leaving live/retryable leases to claim."""
    bootstrap = next(
        (
            task
            for task in store.list_tasks(run_id, db_path=db.path, conn=db.conn)
            if task.task_type == engine_tasks.BOOTSTRAP_TASK
        ),
        None,
    )
    if (
        bootstrap is None
        or (
            bootstrap.status == "leased"
            and bootstrap.attempt < bootstrap.max_attempts
        )
        or bootstrap.status not in {"leased", "failed"}
        or (
            bootstrap.status == "failed"
            and (
                not allow_failed or not is_abandoned_spent_bootstrap(bootstrap)
            )
        )
    ):
        return
    _revive_dead_resume_target(
        run_id,
        bootstrap.task_type,
        bootstrap.idempotency_key,
        db,
    )


def enqueue_run_workflow(
    run_id: str,
    *,
    force_provider: str | None = None,
    resume: bool = False,
    revive_failed_precheckpoint_bootstrap: bool = False,
    db_path: str | None = None,
) -> ScientificTask:
    """Enqueue one idempotent workflow attempt for a run."""
    if resume:
        with store.transaction(db_path) as conn:
            return _enqueue_resumed_workflow(
                run_id,
                _ResumeDB(db_path, conn),
                revive_failed_precheckpoint_bootstrap=revive_failed_precheckpoint_bootstrap,
            )
    return engine_tasks.enqueue_bootstrap(run_id, db_path=db_path)

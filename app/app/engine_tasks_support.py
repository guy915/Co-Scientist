"""Shared plumbing for the durable engine-task modules.

The task-type vocabulary and the checkpoint save/enqueue/restore
helpers used by every ``engine_tasks_*`` module. Split from
``app.engine_tasks``, which re-exports these names, so the
fan-out/ranking/gate modules can share them without an import cycle
back into the dispatcher. The node-completion emitters moved on to
``app.engine_tasks_emit`` and are re-exported below.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app import store
from app.engine_adapter.opts import _build_engine_opts, _build_generator
from app.engine_adapter.provider import _import_hypothesis_generator
from app.engine_tasks_context import ExactSuccessor, TaskCommit
from app.engine_tasks_emit import (
    NodeCompletion as NodeCompletion,
)
from app.engine_tasks_emit import (
    _emit_node_completion as _emit_node_completion,
)
from app.engine_tasks_emit import (
    _emit_node_milestone as _emit_node_milestone,
)
from app.engine_tasks_emit import (
    _plain_final_state as _plain_final_state,
)
from app.report_render import make_emitter as make_emitter
from app.run_modes import resolved_run_config
from app.store import ScientificTask

# Every durable task type in the engine-workflow family shares this
# prefix (bootstrap, node dispatch, finalize, fan-out, ranking) as
# opposed to unrelated task types like "notification.email". Callers
# that only need "does this run still have engine work" (the run
# lifecycle router, the standalone worker) match against this rather
# than the fine-grained task types below.
ENGINE_TASK_PREFIX = "engine."
_CHECKPOINT_PROVIDER = "engine"
BOOTSTRAP_TASK = "engine.bootstrap"
NODE_TASK_PREFIX = "engine.node."
FINALIZE_TASK = "engine.finalize"
REVIEW_ITEM_TASK = "engine.fanout.review.item"
REVIEW_AGGREGATE_TASK = "engine.fanout.review.aggregate"
VERIFICATION_ITEM_TASK = "engine.fanout.verification.item"
VERIFICATION_AGGREGATE_TASK = "engine.fanout.verification.aggregate"
RANKING_MATCH_TASK = "engine.ranking.match"
RANKING_FINALIZE_TASK = "engine.ranking.finalize"
# Emit tournament progress every Nth match rather than once per match. A match
# is its own durable task taking roughly a minute, so a full tournament runs
# for tens of minutes; without this it committed real work the whole time and
# emitted nothing, leaving the live-activity feed showing a healthy run as
# frozen. Per-match events would fix the silence but flood the feed, which
# renders only the newest handful of events and would lose every other phase.
RANKING_PROGRESS_EVERY = 5
GENERATION_STRATEGY_TASK = "engine.fanout.generation.strategy"
GENERATION_AGGREGATE_TASK = "engine.fanout.generation.aggregate"
MATURE_REFLECTION_ITEM_TASK = "engine.fanout.reflection.item"
MATURE_REFLECTION_AGGREGATE_TASK = "engine.fanout.reflection.aggregate"


class SupersededTaskError(RuntimeError):
    """Signals that a newer checkpoint made a leased task obsolete."""


def _require_run(task: ScientificTask, db_path: str | None) -> store.RunRow:
    """Return the task's run or raise if it has been deleted."""
    run = store.get_run(task.run_id, db_path=db_path)
    if run is None:
        raise RuntimeError(f"run {task.run_id} no longer exists")
    return run


def _require_item_task(
    item_id: Any, db_path: str | None, *, kind: str
) -> ScientificTask:
    """Return a fan-out item task or raise if it has vanished mid-flight."""
    item = store.get_task(str(item_id), db_path=db_path)
    if item is None:
        raise RuntimeError(f"{kind} {item_id} disappeared")
    return item


def _successor_task_type(successor: str | None) -> str:
    """Map a node successor to its durable task type (finalize when None)."""
    if successor is None:
        return FINALIZE_TASK
    return f"{NODE_TASK_PREFIX}{successor}"


def _generator_and_opts(
    task: ScientificTask, db_path: str | None
) -> tuple[Any, dict[str, Any]]:
    from app.credentials import get_run_credential

    run = _require_run(task, db_path)
    cfg = resolved_run_config(run.config)
    generator = _build_generator(
        _import_hypothesis_generator(),
        cfg,
        offline=store.run_used_offline(run),
        byok=get_run_credential(task.run_id, db_path=db_path),
    )
    return generator, _build_engine_opts(cfg, run.id, db_path)


def _generator_for_restore(task: ScientificTask, db_path: str | None) -> Any:
    """Build a registry-compatible generator without consuming steering."""
    from app.credentials import get_run_credential

    run = _require_run(task, db_path)
    return _build_generator(
        _import_hypothesis_generator(),
        resolved_run_config(run.config),
        offline=store.run_used_offline(run),
        byok=get_run_credential(task.run_id, db_path=db_path),
    )


def _enqueue_node_successor(
    task: ScientificTask,
    state: dict[str, Any],
    successor_type: str,
    checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> ScientificTask:
    """Enqueue a node's successor, applying any Supervisor queue actions.

    Supervisor queue mutations are applied inside the same transaction as
    the successor enqueue so both observe the same checkpoint commit.
    """
    is_orchestrator = task.task_type == f"{NODE_TASK_PREFIX}orchestrator"
    if is_orchestrator:
        _apply_supervisor_queue_actions(
            task.run_id, state.get("supervisor_queue_actions") or [], conn
        )
    priority = (
        int(state.get("next_task_priority", 90)) if is_orchestrator else 90
    )
    return store.enqueue_task(
        store.NewTask(
            run_id=task.run_id,
            task_type=successor_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{successor_type}:{checkpoint_seq}",
            priority=store.clamp_task_priority(priority),
            dependencies=(task.id,),
            provenance={"scheduled_by": task.task_type},
        ),
        conn=conn,
    )


def _save_node_checkpoint(
    task: ScientificTask,
    envelope: dict[str, Any],
    successor_type: str,
    expected_checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> int:
    """Commit one node's checkpoint inside the caller's transaction.

    ``resume_successor`` names the task that this checkpoint's committed
    state feeds into next, so a crash-resume re-enqueues the right node
    rather than the orchestrator default in
    ``task_worker.enqueue_run_workflow``. It matches the successor enqueued
    right after (same type, same checkpoint_seq), so its idempotency key is
    identical and resume resolves to that exact already-queued task instead
    of creating a second one. Without it, a run interrupted right after
    bootstrap resumed at the orchestrator with no supervisor_guidance in
    state and failed in generation. The cooperative-pause path
    (``_save_paused_state``) already records this; this closes that gap.
    """
    from co_scientist.checkpoint import CHECKPOINT_VERSION

    latest = store.get_latest_checkpoint(task.run_id, conn=conn)
    latest_seq = int(latest["seq"]) if latest else 0
    if latest_seq != expected_checkpoint_seq:
        raise RuntimeError(
            "checkpoint changed while scientific task was executing"
        )
    return store.save_checkpoint(
        task.run_id,
        store.NewCheckpoint(
            stage=f"engine_task:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={
                "provider": _CHECKPOINT_PROVIDER,
                "resume_successor": successor_type,
                **envelope,
            },
        ),
        conn=conn,
    )


def _save_state_and_enqueue(
    task: ScientificTask,
    state: dict[str, Any],
    successor: str | None,
    *,
    expected_checkpoint_seq: int,
    db_path: str | None,
) -> tuple[int, str | None]:
    """Atomically checkpoint one node effect and enqueue its successor."""
    from co_scientist.checkpoint import serialize_workflow_state

    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    successor_type = _successor_task_type(successor)
    with store.transaction(db_path) as conn:
        checkpoint_seq = _save_node_checkpoint(
            task, envelope, successor_type, expected_checkpoint_seq, conn
        )
        successor_task = _enqueue_node_successor(
            task, state, successor_type, checkpoint_seq, conn
        )
    return checkpoint_seq, successor_task.id


def _apply_single_queue_action(
    task_id: str,
    action: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Apply one bounded queue mutation the Supervisor requested."""
    reason = str(action.get("reason") or "Supervisor queue update")
    kind = action.get("action")
    if kind == "cancel":
        store.cancel_task(task_id, reason=reason, conn=conn)
        return
    if kind == "retry":
        store.retry_task(task_id, reason=reason, conn=conn)
        return
    priority = action.get("priority")
    if kind == "reprioritize" and priority is not None:
        store.reprioritize_task(
            task_id, int(priority), reason=reason, conn=conn
        )


def _apply_supervisor_queue_actions(
    run_id: str,
    actions: list[dict[str, Any]],
    conn: sqlite3.Connection,
) -> None:
    """Apply bounded same-run queue mutations inside the checkpoint commit."""
    known_ids = {task.id for task in store.list_tasks(run_id, conn=conn)}
    for action in actions[:8]:
        task_id = str(action.get("task_id") or "")
        if task_id in known_ids:
            _apply_single_queue_action(task_id, action, conn)


def _durable_queue_snapshot(
    run_id: str, db_path: str | None
) -> list[dict[str, Any]]:
    """Return the bounded queue state the Supervisor may safely mutate."""
    return [
        {
            "task_id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "priority": task.priority,
            "attempt": task.attempt,
            "max_attempts": task.max_attempts,
            "dependencies": list(task.dependencies),
            "error": task.error,
        }
        for task in store.list_tasks(run_id, db_path=db_path)[-100:]
        if task.status in {"queued", "leased", "paused", "failed"}
    ]


def _save_exact_checkpoint(
    task: ScientificTask,
    envelope: dict[str, Any],
    expected_checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> int:
    """Commit one checkpoint for a non-node scientific task."""
    from co_scientist.checkpoint import CHECKPOINT_VERSION

    latest = store.get_latest_checkpoint(task.run_id, conn=conn)
    latest_seq = int(latest["seq"]) if latest else 0
    if latest_seq != expected_checkpoint_seq:
        raise RuntimeError("checkpoint changed during scientific task")
    return store.save_checkpoint(
        task.run_id,
        store.NewCheckpoint(
            stage=f"engine_task:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={"provider": _CHECKPOINT_PROVIDER, **envelope},
        ),
        conn=conn,
    )


def _enqueue_exact_successor(
    task: ScientificTask,
    successor: ExactSuccessor,
    checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> ScientificTask:
    """Enqueue a non-node scientific task at an exact checkpoint sequence."""
    inputs = {**successor.inputs, "checkpoint_seq": checkpoint_seq}
    return store.enqueue_task(
        store.NewTask(
            run_id=task.run_id,
            task_type=successor.task_type,
            inputs=inputs,
            idempotency_key=successor.idempotency_key.format(
                checkpoint_seq=checkpoint_seq
            ),
            priority=86,
            dependencies=(task.id,),
            provenance={"scheduled_by": task.task_type},
        ),
        conn=conn,
    )


def _save_state_and_enqueue_exact(
    commit: TaskCommit,
    state: dict[str, Any],
    successor: ExactSuccessor,
) -> tuple[int, str]:
    """Checkpoint one effect and enqueue a non-node scientific task.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        state: Workflow state to serialize into the checkpoint.
        successor: The non-node task to enqueue against the new checkpoint.

    Returns:
        A tuple of (committed checkpoint sequence, successor task id).
    """
    from co_scientist.checkpoint import serialize_workflow_state

    task = commit.task
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(
            task.run_id, db_path=commit.db_path
        ),
    )
    with store.transaction(commit.db_path) as conn:
        checkpoint_seq = _save_exact_checkpoint(
            task, envelope, commit.current_seq, conn
        )
        enqueued = _enqueue_exact_successor(
            task, successor, checkpoint_seq, conn
        )
    return checkpoint_seq, enqueued.id


def _save_paused_state(
    task: ScientificTask,
    state: dict[str, Any],
    resume_successor: str,
    *,
    expected_checkpoint_seq: int,
    db_path: str | None,
) -> int:
    """Checkpoint an in-flight task without making successor work claimable."""
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    with store.transaction(db_path) as conn:
        latest = store.get_latest_checkpoint(task.run_id, conn=conn)
        latest_seq = int(latest["seq"]) if latest else 0
        if latest_seq != expected_checkpoint_seq:
            raise RuntimeError("checkpoint changed while pausing task")
        return store.save_checkpoint(
            task.run_id,
            store.NewCheckpoint(
                stage=f"engine_task_paused:{task.id}",
                schema_version=CHECKPOINT_VERSION,
                last_event_seq=envelope["last_event_seq"],
                state={
                    "provider": _CHECKPOINT_PROVIDER,
                    "resume_successor": resume_successor,
                    **envelope,
                },
            ),
            conn=conn,
        )


def _latest_task_checkpoint(
    task: ScientificTask, db_path: str | None
) -> tuple[dict[str, Any], int]:
    checkpoint = store.get_latest_checkpoint(task.run_id, db_path=db_path)
    if checkpoint is None:
        raise RuntimeError("specialist task has no workflow checkpoint")
    return checkpoint, int(checkpoint["seq"])


def _replay_or_supersede(
    task: ScientificTask,
    db_path: str | None,
    *,
    label: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], int]:
    """Guard a leased task against replay or a superseding checkpoint.

    Shared by every scientific-task executor that expects to run against an
    exact checkpoint sequence (ranking match/finalize, and the review,
    generation, mature-reflection, and verification aggregates). Returns a
    ``(replay_result, checkpoint, current_seq)`` tuple: if ``replay_result``
    is not ``None``, the caller must return it immediately -- this task
    already committed the checkpoint now on record. Otherwise
    ``checkpoint``/``current_seq`` are the task's own checkpoint to restore
    state from. Raises ``SupersededTaskError`` when a different task
    advanced the checkpoint first.
    """
    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return (
            {"checkpoint_seq": current_seq, "replayed": True},
            checkpoint,
            current_seq,
        )
    if current_seq != expected_seq:
        raise SupersededTaskError(f"{label} checkpoint was superseded")
    return None, checkpoint, current_seq


def _restore_item_checkpoint(
    task: ScientificTask, db_path: str | None, *, superseded: str
) -> tuple[dict[str, Any], int]:
    """Restore the read-only workflow state a fan-out item task runs against.

    Rejects a task whose leased checkpoint a newer one has already replaced,
    then rebuilds the immutable state from the current checkpoint.

    Args:
        task: The leased fan-out item task.
        db_path: Optional override for the SQLite database path.
        superseded: Item label for the ``SupersededTaskError`` message.

    Returns:
        The restored workflow state dict and the leased checkpoint sequence.

    Raises:
        SupersededTaskError: When the leased checkpoint was superseded.
    """
    from co_scientist.checkpoint import restore_workflow_state

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if current_seq != expected_seq:
        raise SupersededTaskError(f"{superseded} checkpoint was superseded")
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    return state, expected_seq

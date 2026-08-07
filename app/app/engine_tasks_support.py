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
from app.engine_tasks_context import (
    ExactSuccessor,
    TaskCommit,
    _ack_consumed_steering,
)
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
from app.engine_tasks_metrics import (
    _metrics_snapshot as _metrics_snapshot,
)
from app.engine_tasks_metrics import (
    _performance_assessment as _performance_assessment,
)
from app.engine_tasks_metrics import (
    _plain_metrics as _plain_metrics,
)
from app.engine_tasks_portfolio import (
    _enqueue_node_portfolio as _enqueue_node_portfolio,
)
from app.engine_tasks_queue_actions import (
    _apply_single_queue_action as _apply_single_queue_action,
)
from app.engine_tasks_queue_actions import (
    _apply_supervisor_queue_actions as _apply_supervisor_queue_actions,
)
from app.engine_tasks_queue_actions import (
    _durable_queue_snapshot as _durable_queue_snapshot,
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


class SafetyHoldError(RuntimeError):
    """Signals that a safety gate held the run pending human adjudication.

    Neither a failure nor a completion. The gate did its job, so retrying
    the task cannot change the outcome -- only a reviewer can -- but the
    boundary's work is not done either, and recording it as succeeded is
    what left an approved hold with nothing to claim (a succeeded row is
    never revived, and its idempotency key cannot change while the run
    makes no progress). The worker parks the task instead; approving the
    hold releases it through the ordinary resume path.
    """


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
    ``task_worker.enqueue_run_workflow``. Its own resume-side enqueue
    derives the same predecessor-anchored idempotency key
    (``app.engine_tasks_portfolio``) from this checkpoint's ``stage``, so
    resume resolves to the exact already-queued task instead of creating
    a second one. Without it, a run interrupted right after bootstrap
    resumed at the orchestrator with no supervisor_guidance in state and
    failed in generation. The cooperative-pause path
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
    commit: TaskCommit,
    state: dict[str, Any],
    successor: str | None,
) -> tuple[int, str | None]:
    """Atomically checkpoint one node effect and enqueue its successor.

    Also persists the run's accumulated metrics snapshot in the same
    transaction (finding L14): every node-level, ranking-chain, and
    fan-out-aggregate commit routes through this one function, so a
    single hook here gives a running run's ``GET /api/runs/{id}/metrics``
    live numbers without a second transaction or a poll-driven write.

    The successor enqueue (``app.engine_tasks_portfolio``) also chains
    however much further of the deterministic node run
    ``co_scientist.task_runtime.plan_portfolio`` can already resolve from
    ``state`` (finding F4): a bounded portfolio rather than one task at a
    time, without changing that this transaction still advances the
    checkpoint chain by exactly one commit.
    """
    from co_scientist.checkpoint import serialize_workflow_state

    task, db_path = commit.task, commit.db_path
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    successor_type = _successor_task_type(successor)
    with store.transaction(db_path) as conn:
        checkpoint_seq = _save_node_checkpoint(
            task, envelope, successor_type, commit.current_seq, conn
        )
        successor_task = _enqueue_node_portfolio(
            task, state, successor, successor_type, conn
        )
        _ack_consumed_steering(commit, conn)
        store.save_run_metrics(task.run_id, _metrics_snapshot(state), conn=conn)
    return checkpoint_seq, successor_task.id


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
    commit: TaskCommit,
    state: dict[str, Any],
    resume_successor: str,
) -> int:
    """Checkpoint an in-flight task without making successor work claimable.

    A pause commits the guidance-carrying state as durably as a successor
    commit does, so it retires the same steering in the same transaction.
    """
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    task, db_path = commit.task, commit.db_path
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    with store.transaction(db_path) as conn:
        latest = store.get_latest_checkpoint(task.run_id, conn=conn)
        latest_seq = int(latest["seq"]) if latest else 0
        if latest_seq != commit.current_seq:
            raise RuntimeError("checkpoint changed while pausing task")
        _ack_consumed_steering(commit, conn)
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

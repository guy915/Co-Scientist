"""Cooperative pause checkpoints for durable engine tasks."""

from __future__ import annotations

import sqlite3
from typing import Any

from app import store
from app.engine_tasks.context import TaskCommit, _ack_consumed_steering


def _save_paused_checkpoint(
    commit: TaskCommit,
    state: dict[str, Any],
    resume_successor: str,
    envelope: dict[str, Any],
    conn: sqlite3.Connection,
) -> int:
    """Save paused state inside the task's already-open commit transaction."""
    from co_scientist.checkpoint import CHECKPOINT_VERSION

    from app.engine_tasks.metrics import _metrics_snapshot
    from app.engine_tasks.support import _CHECKPOINT_PROVIDER

    task = commit.task
    latest = store.get_latest_checkpoint(task.run_id, conn=conn)
    latest_seq = int(latest["seq"]) if latest else 0
    if latest_seq != commit.current_seq:
        raise RuntimeError("checkpoint changed while pausing task")
    _ack_consumed_steering(commit, conn, state)
    store.save_run_metrics(task.run_id, _metrics_snapshot(state), conn=conn)
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


def _save_paused_if_requested(
    commit: TaskCommit,
    state: dict[str, Any],
    resume_successor: str,
    envelope: dict[str, Any],
    conn: sqlite3.Connection,
) -> tuple[int, None] | None:
    """Persist the result as paused state when the run is already paused."""
    task = commit.task
    run = conn.execute(
        "SELECT status FROM runs WHERE id=?", (task.run_id,)
    ).fetchone()
    if run is None or run["status"] != store.RunStatus.PAUSED.value:
        return None
    envelope["last_event_seq"] = store.latest_event_seq(task.run_id, conn=conn)
    return (
        _save_paused_checkpoint(
            commit, state, resume_successor, envelope, conn
        ),
        None,
    )


def _save_paused_state(
    commit: TaskCommit,
    state: dict[str, Any],
    resume_successor: str,
) -> int:
    """Checkpoint an in-flight task without making successor work claimable.

    A pause commits the guidance-carrying state as durably as a successor
    commit does, so it retires the same steering in the same transaction.
    """
    from co_scientist.checkpoint import serialize_workflow_state

    from app.engine_tasks.support import assert_task_commit_allowed

    task, db_path = commit.task, commit.db_path
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        envelope["last_event_seq"] = store.latest_event_seq(
            task.run_id, conn=conn
        )
        return _save_paused_checkpoint(
            commit, state, resume_successor, envelope, conn
        )


def _save_paused_state_if_requested(
    commit: TaskCommit,
    state: dict[str, Any],
    resume_successor: str,
) -> int | None:
    """Serialize outside the lock, then atomically check pause and save."""
    from co_scientist.checkpoint import serialize_workflow_state

    from app.engine_tasks.support import assert_task_commit_allowed

    task, db_path = commit.task, commit.db_path
    envelope = serialize_workflow_state(state, last_event_seq=0)
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        paused = _save_paused_if_requested(
            commit, state, resume_successor, envelope, conn
        )
        return paused[0] if paused is not None else None


def _pause_node_task_if_requested(
    commit: TaskCommit,
    run: store.RunRow,
    node_name: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """Checkpoint and pause a node task the operator paused mid-flight.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        run: The task's run row, read for a mid-flight pause.
        node_name: Engine node the paused task was about to run.
        state: Workflow state to checkpoint at the pause point.

    Returns:
        The pause result to return, or ``None`` if the run is not paused.
    """
    if run.status != store.RunStatus.PAUSED.value:
        return None
    checkpoint_seq = _save_paused_state(commit, state, commit.task.task_type)
    return {
        "checkpoint_seq": checkpoint_seq,
        "node": node_name,
        "status": "paused",
    }

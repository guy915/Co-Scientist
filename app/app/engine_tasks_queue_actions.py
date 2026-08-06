"""The bounded queue view and mutations the Supervisor may drive.

Split out of ``engine_tasks_support`` to keep that module on the task
vocabulary and checkpoint plumbing; every name here stays importable from
``app.engine_tasks_support`` via re-export, so existing import sites and
monkeypatch seams are unaffected.

Both halves are deliberately bounded. The snapshot the Supervisor reads is
capped and filtered to unfinished work, and the mutations it may request
are capped per commit and checked against the run's own task ids -- a
planner acting on another run's queue is not a decision this system lets
the model make.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app import store


def _apply_single_queue_action(
    task_id: str,
    action: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Apply one bounded queue mutation the Supervisor requested.

    Args:
        task_id: Id of the task to mutate; already checked to be this run's.
        action: The requested action, with its kind under ``action``.
        conn: The open connection of the checkpoint commit.
    """
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
    """Apply bounded same-run queue mutations inside the checkpoint commit.

    Args:
        run_id: The run whose queue the Supervisor may mutate.
        actions: Requested actions; only the first few are honored.
        conn: The open connection of the checkpoint commit.
    """
    known_ids = {task.id for task in store.list_tasks(run_id, conn=conn)}
    for action in actions[:8]:
        task_id = str(action.get("task_id") or "")
        if task_id in known_ids:
            _apply_single_queue_action(task_id, action, conn)


def _durable_queue_snapshot(
    run_id: str, db_path: str | None
) -> list[dict[str, Any]]:
    """Return the bounded queue state the Supervisor may safely mutate.

    Args:
        run_id: The run whose queue to summarize.
        db_path: Optional override for the SQLite database path.

    Returns:
        One plain dict per unfinished task, newest hundred only.
    """
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

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


def _cascade_cancel_downstream(
    task_id: str,
    candidates: list[Any],
    conn: sqlite3.Connection,
) -> None:
    """Cancel any portfolio lookahead chained behind a cancelled task.

    A Supervisor-requested cancel (finding F4) can target a mid-chain
    portfolio row exactly as a diverging outcome or a permanent failure
    can: cancelling it alone would leave anything chained behind it
    ``queued`` forever with a dependency that can now never reach
    ``completed`` -- unclaimable, yet still reading as claimable work to
    the run's worker cohort. Mirrors
    ``app.engine_tasks_portfolio._cancel_stale_planned_chain``; a no-op
    for a task type nothing is ever portfolio-chained behind.
    """
    from app.engine_tasks_portfolio import _cancel_downstream
    from app.engine_tasks_support import NODE_TASK_PREFIX

    _cancel_downstream(candidates, {task_id}, None, NODE_TASK_PREFIX, conn)


def _apply_single_queue_action(
    task_id: str,
    action: dict[str, Any],
    candidates: list[Any],
    conn: sqlite3.Connection,
) -> None:
    """Apply one bounded queue mutation the Supervisor requested.

    Args:
        task_id: Id of the task to mutate; already checked to be this run's.
        action: The requested action, with its kind under ``action``.
        candidates: The run's tasks, read once by the caller and reused
            here so a cancel's downstream cascade needs no extra query.
        conn: The open connection of the checkpoint commit.
    """
    reason = str(action.get("reason") or "Supervisor queue update")
    kind = action.get("action")
    if kind == "cancel":
        if store.cancel_task(task_id, reason=reason, conn=conn):
            _cascade_cancel_downstream(task_id, candidates, conn)
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
    candidates = store.list_tasks(run_id, conn=conn)
    known_ids = {task.id for task in candidates}
    for action in actions[:8]:
        task_id = str(action.get("task_id") or "")
        if task_id in known_ids:
            _apply_single_queue_action(task_id, action, candidates, conn)


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

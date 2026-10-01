"""The bounded queue view and mutations the Supervisor may drive.

Split out of ``engine_tasks.support`` to keep that module on the task
vocabulary and checkpoint plumbing; the names callers use stay importable
from ``app.engine_tasks.support`` via re-export, so existing import sites and
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
    ``app.engine_tasks.portfolio._cancel_stale_planned_chain``; a no-op
    for a task type nothing is ever portfolio-chained behind.
    """
    from app.engine_tasks.portfolio import _cancel_downstream
    from app.engine_tasks.support import NODE_TASK_PREFIX

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


# How many stacked follow-ups one pass may materialize, matching the cap on
# the mutation actions above. ``stack_companions`` emits at most two today
# (the listing's two periodic branches); the cap is here so the bound does
# not depend on that staying true.
_MAX_STACKED_TASKS = 4


def _apply_supervisor_enqueue_actions(
    predecessor: Any,
    actions: list[dict[str, Any]],
    priority: int,
    conn: sqlite3.Connection,
) -> None:
    """Materialize the follow-up tasks one Supervisor pass stacked.

    Listing 01's ``DecideNextSteps`` queues several tasks from one pass.
    The engine's precedence chain returns one and carries the rest as
    ``enqueue`` queue actions (``scheduling.policy.stack_companions``);
    this is where they become durable rows, inside the same commit
    transaction as the mutation actions above.

    Bounded three ways. Only a task the loop-point router can actually
    dispatch is accepted -- the name is resolved through the graph's own
    ``TASK_ROUTES``, so an unrecognized value creates nothing rather than
    an unclaimable row of an invented type. The row is anchored to this
    run's own predecessor, so no pass can reach another run's queue. And
    the count is capped.

    Chained, never fanned: each stacked row is anchored to the row before
    it and only the first to the committing task, because two rows under
    one predecessor are both claimable at once and the checkpoint chain
    has a single writer per commit. Serial also means the run's rate-limit
    park (``task_worker_outcomes._park_rate_limited_task``) applies to a
    stacked task exactly as it does to any other single task: at most one
    of them is ever in flight, so a throttled companion returns to the
    queue without any sibling burning attempts beside it.

    Note what the shared idempotency key buys: a stacked companion the
    router also resolved as the commit's own successor is the *same* edge,
    so ``_enqueue_after`` reuses that row rather than creating a second
    claimable duplicate under a different key. The same holds one hop
    further in -- the second companion's key names the first companion's
    row, which is the key the first's own commit will derive for its
    successor -- so every stacked row collides with the reactive enqueue
    of the edge it stands for, and applying these actions is safe to do
    unconditionally.

    Args:
        predecessor: The committing task the first stacked row depends on.
        actions: The decision's queue actions, mutations included.
        priority: Queue priority for the stacked rows.
        conn: The open connection of the checkpoint commit.
    """
    from co_scientist.scheduling import stacked_task_values
    from co_scientist.workflow_topology import TASK_ROUTES

    from app.engine_tasks.portfolio import _enqueue_after
    from app.engine_tasks.support import NODE_TASK_PREFIX

    for value in stacked_task_values(actions)[:_MAX_STACKED_TASKS]:
        node = TASK_ROUTES.get(value)
        if node is None:
            continue
        predecessor = _enqueue_after(
            predecessor, f"{NODE_TASK_PREFIX}{node}", priority, conn
        )


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

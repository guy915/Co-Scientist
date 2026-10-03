"""Dependency-anchored node-task portfolio enqueue (finding F4)."""

from __future__ import annotations

import sqlite3
from typing import Any

import app.store as store
from app.store import ScientificTask


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
    pass
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
    park (``task_worker.outcomes._park_rate_limited_task``) applies to a
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

    pass
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


def _enqueue_after(
    predecessor: ScientificTask,
    task_type: str,
    priority: int,
    conn: sqlite3.Connection,
) -> ScientificTask:
    """Enqueue one dependency-anchored task, reusing a duplicate if planned.

    The idempotency key is a pure function of ``(task_type,
    predecessor.id)``, so calling this twice for the same logical edge --
    once as a lookahead, once for real -- resolves to one row.
    """
    return store.enqueue_task(
        store.NewTask(
            run_id=predecessor.run_id,
            task_type=task_type,
            inputs={},
            idempotency_key=f"{task_type}:after:{predecessor.id}",
            priority=store.clamp_task_priority(priority),
            dependencies=(predecessor.id,),
            provenance={"scheduled_by": predecessor.task_type},
        ),
        conn=conn,
    )


def _is_stale_dependent(
    candidate: ScientificTask,
    poisoned_ids: set[str],
    protect_type: str | None,
    node_prefix: str,
) -> bool:
    """Return whether ``candidate`` is a superseded portfolio guess.

    ``protect_type`` exempts the real, reused successor at generation
    zero; every later generation passes ``None``, since nothing chained
    behind an already-cancelled row can be a legitimate reuse.
    """
    if candidate.status != "queued":
        return False
    if not candidate.task_type.startswith(node_prefix):
        return False
    if (
        not candidate.dependencies
        or candidate.dependencies[0] not in poisoned_ids
    ):
        return False
    return protect_type is None or candidate.task_type != protect_type


def _cancel_dependents(
    candidates: list[ScientificTask],
    poisoned_ids: set[str],
    protect_type: str | None,
    node_prefix: str,
    conn: sqlite3.Connection,
) -> set[str]:
    """Cancel every queued node row depending directly on a poisoned id.

    Args:
        candidates: The run's tasks, read once and reused across every
            generation of the walk in ``_cancel_stale_planned_chain``.
        poisoned_ids: Ids whose own successor plan is now known wrong.
        protect_type: See ``_is_stale_dependent``.
        node_prefix: The ``engine.node.`` task-type prefix, so a stray
            fan-out item or aggregate row is never mistaken for a
            portfolio guess.
        conn: Open connection of the caller's transaction.

    Returns:
        The cancelled rows' ids, the next generation's poisoned set.
    """
    cancelled: set[str] = set()
    for candidate in candidates:
        if not _is_stale_dependent(
            candidate, poisoned_ids, protect_type, node_prefix
        ):
            continue
        store.cancel_task(
            candidate.id,
            reason="portfolio plan superseded by the real successor",
            conn=conn,
        )
        cancelled.add(candidate.id)
    return cancelled


def _cancel_downstream(
    candidates: list[ScientificTask],
    start_ids: set[str],
    protect_type: str | None,
    node_prefix: str,
    conn: sqlite3.Connection,
) -> None:
    """Cancel every queued node row transitively depending on ``start_ids``.

    Walks generation by generation: each call to ``_cancel_dependents``
    cancels the rows depending directly on the current poisoned set and
    returns their ids as the next generation's poisoned set, so a plan
    superseded at hop one is cancelled all the way to the end of the
    chain it anchored, however many hops deep it reached.
    """
    poisoned = start_ids
    protect = protect_type
    while poisoned:
        poisoned = _cancel_dependents(
            candidates, poisoned, protect, node_prefix, conn
        )
        protect = None


def _cancel_stale_planned_chain(
    task: ScientificTask,
    keep_type: str,
    conn: sqlite3.Connection,
) -> None:
    """Cancel an earlier lookahead guess and its whole downstream tail.

    A portfolio can plan several hops of a node's successor before any
    of those nodes actually run. When the real outcome diverges from the
    plan -- most often a mid-run safety halt (finding J6) that routes to
    finalize instead of the planned next node -- every row the diverged
    guess was itself the anchor for is now equally wrong, transitively,
    however many hops deep the original plan reached. Leaving even one
    of them queued would leave it permanently unclaimable (its
    dependency now never completes) while still reading as claimable
    work to the run's worker cohort, which never lets a run settle.

    Args:
        task: The task whose successor is being decided for real.
        keep_type: The real successor's task type; a queued row of this
            exact type directly under ``task`` is a reuse target, not a
            stale guess.
        conn: Open connection of the caller's transaction.
    """
    from app.engine_tasks.support import NODE_TASK_PREFIX

    candidates = store.list_tasks(task.run_id, conn=conn)
    _cancel_downstream(candidates, {task.id}, keep_type, NODE_TASK_PREFIX, conn)


def cancel_downstream_portfolio_chain(
    task: ScientificTask, db_path: str | None
) -> None:
    """Cancel every queued row chained behind a task that will never commit.

    A task that permanently fails (exhausts its retry budget, or hits
    ``UnsupportedTaskError``) never reaches ``_save_state_and_enqueue``,
    so nothing ever runs ``_cancel_stale_planned_chain`` for it: the
    lookahead rows a portfolio chained behind it would otherwise stay
    ``queued`` forever with a dependency that can now never reach
    ``completed``. Call this from the worker's own failure path
    (``app.task_worker.outcomes``) *before* the task's own failure is
    recorded, in its own transaction, so the run's "settle when nothing
    claimable remains" check (``app.store.tasks.fail_task`` /
    ``app.store.runs_views``, not this module's to change) sees the
    cancelled chain already gone rather than missing its one chance to
    fire and leaving the run non-terminal with no worker left to advance
    it.

    Only call this once a failure is already known to be terminal (no
    retry budget left, or a permanent error kind): cancelling ahead of an
    ordinary retry would strand the chain a *successful* retry still
    needs to reuse.
    """
    from app.engine_tasks.support import NODE_TASK_PREFIX

    with store.transaction(db_path) as conn:
        candidates = store.list_tasks(task.run_id, conn=conn)
        _cancel_downstream(candidates, {task.id}, None, NODE_TASK_PREFIX, conn)


def _enqueue_lookahead_tail(
    head: ScientificTask,
    successor: str,
    state: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Chain the resolvable deterministic hops after ``head`` onto it.

    Each hop the engine's ``plan_portfolio`` can resolve without running
    its own node is anchored to the row this function itself just
    created, never to ``head`` or an unresolved fan-out aggregate, so it
    can never depend on state that does not exist yet.
    """
    from co_scientist.task_runtime import plan_portfolio

    from app.engine_tasks.support import NODE_TASK_PREFIX

    predecessor = head
    for hop in plan_portfolio(successor, state)[1:]:
        predecessor = _enqueue_after(
            predecessor, f"{NODE_TASK_PREFIX}{hop}", 90, conn
        )


def _enqueue_node_portfolio(
    task: ScientificTask,
    state: dict[str, Any],
    successor: str | None,
    successor_type: str,
    conn: sqlite3.Connection,
) -> ScientificTask:
    """Enqueue a node's successor plus its resolvable deterministic tail.

    Applies any Supervisor queue actions carried by an orchestrator
    commit, cancels a previously planned row this outcome superseded,
    enqueues the portfolio's head anchored to ``task``, and chains
    however much further ``plan_portfolio`` can resolve behind it.

    Args:
        task: The task whose commit is deciding a successor.
        state: Workflow state committed by this task.
        successor: The node name ``co_scientist.task_runtime.
            next_task_type`` returned, or ``None`` at the terminal node.
        successor_type: ``successor`` already mapped to its durable task
            type (``engine.finalize`` when ``successor`` is ``None``).
        conn: Open connection of the caller's checkpoint transaction.

    Returns:
        The enqueued (or reused) head task.
    """
    from app.engine_tasks.support import NODE_TASK_PREFIX

    is_orchestrator = task.task_type == f"{NODE_TASK_PREFIX}orchestrator"
    if is_orchestrator:
        _apply_supervisor_queue_actions(
            task.run_id, state.get("supervisor_queue_actions") or [], conn
        )
    priority = (
        int(state.get("next_task_priority", 90)) if is_orchestrator else 90
    )
    _cancel_stale_planned_chain(task, successor_type, conn)
    head = _enqueue_after(task, successor_type, priority, conn)
    if is_orchestrator:
        # After the head, never with the mutation actions above: those run
        # before ``_cancel_stale_planned_chain``, which would sweep a row
        # enqueued there as a superseded plan.
        _apply_supervisor_enqueue_actions(
            task,
            state.get("supervisor_queue_actions") or [],
            priority,
            conn,
        )
    if successor is not None:
        _enqueue_lookahead_tail(head, successor, state, conn)
    return head

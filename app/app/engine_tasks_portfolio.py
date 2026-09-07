"""Dependency-anchored node-task portfolio enqueue (finding F4).

Execution used to enqueue exactly one successor node task per commit,
reactively, once its predecessor had already finished. This module lets
one commit enqueue a bounded run of future ``engine.node.*`` tasks --
the deterministic tail the engine's ``co_scientist.task_runtime.
plan_portfolio`` can already resolve from committed state -- chained by
the durable queue's existing ``dependencies`` gate, so the checkpoint
chain stays exactly as serial as it is today (see
``app.engine_tasks_support._save_state_and_enqueue``, the module's only
caller).

Every row this module creates is keyed ``{task_type}:after:{predecessor
task id}`` rather than by checkpoint sequence. A sequence number is not
known for a lookahead row planned before its predecessor has run, and
keying the *immediate* successor differently (sequence-based) would let
the same logical edge be enqueued twice -- once speculatively by a
lookahead plan, once reactively once the predecessor actually commits --
under two different keys that never collide. The predecessor-id key
collides on ``ON CONFLICT DO NOTHING`` in both cases, so the two
enqueue attempts always resolve to the same row.

A plan can still turn out wrong: state a lookahead walk had no way to
see yet (most notably a mid-run safety halt, finding J6) can make a
predecessor's real successor differ from what was planned two or more
hops earlier. ``_cancel_stale_planned_chain`` removes the abandoned
guess *and everything chained behind it*, in the same transaction as the
real successor. Cancelling only the row directly superseded is not
enough: a row two or more hops into a plan depends on the row one hop
closer, not on the task whose outcome just diverged, so it would stay
``queued`` forever with a dependency that can now never reach
``completed`` -- ``app.store.tasks_probes.cohort_poll`` (not this
module's to change) answers "claimable work exists" from a queued row's
mere existence, dependency-blind by design, so an orphan like that never
lets a run's worker cohort conclude there is nothing left to do. That
is a hang, not a slow settle: this is the regression this module
shipped with the first time.
``app.engine_tasks_node._check_node_task_checkpoint`` is the backstop if
a stale row is ever claimed anyway (it cannot be, once cancelled, but a
row that slips past cancellation for some other reason still cannot
run): it verifies not just that the predecessor committed, but that the
predecessor's own recorded successor names this exact task, and settles
it as superseded otherwise -- the outcome the durable worker already
treats as a benign, idempotent completion.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app import store
from app.engine_tasks_queue_actions import (
    _apply_supervisor_enqueue_actions,
    _apply_supervisor_queue_actions,
)
from app.store import ScientificTask


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
    from app.engine_tasks_support import NODE_TASK_PREFIX

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
    (``app.task_worker_outcomes``) *before* the task's own failure is
    recorded, in its own transaction, so the run's "settle when nothing
    claimable remains" check (``app.store.tasks.fail_task`` /
    ``app.store.runs_reconcile``, not this module's to change) sees the
    cancelled chain already gone rather than missing its one chance to
    fire and leaving the run non-terminal with no worker left to advance
    it.

    Only call this once a failure is already known to be terminal (no
    retry budget left, or a permanent error kind): cancelling ahead of an
    ordinary retry would strand the chain a *successful* retry still
    needs to reuse.
    """
    from app.engine_tasks_support import NODE_TASK_PREFIX

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

    from app.engine_tasks_support import NODE_TASK_PREFIX

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
    from app.engine_tasks_support import NODE_TASK_PREFIX

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

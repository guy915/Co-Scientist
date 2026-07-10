"""Orchestrator node - the adaptive scheduling loop point.

This is the decision node the compiled graph re-enters after each work phase
(PLAN.md Milestone 2). It computes observable statistics from the workflow
state, consults the deterministic scheduling policy, records the decision (with
its reason) into the task-history ledger as data, emits a progress event, and
sets ``next_task`` for the graph's conditional edge to route on.

The decision must happen in a node, not a LangGraph edge function: edge
functions can only read state and return a name, so they cannot record the
reason or emit the event the milestone requires.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models import Hypothesis, phase_message
from co_scientist.nodes.progress import emit_progress
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskRecord,
    TaskStatus,
    TaskType,
    decide_next_task,
    validate_decision,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Progress percentage for the orchestrator decision event. It sits between the
# ranking/deep-verification band and the terminal synthesis so the UI shows
# forward motion each loop.
_PROGRESS_ORCHESTRATOR = 80


def _default_budget(state: WorkflowState) -> Budget:
    """Return the run's compute budget, or one derived from max_iterations.

    A run may configure a full budget via ``state["budget"]``; otherwise the
    only ceiling is the existing ``max_iterations`` satisfied-completion cap.
    """
    raw = state.get("budget")
    if raw:
        return Budget.from_dict(raw)
    return Budget(max_iterations=state.get("max_iterations", 0))


def _init_bookkeeping(hypotheses: list[Hypothesis]) -> dict[str, Any]:
    """Seed orchestrator bookkeeping on the first loop-point decision.

    Anchors the pool sizes to the post-initial-generation pool so the first
    decision sees no proximity backlog and a yield tie — which, with the last
    work task treated as the initial GENERATE, evolves the leaders first
    (matching the established first-iteration behavior) before later cycles
    alternate into generation.
    """
    pool_size = len(hypotheses)
    return {
        # Sentinel so the first decision's Elo comparison never counts as
        # "stable" (there is no prior cycle to be stable against).
        "prev_top_elo": None,
        "rank_stable_cycles": 0,
        "pool_at_last_proximity": pool_size,
        "pool_at_last_decision": pool_size,
        "last_work_task": TaskType.GENERATE.value,
    }


def _yields(pool_size: int, book: dict[str, Any]) -> tuple[float, float]:
    """Return (generation_yield, evolution_yield) from the pool delta.

    The delta since the previous decision is attributed to whichever work task
    ran last: new rows after a GENERATE are generation yield, appended children
    after an EVOLVE are evolution yield. A yield is a simple count of net new
    hypotheses (0 when the last task was maintenance such as proximity).
    """
    delta = max(
        0, pool_size - int(book.get("pool_at_last_decision", pool_size))
    )
    last = book.get("last_work_task")
    if last == TaskType.GENERATE.value:
        return float(delta), 0.0
    if last == TaskType.EVOLVE.value:
        return 0.0, float(delta)
    return 0.0, 0.0


def _rank_stable_cycles(
    top_elo: int, total_matches: int, book: dict[str, Any]
) -> int:
    """Return the updated count of consecutive stable-leaderboard cycles.

    Stability requires at least one match to have been played (an untouched
    initial pool is not "converged") and the top Elo to be unchanged from the
    previous decision. The seeded ``prev_top_elo`` of None (first decision) is
    never stable — there is no prior cycle to compare against.
    """
    prev = book.get("prev_top_elo")
    prior = int(book.get("rank_stable_cycles", 0))
    if total_matches > 0 and prev is not None and top_elo == int(prev):
        return prior + 1
    return 0


def _compute_stats(
    state: WorkflowState, book: dict[str, Any]
) -> SchedulerStats:
    """Derive the scheduler's observable statistics from workflow state.

    Args:
        state: Current workflow state.
        book: Orchestrator bookkeeping from before this decision.

    Returns:
        The statistics the deterministic policy reads.
    """
    hyps: list[Hypothesis] = state["hypotheses"]
    pool_size = len(hyps)
    reviewed = sum(1 for h in hyps if h.reviews)
    total_matches = sum(h.total_matches for h in hyps)
    # Average tournament participations per hypothesis (see SchedulerStats).
    avg_coverage = total_matches / pool_size if pool_size else 0.0
    top_elo = max((h.elo_rating for h in hyps), default=INITIAL_ELO_RATING)
    metrics = state.get("metrics")
    llm_calls = metrics.llm_calls if metrics is not None else 0
    gen_yield, evo_yield = _yields(pool_size, book)
    start = state.get("start_time") or time.time()

    return SchedulerStats(
        pool_size=pool_size,
        reviewed_count=reviewed,
        unreviewed_count=pool_size - reviewed,
        total_matches=total_matches,
        match_coverage=avg_coverage,
        pool_grew_since_proximity=(
            pool_size > int(book.get("pool_at_last_proximity", pool_size))
        ),
        top_elo=top_elo,
        rank_stable_cycles=_rank_stable_cycles(top_elo, total_matches, book),
        generation_yield=gen_yield,
        evolution_yield=evo_yield,
        iteration=state.get("current_iteration", 0),
        last_work_task=_task_type_or_none(book.get("last_work_task")),
        llm_calls=llm_calls,
        tasks_run=len(state.get("task_history", [])),
        elapsed_s=time.time() - start,
        pending_steering=bool(state.get("pending_steering")),
        cancelled=bool(state.get("cancel_requested")),
        safety_blocked=bool(state.get("safety_blocked")),
    )


def _task_type_or_none(value: Any) -> TaskType | None:
    """Coerce a stored task-type string back to its enum, or None."""
    if value is None:
        return None
    return TaskType(value)


def _next_bookkeeping(
    book: dict[str, Any],
    stats: SchedulerStats,
    decision: SupervisorDecision,
) -> dict[str, Any]:
    """Compute the bookkeeping to carry into the next decision.

    Updates the rank-stability counter and previous top Elo, resets the
    proximity anchor after a proximity task, and remembers the pool size and
    the last *work* task (generate/evolve) so the next decision can measure
    yield and break ties.
    """
    updated = dict(book)
    updated["prev_top_elo"] = stats.top_elo
    updated["rank_stable_cycles"] = stats.rank_stable_cycles
    updated["pool_at_last_decision"] = stats.pool_size
    if decision.next_task is TaskType.PROXIMITY:
        updated["pool_at_last_proximity"] = stats.pool_size
    if decision.next_task in (TaskType.GENERATE, TaskType.EVOLVE):
        updated["last_work_task"] = decision.next_task.value
    return updated


def _appended_task_record(
    state: WorkflowState, decision: SupervisorDecision, iteration: int
) -> list[dict[str, Any]]:
    """Return task_history with this decision's record appended."""
    record = TaskRecord(
        task_type=decision.next_task,
        status=(
            TaskStatus.COMPLETED if decision.terminate else TaskStatus.QUEUED
        ),
        reason=decision.reason,
        iteration=iteration,
        termination_reason=decision.termination_reason,
    )
    history = list(state.get("task_history", []))
    history.append(record.to_dict())
    return history


async def orchestrator_node(state: WorkflowState) -> dict[str, Any]:
    """Decide and record the next task at the adaptive loop point.

    Computes observable statistics, consults the deterministic policy
    (validated for allowed transitions), appends a task record with the
    decision's reason, emits a progress event, and sets ``next_task`` for the
    graph's conditional edge.

    Args:
        state: Current workflow state.

    Returns:
        State delta: ``next_task``, appended ``task_history``, updated
        ``orchestrator_state``, ``current_iteration`` (incremented on a work
        task), and ``termination_reason`` when terminating.
    """
    book = state.get("orchestrator_state") or _init_bookkeeping(
        state["hypotheses"]
    )
    stats = _compute_stats(state, book)
    budget = _default_budget(state)

    decision = validate_decision(decide_next_task(stats, budget), stats)

    iteration = state.get("current_iteration", 0)
    # A work cycle (generate/evolve) advances the iteration counter; a
    # maintenance task (proximity/rank/reflect) and termination do not.
    if decision.next_task in (TaskType.GENERATE, TaskType.EVOLVE):
        iteration += 1

    logger.info(
        "Orchestrator scheduled %s (iteration %s): %s",
        decision.next_task.value,
        iteration,
        decision.reason,
    )

    await emit_progress(
        state,
        "orchestrator_decision",
        f"Supervisor scheduled {decision.next_task.value}: {decision.reason}",
        _PROGRESS_ORCHESTRATOR,
        next_task=decision.next_task.value,
        termination_reason=(
            decision.termination_reason.value
            if decision.termination_reason is not None
            else None
        ),
    )

    return {
        "next_task": decision.next_task.value,
        "task_history": _appended_task_record(state, decision, iteration),
        "orchestrator_state": _next_bookkeeping(book, stats, decision),
        "current_iteration": iteration,
        # Steering is a one-shot high-priority request: clear it once the
        # orchestrator has seen it (and scheduled work to incorporate it) so
        # the loop does not re-trigger on the same message.
        "pending_steering": False,
        "termination_reason": (
            decision.termination_reason.value
            if decision.termination_reason is not None
            else None
        ),
        "messages": phase_message(
            "orchestrator",
            decision.reason,
            next_task=decision.next_task.value,
        ),
    }

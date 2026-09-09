"""Orchestrator node - the adaptive scheduling loop point.

This is the decision node the compiled graph re-enters after each work phase.
It computes observable statistics from the workflow
state, consults the deterministic scheduling policy, records the decision (with
its reason) into the task-history ledger as data, emits a progress event, and
sets ``next_task`` for the graph's conditional edge to route on.

The decision must happen in a node, not a LangGraph edge function: edge
functions can only read state and return a name, so they cannot record the
reason or emit the event the milestone requires.

The observable statistics live in ``orchestrator_stats`` and the carried
bookkeeping (including the settlement allowance) in
``orchestrator_bookkeeping``; both are re-exported here for compatibility.
"""

from __future__ import annotations

import dataclasses
import logging
import time as time
from typing import Any

from co_scientist.agents.ranking.ranking_lifecycle import (
    _tournament_round_count as _tournament_round_count,
)
from co_scientist.agents.supervisor.orchestrator_bookkeeping import (
    _init_bookkeeping as _init_bookkeeping,
)
from co_scientist.agents.supervisor.orchestrator_bookkeeping import (
    _initial_settlement_allowance as _initial_settlement_allowance,
)
from co_scientist.agents.supervisor.orchestrator_bookkeeping import (
    _is_settlement_rank as _is_settlement_rank,
)
from co_scientist.agents.supervisor.orchestrator_bookkeeping import (
    _next_bookkeeping as _next_bookkeeping,
)
from co_scientist.agents.supervisor.orchestrator_bookkeeping import (
    _settled_allowance as _settled_allowance,
)
from co_scientist.agents.supervisor.orchestrator_stats import (
    _build_scheduler_stats as _build_scheduler_stats,
)
from co_scientist.agents.supervisor.orchestrator_stats import (
    _compute_stats as _compute_stats,
)
from co_scientist.agents.supervisor.orchestrator_stats import (
    _default_budget as _default_budget,
)
from co_scientist.agents.supervisor.orchestrator_stats import (
    _rank_stable_cycles as _rank_stable_cycles,
)
from co_scientist.agents.supervisor.orchestrator_stats import (
    _rankable_coverage as _rankable_coverage,
)
from co_scientist.agents.supervisor.orchestrator_stats import (
    _scheduler_scalars as _scheduler_scalars,
)
from co_scientist.agents.supervisor.orchestrator_stats import (
    _StatsScalars as _StatsScalars,
)
from co_scientist.agents.supervisor.orchestrator_stats import (
    _task_type_or_none as _task_type_or_none,
)
from co_scientist.agents.supervisor.orchestrator_stats import (
    _yields as _yields,
)
from co_scientist.agents.supervisor.supervisor_decision import (
    WORK_TASKS,
    choose_supervisor_task,
)
from co_scientist.constants import INITIAL_ELO_RATING as INITIAL_ELO_RATING
from co_scientist.constants import PROGRESS_ORCHESTRATOR_DECISION
from co_scientist.models import Hypothesis as Hypothesis
from co_scientist.models import (
    MetricDeltas,
    create_metrics_update,
    phase_message,
)
from co_scientist.progress import emit_progress
from co_scientist.scheduling import Budget as Budget
from co_scientist.scheduling import (
    SchedulerStats,
    SupervisorDecision,
    TaskRecord,
    TaskStatus,
)
from co_scientist.scheduling import TaskType as TaskType
from co_scientist.scheduling import policy as policy
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _DecisionOutcome:
    """One scheduling decision plus its derived recording fields."""

    decision: SupervisorDecision
    decision_provenance: str
    iteration: int
    observable_reason: str
    termination_reason_value: str | None
    # Real LLM calls this decision spent -- 1 when the planner model was
    # consulted, 0 for a hard-stop or required transition (finding L3).
    llm_calls: int = 0


def _appended_task_record(
    state: WorkflowState,
    decision: SupervisorDecision,
    iteration: int,
    observable_reason: str,
) -> list[dict[str, Any]]:
    """Return task_history with this decision's record appended."""
    record = TaskRecord(
        task_type=decision.next_task,
        status=(
            TaskStatus.COMPLETED if decision.terminate else TaskStatus.QUEUED
        ),
        reason=observable_reason,
        iteration=iteration,
        termination_reason=decision.termination_reason,
    )
    history = list(state.get("task_history", []))
    serialized = record.to_dict()
    serialized["priority"] = decision.priority
    # The raw model rationale remains available for operator audit but is not
    # presented as a factual activity summary.
    serialized["planner_reason"] = decision.reason
    history.append(serialized)
    return history


def _observable_decision_reason(
    stats: SchedulerStats,
    decision: SupervisorDecision,
) -> str:
    """Describe an allocation using committed facts instead of model claims."""
    match_count = stats.total_matches // 2
    reason = (
        f"Supervisor selected {decision.next_task.value} from live state: "
        f"{stats.pool_size} hypotheses, {stats.reviewed_count} reviewed, "
        f"{match_count} committed matches, iteration {stats.iteration}."
    )
    if stats.pending_steering:
        reason += " Scientist feedback is pending incorporation."
    return reason


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
    (
        stats,
        decision,
        decision_provenance,
        llm_calls,
    ) = await _run_supervisor_decision(state, book)
    iteration, observable_reason, termination_reason_value = _decision_context(
        state, stats, decision
    )
    outcome = _DecisionOutcome(
        decision=decision,
        decision_provenance=decision_provenance,
        iteration=iteration,
        observable_reason=observable_reason,
        termination_reason_value=termination_reason_value,
        llm_calls=llm_calls,
    )
    return await _finalize_orchestrator_decision(state, book, stats, outcome)


async def _finalize_orchestrator_decision(
    state: WorkflowState,
    book: dict[str, Any],
    stats: SchedulerStats,
    outcome: _DecisionOutcome,
) -> dict[str, Any]:
    """Logs/streams the decision, then assembles the orchestrator_node delta."""
    await _emit_orchestrator_decision(state, outcome)
    return _orchestrator_result(state, book, stats, outcome)


async def _run_supervisor_decision(
    state: WorkflowState, book: dict[str, Any]
) -> tuple[SchedulerStats, SupervisorDecision, str, int]:
    """Computes scheduler stats and budget, then asks the policy to decide."""
    stats = _compute_stats(state, book)
    budget = _default_budget(state)
    decision, decision_provenance, llm_calls = await choose_supervisor_task(
        state, stats, budget
    )
    # Stacking runs after the primary is settled, never inside the policy:
    # the planner's own guards rebuild a decision with
    # ``dataclasses.replace(baseline, queue_actions=...)``, which would drop
    # a companion attached any earlier.
    return (
        stats,
        policy.stack_companions(decision, stats, budget),
        decision_provenance,
        llm_calls,
    )


def _advance_iteration(
    state: WorkflowState, decision: SupervisorDecision
) -> int:
    """Advances current_iteration for a work task; unchanged for maintenance.

    A work cycle (generate/evolve) advances the iteration counter; a
    maintenance task (proximity/rank/reflect) and termination do not.
    """
    iteration = state.get("current_iteration", 0)
    if decision.next_task in WORK_TASKS:
        iteration += 1
    return iteration


def _decision_context(
    state: WorkflowState, stats: SchedulerStats, decision: SupervisorDecision
) -> tuple[int, str, str | None]:
    """Derives the iteration, observable reason, and termination value."""
    iteration = _advance_iteration(state, decision)
    observable_reason = _observable_decision_reason(stats, decision)
    termination_reason_value = (
        decision.termination_reason.value
        if decision.termination_reason is not None
        else None
    )
    return iteration, observable_reason, termination_reason_value


async def _emit_orchestrator_decision(
    state: WorkflowState,
    outcome: _DecisionOutcome,
) -> None:
    """Logs and streams the scheduling decision."""
    decision = outcome.decision
    logger.info(
        "Orchestrator scheduled %s (iteration %s): %s",
        decision.next_task.value,
        outcome.iteration,
        outcome.observable_reason,
    )
    await emit_progress(
        state,
        "orchestrator_decision",
        outcome.observable_reason,
        PROGRESS_ORCHESTRATOR_DECISION,
        next_task=decision.next_task.value,
        termination_reason=outcome.termination_reason_value,
        decision_provenance=outcome.decision_provenance,
    )


def _orchestrator_result(
    state: WorkflowState,
    book: dict[str, Any],
    stats: SchedulerStats,
    outcome: _DecisionOutcome,
) -> dict[str, Any]:
    """Assembles the orchestrator_node state delta."""
    decision = outcome.decision
    return {
        "next_task": decision.next_task.value,
        "next_task_priority": decision.priority,
        "supervisor_queue_actions": list(decision.queue_actions),
        "task_history": _appended_task_record(
            state, decision, outcome.iteration, outcome.observable_reason
        ),
        "orchestrator_state": _next_bookkeeping(
            book, stats, decision, state["hypotheses"]
        ),
        "supervisor_decision_provenance": outcome.decision_provenance,
        "current_iteration": outcome.iteration,
        # Steering is a one-shot high-priority request: clear it once the
        # orchestrator has seen it (and scheduled work to incorporate it) so
        # the loop does not re-trigger on the same message.
        "pending_steering": False,
        "termination_reason": outcome.termination_reason_value,
        "messages": phase_message(
            "orchestrator",
            outcome.observable_reason,
            next_task=decision.next_task.value,
        ),
        # finding L3: previously omitted, so a spent orchestrator planning
        # call never reached the accumulated llm_calls max_llm_calls reads.
        "metrics": create_metrics_update(
            deltas=MetricDeltas(llm_calls=outcome.llm_calls)
        ),
    }

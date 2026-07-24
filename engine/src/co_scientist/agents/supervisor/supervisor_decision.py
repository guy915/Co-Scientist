"""Model-directed Supervisor allocation at each orchestration loop point."""

from __future__ import annotations

import json
import logging
from typing import Any

from co_scientist.constants import MEDIUM_TEMPERATURE
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    decide_next_task,
    required_transition,
    validate_decision,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

_PRODUCTIVE_TASKS = (
    TaskType.GENERATE,
    TaskType.REFLECT,
    TaskType.RANK,
    TaskType.EVOLVE,
    TaskType.PROXIMITY,
)

# Work tasks grow the hypothesis pool and advance the iteration counter, unlike
# maintenance tasks (reflect/rank/proximity). Shared so the orchestrator's
# iteration bookkeeping and the post-budget growth guard here agree on the set.
WORK_TASKS = frozenset({TaskType.GENERATE, TaskType.EVOLVE})

_DECISION_SCHEMA: dict[str, Any] = {
    "name": "supervisor_allocation",
    "schema": {
        "type": "object",
        "properties": {
            "next_task": {
                "type": "string",
                "enum": [task.value for task in _PRODUCTIVE_TASKS],
            },
            "reason": {"type": "string", "minLength": 1},
            "priority": {"type": "integer", "minimum": 0, "maximum": 100},
            "queue_actions": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["reprioritize", "cancel", "retry"],
                        },
                        "task_id": {"type": "string", "minLength": 1},
                        "priority": {
                            "type": ["integer", "null"],
                            "minimum": 0,
                            "maximum": 100,
                        },
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["action", "task_id", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["next_task", "reason"],
        "additionalProperties": False,
    },
}


def _hard_stop(
    stats: SchedulerStats,
    budget: Budget,
    baseline: SupervisorDecision,
) -> SupervisorDecision | None:
    """Return a code-enforced stop that no model allocation may bypass.

    Args:
        stats: Live statistics derived from workflow state.
        budget: The run's hard compute limits.
        baseline: The disclosed scheduler's decision for these same
            stats/budget, reused for the satisfied-completion/convergence
            fall-through rather than recomputed.
    """
    reason = _hard_stop_reason(stats, budget)
    if reason is None:
        # Satisfied completion and convergence are evaluated by the disclosed
        # scheduler predicates after required review/ranking/proximity work.
        return baseline if baseline.terminate else None
    termination_reason, message = reason
    return SupervisorDecision(
        next_task=TaskType.TERMINATE,
        reason=message,
        terminate=True,
        termination_reason=termination_reason,
    )


def _budget_exceeded(limit: float | None, value: float) -> bool:
    """Return whether an optional budget ceiling has been reached or passed."""
    return limit is not None and value >= limit


# Ordered (triggered, reason, message) checks for _hard_stop_reason: the
# first true entry wins, matching the original if/elif precedence exactly.
def _hard_stop_checks(
    stats: SchedulerStats, budget: Budget
) -> tuple[tuple[bool, TerminationReason, str], ...]:
    """Build the ordered hard-stop predicates for these stats/budget."""
    return (
        (stats.cancelled, TerminationReason.CANCELLED, "run cancelled"),
        (
            stats.safety_blocked,
            TerminationReason.SAFETY,
            "safety block halted the run",
        ),
        (
            _budget_exceeded(budget.max_llm_calls, stats.llm_calls),
            TerminationReason.BUDGET,
            "LLM-call budget exhausted",
        ),
        (
            _budget_exceeded(budget.max_tasks, stats.tasks_run),
            TerminationReason.MAX_TASKS,
            "task budget exhausted",
        ),
        (
            _budget_exceeded(budget.max_wall_clock_s, stats.elapsed_s),
            TerminationReason.WALL_CLOCK,
            "wall-clock budget exhausted",
        ),
    )


def _hard_stop_reason(
    stats: SchedulerStats, budget: Budget
) -> tuple[TerminationReason, str] | None:
    """Return the code-enforced termination reason, if any, for these stats."""
    for triggered, reason, message in _hard_stop_checks(stats, budget):
        if triggered:
            return reason, message
    return None


def _planning_prompt(
    state: WorkflowState, stats: SchedulerStats, budget: Budget
) -> str:
    """Build the Supervisor's live allocation prompt from shared memory."""
    context = {
        "research_goal": state["research_goal"],
        "research_plan": state.get("supervisor_guidance") or {},
        "statistics": stats.to_dict(),
        "budget": budget.to_dict(),
        "recent_tasks": state.get("task_history", [])[-12:],
        "meta_review": state.get("meta_review") or {},
        "pending_steering": state.get("pending_steering") or False,
        "held_for_review": len(state.get("held_for_review", [])),
        "durable_task_queue": state.get("durable_task_queue") or [],
    }
    return (
        "You are the adaptive Supervisor for a scientific co-research system. "
        "Allocate the single most valuable next specialist task from generate, "
        "reflect, rank, evolve, or proximity. Use the live state rather than a "
        "fixed phase order. Prioritize unresolved verification and review work "
        "as hypotheses mature, incorporate scientist steering immediately, and "
        "balance exploration against improvement. Explain the observable basis "
        "for the allocation without revealing hidden chain-of-thought. Use "
        "queue_actions only when a listed queued/failed task should be "
        "reprioritized, cancelled as superseded, or retried because state has "
        "materially changed. Never target an unlisted task.\n\n"
        "Live shared memory:\n"
        f"{json.dumps(context, sort_keys=True, default=str)}"
    )


def _repeats_without_iteration_progress(
    state: WorkflowState,
    stats: SchedulerStats,
    proposed: SupervisorDecision,
    baseline: SupervisorDecision,
) -> bool:
    """Detect a model allocation that already ran in the current cycle."""
    if proposed.next_task is baseline.next_task:
        return False
    return any(
        str(record.get("task_type")) == proposed.next_task.value
        and int(record.get("iteration", -1)) == stats.iteration
        for record in state.get("task_history", [])
    )


def _needs_queue_adjudication(state: WorkflowState) -> bool:
    """Return whether a failed durable task needs a model queue action.

    A failed durable task is not revived by anything automatic: the retry
    budget is spent, resume only requeues *paused* rows, and the Supervisor's
    ``queue_actions`` are the sole route back. Skipping the planning call
    while one is pending would strand it for the rest of the run, so a
    failed row makes even a forced transition worth the round-trip.
    """
    return any(
        str(entry.get("status")) == "failed"
        for entry in state.get("durable_task_queue") or ()
    )


async def choose_supervisor_task(
    state: WorkflowState,
    stats: SchedulerStats,
    budget: Budget,
) -> tuple[SupervisorDecision, str]:
    """Choose the next productive task, consulting the model only if needed.

    Hard cancellation, safety, and compute limits are enforced before the
    model call. A malformed or unavailable planning call falls back to the
    existing deterministic policy and records that provenance explicitly.

    Most loop points do not present a choice. The disclosed scheduler's
    steps 1-10 are required transitions -- review an unreviewed backlog,
    grow a pool too small to rank, refresh stale proximity, stop on a spent
    budget -- and the guards below would overrule a model that disagreed
    with them anyway. Spending an uncached planning round-trip to be told
    what the code already decided costs the run real wall-clock time on its
    serial spine, so a forced transition returns immediately and the model
    is consulted only for the open generation-vs-evolution judgement.

    Args:
        state: Current shared workflow state.
        stats: Live statistics derived from that state.
        budget: The run's hard compute limits.

    Returns:
        The validated decision and its provenance label.
    """
    # The disclosed scheduler's decision for these stats/budget. Computed once
    # and reused for the hard-stop fall-through, the non-progress fallback, the
    # post-budget growth guard, and the exception fallback -- the policy is
    # pure and stats/budget do not change across those uses.
    forced = required_transition(stats, budget)
    baseline = forced if forced is not None else decide_next_task(stats, budget)

    stop = _hard_stop(stats, budget, baseline)
    if stop is not None:
        return stop, "hard-invariant"

    if forced is not None and not _needs_queue_adjudication(state):
        return validate_decision(forced, stats), "required-transition"

    try:
        validated = await _call_supervisor_planner(state, stats, budget)
        return _resolve_planner_decision(
            state, stats, budget, baseline, validated
        )
    except Exception as exc:
        logger.warning("Supervisor allocation failed; using fallback: %s", exc)
        fallback = validate_decision(baseline, stats)
        return fallback, "reconstructed-fallback"


async def _call_supervisor_planner(
    state: WorkflowState, stats: SchedulerStats, budget: Budget
) -> SupervisorDecision:
    """Calls the allocation model and validates its proposed allocation.

    Runs on the worker model with thinking off. What reaches this call is
    no longer open-ended planning: the required transitions are already
    settled in code, leaving a choice between two named tasks over
    statistics the prompt states outright, plus optional queue actions on a
    listed set of task ids. That is a classification against supplied
    numbers rather than a reasoning problem, and every answer is bounded by
    ``validate_decision`` and the guards around it. The reasoning tier's
    latency lands squarely on the run's serial spine, so it is spent where
    it changes an answer instead of on every loop point.
    """
    response = await call_llm_json(
        prompt=_planning_prompt(state, stats, budget),
        spec=CompletionSpec(
            model_name=state["model_name"],
            temperature=MEDIUM_TEMPERATURE,
            json_schema=_DECISION_SCHEMA,
        ),
        options=LLMCallOptions(
            use_cache=False,
            run_id=state.get("run_id"),
            prompt_name="supervisor_allocation",
            prompt_metadata={"iteration": stats.iteration},
            enable_thinking=False,
        ),
    )
    proposed = SupervisorDecision(
        next_task=TaskType(str(response["next_task"])),
        reason=str(response["reason"]),
        priority=max(0, min(100, int(response.get("priority", 50)))),
        queue_actions=tuple(response.get("queue_actions") or ()),
    )
    return validate_decision(proposed, stats)


def _resolve_planner_decision(
    state: WorkflowState,
    stats: SchedulerStats,
    budget: Budget,
    baseline: SupervisorDecision,
    validated: SupervisorDecision,
) -> tuple[SupervisorDecision, str]:
    """Applies the non-progress and post-budget-growth guards to a proposal."""
    if _repeats_without_iteration_progress(state, stats, validated, baseline):
        # A freeform Supervisor may spend one maintenance pass beyond the
        # baseline, but repeating the same pass without a work-cycle
        # advance is a non-progress loop. Fall back to the disclosed
        # scheduler and record that the code-enforced invariant fired.
        return baseline, "hard-invariant"
    if (
        not stats.pending_steering
        and stats.iteration >= budget.max_iterations
        and validated.next_task in WORK_TASKS
    ):
        # Once the exploration budget is spent, the model may select the
        # required review/ranking/proximity cleanup but cannot grow the
        # pool again. The deterministic policy owns that terminal drain.
        return baseline, "hard-invariant"
    return validated, "model"

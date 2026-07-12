"""Model-directed Supervisor allocation at each orchestration loop point."""

from __future__ import annotations

import json
import logging
from typing import Any

from co_scientist.constants import MEDIUM_TEMPERATURE
from co_scientist.llm import call_llm_json
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    decide_next_task,
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
        },
        "required": ["next_task", "reason"],
        "additionalProperties": False,
    },
}


def _hard_stop(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Return a code-enforced stop that no model allocation may bypass."""
    reason: tuple[TerminationReason, str] | None = None
    if stats.cancelled:
        reason = (TerminationReason.CANCELLED, "run cancelled")
    elif stats.safety_blocked:
        reason = (TerminationReason.SAFETY, "safety block halted the run")
    elif (
        budget.max_llm_calls is not None
        and stats.llm_calls >= budget.max_llm_calls
    ):
        reason = (TerminationReason.BUDGET, "LLM-call budget exhausted")
    elif budget.max_tasks is not None and stats.tasks_run >= budget.max_tasks:
        reason = (TerminationReason.MAX_TASKS, "task budget exhausted")
    elif (
        budget.max_wall_clock_s is not None
        and stats.elapsed_s >= budget.max_wall_clock_s
    ):
        reason = (TerminationReason.WALL_CLOCK, "wall-clock budget exhausted")
    if reason is None:
        # Satisfied completion and convergence are evaluated by the disclosed
        # scheduler predicates after required review/ranking/proximity work.
        baseline = decide_next_task(stats, budget)
        return baseline if baseline.terminate else None
    termination_reason, message = reason
    return SupervisorDecision(
        next_task=TaskType.TERMINATE,
        reason=message,
        terminate=True,
        termination_reason=termination_reason,
    )


def _planning_prompt(
    state: WorkflowState, stats: SchedulerStats, budget: Budget
) -> str:
    """Build the Supervisor's live allocation prompt from shared memory."""
    context = {
        "research_goal": state["research_goal"],
        "research_plan": state.get("supervisor_guidance") or {},
        "statistics": stats.to_dict(),
        "budget": budget.to_dict(),
        "recent_tasks": list(state.get("task_history", []))[-12:],
        "meta_review": state.get("meta_review") or {},
        "pending_steering": state.get("pending_steering") or False,
        "held_for_review": len(state.get("held_for_review", [])),
    }
    return (
        "You are the adaptive Supervisor for a scientific co-research system. "
        "Allocate the single most valuable next specialist task from generate, "
        "reflect, rank, evolve, or proximity. Use the live state rather than a "
        "fixed phase order. Prioritize unresolved verification and review work "
        "as hypotheses mature, incorporate scientist steering immediately, and "
        "balance exploration against improvement. Explain the observable basis "
        "for the allocation without revealing hidden chain-of-thought.\n\n"
        "Live shared memory:\n"
        f"{json.dumps(context, sort_keys=True, default=str)}"
    )


async def choose_supervisor_task(
    state: WorkflowState,
    stats: SchedulerStats,
    budget: Budget,
) -> tuple[SupervisorDecision, str]:
    """Choose the next productive task through the Supervisor model.

    Hard cancellation, safety, and compute limits are enforced before the
    model call. A malformed or unavailable planning call falls back to the
    existing deterministic policy and records that provenance explicitly.

    Args:
        state: Current shared workflow state.
        stats: Live statistics derived from that state.
        budget: The run's hard compute limits.

    Returns:
        The validated decision and its provenance label.
    """
    stop = _hard_stop(stats, budget)
    if stop is not None:
        return stop, "hard-invariant"

    try:
        response = await call_llm_json(
            prompt=_planning_prompt(state, stats, budget),
            model_name=state["supervisor_model_name"],
            max_tokens=800,
            temperature=MEDIUM_TEMPERATURE,
            json_schema=_DECISION_SCHEMA,
            use_cache=False,
            run_id=state.get("run_id"),
            prompt_name="supervisor_allocation",
            prompt_metadata={"iteration": stats.iteration},
        )
        proposed = SupervisorDecision(
            next_task=TaskType(str(response["next_task"])),
            reason=str(response["reason"]),
        )
        return validate_decision(proposed, stats), "model"
    except Exception as exc:
        logger.warning("Supervisor allocation failed; using fallback: %s", exc)
        fallback = validate_decision(decide_next_task(stats, budget), stats)
        return fallback, "reconstructed-fallback"

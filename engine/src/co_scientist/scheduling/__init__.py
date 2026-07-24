"""Adaptive orchestration: task types, scheduler stats, and the policy.

This package holds the *deterministic* Supervisor scheduling policy. The
compiled LangGraph consults it at the loop point to choose
the next task from observable state, rather than following a fixed sequence.
An LLM Supervisor may still recommend weights/actions, but this code validates
the decision, the allowed transitions, the budget, and termination.

The policy is a pure function (:func:`decide_next_task`) so it can be tested in
isolation across the required scheduling states without spinning up the graph.
"""

from co_scientist.scheduling.models import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskRecord,
    TaskStatus,
    TaskType,
    TerminationReason,
)
from co_scientist.scheduling.policy import (
    ALLOWED_LOOP_TASKS,
    decide_next_task,
    required_transition,
    validate_decision,
)

__all__ = [
    "ALLOWED_LOOP_TASKS",
    "Budget",
    "SchedulerStats",
    "SupervisorDecision",
    "TaskRecord",
    "TaskStatus",
    "TaskType",
    "TerminationReason",
    "decide_next_task",
    "required_transition",
    "validate_decision",
]

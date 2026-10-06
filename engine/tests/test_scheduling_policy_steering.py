from __future__ import annotations

from typing import cast

from co_scientist.agents.meta_review.research_overview import (
    is_interim_firing,
)
from co_scientist.checkpoint import (
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    decide_next_task,
    stacked_task_values,
)
from co_scientist.scheduling.policy import (
    stack_companions,
)
from co_scientist.state import WorkflowState
from co_scientist.workflow_topology import (
    route_after_meta_review,
)
from tests._state import make_state


def _settled_stats(**overrides: object) -> SchedulerStats:
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 0,
        "rankable_count": 6,
        "total_matches": 12,
        "match_coverage": 2.0,
        "iteration": 2,
        "iterations_since_meta_review": 0,
        "feedback_since_meta_review": 0,
        "iterations_since_research_overview": 2,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


_BUDGET = Budget(max_iterations=4, max_llm_calls=7000)

_CHEAP_BUDGET = Budget(max_iterations=4, max_llm_calls=1200)


def _due_stats(**overrides: object) -> SchedulerStats:
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 2,
        "rankable_count": 6,
        "total_matches": 12,
        "match_coverage": 2.0,
        "iteration": 1,
        "iterations_since_meta_review": 1,
        "feedback_since_meta_review": 6,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_a_terminating_decision_is_never_wrapped() -> None:
    stats = _due_stats(unreviewed_count=0, llm_calls=99)
    spent = Budget(max_iterations=4, max_llm_calls=1)
    decision = stack_companions(decide_next_task(stats, spent), stats, spent)
    assert decision.terminate
    assert not stacked_task_values(decision.queue_actions)


def _overview_due(**overrides: object) -> SchedulerStats:
    return _due_stats(iterations_since_research_overview=2, **overrides)


def test_the_overview_companion_is_gated_by_the_tier_ceiling() -> None:
    stats = _overview_due()
    decision = stack_companions(
        decide_next_task(stats, _CHEAP_BUDGET), stats, _CHEAP_BUDGET
    )
    assert stacked_task_values(decision.queue_actions) == (
        TaskType.META_REVIEW.value,
    )


def test_the_overview_never_runs_ahead_of_a_critique_being_written() -> None:
    """An overview scheduled before its critique would read the previous
    cycle."""
    meta_review = SupervisorDecision(
        next_task=TaskType.META_REVIEW, reason="periodic feedback is due"
    )
    stacked = stack_companions(meta_review, _overview_due(), _BUDGET)
    assert not stacked_task_values(stacked.queue_actions)


def test_the_stacked_list_survives_a_checkpoint_round_trip() -> None:
    """Companion tasks read restored state; losing this key silently skips or
    mislabels synthesis."""
    state = make_state(next_task=TaskType.REFLECT.value)
    state["supervisor_queue_actions"] = [
        {"action": "enqueue", "task_type": TaskType.META_REVIEW.value},
        {"action": "enqueue", "task_type": TaskType.SYNTHESIZE.value},
    ]
    restored = restore_workflow_state(
        serialize_workflow_state(dict(state), last_event_seq=0)
    )
    assert stacked_task_values(restored["supervisor_queue_actions"]) == (
        TaskType.META_REVIEW.value,
        TaskType.SYNTHESIZE.value,
    )
    assert is_interim_firing(cast(WorkflowState, restored))
    assert route_after_meta_review(cast(WorkflowState, restored)) == (
        "research_overview"
    )

from __future__ import annotations

from typing import Any, cast

import pytest

from co_scientist.agents.meta_review.research_overview import (
    build_interim_overview,
    format_interim_overview,
    is_interim_firing,
)
from co_scientist.agents.supervisor.orchestrator import (
    _research_overview_anchor,
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
    validate_decision,
)
from co_scientist.state import WorkflowState
from co_scientist.task_runtime import next_task_type, plan_portfolio
from co_scientist.workflow_topology import (
    route_after_meta_review,
    route_after_research_overview,
    route_next_task,
)
from tests._state import make_state

_EXTENDED = Budget(max_iterations=3, max_llm_calls=7000)
_STANDARD = Budget(max_iterations=3, max_llm_calls=2500)


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


def test_the_interim_overview_reaches_generation() -> None:
    written = build_interim_overview(
        {
            "overview": {
                "research_directions": [
                    {"title": "Releasing the myeloid brake"}
                ]
            },
            "open_questions": ["What sets the reversal threshold?"],
        }
    )
    block = format_interim_overview(make_state(interim_overview=written))

    assert "Releasing the myeloid brake" in block
    assert "What sets the reversal threshold?" in block
    assert "interim research overview" in block.lower()


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


def test_one_pass_queues_the_primary_and_its_companion() -> None:
    stats = _due_stats()
    decision = stack_companions(
        decide_next_task(stats, _BUDGET), stats, _BUDGET
    )
    assert decision.next_task is TaskType.REFLECT
    assert stacked_task_values(decision.queue_actions) == (
        TaskType.META_REVIEW.value,
    )


def test_a_terminating_decision_is_never_wrapped() -> None:
    stats = _due_stats(unreviewed_count=0, llm_calls=99)
    spent = Budget(max_iterations=4, max_llm_calls=1)
    decision = stack_companions(decide_next_task(stats, spent), stats, spent)
    assert decision.terminate
    assert not stacked_task_values(decision.queue_actions)


def test_evolve_is_not_stacked_because_it_already_runs_meta_review() -> None:
    """Evolution already enters through meta-review; stacking would buy it
    twice."""
    evolve = SupervisorDecision(
        next_task=TaskType.EVOLVE, reason="evolution out-yields generation"
    )
    stacked = stack_companions(evolve, _due_stats(), _BUDGET)
    assert not stacked_task_values(stacked.queue_actions)


def test_a_stacked_pass_runs_the_companion_before_the_primary() -> None:
    """Parallel companion commits would fork the checkpoint chain at one
    predecessor."""
    state = make_state(next_task=TaskType.REFLECT.value)
    state["supervisor_queue_actions"] = [
        {
            "action": "enqueue",
            "task_type": TaskType.META_REVIEW.value,
            "reason": "periodic system feedback",
        }
    ]
    assert route_next_task(state) == "meta_review"
    assert route_after_meta_review(state) == "review"
    assert plan_portfolio("meta_review", state) == ["meta_review", "review"]


def _overview_due(**overrides: object) -> SchedulerStats:
    return _due_stats(iterations_since_research_overview=2, **overrides)


def test_one_pass_stacks_both_periodic_branches() -> None:
    """The overview must read the critique just synthesized by meta-review."""
    stats = _overview_due()
    decision = stack_companions(
        decide_next_task(stats, _BUDGET), stats, _BUDGET
    )
    assert decision.next_task is TaskType.REFLECT
    assert stacked_task_values(decision.queue_actions) == (
        TaskType.META_REVIEW.value,
        TaskType.SYNTHESIZE.value,
    )


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


def test_the_routers_walk_companion_to_companion_to_primary() -> None:
    state = make_state(next_task=TaskType.REFLECT.value)
    state["supervisor_queue_actions"] = [
        {"action": "enqueue", "task_type": TaskType.META_REVIEW.value},
        {"action": "enqueue", "task_type": TaskType.SYNTHESIZE.value},
    ]
    assert route_next_task(state) == "meta_review"
    assert route_after_meta_review(state) == "research_overview"
    assert route_after_research_overview(state) == "review"
    assert plan_portfolio("meta_review", state) == [
        "meta_review",
        "research_overview",
        "review",
    ]


def test_a_stacked_overview_is_an_interim_firing() -> None:
    """The primary retains next_task; reading that alone would publish mid-
    cycle."""
    state = make_state(next_task=TaskType.REFLECT.value)
    state["supervisor_queue_actions"] = [
        {"action": "enqueue", "task_type": TaskType.SYNTHESIZE.value}
    ]
    assert is_interim_firing(state)
    assert route_next_task(state) == "research_overview"
    assert route_after_research_overview(state) == "review"


def test_a_stacked_overview_resets_its_own_cadence_anchor() -> None:
    """Companions do not advance iterations; resetting the anchor prevents
    repeated stacking."""
    stats = _overview_due(iteration=3)
    decision = stack_companions(
        decide_next_task(stats, _BUDGET), stats, _BUDGET
    )
    book = {"iteration_at_last_research_overview": 0}
    assert _research_overview_anchor(book, stats, decision) == 3


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


@pytest.mark.parametrize(
    ("overrides", "budget", "expected"),
    [
        ({}, _EXTENDED, TaskType.SYNTHESIZE),
        # The cheaper tiers never fire the overview.
        ({}, _STANDARD, None),
        ({}, Budget(max_iterations=1, max_llm_calls=1200), None),
        ({"iterations_since_research_overview": 1}, _EXTENDED, None),
        # Overview firings do not advance iterations; resetting the anchor
        # prevents an infinite loop.
        ({"iterations_since_research_overview": 0}, _EXTENDED, None),
        ({"unreviewed_count": 3}, _EXTENDED, TaskType.REFLECT),
    ],
)
def test_the_periodic_overview_fires_on_its_cadence_and_tier(
    overrides: dict[str, Any], budget: Budget, expected: TaskType | None
) -> None:
    stats = _settled_stats(**overrides)
    decision = validate_decision(decide_next_task(stats, budget), stats)
    if expected is None:
        assert decision.next_task is not TaskType.SYNTHESIZE
    else:
        assert decision.next_task is expected


def test_only_the_final_firing_ends_the_run() -> None:
    ultra = Budget(max_iterations=4, max_llm_calls=14000)
    assert decide_next_task(_settled_stats(iteration=4), ultra).terminate

    periodic = make_state(next_task=TaskType.SYNTHESIZE.value)
    assert route_after_research_overview(periodic) == "orchestrator"
    assert next_task_type("research_overview", periodic) == "orchestrator"
    terminal = make_state(next_task=TaskType.TERMINATE.value)
    assert route_after_research_overview(terminal) is None
    assert next_task_type("research_overview", terminal) is None
    assert not is_interim_firing(terminal)

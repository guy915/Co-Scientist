from __future__ import annotations

from typing import cast

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
    ALLOWED_LOOP_TASKS,
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    decide_next_task,
    stacked_task_values,
)
from co_scientist.scheduling.policy import (
    _check_research_overview_cadence,
    stack_companions,
    validate_decision,
)
from co_scientist.state import WorkflowState
from co_scientist.task_runtime import next_task_type, plan_portfolio
from co_scientist.workflow_topology import (
    TASK_ROUTES,
    route_after_meta_review,
    route_after_research_overview,
    route_next_task,
)
from tests._state import BUDGET, healthy_stats, make_state

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


def test_synthesize_is_a_dispatchable_loop_task() -> None:
    assert TaskType.SYNTHESIZE in ALLOWED_LOOP_TASKS
    stats = _settled_stats()
    decision = validate_decision(decide_next_task(stats, _EXTENDED), stats)
    assert decision.next_task is TaskType.SYNTHESIZE


def test_the_cheaper_tiers_never_fire_it() -> None:
    stats = _settled_stats()
    assert _check_research_overview_cadence(stats, _STANDARD) is None
    express = Budget(max_iterations=1, max_llm_calls=1200)
    assert _check_research_overview_cadence(stats, express) is None


def test_it_does_not_fire_every_cycle() -> None:
    stats = _settled_stats(iterations_since_research_overview=1)
    assert _check_research_overview_cadence(stats, _EXTENDED) is None


def test_a_firing_that_just_ran_cannot_immediately_re_fire() -> None:
    """Overview firings do not advance iterations; resetting the anchor
    prevents an infinite loop."""
    stats = _settled_stats(iterations_since_research_overview=0)
    assert _check_research_overview_cadence(stats, _EXTENDED) is None


def test_the_last_iteration_terminates_rather_than_firing() -> None:
    """An interim overview has no generation reader after the final
    iteration."""
    ultra = Budget(max_iterations=4, max_llm_calls=14000)
    stats = _settled_stats(iteration=4)
    assert decide_next_task(stats, ultra).terminate is True


def test_cadence_never_outranks_a_review_backlog() -> None:
    stats = _settled_stats(unreviewed_count=3)
    assert decide_next_task(stats, _EXTENDED).next_task is TaskType.REFLECT


def test_a_periodic_firing_returns_to_the_loop_point() -> None:
    state = make_state(next_task=TaskType.SYNTHESIZE.value)
    assert route_after_research_overview(state) == "orchestrator"
    assert next_task_type("research_overview", state) == "orchestrator"


def test_the_terminal_firing_still_ends_the_run() -> None:
    state = make_state(next_task=TaskType.TERMINATE.value)
    assert route_after_research_overview(state) is None
    assert next_task_type("research_overview", state) is None


def test_synthesize_enters_at_the_overview_node() -> None:
    assert TASK_ROUTES[TaskType.SYNTHESIZE.value] == "research_overview"


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


def test_no_interim_overview_renders_nothing() -> None:
    assert format_interim_overview(make_state()) == ""


def test_owed_review_outranks_budget_termination() -> None:
    stats = healthy_stats(owed_review_count=1, tasks_run=100)

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.REFLECT
    assert "review" in decision.reason


def test_owed_review_refuses_to_override_the_llm_call_ceiling() -> None:
    # A spent physical-call ceiling cannot fund forced reflection.
    stats = healthy_stats(owed_review_count=1, llm_calls=1000)

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


def test_owed_review_stays_inert_while_the_budget_has_room() -> None:
    # The permanent override marker must not be spent by an ordinary healthy
    # cycle.
    stats = healthy_stats(owed_review_count=1)

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.GENERATE


def test_safety_block_outranks_owed_review() -> None:
    stats = healthy_stats(
        owed_review_count=1, tasks_run=100, safety_blocked=True
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.SAFETY


def test_steering_outranks_owed_review() -> None:
    stats = healthy_stats(
        owed_review_count=1, tasks_run=100, pending_steering=True
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.GENERATE
    assert "steering" in decision.reason


def test_owed_coverage_outranks_owed_review() -> None:
    # Owed coverage retains precedence on the same exhausted-budget cycle.
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
        owed_review_count=1,
        tasks_run=100,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.RANK


def test_zero_owed_review_leaves_budget_termination_alone() -> None:
    stats = healthy_stats(owed_review_count=0, llm_calls=1000)

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


def test_budget_outranks_ordinary_backlog_without_an_owed_review() -> None:
    stats = healthy_stats(
        unreviewed_count=5, owed_review_count=0, llm_calls=1000
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


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


def test_the_primary_keeps_its_own_identity() -> None:
    """Settlement allowance, iteration and yield attribution key on the
    primary task."""
    stats = _due_stats(unreviewed_count=0, owed_coverage_rounds=3)
    decision = stack_companions(
        decide_next_task(stats, _BUDGET), stats, _BUDGET
    )
    assert decision.next_task is TaskType.RANK
    assert stacked_task_values(decision.queue_actions)


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


def test_nothing_is_stacked_when_the_cadence_is_not_due() -> None:
    stats = _due_stats(feedback_since_meta_review=0)
    decision = stack_companions(
        decide_next_task(stats, _BUDGET), stats, _BUDGET
    )
    assert not stacked_task_values(decision.queue_actions)


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


def test_an_unstacked_pass_routes_straight_to_the_primary() -> None:
    state = make_state(next_task=TaskType.REFLECT.value)
    assert route_next_task(state) == "review"


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


def test_a_companion_is_never_stacked_onto_its_own_primary() -> None:
    synthesize = SupervisorDecision(
        next_task=TaskType.SYNTHESIZE, reason="periodic overview is due"
    )
    stacked = stack_companions(synthesize, _overview_due(), _BUDGET)
    assert stacked_task_values(stacked.queue_actions) == (
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


def test_a_terminal_firing_is_still_terminal() -> None:
    state = make_state(next_task=TaskType.TERMINATE.value)
    assert not is_interim_firing(state)
    assert route_after_research_overview(state) is None


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


def test_steering_outranks_budget_exhaustion() -> None:
    budget = Budget(max_iterations=100, max_llm_calls=10)
    stats = healthy_stats(llm_calls=10, pending_steering=True)
    decision = decide_next_task(stats, budget)
    assert decision.next_task is TaskType.GENERATE
    assert not decision.terminate

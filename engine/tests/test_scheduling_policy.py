from __future__ import annotations

from co_scientist.scheduling import (
    ALLOWED_LOOP_TASKS,
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    decide_next_task,
    validate_decision,
)
from co_scientist.scheduling.policy import _check_meta_review_cadence
from co_scientist.task_runtime import next_task_type
from co_scientist.workflow_topology import TASK_ROUTES, route_after_meta_review
from tests._state import BUDGET, healthy_stats, make_state


def test_generation_heavy_state_generates() -> None:
    stats = healthy_stats(generation_yield=0.9, evolution_yield=0.1)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.GENERATE
    assert not decision.terminate


def test_evolution_heavy_state_evolves() -> None:
    stats = healthy_stats(generation_yield=0.1, evolution_yield=0.8)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.EVOLVE


def test_verification_backlogged_state_reviews() -> None:
    stats = healthy_stats(unreviewed_count=3)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.REFLECT


def test_converged_state_terminates() -> None:
    stats = healthy_stats(
        rank_stable_cycles=2, iteration=2, evolved_since_stable=True
    )
    decision = decide_next_task(stats, BUDGET, convergence_cycles=2)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.CONVERGED


def test_convergence_held_off_until_min_cycles() -> None:
    stats = healthy_stats(rank_stable_cycles=5, iteration=1)
    decision = decide_next_task(
        stats, BUDGET, convergence_cycles=2, min_cycles_before_convergence=2
    )
    assert not decision.terminate


def test_budget_exhausted_state_terminates() -> None:
    budget = Budget(max_iterations=100, max_llm_calls=50)
    stats = healthy_stats(llm_calls=50)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


def test_task_budget_exhausted_terminates() -> None:
    budget = Budget(max_iterations=100, max_tasks=20)
    stats = healthy_stats(tasks_run=20)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.MAX_TASKS


def test_wall_clock_exhausted_terminates() -> None:
    budget = Budget(max_iterations=100, max_wall_clock_s=60.0)
    stats = healthy_stats(elapsed_s=61.0)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.WALL_CLOCK


def test_max_ideas_exhausted_terminates() -> None:
    budget = Budget(max_iterations=100, max_ideas=10)
    stats = healthy_stats(pool_size=10, unreviewed_count=0)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.MAX_IDEAS


def test_max_ideas_defers_to_review_backlog() -> None:
    """Stopping before the backlog would strand already generated ideas."""
    budget = Budget(max_iterations=100, max_ideas=10)
    stats = healthy_stats(pool_size=10, unreviewed_count=2)
    decision = decide_next_task(stats, budget)
    assert not decision.terminate
    assert decision.next_task is TaskType.REFLECT


def test_max_matches_per_idea_exhausted_terminates() -> None:
    budget = Budget(max_iterations=100, max_matches_per_idea=3.0)
    stats = healthy_stats(rankable_count=6, match_coverage=3.0)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.MAX_MATCHES_PER_IDEA


def test_max_matches_per_idea_below_threshold_continues() -> None:
    budget = Budget(max_iterations=100, max_matches_per_idea=3.0)
    stats = healthy_stats(rankable_count=6, match_coverage=2.0)
    decision = decide_next_task(stats, budget)
    assert not decision.terminate


def test_steered_state_generates() -> None:
    stats = healthy_stats(pending_steering=True, evolution_yield=0.9)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.GENERATE
    assert "steering" in decision.reason


def test_retry_state_reschedules_failed_task() -> None:
    stats = healthy_stats(last_task_failed=TaskType.RANK, retries_remaining=1)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.RANK
    assert "retry" in decision.reason.lower()


def test_stale_cancelled_flag_does_not_terminate() -> None:
    """The durable executor owns cancellation, not the scheduling policy."""
    stats = healthy_stats(cancelled=True)
    decision = decide_next_task(stats, BUDGET)
    assert not decision.terminate


def test_safety_block_terminates() -> None:
    stats = healthy_stats(safety_blocked=True)
    decision = decide_next_task(stats, BUDGET)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.SAFETY


def test_yield_tie_without_stagnation_generates() -> None:
    stats = healthy_stats(
        generation_yield=0.0,
        evolution_yield=0.0,
        rank_stable_cycles=0,
        last_work_task=TaskType.EVOLVE,
    )
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.GENERATE


def test_yield_tie_with_stagnation_evolves() -> None:
    stats = healthy_stats(
        generation_yield=0.0,
        evolution_yield=0.0,
        rank_stable_cycles=1,
        last_work_task=TaskType.GENERATE,
    )
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.EVOLVE
    assert "stagnant" in decision.reason


def test_yield_tie_with_standing_stagnation_generates() -> None:
    """Repeated breeding of a narrow pool would starve generation."""
    stats = healthy_stats(
        generation_yield=0.0,
        evolution_yield=0.0,
        rank_stable_cycles=3,
        last_work_task=TaskType.EVOLVE,
    )
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.GENERATE
    assert "already had its turn" in decision.reason


def test_safety_outranks_budget_and_backlog() -> None:
    budget = Budget(max_iterations=100, max_llm_calls=1)
    stats = healthy_stats(
        safety_blocked=True, llm_calls=100, unreviewed_count=5
    )
    decision = decide_next_task(stats, budget)
    assert decision.termination_reason is TerminationReason.SAFETY


def test_budget_outranks_backlog() -> None:
    budget = Budget(max_iterations=100, max_llm_calls=10)
    stats = healthy_stats(llm_calls=10, unreviewed_count=5)
    decision = decide_next_task(stats, budget)
    assert decision.termination_reason is TerminationReason.BUDGET


def test_small_pool_generates_even_when_evolution_yield_high() -> None:
    stats = healthy_stats(pool_size=1, reviewed_count=1, evolution_yield=0.9)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.GENERATE


def test_low_coverage_ranks() -> None:
    stats = healthy_stats(match_coverage=0.0)
    decision = decide_next_task(stats, BUDGET, min_match_coverage=1.0)
    assert decision.next_task is TaskType.RANK


def test_pool_growth_refreshes_proximity() -> None:
    stats = healthy_stats(pool_grew_since_proximity=True)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.PROXIMITY


def test_iteration_budget_reached_completes() -> None:
    stats = healthy_stats(iteration=5)
    decision = decide_next_task(stats, Budget(max_iterations=5))
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.COMPLETED


def test_starved_generation_terminates_at_iteration_budget() -> None:
    """Failed growth still consumes iterations, avoiding the graph recursion
    limit."""
    stats = healthy_stats(pool_size=1, reviewed_count=1, iteration=5)
    decision = decide_next_task(stats, Budget(max_iterations=5))
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.COMPLETED


def test_unrankable_pool_does_not_loop_on_ranking() -> None:
    """Gated ideas cannot earn tournament coverage and must not hold its
    floor open."""
    stats = healthy_stats(rankable_count=0, match_coverage=0.0, iteration=1)
    decision = decide_next_task(stats, BUDGET, min_match_coverage=1.0)
    assert decision.next_task is not TaskType.RANK
    assert not decision.terminate
    at_budget = healthy_stats(rankable_count=0, match_coverage=0.0, iteration=5)
    end = decide_next_task(at_budget, Budget(max_iterations=5))
    assert end.terminate
    assert end.termination_reason is TerminationReason.COMPLETED


def test_validate_rejects_rank_on_tiny_pool() -> None:
    stats = healthy_stats(pool_size=1, rankable_count=1)
    recommended = SupervisorDecision(TaskType.RANK, "llm said rank")
    validated = validate_decision(recommended, stats)
    assert validated.next_task is TaskType.GENERATE
    assert "corrected" in validated.reason


def test_validate_rejects_evolve_without_reviews() -> None:
    stats = healthy_stats(reviewed_count=0, unreviewed_count=3)
    recommended = SupervisorDecision(TaskType.EVOLVE, "llm said evolve")
    validated = validate_decision(recommended, stats)
    assert validated.next_task is TaskType.REFLECT

    stats2 = healthy_stats(reviewed_count=0, unreviewed_count=0, pool_size=2)
    validated2 = validate_decision(
        SupervisorDecision(TaskType.EVOLVE, "llm said evolve"), stats2
    )
    assert validated2.next_task is TaskType.GENERATE


def test_correction_carries_queue_actions_through() -> None:
    """Failed rows have no other revival path; corrections must retain queue
    actions."""
    retry = ({"action": "retry", "task_id": "t-9", "reason": "transient"},)

    steered = validate_decision(
        SupervisorDecision(TaskType.RANK, "llm said rank", queue_actions=retry),
        healthy_stats(pending_steering=True),
    )
    assert steered.next_task is TaskType.GENERATE
    assert steered.queue_actions == retry

    ranked = validate_decision(
        SupervisorDecision(TaskType.RANK, "llm said rank", queue_actions=retry),
        healthy_stats(pool_size=1, rankable_count=1),
    )
    assert ranked.next_task is TaskType.GENERATE
    assert ranked.queue_actions == retry

    evolved = validate_decision(
        SupervisorDecision(
            TaskType.EVOLVE, "llm said evolve", queue_actions=retry
        ),
        healthy_stats(reviewed_count=0, unreviewed_count=3),
    )
    assert evolved.next_task is TaskType.REFLECT
    assert evolved.queue_actions == retry

    assert frozenset(TaskType) == ALLOWED_LOOP_TASKS


def test_validate_passes_valid_decision_unchanged() -> None:
    stats = healthy_stats()
    decision = SupervisorDecision(TaskType.EVOLVE, "evolve leaders")
    assert validate_decision(decision, stats) is decision


def test_validate_passes_terminate_unchanged() -> None:
    stats = healthy_stats(pool_size=0)
    decision = SupervisorDecision(
        TaskType.TERMINATE,
        "done",
        terminate=True,
        termination_reason=TerminationReason.COMPLETED,
    )
    assert validate_decision(decision, stats) is decision


def test_decision_and_stats_round_trip_to_dict() -> None:
    stats = healthy_stats(last_task_failed=TaskType.RANK)
    stats_dict = stats.to_dict()
    assert stats_dict["last_task_failed"] == "rank"

    decision = _terminate_decision()
    d = decision.to_dict()
    assert d["next_task"] == "terminate"
    assert d["termination_reason"] == "converged"


def _terminate_decision() -> SupervisorDecision:
    return SupervisorDecision(
        TaskType.TERMINATE,
        "stable",
        terminate=True,
        termination_reason=TerminationReason.CONVERGED,
    )


def test_budget_from_dict_tolerates_a_pre_f11_checkpoint() -> None:
    pre_f11_payload = {
        "max_iterations": 5,
        "max_llm_calls": 1000,
        "max_tasks": 100,
        "max_wall_clock_s": None,
    }
    budget = Budget.from_dict(pre_f11_payload)
    assert budget.max_ideas is None
    assert budget.max_matches_per_idea is None
    stats = healthy_stats(tasks_run=100)
    decision = decide_next_task(stats, budget)
    assert decision.termination_reason is TerminationReason.MAX_TASKS


def test_stale_cancelled_termination_reason_string_is_inert_data() -> None:
    """Stored termination reasons are opaque strings, not reparsed enums."""
    stale_history_entry = {
        "task_type": "generate",
        "status": "completed",
        "reason": "done",
        "iteration": 3,
        "termination_reason": "cancelled",
    }
    # Nothing in the scheduling module parses this back into an enum; it is
    # opaque data that a resumed run only ever carries forward or displays.
    assert stale_history_entry["termination_reason"] == "cancelled"
    assert "cancelled" not in {r.value for r in TerminationReason}
    stats = healthy_stats()
    decision = decide_next_task(stats, BUDGET)
    assert decision.termination_reason != "cancelled"


def test_stagnation_evolves_before_it_terminates() -> None:
    stats = healthy_stats(
        rank_stable_cycles=2, iteration=2, evolved_since_stable=False
    )
    decision = decide_next_task(
        stats, Budget(max_iterations=4), convergence_cycles=2
    )
    assert not decision.terminate
    assert decision.next_task is TaskType.EVOLVE


def test_stagnation_terminates_once_evolution_has_answered_it() -> None:
    stats = healthy_stats(
        rank_stable_cycles=2, iteration=2, evolved_since_stable=True
    )
    decision = decide_next_task(
        stats, Budget(max_iterations=4), convergence_cycles=2
    )
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.CONVERGED


def test_the_extra_evolve_cycle_cannot_outlive_the_iteration_budget() -> None:
    """The iteration ceiling still bounds convergence's evolution
    opportunity."""
    stats = healthy_stats(
        rank_stable_cycles=5, iteration=4, evolved_since_stable=False
    )
    decision = decide_next_task(
        stats, Budget(max_iterations=4), convergence_cycles=2
    )
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.COMPLETED


def test_spent_tournament_budget_stops_asking_to_rank() -> None:
    stats = healthy_stats(match_coverage=0.0, tournament_rounds_remaining=0)

    decision = decide_next_task(stats, BUDGET, min_match_coverage=1.0)

    assert decision.next_task is not TaskType.RANK


def test_remaining_tournament_budget_still_ranks() -> None:
    stats = healthy_stats(match_coverage=0.0, tournament_rounds_remaining=4)

    decision = decide_next_task(stats, BUDGET, min_match_coverage=1.0)

    assert decision.next_task is TaskType.RANK


def test_uncompared_idea_ranks_despite_healthy_average() -> None:
    # Average coverage can hide an individual idea that has never played.
    stats = healthy_stats(
        rankable_count=3,
        match_coverage=1.33,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.RANK


def test_owed_coverage_outranks_budget_termination() -> None:
    # A spent budget must not strand an idea that never played. The ceiling
    # is a runaway backstop, and the allowance bounds the overshoot.
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.RANK


def test_owed_coverage_outranks_max_matches_per_idea() -> None:
    budget = Budget(max_iterations=5, max_matches_per_idea=1.0)
    stats = healthy_stats(
        rankable_count=3,
        match_coverage=1.0,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
    )

    decision = decide_next_task(stats, budget)

    assert decision.next_task is TaskType.RANK


def test_safety_block_outranks_owed_coverage() -> None:
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
        safety_blocked=True,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.SAFETY


def test_steering_outranks_owed_coverage() -> None:
    # Steering is cleared when observed; settlement would lose it without new
    # work.
    # Pending steering intentionally buys a cycle above exhausted budget
    # ceilings.
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=2,
        owed_coverage_rounds=2,
        pending_steering=True,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.GENERATE
    assert "steering" in decision.reason


def test_spent_allowance_stops_overriding_the_budget() -> None:
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
        settlement_allowance=0,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.BUDGET


def test_stalled_settlement_stops_overriding_the_budget() -> None:
    # A round that did not reduce the backlog will not reduce it next time
    # either; spending the rest of the allowance on it wastes real debates.
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=2,
        owed_coverage_rounds=2,
        settlement_allowance=5,
        owed_at_last_settlement=2,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.TERMINATE


def test_settlement_continues_while_backlog_shrinks() -> None:
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
        settlement_allowance=5,
        owed_at_last_settlement=3,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.RANK


def test_single_rankable_hypothesis_never_settles() -> None:
    # Inconsistent owed rounds exercise the guard independently of floor
    # calculation.
    stats = healthy_stats(
        pool_size=1,
        rankable_count=1,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is not TaskType.RANK


def test_fully_compared_pool_is_unaffected() -> None:
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=0,
        owed_coverage_rounds=0,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.BUDGET


_BUDGET = Budget(max_iterations=4)


def _settled_stats(**overrides: object) -> SchedulerStats:
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 0,
        "rankable_count": 6,
        "total_matches": 12,
        "match_coverage": 2.0,
        "iteration": 1,
        "iterations_since_meta_review": 1,
        "feedback_since_meta_review": 6,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_meta_review_is_a_dispatchable_loop_task() -> None:
    assert TaskType.META_REVIEW in ALLOWED_LOOP_TASKS
    decision = validate_decision(
        decide_next_task(_settled_stats(), _BUDGET), _settled_stats()
    )
    assert decision.next_task is TaskType.META_REVIEW


def test_cadence_fires_once_new_critique_material_exists() -> None:
    assert _check_meta_review_cadence(_settled_stats()) is not None


def test_cadence_holds_without_a_completed_work_cycle() -> None:
    stats = _settled_stats(iterations_since_meta_review=0)
    assert _check_meta_review_cadence(stats) is None


def test_cadence_holds_without_new_reviews_or_matches() -> None:
    """A second synthesis with no new material buys no new information."""
    stats = _settled_stats(feedback_since_meta_review=0)
    assert _check_meta_review_cadence(stats) is None


def test_cadence_never_outranks_a_review_backlog() -> None:
    stats = _settled_stats(unreviewed_count=3)
    assert decide_next_task(stats, _BUDGET).next_task is TaskType.REFLECT


def test_a_run_that_never_evolves_still_reaches_meta_review() -> None:
    assert TASK_ROUTES[TaskType.META_REVIEW.value] == "meta_review"
    assert TASK_ROUTES[TaskType.EVOLVE.value] == "meta_review"


def test_meta_review_returns_to_the_loop_point_when_standalone() -> None:
    state = make_state(next_task=TaskType.META_REVIEW.value)
    assert route_after_meta_review(state) == "orchestrator"
    assert next_task_type("meta_review", state) == "orchestrator"


def test_meta_review_still_prefixes_evolve() -> None:
    state = make_state(next_task=TaskType.EVOLVE.value)
    assert route_after_meta_review(state) == "evolve"
    assert next_task_type("meta_review", state) == "evolve"

"""Deterministic scheduling-policy acceptance tests.

Covers the required scheduling states — generation-heavy, evolution-heavy,
verification-backlogged, converged, budget-exhausted, steered, and retry —
plus the allowed-transition validation. All assertions are against the pure
:func:`decide_next_task` / :func:`validate_decision` functions, independent of
the graph topology.
"""

from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    decide_next_task,
    validate_decision,
)

# A generous budget so budget ceilings never fire unless a test sets them.
_BUDGET = Budget(max_iterations=5, max_llm_calls=1000, max_tasks=100)


def _healthy_stats(**overrides: object) -> SchedulerStats:
    """A mid-run pool with no backlog, adequate coverage, room to iterate."""
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 0,
        "rankable_count": 6,
        "match_coverage": 3.0,
        "iteration": 1,
        "rank_stable_cycles": 0,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


# --- Required scheduling states ---------------------------------------------


def test_generation_heavy_state_generates() -> None:
    """When generation out-yields evolution, schedule GENERATE."""
    stats = _healthy_stats(generation_yield=0.9, evolution_yield=0.1)
    decision = decide_next_task(stats, _BUDGET)
    assert decision.next_task is TaskType.GENERATE
    assert not decision.terminate


def test_evolution_heavy_state_evolves() -> None:
    """When evolution out-yields generation with leaders, schedule EVOLVE."""
    stats = _healthy_stats(generation_yield=0.1, evolution_yield=0.8)
    decision = decide_next_task(stats, _BUDGET)
    assert decision.next_task is TaskType.EVOLVE


def test_verification_backlogged_state_reviews() -> None:
    """Unreviewed hypotheses are reviewed before ranking or evolving."""
    stats = _healthy_stats(unreviewed_count=3)
    decision = decide_next_task(stats, _BUDGET)
    assert decision.next_task is TaskType.REFLECT


def test_converged_state_terminates() -> None:
    """A stable leaderboard with no backlog terminates as converged."""
    stats = _healthy_stats(rank_stable_cycles=2, iteration=2)
    decision = decide_next_task(stats, _BUDGET, convergence_cycles=2)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.CONVERGED


def test_convergence_held_off_until_min_cycles() -> None:
    """A stable leaderboard does not converge before the min work cycles.

    Guarantees the loop evolves and generates at least once before a stable
    tournament is allowed to stop the run.
    """
    stats = _healthy_stats(rank_stable_cycles=5, iteration=1)
    decision = decide_next_task(
        stats, _BUDGET, convergence_cycles=2, min_cycles_before_convergence=2
    )
    assert not decision.terminate


def test_budget_exhausted_state_terminates() -> None:
    """Hitting the LLM-call ceiling terminates with a budget reason."""
    budget = Budget(max_iterations=100, max_llm_calls=50)
    stats = _healthy_stats(llm_calls=50)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


def test_task_budget_exhausted_terminates() -> None:
    """Hitting the task ceiling terminates with a max-tasks reason."""
    budget = Budget(max_iterations=100, max_tasks=20)
    stats = _healthy_stats(tasks_run=20)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.MAX_TASKS


def test_wall_clock_exhausted_terminates() -> None:
    """Hitting the wall-clock ceiling terminates with a wall-clock reason."""
    budget = Budget(max_iterations=100, max_wall_clock_s=60.0)
    stats = _healthy_stats(elapsed_s=61.0)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.WALL_CLOCK


def test_steered_state_generates() -> None:
    """Pending user steering is a high-priority request to generate anew."""
    stats = _healthy_stats(pending_steering=True, evolution_yield=0.9)
    decision = decide_next_task(stats, _BUDGET)
    assert decision.next_task is TaskType.GENERATE
    assert "steering" in decision.reason


def test_retry_state_reschedules_failed_task() -> None:
    """A failed task with retries left is rescheduled before new work."""
    stats = _healthy_stats(last_task_failed=TaskType.RANK, retries_remaining=1)
    decision = decide_next_task(stats, _BUDGET)
    assert decision.next_task is TaskType.RANK
    assert "retry" in decision.reason.lower()


def test_cancelled_state_terminates() -> None:
    """External cancellation terminates immediately."""
    stats = _healthy_stats(cancelled=True)
    decision = decide_next_task(stats, _BUDGET)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.CANCELLED


def test_safety_block_terminates() -> None:
    """A safety block halts the run (Milestone 6 hook)."""
    stats = _healthy_stats(safety_blocked=True)
    decision = decide_next_task(stats, _BUDGET)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.SAFETY


def test_yield_tie_after_evolution_generates() -> None:
    """On a yield tie, alternate to GENERATE after the last cycle evolved.

    Guarantees later cycles keep exploring new regions rather than only ever
    evolving (M2 acceptance: new Generation work after the first tournament).
    """
    stats = _healthy_stats(
        generation_yield=0.0,
        evolution_yield=0.0,
        last_work_task=TaskType.EVOLVE,
    )
    decision = decide_next_task(stats, _BUDGET)
    assert decision.next_task is TaskType.GENERATE


def test_yield_tie_after_generation_evolves() -> None:
    """On a yield tie, evolve the leaders after the last cycle generated."""
    stats = _healthy_stats(
        generation_yield=0.0,
        evolution_yield=0.0,
        last_work_task=TaskType.GENERATE,
    )
    decision = decide_next_task(stats, _BUDGET)
    assert decision.next_task is TaskType.EVOLVE


# --- Precedence / ordering --------------------------------------------------


def test_cancellation_outranks_budget_and_backlog() -> None:
    """Cancellation is checked before budget and productive work."""
    budget = Budget(max_iterations=100, max_llm_calls=1)
    stats = _healthy_stats(cancelled=True, llm_calls=100, unreviewed_count=5)
    decision = decide_next_task(stats, budget)
    assert decision.termination_reason is TerminationReason.CANCELLED


def test_budget_outranks_backlog() -> None:
    """A hard budget stop wins over a review backlog."""
    budget = Budget(max_iterations=100, max_llm_calls=10)
    stats = _healthy_stats(llm_calls=10, unreviewed_count=5)
    decision = decide_next_task(stats, budget)
    assert decision.termination_reason is TerminationReason.BUDGET


def test_small_pool_generates_even_when_evolution_yield_high() -> None:
    """A sub-tournament pool must generate before it can rank/evolve."""
    stats = _healthy_stats(pool_size=1, reviewed_count=1, evolution_yield=0.9)
    decision = decide_next_task(stats, _BUDGET)
    assert decision.next_task is TaskType.GENERATE


def test_low_coverage_ranks() -> None:
    """Below the minimum match coverage, schedule more tournament rounds."""
    stats = _healthy_stats(match_coverage=0.0)
    decision = decide_next_task(stats, _BUDGET, min_match_coverage=1.0)
    assert decision.next_task is TaskType.RANK


def test_pool_growth_refreshes_proximity() -> None:
    """After the pool grows, proximity is refreshed before the next choice."""
    stats = _healthy_stats(pool_grew_since_proximity=True)
    decision = decide_next_task(stats, _BUDGET)
    assert decision.next_task is TaskType.PROXIMITY


def test_iteration_budget_reached_completes() -> None:
    """Reaching the iteration budget terminates as satisfied completion."""
    stats = _healthy_stats(iteration=5)
    decision = decide_next_task(stats, Budget(max_iterations=5))
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.COMPLETED


def test_starved_generation_terminates_at_iteration_budget() -> None:
    """A pool stuck below tournament size still stops at the iteration budget.

    Each GENERATE advances the iteration counter even when it fails to grow
    the pool, so the iteration ceiling must outrank the pool-too-small branch;
    otherwise a starved run only dies via the graph recursion limit instead of
    terminating with a recorded reason.
    """
    stats = _healthy_stats(pool_size=1, reviewed_count=1, iteration=5)
    decision = decide_next_task(stats, Budget(max_iterations=5))
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.COMPLETED


def test_unrankable_pool_does_not_loop_on_ranking() -> None:
    """A pool with fewer than two rankable ideas must not demand ranking.

    Regression: when the pre-ranking evidence gate marks most ideas
    ``evidence_blocked`` they leave the tournament, so their match coverage
    stays zero. Measuring coverage over the full pool held it below the gate
    forever and looped the orchestrator on RANK. With coverage measured over
    the rankable pool, a run whose ideas are all gated advances (generate/
    evolve) and terminates at its iteration budget instead of looping.
    """
    # Six reviewed ideas in the pool, none rankable, zero coverage, mid-budget.
    stats = _healthy_stats(rankable_count=0, match_coverage=0.0, iteration=1)
    decision = decide_next_task(stats, _BUDGET, min_match_coverage=1.0)
    assert decision.next_task is not TaskType.RANK
    assert not decision.terminate
    # At the iteration budget the same unrankable pool terminates, not loops.
    at_budget = _healthy_stats(
        rankable_count=0, match_coverage=0.0, iteration=5
    )
    end = decide_next_task(at_budget, Budget(max_iterations=5))
    assert end.terminate
    assert end.termination_reason is TerminationReason.COMPLETED


# --- Allowed-transition validation ------------------------------------------


def test_validate_rejects_rank_on_tiny_pool() -> None:
    """An LLM recommending RANK with <2 rankable ideas is corrected."""
    stats = _healthy_stats(pool_size=1, rankable_count=1)
    recommended = SupervisorDecision(TaskType.RANK, "llm said rank")
    validated = validate_decision(recommended, stats)
    assert validated.next_task is TaskType.GENERATE
    assert "corrected" in validated.reason


def test_validate_rejects_evolve_without_reviews() -> None:
    """EVOLVE with no reviewed hypotheses is corrected to REFLECT/GENERATE."""
    stats = _healthy_stats(reviewed_count=0, unreviewed_count=3)
    recommended = SupervisorDecision(TaskType.EVOLVE, "llm said evolve")
    validated = validate_decision(recommended, stats)
    assert validated.next_task is TaskType.REFLECT

    stats2 = _healthy_stats(reviewed_count=0, unreviewed_count=0, pool_size=2)
    validated2 = validate_decision(
        SupervisorDecision(TaskType.EVOLVE, "llm said evolve"), stats2
    )
    assert validated2.next_task is TaskType.GENERATE


def test_validate_passes_valid_decision_unchanged() -> None:
    """A valid decision is returned unchanged."""
    stats = _healthy_stats()
    decision = SupervisorDecision(TaskType.EVOLVE, "evolve leaders")
    assert validate_decision(decision, stats) is decision


def test_validate_passes_terminate_unchanged() -> None:
    """A terminate decision is never downgraded by validation."""
    stats = _healthy_stats(pool_size=0)
    decision = SupervisorDecision(
        TaskType.TERMINATE,
        "done",
        terminate=True,
        termination_reason=TerminationReason.COMPLETED,
    )
    assert validate_decision(decision, stats) is decision


# --- Serialization ----------------------------------------------------------


def test_decision_and_stats_round_trip_to_dict() -> None:
    """Decision/stats serialize to plain dicts for state/event transport."""
    stats = _healthy_stats(last_task_failed=TaskType.RANK)
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


def test_spent_tournament_budget_stops_asking_to_rank() -> None:
    """An exhausted budget must not be scheduled against forever.

    Coverage is a property of the pool and can sit below its threshold
    permanently. Once the run's tournament budget is spent, ranking can no
    longer move it, so a scheduler blind to the budget would request a task
    that returns immediately, every cycle, for the rest of the run.
    """
    stats = _healthy_stats(match_coverage=0.0, tournament_rounds_remaining=0)

    decision = decide_next_task(stats, _BUDGET, min_match_coverage=1.0)

    assert decision.next_task is not TaskType.RANK


def test_remaining_tournament_budget_still_ranks() -> None:
    """Low coverage with budget left is still answered by ranking."""
    stats = _healthy_stats(match_coverage=0.0, tournament_rounds_remaining=4)

    decision = decide_next_task(stats, _BUDGET, min_match_coverage=1.0)

    assert decision.next_task is TaskType.RANK


# --- Owed tournament coverage -----------------------------------------------


def test_uncompared_idea_ranks_despite_healthy_average() -> None:
    # An average cannot see an individual zero: 2 ideas at 2 matches each
    # averages 1.33 across 3 and clears the 1.0 threshold while one idea has
    # never played. The per-hypothesis check is what catches it.
    stats = _healthy_stats(
        rankable_count=3, match_coverage=1.33, unmatched_rankable_count=1
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.RANK


def test_owed_coverage_outranks_budget_termination() -> None:
    # A spent budget must not strand an idea that never played. The ceiling
    # is a runaway backstop, and the allowance bounds the overshoot.
    stats = _healthy_stats(
        rankable_count=3, unmatched_rankable_count=1, llm_calls=1000
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.RANK


def test_cancellation_outranks_owed_coverage() -> None:
    # The operator asked the run to stop; further tournament work is wrong.
    stats = _healthy_stats(
        rankable_count=3, unmatched_rankable_count=1, cancelled=True
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.CANCELLED


def test_safety_block_outranks_owed_coverage() -> None:
    stats = _healthy_stats(
        rankable_count=3, unmatched_rankable_count=1, safety_blocked=True
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.SAFETY


def test_steering_outranks_owed_coverage() -> None:
    # orchestrator_node clears pending_steering on the cycle it observes it,
    # so a settlement round taken on that cycle would mark the scientist's
    # message applied with nothing scheduled to incorporate it. Owed coverage
    # sits above the budget ceilings, so this places steering above them too:
    # a pending message buys one cycle on an exhausted budget, by design.
    stats = _healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=2,
        pending_steering=True,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.GENERATE
    assert "steering" in decision.reason


def test_spent_allowance_stops_overriding_the_budget() -> None:
    # The allowance is what bounds the override. At zero the check is inert
    # even though an idea is still uncompared, so the run can stop.
    stats = _healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        settlement_allowance=0,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.BUDGET


def test_stalled_settlement_stops_overriding_the_budget() -> None:
    # A round that did not reduce the backlog will not reduce it next time
    # either; spending the rest of the allowance on it wastes real debates.
    stats = _healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=2,
        settlement_allowance=5,
        unmatched_at_last_settlement=2,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.TERMINATE


def test_settlement_continues_while_backlog_shrinks() -> None:
    stats = _healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        settlement_allowance=5,
        unmatched_at_last_settlement=3,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.RANK


def test_single_rankable_hypothesis_never_settles() -> None:
    # Nothing to pair against, so demanding coverage could never be met.
    stats = _healthy_stats(
        pool_size=1,
        rankable_count=1,
        unmatched_rankable_count=1,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is not TaskType.RANK


def test_fully_compared_pool_is_unaffected() -> None:
    # Regression guard: with nothing owed, the budget ceiling still stops.
    stats = _healthy_stats(
        rankable_count=3, unmatched_rankable_count=0, llm_calls=1000
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.BUDGET

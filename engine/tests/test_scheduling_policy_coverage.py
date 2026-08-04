"""Tournament-coverage and settlement acceptance tests for scheduling policy.

Covers the whole-run tournament-pairs budget that bounds ranking
(``tournament_rounds_remaining``) and the owed-coverage settlement episode
that lets an uncompared idea override a spent run budget for a bounded,
non-stalling number of rounds. All assertions are against the pure
:func:`decide_next_task` function, independent of the graph topology. Shared
``BUDGET``/``healthy_stats`` fixtures live in ``tests._scheduling``.
"""

from co_scientist.scheduling import (
    TaskType,
    TerminationReason,
    decide_next_task,
)
from tests._scheduling import BUDGET, healthy_stats

# --- Tournament budget ------------------------------------------------------


def test_spent_tournament_budget_stops_asking_to_rank() -> None:
    """An exhausted budget must not be scheduled against forever.

    Coverage is a property of the pool and can sit below its threshold
    permanently. Once the run's tournament budget is spent, ranking can no
    longer move it, so a scheduler blind to the budget would request a task
    that returns immediately, every cycle, for the rest of the run.
    """
    stats = healthy_stats(match_coverage=0.0, tournament_rounds_remaining=0)

    decision = decide_next_task(stats, BUDGET, min_match_coverage=1.0)

    assert decision.next_task is not TaskType.RANK


def test_remaining_tournament_budget_still_ranks() -> None:
    """Low coverage with budget left is still answered by ranking."""
    stats = healthy_stats(match_coverage=0.0, tournament_rounds_remaining=4)

    decision = decide_next_task(stats, BUDGET, min_match_coverage=1.0)

    assert decision.next_task is TaskType.RANK


# --- Owed tournament coverage -----------------------------------------------


def test_uncompared_idea_ranks_despite_healthy_average() -> None:
    # An average cannot see an individual zero: 2 ideas at 2 matches each
    # averages 1.33 across 3 and clears the 1.0 threshold while one idea has
    # never played. The per-hypothesis check is what catches it.
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


def test_cancellation_outranks_owed_coverage() -> None:
    # The operator asked the run to stop; further tournament work is wrong.
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
        cancelled=True,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.CANCELLED


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
    # orchestrator_node clears pending_steering on the cycle it observes it,
    # so a settlement round taken on that cycle would mark the scientist's
    # message applied with nothing scheduled to incorporate it. Owed coverage
    # sits above the budget ceilings, so this places steering above them too:
    # a pending message buys one cycle on an exhausted budget, by design.
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
    # The allowance is what bounds the override. At zero the check is inert
    # even though an idea is still uncompared, so the run can stop.
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
    # Nothing to pair against, so demanding coverage could never be met.
    # The owed-rounds figure here is deliberately inconsistent with the pool:
    # the coverage floor already returns zero for a pool that admits no
    # pairing, and this pins the check's own guard as the second line of
    # defence rather than resting on that.
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
    # Regression guard: with nothing owed, the budget ceiling still stops.
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=0,
        owed_coverage_rounds=0,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.BUDGET

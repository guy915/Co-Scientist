"""Settlement-allowance lifecycle and the owed-coverage termination bound.

Covers the orchestrator-side half of owed-coverage settlement: deriving the
unmatched count from the pool, and initialising, decrementing, and never
refilling the allowance that bounds how long the scheduler may override a
budget ceiling to finish owed tournament rounds.
"""

from co_scientist.agents.supervisor.orchestrator import (
    _init_bookkeeping,
    _next_bookkeeping,
    _rankable_coverage,
)
from co_scientist.models import Hypothesis
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    decide_next_task,
)


def _hyp(hyp_id: str, wins: int = 0, losses: int = 0) -> Hypothesis:
    """A minimal rankable hypothesis with the given match tally."""
    return Hypothesis(
        id=hyp_id,
        text=f"statement {hyp_id}",
        win_count=wins,
        loss_count=losses,
    )


def test_rankable_coverage_counts_never_matched_hypotheses() -> None:
    # A healthy average hides individual zeros: two ideas at two matches
    # each averages 1.33 across three, passing a 1.0 average gate while one
    # idea has never played.
    rankable, avg, unmatched = _rankable_coverage(
        [_hyp("a", wins=2), _hyp("b", losses=2), _hyp("c")]
    )

    assert rankable == 3
    assert avg > 1.0
    assert unmatched == 1


def test_rankable_coverage_ignores_unrankable_hypotheses() -> None:
    # An evidence-gate-rejected idea can never accrue matches, so counting
    # it as unmatched would demand tournament rounds that cannot help it.
    blocked = _hyp("blocked")
    blocked.review_disposition = "evidence_blocked"

    rankable, _, unmatched = _rankable_coverage([_hyp("a", wins=1), blocked])

    assert rankable == 1
    assert unmatched == 0


def _settlement_stats(**overrides: object) -> SchedulerStats:
    """Stats for a pool mid-settlement, with overridable allowance state."""
    base: dict[str, object] = {
        "pool_size": 6,
        "rankable_count": 6,
        "unmatched_rankable_count": 4,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


_RANK = SupervisorDecision(next_task=TaskType.RANK, reason="settle")


def test_first_settlement_initialises_and_spends_one_round() -> None:
    # Four unmatched ideas need at most two rounds (two per pairing); the
    # first firing spends one of them.
    book = _next_bookkeeping(_init_bookkeeping([]), _settlement_stats(), _RANK)

    assert book["settlement_allowance"] == 1
    assert book["unmatched_at_last_settlement"] == 4


def test_allowance_is_bounded_by_distinct_pairs() -> None:
    # Two rankable ideas admit exactly one pairing. The allowance formula
    # takes min(half-count, max_pairs): with 4 unmatched, half-count is 2
    # but max_pairs is 1, so the cap applies. This state (2 rankable, 4
    # unmatched) cannot exist in a real pool but is legal as plain dataclass
    # fields; it forces the discriminator: without the max_pairs term, the
    # allowance would be 2 instead of 1.
    stats = _settlement_stats(rankable_count=2, unmatched_rankable_count=4)

    book = _next_bookkeeping(_init_bookkeeping([]), stats, _RANK)

    assert book["settlement_allowance"] == 0


def test_allowance_decrements_and_never_refills() -> None:
    # New hypotheses arriving mid-settlement must not hand the run more
    # rounds: a refillable counter would not bound anything.
    book = {
        "settlement_allowance": 3,
        "unmatched_at_last_settlement": 2,
        "pool_at_last_decision": 6,
    }

    updated = _next_bookkeeping(
        book, _settlement_stats(unmatched_rankable_count=99), _RANK
    )

    assert updated["settlement_allowance"] == 2


def test_allowance_floors_at_zero() -> None:
    book = {"settlement_allowance": 0, "unmatched_at_last_settlement": 1}

    updated = _next_bookkeeping(book, _settlement_stats(), _RANK)

    assert updated["settlement_allowance"] == 0


def test_non_settlement_rank_leaves_the_allowance_alone() -> None:
    # A ranking round requested for ordinary calibration, with nothing owed,
    # must not consume settlement budget.
    book = _init_bookkeeping([])

    updated = _next_bookkeeping(
        book, _settlement_stats(unmatched_rankable_count=0), _RANK
    )

    assert updated.get("settlement_allowance") is None


def test_settlement_terminates_while_the_backlog_still_shrinks() -> None:
    # The load-bearing case. The backlog falls by one every round, so the
    # stall guard never fires and cannot be what stops this -- only the
    # allowance can. A pool of 8 with 8 unmatched is granted 4 rounds, which
    # runs out long before a backlog shrinking one at a time reaches zero.
    #
    # The loop cap is a test failsafe, not the mechanism under test: 50 is
    # far above the largest allowance this pool could be granted.
    budget = Budget(max_iterations=5, max_llm_calls=10)
    book = _init_bookkeeping([])
    backlog = 8
    decision = None
    rounds = 0

    for _ in range(50):
        stats = SchedulerStats(
            pool_size=8,
            reviewed_count=8,
            rankable_count=8,
            unmatched_rankable_count=backlog,
            llm_calls=999,
            settlement_allowance=book.get("settlement_allowance"),
            unmatched_at_last_settlement=book.get(
                "unmatched_at_last_settlement"
            ),
        )
        decision = decide_next_task(stats, budget)
        if decision.terminate:
            break
        book = _next_bookkeeping(book, stats, decision)
        backlog -= 1
        rounds += 1

    assert decision is not None
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET
    # Stopped on the allowance (4 rounds), with work still outstanding.
    assert rounds == 4
    assert backlog > 0


def test_settlement_terminates_when_ranking_never_helps() -> None:
    # The stall guard's own case: a round that changes nothing must not be
    # repeated. Terminates faster than the allowance alone would.
    budget = Budget(max_iterations=5, max_llm_calls=10)
    book = _init_bookkeeping([])
    decision = None

    for _ in range(50):
        stats = SchedulerStats(
            pool_size=8,
            reviewed_count=8,
            rankable_count=8,
            unmatched_rankable_count=8,
            llm_calls=999,
            settlement_allowance=book.get("settlement_allowance"),
            unmatched_at_last_settlement=book.get(
                "unmatched_at_last_settlement"
            ),
        )
        decision = decide_next_task(stats, budget)
        if decision.terminate:
            break
        book = _next_bookkeeping(book, stats, decision)

    assert decision is not None
    assert decision.terminate


def test_settlement_allowance_is_monotonically_decreasing() -> None:
    # The termination proof rests on this and nothing else: the counter
    # never increases, on any path, whatever the pool does.
    book = _init_bookkeeping([])
    seen: list[int] = []

    for unmatched in (8, 8, 12, 3, 40):
        stats = _settlement_stats(
            rankable_count=8,
            unmatched_rankable_count=unmatched,
            settlement_allowance=book.get("settlement_allowance"),
        )
        book = _next_bookkeeping(book, stats, _RANK)
        seen.append(int(book["settlement_allowance"]))

    assert seen == sorted(seen, reverse=True)
    assert seen[-1] == 0

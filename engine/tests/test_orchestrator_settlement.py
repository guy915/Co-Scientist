"""Settlement-allowance lifecycle and the owed-coverage termination bound.

Covers the orchestrator-side half of owed-coverage settlement: deriving the
unmatched count from the pool, and initialising, decrementing, and never
refilling the allowance that bounds how long the scheduler may override a
budget ceiling to finish owed tournament rounds.
"""

from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor
from co_scientist.agents.supervisor.orchestrator import (
    _init_bookkeeping,
    _initial_settlement_allowance,
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


def _pool(unmatched: int, covered: int = 0) -> list[Hypothesis]:
    """A rankable pool: `unmatched` ideas that never played, `covered` that did.

    A covered idea carries two matches, which is
    ``TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS``, so it owes the tournament
    nothing and every owed slot in the pool belongs to an unmatched idea.
    """
    return [_hyp(f"u{i}") for i in range(unmatched)] + [
        _hyp(f"c{i}", wins=1, losses=1) for i in range(covered)
    ]


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


def test_allowance_is_the_tournament_coverage_floor() -> None:
    """One count of what the pool owes, not two that agree at the extremes.

    The allowance and ``ranking_lifecycle._coverage_floor`` answer the same
    question -- how many rounds the pool's owed matches could still use -- so
    they are one implementation. A near-copy that counted ideas with no match
    at all agreed with the floor on an untouched pool and on a fully covered
    one, and disagreed everywhere in between: ten ideas sitting at one match
    each owe a second match apiece, which is five rounds to the tournament and
    read as zero to the orchestrator, ending settlement while the tournament's
    own floor was still asking for rounds.
    """
    untouched = _pool(10)
    partially = [_hyp(f"h{i}", wins=1) for i in range(10)]
    covered = _pool(0, 10)

    assert _initial_settlement_allowance(partially) == 5
    for pool in (untouched, partially, covered):
        assert _initial_settlement_allowance(pool) == _coverage_floor(pool)


def test_first_settlement_initialises_and_spends_one_round() -> None:
    # Four ideas that never played owe two matches each: eight slots, which
    # is four rounds at two slots settled per pairing. The first firing
    # spends one of them.
    book = _next_bookkeeping(
        _init_bookkeeping([]), _settlement_stats(), _RANK, _pool(4, 2)
    )

    assert book["settlement_allowance"] == 3
    assert book["unmatched_at_last_settlement"] == 4


def test_allowance_is_bounded_by_distinct_pairs() -> None:
    # Two rankable ideas owe four match slots between them, which is two
    # rounds' worth, but they admit exactly one distinct pairing. The
    # allowance takes min(half-slots, max_pairs), so the cap applies: without
    # the max_pairs term the initial allowance would be 2 and this would read
    # 1 after the first firing.
    stats = _settlement_stats(
        pool_size=2, rankable_count=2, unmatched_rankable_count=2
    )

    book = _next_bookkeeping(_init_bookkeeping([]), stats, _RANK, _pool(2))

    assert book["settlement_allowance"] == 0


def test_allowance_decrements_and_never_refills() -> None:
    # New hypotheses arriving mid-settlement must not hand the run more
    # rounds: a refillable counter would not bound anything. The pool here
    # owes far more than the allowance already carries.
    book = {
        "settlement_allowance": 3,
        "unmatched_at_last_settlement": 2,
        "pool_at_last_decision": 6,
    }

    updated = _next_bookkeeping(
        book,
        _settlement_stats(unmatched_rankable_count=99),
        _RANK,
        _pool(40),
    )

    assert updated["settlement_allowance"] == 2


def test_allowance_floors_at_zero() -> None:
    book = {"settlement_allowance": 0, "unmatched_at_last_settlement": 1}

    updated = _next_bookkeeping(book, _settlement_stats(), _RANK, _pool(4, 2))

    assert updated["settlement_allowance"] == 0


def test_non_settlement_rank_leaves_the_allowance_alone() -> None:
    # A ranking round requested for ordinary calibration, with nothing owed,
    # must not consume settlement budget.
    book = _init_bookkeeping([])

    updated = _next_bookkeeping(
        book,
        _settlement_stats(unmatched_rankable_count=0),
        _RANK,
        _pool(0, 6),
    )

    assert updated.get("settlement_allowance") is None


def _loop_stats(book: dict[str, object], **overrides: object) -> SchedulerStats:
    """Stats for one decision, with the allowance read out of bookkeeping."""
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "rankable_count": 6,
        "settlement_allowance": book.get("settlement_allowance"),
        "unmatched_at_last_settlement": book.get(
            "unmatched_at_last_settlement"
        ),
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_late_backlog_settles_after_an_early_episode_cleared() -> None:
    # The motivating production shape. An early cycle carries one unmatched
    # idea and ranks it; the backlog then reaches zero. A later wave leaves
    # 13 ideas unmatched at an exhausted budget. A run-scoped allowance was
    # sized (and spent) on the early episode, so unless it re-arms once the
    # backlog clears, the late wave never settles and the run ends exactly
    # as it did before the check existed.
    budget = Budget(max_iterations=5, max_llm_calls=10)
    book = _init_bookkeeping([])

    early = _loop_stats(book, unmatched_rankable_count=1)
    early_decision = decide_next_task(early, budget)
    assert early_decision.next_task is TaskType.RANK
    book = _next_bookkeeping(book, early, early_decision, _pool(1, 5))

    cleared = _loop_stats(book, unmatched_rankable_count=0)
    book = _next_bookkeeping(
        book, cleared, decide_next_task(cleared, budget), _pool(0, 6)
    )

    late = _loop_stats(
        book,
        pool_size=48,
        reviewed_count=48,
        rankable_count=48,
        unmatched_rankable_count=13,
        llm_calls=999,
    )

    assert decide_next_task(late, budget).next_task is TaskType.RANK


def test_cleared_backlog_rearms_the_allowance() -> None:
    # The episode boundary itself: once nothing is owed, both the allowance
    # and the stall reference return to their unarmed state so a future
    # backlog is sized from what it actually owes.
    book = {
        "settlement_allowance": 0,
        "unmatched_at_last_settlement": 2,
    }

    updated = _next_bookkeeping(
        book,
        _settlement_stats(unmatched_rankable_count=0),
        _RANK,
        _pool(0, 6),
    )

    assert updated["settlement_allowance"] is None
    assert updated["unmatched_at_last_settlement"] is None


def test_ordinary_ranking_does_not_charge_the_allowance() -> None:
    # A RANK the owed-coverage check did not ask for must not spend
    # settlement budget. Here the stall guard has the check suppressed, so
    # this round came from the average-coverage gate instead. Inferring
    # intent from "RANK while anything is unmatched" charged it anyway.
    stats = _settlement_stats(
        unmatched_rankable_count=2,
        settlement_allowance=5,
        unmatched_at_last_settlement=2,
    )
    book = {"settlement_allowance": 5, "unmatched_at_last_settlement": 2}

    updated = _next_bookkeeping(book, stats, _RANK, _pool(2, 4))

    assert updated["settlement_allowance"] == 5
    assert updated["unmatched_at_last_settlement"] == 2


def test_stall_guard_does_not_compare_across_episodes() -> None:
    # A larger later backlog is not a stall: 13 owed after an episode that
    # recorded 2 must still settle rather than read as "no progress".
    book = {
        "settlement_allowance": None,
        "unmatched_at_last_settlement": 2,
    }
    cleared = _settlement_stats(unmatched_rankable_count=0)

    updated = _next_bookkeeping(book, cleared, _RANK, _pool(0, 6))
    stats = _settlement_stats(
        rankable_count=48,
        unmatched_rankable_count=13,
        settlement_allowance=updated["settlement_allowance"],
        unmatched_at_last_settlement=updated["unmatched_at_last_settlement"],
        llm_calls=999,
    )

    decision = decide_next_task(
        stats, Budget(max_iterations=5, max_llm_calls=10)
    )

    assert decision.next_task is TaskType.RANK


def test_settlement_terminates_while_the_backlog_still_shrinks() -> None:
    # The load-bearing case. The backlog falls by one every round, so the
    # stall guard never fires and cannot be what stops this -- only the
    # allowance can.
    #
    # A two-idea pool is what makes the allowance bind, and deliberately so.
    # The allowance is the pool's coverage floor, and a round that settles
    # anything retires at least as much owed coverage as the round costs, so
    # on a larger pool a settlement that keeps making progress finishes before
    # the allowance does -- which is the point of sizing it from the floor.
    # The distinct-pairs cap is the remaining way it can run out first: these
    # two ideas owe four match slots but admit a single pairing, so they are
    # granted one round against a backlog of two.
    #
    # The loop cap is a test failsafe, not the mechanism under test: 50 is
    # far above the largest allowance this pool could be granted.
    budget = Budget(max_iterations=5, max_llm_calls=10)
    book = _init_bookkeeping([])
    backlog = 2
    decision = None
    rounds = 0

    for _ in range(50):
        stats = SchedulerStats(
            pool_size=2,
            reviewed_count=2,
            rankable_count=2,
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
        book = _next_bookkeeping(
            book, stats, decision, _pool(backlog, 2 - backlog)
        )
        backlog -= 1
        rounds += 1

    assert decision is not None
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET
    # Stopped on the allowance (1 round), with work still outstanding.
    assert rounds == 1
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
        book = _next_bookkeeping(book, stats, decision, _pool(8))

    assert decision is not None
    assert decision.terminate


def test_settlement_allowance_is_monotonically_decreasing() -> None:
    # The termination proof rests on this and nothing else: the counter
    # never increases, on any path, whatever the pool does. The pool here
    # shrinks, grows, and doubles between rounds; only the first round sizes
    # the allowance, and no later one may add to it.
    book = _init_bookkeeping([])
    seen: list[int] = []

    for pool in (_pool(4), _pool(4), _pool(6), _pool(1, 3), _pool(8)):
        unmatched = sum(1 for h in pool if h.total_matches == 0)
        stats = _settlement_stats(
            pool_size=len(pool),
            rankable_count=len(pool),
            unmatched_rankable_count=unmatched,
            settlement_allowance=book.get("settlement_allowance"),
        )
        book = _next_bookkeeping(book, stats, _RANK, pool)
        seen.append(int(book["settlement_allowance"]))

    assert seen == sorted(seen, reverse=True)
    assert seen[-1] == 0

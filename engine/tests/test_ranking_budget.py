"""Tests for the tournament round budget and its coverage floor.

``tournament_pairs`` is a whole-run allowance rather than a per-invocation
one, and it bounds how far a run refines its ordering -- never whether a
hypothesis is rated at all. These cover both halves: the budget arithmetic
across a run, and the coverage floor that outranks it so no rankable idea
finishes a run reporting the starting Elo it never played for.

Split from ``test_ranking.py`` to keep that file under the line ceiling.
"""

from co_scientist.agents.ranking.ranking import ranking_node
from tests._state import make_hypothesis, make_state


def test_tournament_budget_is_spent_across_the_whole_run() -> None:
    """tournament_pairs is a run-level allowance, not a per-invocation one.

    The scheduler asks for ranking once per cycle. Charging each invocation
    the full allowance is how a standard run configured for 12 matches came
    to judge about 22, every one of them real model work on the serial
    spine.

    Every hypothesis here has already played, so the coverage floor is zero
    and the budget arithmetic is what remains. The floor's precedence over
    the budget is pinned separately below.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import ExecutionMetrics

    hypotheses = [
        make_hypothesis(text=f"h{i}", win_count=1, loss_count=1)
        for i in range(4)
    ]

    fresh = make_state(hypotheses=hypotheses, tournament_pairs=12)
    assert _tournament_round_count(fresh, hypotheses) == 12

    partway = make_state(
        hypotheses=hypotheses,
        tournament_pairs=12,
        metrics=ExecutionMetrics(tournaments_count=9),
    )
    assert _tournament_round_count(partway, hypotheses) == 3

    spent = make_state(
        hypotheses=hypotheses,
        tournament_pairs=12,
        metrics=ExecutionMetrics(tournaments_count=12),
    )
    assert _tournament_round_count(spent, hypotheses) == 0


def test_budget_scales_with_a_pool_the_tier_number_cannot_cover() -> None:
    """The allowance tracks the pool, which the tier constant does not.

    Evolution keeps adding ideas after the first ranking cycle, so a flat
    per-tier ceiling is spent on the ideas that existed first and every idea
    added later gets only the coverage floor's single match. A production run
    ended with twelve of eighteen rankable ideas on exactly one match, which
    from the flat starting rating leaves two reachable ratings -- the report
    showed a dozen ideas tied at 1212 and 1188 and called it a ranking.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )

    hypotheses = [
        make_hypothesis(text=f"h{i}", win_count=1, loss_count=1)
        for i in range(18)
    ]
    state = make_state(hypotheses=hypotheses, tournament_pairs=12)

    # 18 rankable ideas at three matches each, two ideas per match.
    assert _tournament_round_count(state, hypotheses) == 27


def test_budget_is_not_refunded_when_dedup_removes_hypotheses() -> None:
    """Consumed rounds come from run metrics, not from the surviving pool.

    Proximity dedup removes hypotheses and their match tallies with them.
    Recounting from the pool would hand the run back budget it had already
    spent every time the pool was cleaned.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import (
        consumed_tournament_rounds,
    )
    from co_scientist.models import ExecutionMetrics

    state = make_state(
        hypotheses=[],
        tournament_pairs=12,
        metrics=ExecutionMetrics(tournaments_count=8),
    )

    assert consumed_tournament_rounds(state) == 8


async def test_ranking_node_is_a_no_op_once_the_budget_is_spent() -> None:
    """A spent budget skips the tournament instead of buying another.

    Every hypothesis has already played, so nothing is owed a first match.
    """
    from co_scientist.models import ExecutionMetrics

    hypotheses = [
        make_hypothesis(text=f"h{i}", win_count=1, loss_count=1)
        for i in range(4)
    ]
    state = make_state(
        hypotheses=hypotheses,
        tournament_pairs=6,
        metrics=ExecutionMetrics(tournaments_count=6),
    )

    result = await ranking_node(state)

    assert result == {"hypotheses": hypotheses}


def test_spent_budget_still_owes_every_idea_a_win_loss_record() -> None:
    """Coverage outranks the budget: no idea is rated on a coin flip.

    tournament_pairs bounds how far a run refines its ordering. It must not
    decide that a hypothesis is reported at the starting Elo of 1200, which
    in the report is indistinguishable from a rating earned in matches --
    nor on a single match, which from that flat seed has exactly two
    possible outcomes and so reports one of two numbers.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import ExecutionMetrics

    played = [
        make_hypothesis(text=f"old{i}", win_count=1, loss_count=1)
        for i in range(2)
    ]
    unplayed = [make_hypothesis(text=f"new{i}") for i in range(3)]
    spent = make_state(
        hypotheses=played + unplayed,
        tournament_pairs=6,
        metrics=ExecutionMetrics(tournaments_count=6),
    )

    # The two played ideas already have a record; the three unplayed ones owe
    # two matches each, which is six slots and so ceil(6/2) = 3 rounds.
    assert _tournament_round_count(spent, played + unplayed) == 3


def test_one_match_is_not_enough_coverage_to_close_the_floor() -> None:
    """An idea on one match is still owed another.

    This is the shape the bug took in production: the floor funded one match
    per idea while the matchmaker was trying to reach two, so every idea the
    budget could not afford played exactly once. From the flat 1200 seed that
    leaves two reachable ratings, and a run reported six ideas at 1212 and
    seven at 1188 as though that were a ranking.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor

    once = [make_hypothesis(text=f"h{i}", win_count=1) for i in range(4)]

    assert _coverage_floor(once) == 2


def test_unrankable_ideas_do_not_hold_the_coverage_floor_open() -> None:
    """Quarantined ideas can never be matched, so they cannot owe a match.

    Counting them would keep the floor permanently above zero and loop the
    orchestrator on ranking for the rest of the run.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import ExecutionMetrics

    hypotheses = [
        make_hypothesis(text="played", win_count=1, loss_count=1),
        make_hypothesis(text="blocked", review_disposition="evidence_blocked"),
        make_hypothesis(text="rejected", review_disposition="non_novel"),
    ]
    spent = make_state(
        hypotheses=hypotheses,
        tournament_pairs=6,
        metrics=ExecutionMetrics(tournaments_count=6),
    )

    assert _tournament_round_count(spent, hypotheses) == 0


def test_floor_counts_a_lone_undercovered_idea_s_own_rounds() -> None:
    """A single idea can only settle one of its owed slots per round.

    ``ceil(owed / 2)`` assumes every match pairs two under-covered ideas, so
    each round settles two owed slots. Once the pool is down to ONE idea below
    the minimum, each of its matches settles a single slot of its own, and it
    needs as many rounds as it owes matches. The old ``ceil(owed / 2)`` gave a
    lone idea owing two matches a single round: it played once, stayed one
    match short of the minimum, and the tournament stopped. The floor must be
    at least the largest individual debt.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor

    lone_fresh = make_hypothesis(text="fresh")
    covered = [
        make_hypothesis(text=f"c{i}", win_count=1, loss_count=1)
        for i in range(4)
    ]

    # One idea owes two matches; the rest are covered. ceil(2/2)=1 is too
    # few -- the idea can play only one of those matches per round.
    assert _coverage_floor([lone_fresh, *covered]) == 2


def test_floor_is_at_least_the_largest_individual_debt() -> None:
    """The round count is bounded below by the most-indebted idea.

    Two ideas each owing two matches need two rounds even though their four
    owed slots divide into two pairings: they cannot face each other twice in
    one build, so the second round pairs each with a covered idea instead.
    The two bounds (ceil of the slots, largest single debt) agree here; the
    point is the floor never reports less than either.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor

    two_fresh = [make_hypothesis(text=f"new{i}") for i in range(2)]
    covered = [
        make_hypothesis(text=f"c{i}", win_count=1, loss_count=1)
        for i in range(3)
    ]

    # Four owed slots -> ceil(4/2)=2; largest debt is 2. Floor is 2.
    assert _coverage_floor([*two_fresh, *covered]) == 2

"""Tests for deterministic weighted tournament matchmaking (Milestone 3).

Proves the pairing biases (similar, newer, top-ranked, low-coverage), the
absence of invalid matches (self / immediate duplicate), minimum coverage
(no starvation), and replayability for a fixed seed — the M3 acceptance
requirements — against the pure :func:`build_weighted_pairings`.
"""

import itertools
from collections import Counter

from co_scientist.agents.ranking.ranking_matchmaking import (
    MatchCandidate,
    MatchmakingWeights,
    build_weighted_pairings,
)


def _cands(*specs: tuple[str, int, int, str | None]) -> list[MatchCandidate]:
    """Build candidates from (id, elo, matches, cluster) tuples."""
    return [MatchCandidate(i, e, m, c) for (i, e, m, c) in specs]


def test_no_self_or_immediate_duplicate_matches() -> None:
    """No pairing pits a hypothesis against itself; no back-to-back rematch."""
    candidates = _cands(
        ("a", 1200, 0, None),
        ("b", 1200, 0, None),
        ("c", 1200, 0, None),
        ("d", 1200, 0, None),
    )
    pairs = build_weighted_pairings(candidates, rounds=12, seed=7)
    for x, y in pairs:
        assert x != y  # no self-match
    # No identical pair appears twice in a row.
    for prev, cur in itertools.pairwise(pairs):
        assert set(prev) != set(cur)


def test_minimum_coverage_reached_no_starvation() -> None:
    """Every hypothesis reaches the minimum match coverage before extras."""
    candidates = _cands(
        ("a", 1400, 0, None),
        ("b", 1200, 0, None),
        ("c", 1100, 0, None),
        ("d", 1000, 0, None),
        ("e", 900, 0, None),
    )
    # Exactly enough rounds to cover 5 hypotheses at 1 match each needs at
    # least ceil(5/2)=3 rounds; give a few more and require full coverage.
    pairs = build_weighted_pairings(
        candidates,
        rounds=6,
        seed=3,
        weights=MatchmakingWeights(min_coverage=1),
    )
    played: Counter[str] = Counter()
    for x, y in pairs:
        played[x] += 1
        played[y] += 1
    for c in candidates:
        assert played[c.id] >= 1, f"{c.id} was starved"


def test_newer_hypotheses_are_prioritized() -> None:
    """Hypotheses with fewer prior matches play more, all else equal."""
    candidates = _cands(
        ("veteran", 1200, 20, None),
        ("newA", 1200, 0, None),
        ("newB", 1200, 0, None),
        ("newC", 1200, 0, None),
    )
    pairs = build_weighted_pairings(candidates, rounds=30, seed=11)
    played: Counter[str] = Counter()
    for x, y in pairs:
        played[x] += 1
        played[y] += 1
    # The three fresh hypotheses collectively play more than the veteran.
    fresh = played["newA"] + played["newB"] + played["newC"]
    assert fresh > played["veteran"] * 2


def test_top_ranked_hypotheses_are_prioritized() -> None:
    """Higher-Elo hypotheses are matched more often, coverage being equal.

    Scheduled well under the pool's distinct-pair ceiling (4 of a possible
    10), because that is the only regime where the weights decide anything:
    a build allowed to schedule every pair matches everyone equally by
    construction. Summed over seeds so the claim is about the weighting and
    not about one lucky draw.
    """
    candidates = _cands(
        ("top", 1600, 5, None),
        ("midA", 1200, 5, None),
        ("midB", 1200, 5, None),
        ("midC", 1200, 5, None),
        ("low", 800, 5, None),
    )
    played: Counter[str] = Counter()
    for seed in range(10):
        for x, y in build_weighted_pairings(candidates, rounds=4, seed=seed):
            played[x] += 1
            played[y] += 1
    assert played["top"] > played["low"]


def test_similar_hypotheses_are_preferred() -> None:
    """Partners in the same proximity cluster are compared more often.

    Two clusters of three, so 6 of the 15 distinct pairs are same-cluster
    and 9 are cross-cluster: preferring similarity has to beat those odds.
    Scheduled at 6 rounds rather than exhaustively, since a build that
    takes every pair takes all 9 cross-cluster ones too.
    """
    candidates = _cands(
        ("a1", 1200, 5, "cluster-1"),
        ("a2", 1200, 5, "cluster-1"),
        ("a3", 1200, 5, "cluster-1"),
        ("b1", 1200, 5, "cluster-2"),
        ("b2", 1200, 5, "cluster-2"),
        ("b3", 1200, 5, "cluster-2"),
    )
    same_cluster = cross_cluster = 0
    for seed in range(10):
        pairs = build_weighted_pairings(
            candidates,
            rounds=6,
            seed=seed,
            weights=MatchmakingWeights(similarity_bonus=5.0),
        )
        # ids share their first letter within a cluster
        same = sum(1 for x, y in pairs if x[0] == y[0])
        same_cluster += same
        cross_cluster += len(pairs) - same
    assert same_cluster > cross_cluster


def test_deterministic_for_fixed_seed() -> None:
    """A fixed seed replays the identical schedule."""
    candidates = _cands(
        ("a", 1300, 2, "c1"),
        ("b", 1200, 4, "c1"),
        ("c", 1100, 1, "c2"),
        ("d", 1000, 3, "c2"),
    )
    first = build_weighted_pairings(candidates, rounds=15, seed=42)
    second = build_weighted_pairings(candidates, rounds=15, seed=42)
    assert first == second
    # A different seed generally yields a different schedule.
    other = build_weighted_pairings(candidates, rounds=15, seed=43)
    assert other != first


def test_fewer_than_two_candidates_yields_no_pairs() -> None:
    """A single-candidate (or empty) pool cannot be paired."""
    assert build_weighted_pairings(_cands(("a", 1200, 0, None)), 5, 1) == []
    assert build_weighted_pairings([], 5, 1) == []


def test_a_pair_is_never_scheduled_twice_in_one_build() -> None:
    """One build picks every matchup from a single Elo snapshot.

    Re-scheduling a pair it has already chosen therefore replays a
    comparison rather than making one, and moves the winner's rating for
    it. Asking for far more rounds than the pool has pairs must yield the
    pairs it has, not repeats.
    """
    candidates = _cands(
        ("a", 1200, 0, None),
        ("b", 1200, 0, None),
        ("c", 1200, 0, None),
        ("d", 1200, 0, None),
    )
    pairs = build_weighted_pairings(candidates, rounds=50, seed=3)

    assert len(pairs) == len({frozenset(pair) for pair in pairs})
    # 4 candidates admit exactly 4*3/2 distinct pairs.
    assert len(pairs) == 6


def test_two_rankable_ideas_yield_one_match_not_a_ratchet() -> None:
    """The production failure: a two-idea pool judged one pair six times.

    Every run in production spent its whole tournament this way, and the
    winner was reported at 1259 as though it had beaten six opponents when
    it had beaten one opponent six times.
    """
    candidates = _cands(("a", 1200, 0, None), ("b", 1200, 0, None))

    pairs = build_weighted_pairings(candidates, rounds=6, seed=1)

    assert pairs == [("a", "b")] or pairs == [("b", "a")]


def test_every_candidate_is_matched_when_rounds_allow() -> None:
    """No hypothesis leaves a build unmatched while rounds remain.

    An unmatched hypothesis keeps its starting rating, which then reads as
    a tournament result it never earned.
    """
    candidates = _cands(
        ("a", 1500, 0, None),
        ("b", 1400, 0, None),
        ("c", 1300, 0, None),
        ("d", 800, 0, None),
        ("e", 700, 0, None),
        ("f", 600, 0, None),
    )
    for seed in range(10):
        pairs = build_weighted_pairings(candidates, rounds=3, seed=seed)
        matched = {name for pair in pairs for name in pair}
        assert matched == {c.id for c in candidates}, f"seed {seed}"

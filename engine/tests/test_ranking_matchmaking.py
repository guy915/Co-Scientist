"""Tests for deterministic weighted tournament matchmaking (Milestone 3).

Proves the pairing biases (similar, newer, top-ranked, low-coverage), the
absence of invalid matches (self / immediate duplicate), minimum coverage
(no starvation), and replayability for a fixed seed — the M3 acceptance
requirements — against the pure :func:`build_weighted_pairings`.
"""

import itertools
from collections import Counter

from co_scientist.nodes.ranking_matchmaking import (
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
    """Higher-Elo hypotheses are matched more often, coverage being equal."""
    candidates = _cands(
        ("top", 1600, 5, None),
        ("midA", 1200, 5, None),
        ("midB", 1200, 5, None),
        ("low", 800, 5, None),
    )
    pairs = build_weighted_pairings(candidates, rounds=40, seed=5)
    played: Counter[str] = Counter()
    for x, y in pairs:
        played[x] += 1
        played[y] += 1
    assert played["top"] > played["low"]


def test_similar_hypotheses_are_preferred() -> None:
    """Partners in the same proximity cluster are compared more often.

    Uses two clusters of three so there are enough same-cluster pairs that
    duplicate-avoidance does not force cross-cluster matches (ids share their
    first letter within a cluster).
    """
    candidates = _cands(
        ("a1", 1200, 5, "cluster-1"),
        ("a2", 1200, 5, "cluster-1"),
        ("a3", 1200, 5, "cluster-1"),
        ("b1", 1200, 5, "cluster-2"),
        ("b2", 1200, 5, "cluster-2"),
        ("b3", 1200, 5, "cluster-2"),
    )
    pairs = build_weighted_pairings(
        candidates,
        rounds=90,
        seed=9,
        weights=MatchmakingWeights(similarity_bonus=5.0),
    )
    same_cluster = sum(
        1
        for x, y in pairs
        if x[0] == y[0]  # ids share the cluster prefix letter
    )
    cross_cluster = len(pairs) - same_cluster
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

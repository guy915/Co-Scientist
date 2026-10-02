"""Deterministic hypothesis pairing, shared by graph and durable ranking."""

import hashlib

from co_scientist.agents.ranking.ranking_matchmaking import (
    MatchCandidate,
    build_weighted_pairings,
)
from co_scientist.models import Hypothesis


def _build_match_candidates(
    hypotheses: list[Hypothesis],
) -> list[MatchCandidate]:
    """Reduces hypotheses to the fields matchmaking needs."""
    return [
        MatchCandidate(
            id=h.id,
            elo=h.elo_rating,
            matches=h.total_matches,
            cluster_id=h.similarity_cluster_id,
        )
        for h in hypotheses
    ]


def build_tournament_pairings(
    hypotheses: list[Hypothesis],
    tournament_rounds: int,
    research_goal: str,
    current_iteration: int,
    judged: set[frozenset[str]] | None = None,
) -> list[tuple[Hypothesis, Hypothesis]]:
    """Builds deterministic weighted pairwise matchups for one tournament.

    Uses proximity-, recency-, and rank-aware matchmaking (Milestone 3; paper
    invariant SSR §4): pairings favor scientifically similar hypotheses (same
    proximity cluster), newer hypotheses needing calibration, and top-ranked
    hypotheses needing discrimination, while guaranteeing minimum match
    coverage and avoiding self/immediate-duplicate matches.

    The seed is derived from research_goal and current_iteration so identical
    inputs replay identical pairings (cache consistency across iterations).
    Uses hashlib instead of hash() so the seed is stable across processes.

    Args:
        hypotheses: All hypotheses eligible for pairing.
        tournament_rounds: Number of pairings to generate.
        research_goal: Research goal, used to seed the deterministic RNG.
        current_iteration: Current workflow iteration, used to seed the RNG.
        judged: Pairs this tournament has already judged. Never offered
            again, so a tournament runs out of comparisons rather than
            replaying one.

    Returns:
        List of (hypothesis_a, hypothesis_b) pairings, one per round; empty
        once every distinct pair has been judged.
    """
    seed_string = f"{research_goal}_{current_iteration}"
    seed = int(hashlib.md5(seed_string.encode()).hexdigest()[:8], 16)

    by_id = {h.id: h for h in hypotheses}
    candidates = _build_match_candidates(hypotheses)
    id_pairs = build_weighted_pairings(
        candidates, tournament_rounds, seed, exclude=judged
    )
    return [(by_id[a], by_id[b]) for a, b in id_pairs]

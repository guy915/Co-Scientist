"""Deterministic weighted tournament matchmaking.

Replaces bounded random sampling with proximity-, recency-, and rank-aware
pairing (paper invariant SSR §4 Ranking). The pairing
policy favors:

- scientifically similar hypotheses (same proximity cluster);
- newer hypotheses needing calibration (fewer prior matches);
- top-ranked hypotheses needing discrimination (higher Elo);
- candidates with low match coverage;

while preventing self-matches, immediate duplicate rematches, and starvation
(every hypothesis reaches a configured minimum match coverage before extra
discriminating matches are scheduled).

The core :func:`build_weighted_pairings` is a pure function of a candidate list
and a seed, so the biases and coverage guarantees are unit-testable and a fixed
seed replays identically (Google leaves the exact weights unspecified; the
weights here are documented clone defaults).
"""

from __future__ import annotations

import dataclasses
import random


@dataclasses.dataclass(frozen=True)
class MatchCandidate:
    """A hypothesis reduced to the fields matchmaking needs."""

    id: str
    elo: int
    matches: int
    cluster_id: str | None = None


@dataclasses.dataclass
class MatchmakingWeights:
    """Tunable weights for the pairing policy.

    The defaults are clone-defined (Google leaves the exact weights
    unspecified): recency (calibrating new hypotheses) and rank
    (discriminating leaders) dominate the selection score, with a mild
    low-coverage term to prevent starvation; ``similarity_bonus`` boosts
    partners in the primary's proximity cluster; ``min_coverage`` is the
    per-hypothesis match floor reached before extra discriminating matches
    are scheduled.
    """

    recency: float = 1.0
    rank: float = 1.0
    coverage: float = 0.5
    similarity_bonus: float = 2.0
    min_coverage: int = 1


def _elo_range(candidates: list[MatchCandidate]) -> tuple[int, int]:
    """Return the (min, max) Elo across candidates for rank normalization."""
    elos = [c.elo for c in candidates]
    return min(elos), max(elos)


def _priority(
    candidate: MatchCandidate,
    coverage: dict[str, int],
    elo_lo: int,
    elo_hi: int,
    weights: MatchmakingWeights,
) -> float:
    """Score a candidate's selection priority from recency, rank, coverage.

    Higher is more likely to be picked. Recency rewards fewer prior matches
    (newer hypotheses need calibration); rank rewards higher normalized Elo
    (leaders need discrimination); coverage rewards under-played hypotheses.
    """
    recency = 1.0 / (1.0 + candidate.matches)
    span = (elo_hi - elo_lo) or 1
    rank = (candidate.elo - elo_lo) / span
    played = coverage.get(candidate.id, 0)
    low_coverage = 1.0 / (1.0 + played)
    return (
        weights.recency * recency
        + weights.rank * rank
        + weights.coverage * low_coverage
    )


def _weighted_choice(
    scored: list[tuple[MatchCandidate, float]], rng: random.Random
) -> MatchCandidate:
    """Pick one candidate weighted by its score (deterministic given rng)."""
    total = sum(score for _, score in scored)
    if total <= 0:
        return rng.choice([c for c, _ in scored])
    threshold = rng.random() * total
    cumulative = 0.0
    for candidate, score in scored:
        cumulative += score
        if cumulative >= threshold:
            return candidate
    return scored[-1][0]


def _select_primary(
    candidates: list[MatchCandidate],
    coverage: dict[str, int],
    weights: MatchmakingWeights,
    rng: random.Random,
) -> MatchCandidate:
    """Select the first side of a match.

    Under-covered hypotheses (below ``min_coverage``) are chosen first to
    prevent starvation; once every hypothesis is covered, selection is
    weighted by the recency/rank/coverage priority.
    """
    undercovered = [
        c for c in candidates if coverage.get(c.id, 0) < weights.min_coverage
    ]
    pool = undercovered or candidates
    elo_lo, elo_hi = _elo_range(candidates)
    scored = [
        (c, _priority(c, coverage, elo_lo, elo_hi, weights)) for c in pool
    ]
    return _weighted_choice(scored, rng)


def _is_eligible_partner(
    candidate: MatchCandidate,
    primary: MatchCandidate,
    recent_pairs: set[frozenset[str]],
) -> bool:
    """Return whether candidate may pair with primary this round.

    Excludes ``primary`` itself and any pair already scheduled this round
    set (no self-matches, no immediate duplicate rematches).
    """
    if candidate.id == primary.id:
        return False
    return frozenset({primary.id, candidate.id}) not in recent_pairs


def _partner_score(
    candidate: MatchCandidate,
    primary: MatchCandidate,
    coverage: dict[str, int],
    elo_lo: int,
    elo_hi: int,
    weights: MatchmakingWeights,
) -> float:
    """Score candidate as a partner, with a same-cluster similarity bonus."""
    score = _priority(candidate, coverage, elo_lo, elo_hi, weights)
    same_cluster = (
        primary.cluster_id is not None
        and candidate.cluster_id == primary.cluster_id
    )
    return score + weights.similarity_bonus if same_cluster else score


def _select_partner(
    primary: MatchCandidate,
    candidates: list[MatchCandidate],
    coverage: dict[str, int],
    recent_pairs: set[frozenset[str]],
    weights: MatchmakingWeights,
    rng: random.Random,
) -> MatchCandidate | None:
    """Select the second side of a match for ``primary``.

    Excludes ``primary`` itself and any pair already scheduled this round set
    (no self-matches, no immediate duplicate rematches). Partners in the same
    proximity cluster get a similarity bonus so similar hypotheses are more
    likely compared. Returns None if no valid partner remains.
    """
    elo_lo, elo_hi = _elo_range(candidates)
    scored = [
        (c, _partner_score(c, primary, coverage, elo_lo, elo_hi, weights))
        for c in candidates
        if _is_eligible_partner(c, primary, recent_pairs)
    ]
    if not scored:
        return None
    return _weighted_choice(scored, rng)


def _select_round_partner(
    primary: MatchCandidate,
    candidates: list[MatchCandidate],
    coverage: dict[str, int],
    recent_pairs: set[frozenset[str]],
    prev_pair: frozenset[str] | None,
    weights: MatchmakingWeights,
    rng: random.Random,
) -> MatchCandidate | None:
    """Selects a partner for ``primary``, relaxing forbidden pairs as needed.

    Fallback ladder: avoid all recent pairs, then only the immediately
    previous pair (so no back-to-back rematch), then — only when even
    that leaves no partner (a two-hypothesis pool) — allow any non-self
    partner so the tournament can still rematch.
    """
    prev_only: set[frozenset[str]] = (
        {prev_pair} if prev_pair is not None else set()
    )
    for forbidden in (recent_pairs | prev_only, prev_only, set()):
        partner = _select_partner(
            primary, candidates, coverage, forbidden, weights, rng
        )
        if partner is not None:
            return partner
    return None


def _schedule_one_pairing(
    candidates: list[MatchCandidate],
    coverage: dict[str, int],
    recent_pairs: set[frozenset[str]],
    prev_pair: frozenset[str] | None,
    weights: MatchmakingWeights,
    rng: random.Random,
) -> tuple[str, str] | None:
    """Selects and commits one pairing, updating coverage and recency.

    Returns:
        The scheduled ``(primary_id, partner_id)`` pair, or None if no
        valid partner exists for the round's chosen primary.
    """
    primary = _select_primary(candidates, coverage, weights, rng)
    partner = _select_round_partner(
        primary, candidates, coverage, recent_pairs, prev_pair, weights, rng
    )
    if partner is None:
        return None
    coverage[primary.id] += 1
    coverage[partner.id] += 1
    recent_pairs.add(frozenset({primary.id, partner.id}))
    return primary.id, partner.id


def _init_pairing_state(
    candidates: list[MatchCandidate],
    seed: int,
    weights: MatchmakingWeights | None,
) -> tuple[MatchmakingWeights, random.Random, dict[str, int], int]:
    """Initializes RNG, per-hypothesis coverage, and the max-pairs bound."""
    resolved_weights = weights or MatchmakingWeights()
    rng = random.Random(seed)
    coverage = {c.id: c.matches for c in candidates}
    max_pairs = len(candidates) * (len(candidates) - 1) // 2
    return resolved_weights, rng, coverage, max_pairs


def _reset_if_exhausted(
    recent_pairs: set[frozenset[str]],
    prev_pair: frozenset[str] | None,
    max_pairs: int,
) -> set[frozenset[str]]:
    """Resets the recent-pairs window once every valid pair has been used.

    A long tournament on a small pool can still schedule rematches without
    starving -- it just avoids back-to-back repeats. The immediately
    previous pair is always forbidden (even across a reset) so no pair
    repeats twice in a row.
    """
    if len(recent_pairs) >= max_pairs:
        return {prev_pair} if prev_pair is not None else set()
    return recent_pairs


def build_weighted_pairings(
    candidates: list[MatchCandidate],
    rounds: int,
    seed: int,
    weights: MatchmakingWeights | None = None,
) -> list[tuple[str, str]]:
    """Build ``rounds`` weighted, deterministic pairwise matchups.

    Args:
        candidates: The hypotheses eligible for pairing (reduced form).
        rounds: Number of matchups to schedule.
        seed: Deterministic RNG seed (identical seed → identical schedule).
        weights: Optional pairing weights (documented clone defaults used
            when omitted).

    Returns:
        A list of ``(primary_id, partner_id)`` pairs. Empty when fewer than
        two candidates exist (no valid pairing).
    """
    if len(candidates) < 2:
        return []
    weights, rng, coverage, max_pairs = _init_pairing_state(
        candidates, seed, weights
    )

    pairings: list[tuple[str, str]] = []
    recent_pairs: set[frozenset[str]] = set()
    prev_pair: frozenset[str] | None = None
    for _ in range(rounds):
        recent_pairs = _reset_if_exhausted(recent_pairs, prev_pair, max_pairs)
        pair = _schedule_one_pairing(
            candidates, coverage, recent_pairs, prev_pair, weights, rng
        )
        if pair is None:
            continue
        pairings.append(pair)
        prev_pair = frozenset(pair)

    return pairings

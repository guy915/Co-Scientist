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

Every matchup within one build is distinct. A build selects all of its
pairings from a single Elo snapshot, so re-scheduling a pair it has already
chosen cannot discriminate between those two hypotheses -- it replays one
comparison and ratchets the winner's rating for it. Rematches across ranking
cycles remain available, since each cycle re-pairs against updated ratings.

The core :func:`build_weighted_pairings` is a pure function of a candidate list
and a seed, so the biases and coverage guarantees are unit-testable and a fixed
seed replays identically (Google leaves the exact weights unspecified; the
weights here are documented clone defaults).
"""

from __future__ import annotations

import dataclasses
import random

from co_scientist.constants import TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS


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

    ``min_coverage`` is the shared
    ``TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS``: a rating built from one match
    is a coin flip, not a measurement. It is imported rather than spelled
    again here because the ranking budget's coverage floor has to fund
    exactly this number -- the two were written independently as 2 and 1,
    and every idea the budget could not afford played once and landed on one
    of the two reachable ratings.
    """

    recency: float = 1.0
    rank: float = 1.0
    coverage: float = 0.5
    similarity_bonus: float = 2.0
    min_coverage: int = TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS


@dataclasses.dataclass(frozen=True)
class _PairingState:
    """Build-invariant scoring inputs threaded through every selection.

    ``coverage`` (per-hypothesis match counts) is mutated in place across a
    build as pairings are committed; ``rng`` carries deterministic RNG
    state. ``elo_lo``/``elo_hi`` bound the fixed candidate list, so they are
    computed once and reused for rank normalization.
    """

    coverage: dict[str, int]
    weights: MatchmakingWeights
    rng: random.Random
    elo_lo: int
    elo_hi: int


def _elo_range(candidates: list[MatchCandidate]) -> tuple[int, int]:
    """Return the (min, max) Elo across candidates for rank normalization."""
    elos = [c.elo for c in candidates]
    return min(elos), max(elos)


def _priority(candidate: MatchCandidate, state: _PairingState) -> float:
    """Score a candidate's selection priority from recency, rank, coverage.

    Higher is more likely to be picked. Recency rewards fewer prior matches
    (newer hypotheses need calibration); rank rewards higher normalized Elo
    (leaders need discrimination); coverage rewards under-played hypotheses.
    """
    recency = 1.0 / (1.0 + candidate.matches)
    span = (state.elo_hi - state.elo_lo) or 1
    rank = (candidate.elo - state.elo_lo) / span
    played = state.coverage.get(candidate.id, 0)
    low_coverage = 1.0 / (1.0 + played)
    return (
        state.weights.recency * recency
        + state.weights.rank * rank
        + state.weights.coverage * low_coverage
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


def _coverage_pool(
    candidates: list[MatchCandidate],
    state: _PairingState,
) -> list[MatchCandidate]:
    """Narrows a selection pool to the hypotheses owed a match first.

    Coverage is filled one level at a time: of the candidates still below
    ``min_coverage``, only those with the *fewest* matches so far are
    offered. Taking the whole below-floor set instead lets a hypothesis play
    its second match while another has yet to play its first, which loses the
    guarantee that a build with enough rounds matches everybody.

    Returns the full list once every candidate has reached the floor, at
    which point the weighted priority decides.
    """
    below = [
        c
        for c in candidates
        if state.coverage.get(c.id, 0) < state.weights.min_coverage
    ]
    if not below:
        return candidates
    fewest = min(state.coverage.get(c.id, 0) for c in below)
    return [c for c in below if state.coverage.get(c.id, 0) == fewest]


def _select_primary(
    candidates: list[MatchCandidate],
    state: _PairingState,
) -> MatchCandidate:
    """Select the first side of a match.

    Under-covered hypotheses are chosen first to prevent starvation (see
    ``_coverage_pool``); once every hypothesis has reached the floor,
    selection is weighted by the recency/rank/coverage priority.
    """
    scored = [
        (c, _priority(c, state)) for c in _coverage_pool(candidates, state)
    ]
    return _weighted_choice(scored, state.rng)


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
    state: _PairingState,
) -> float:
    """Score candidate as a partner, with a same-cluster similarity bonus."""
    score = _priority(candidate, state)
    same_cluster = (
        primary.cluster_id is not None
        and candidate.cluster_id == primary.cluster_id
    )
    return score + state.weights.similarity_bonus if same_cluster else score


def _select_partner(
    primary: MatchCandidate,
    candidates: list[MatchCandidate],
    recent_pairs: set[frozenset[str]],
    state: _PairingState,
) -> MatchCandidate | None:
    """Select the second side of a match for ``primary``.

    Excludes ``primary`` itself and any pair already scheduled this round set
    (no self-matches, no immediate duplicate rematches). Partners in the same
    proximity cluster get a similarity bonus so similar hypotheses are more
    likely compared. Returns None if no valid partner remains.

    Under-covered candidates are preferred, exactly as in ``_select_primary``.
    Applying the floor to only one side of the match made coverage a tendency
    rather than a guarantee: a build with enough rounds to pair everyone could
    still spend one on an already-covered partner and leave a hypothesis
    unmatched, which then reports its starting rating as a tournament result.
    """
    eligible = [
        c for c in candidates if _is_eligible_partner(c, primary, recent_pairs)
    ]
    if not eligible:
        return None
    pool = _coverage_pool(eligible, state)
    scored = [(c, _partner_score(c, primary, state)) for c in pool]
    return _weighted_choice(scored, state.rng)


def _select_round_partner(
    primary: MatchCandidate,
    candidates: list[MatchCandidate],
    recent_pairs: set[frozenset[str]],
    prev_pair: frozenset[str] | None,
    state: _PairingState,
) -> MatchCandidate | None:
    """Selects a partner for ``primary``, relaxing forbidden pairs as needed.

    Pairs already scheduled in this build are never reoffered, and the
    immediately previous pair is forbidden on top of that so no matchup
    repeats back to back. There is deliberately no rung that relaxes into
    an already-scheduled pair: the build chooses every matchup from one Elo
    snapshot, so a repeat replays a comparison instead of making one.

    Returns None when ``primary`` has already faced every other candidate,
    leaving the caller free to try a different primary.
    """
    prev_only: set[frozenset[str]] = (
        {prev_pair} if prev_pair is not None else set()
    )
    return _select_partner(primary, candidates, recent_pairs | prev_only, state)


def _commit_pairing(
    primary: MatchCandidate,
    partner: MatchCandidate,
    recent_pairs: set[frozenset[str]],
    state: _PairingState,
) -> tuple[str, str]:
    """Records a chosen pairing against coverage and the scheduled set."""
    state.coverage[primary.id] += 1
    state.coverage[partner.id] += 1
    recent_pairs.add(frozenset({primary.id, partner.id}))
    return primary.id, partner.id


def _schedule_one_pairing(
    candidates: list[MatchCandidate],
    recent_pairs: set[frozenset[str]],
    prev_pair: frozenset[str] | None,
    state: _PairingState,
) -> tuple[str, str] | None:
    """Selects and commits one not-yet-scheduled pairing.

    Retries with a freshly drawn primary when the first pick has already
    faced every other candidate, so one exhausted hypothesis cannot end a
    build while unplayed pairs remain elsewhere in the pool.

    Returns:
        The scheduled ``(primary_id, partner_id)`` pair, or None once every
        distinct pair in the pool has been scheduled.
    """
    for _ in range(len(candidates)):
        primary = _select_primary(candidates, state)
        partner = _select_round_partner(
            primary, candidates, recent_pairs, prev_pair, state
        )
        if partner is not None:
            return _commit_pairing(primary, partner, recent_pairs, state)
    return _any_unscheduled_pairing(candidates, recent_pairs, state)


def _any_unscheduled_pairing(
    candidates: list[MatchCandidate],
    recent_pairs: set[frozenset[str]],
    state: _PairingState,
) -> tuple[str, str] | None:
    """Deterministic sweep for any pair this build has not scheduled.

    The weighted draw above is random, so on a pool where most pairs are
    already used it can miss the few that remain. This makes exhaustion a
    fact about the pool rather than an artifact of sampling luck.
    """
    for i, primary in enumerate(candidates):
        for partner in candidates[i + 1 :]:
            if frozenset({primary.id, partner.id}) not in recent_pairs:
                return _commit_pairing(primary, partner, recent_pairs, state)
    return None


def _init_pairing_state(
    candidates: list[MatchCandidate],
    seed: int,
    weights: MatchmakingWeights | None,
) -> tuple[_PairingState, int]:
    """Initializes the build-invariant pairing state and max-pairs bound."""
    coverage = {c.id: c.matches for c in candidates}
    elo_lo, elo_hi = _elo_range(candidates)
    state = _PairingState(
        coverage=coverage,
        weights=weights or MatchmakingWeights(),
        rng=random.Random(seed),
        elo_lo=elo_lo,
        elo_hi=elo_hi,
    )
    max_pairs = len(candidates) * (len(candidates) - 1) // 2
    return state, max_pairs


def build_weighted_pairings(
    candidates: list[MatchCandidate],
    rounds: int,
    seed: int,
    weights: MatchmakingWeights | None = None,
    exclude: set[frozenset[str]] | None = None,
) -> list[tuple[str, str]]:
    """Build up to ``rounds`` weighted, deterministic pairwise matchups.

    Every matchup in one build is distinct, and ``exclude`` extends that
    across builds: a caller judging one round at a time passes the pairs it
    has already judged, and gets back only comparisons it has not made yet.

    Repeating a pair cannot discriminate between those two hypotheses -- it
    replays one comparison and ratchets the winner's rating for it.
    Production ran whole tournaments this way: a pool left with two rankable
    ideas judged the same pair six times and reported the winner at 1259 as
    though it had beaten six opponents.

    The count is therefore capped at the distinct pairs still available,
    which for n candidates is n*(n-1)/2 less the excluded ones -- a
    two-candidate pool yields one match however many rounds are requested,
    and none once that match has been judged. Rematches across ranking
    cycles stay available and meaningful, because each cycle re-pairs
    against updated ratings.

    Args:
        candidates: The hypotheses eligible for pairing (reduced form).
        rounds: Maximum number of matchups to schedule.
        seed: Deterministic RNG seed (identical seed → identical schedule).
        weights: Optional pairing weights (documented clone defaults used
            when omitted).
        exclude: Pairs already judged, as ``frozenset`` of the two ids.
            Never offered again by this build.

    Returns:
        A list of distinct ``(primary_id, partner_id)`` pairs, at most
        ``rounds`` long and excluding ``exclude``. Empty when fewer than two
        candidates exist or every pair is already excluded.
    """
    if len(candidates) < 2:
        return []
    state, all_pairs = _init_pairing_state(candidates, seed, weights)
    recent_pairs: set[frozenset[str]] = set(exclude or ())
    max_pairs = all_pairs - len(recent_pairs)

    pairings: list[tuple[str, str]] = []
    prev_pair: frozenset[str] | None = None
    for _ in range(min(rounds, max_pairs)):
        pair = _schedule_one_pairing(candidates, recent_pairs, prev_pair, state)
        if pair is None:
            break
        pairings.append(pair)
        prev_pair = frozenset(pair)

    return pairings

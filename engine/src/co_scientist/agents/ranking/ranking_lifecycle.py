"""Tournament setup and teardown for the Elo ranking node.

Owns the round-invariant scaffolding around the judged matchups: sorting
the pool, resolving the tier-configured round count, gathering the
cross-node context threaded into every matchup, emitting the
start/complete progress events, and building the node's state delta.
Pairing selection, Elo commits, and the graph node stay in ``ranking.py``,
which re-exports these names for compatibility.
"""

import logging
from typing import Any, NamedTuple

from co_scientist.agents.ranking.ranking_results import (
    _build_ranking_delta,
)
from co_scientist.constants import (
    PROGRESS_TOURNAMENT_COMPLETE,
    PROGRESS_TOURNAMENT_START,
    TOURNAMENT_MATCHES_PER_HYPOTHESIS,
    TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS,
    truncate,
)
from co_scientist.models import Hypothesis, rank_by_elo
from co_scientist.progress import emit_progress
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


class _TournamentGuidance(NamedTuple):
    """Cross-node context threaded unchanged into every judged matchup.

    A NamedTuple so it still unpacks positionally as the historical
    ``(supervisor_guidance, tool_registry, meta_review, run_setup_guidance,
    run_focus_guidance)`` 5-tuple for callers that iterate it.
    """

    supervisor_guidance: dict[str, Any] | None = None
    tool_registry: Any | None = None
    meta_review: dict[str, Any] | None = None
    run_setup_guidance: str | None = None
    run_focus_guidance: str | None = None


def _gather_tournament_context(state: WorkflowState) -> _TournamentGuidance:
    """Gathers the cross-node context threaded into every judged matchup.

    These are set earlier in the workflow (supervisor planning, a prior
    iteration's meta-review, and the run's setup/focus prompts); threaded
    unchanged into every judged matchup so the judge sees the same context
    for every pairing.

    Args:
        state: Current workflow state.

    Returns:
        The bundled tournament guidance (supervisor guidance, tool registry,
        meta-review, run setup/focus guidance).
    """
    return _TournamentGuidance(
        supervisor_guidance=state.get("supervisor_guidance"),
        tool_registry=state.get("tool_registry"),
        meta_review=state.get("meta_review"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )


def _sort_hypotheses_for_tournament(hypotheses: list[Hypothesis]) -> None:
    """Sorts the pool by review score in place (text as tiebreaker)."""
    hypotheses.sort(key=lambda h: (h.score, h.text), reverse=True)
    logger.info(
        "Sorted hypotheses by review score (top score: %.2f)",
        hypotheses[0].score,
    )


def consumed_tournament_rounds(state: WorkflowState) -> int:
    """Return how many tournament matches this run has already judged.

    Read from the run's accumulated metrics rather than recounted from the
    pool. A hypothesis carries its own match tally, but proximity dedup
    removes hypotheses and their tallies with them, so a recount would fall
    as the pool was cleaned and hand the run back budget it had already
    spent. The metric only ever accumulates.
    """
    metrics = state.get("metrics")
    return max(0, int(getattr(metrics, "tournaments_count", 0) or 0))


def _coverage_floor(hypotheses: list[Hypothesis]) -> int:
    """Rounds needed to give every rankable idea a win-loss record.

    A hypothesis that leaves a run unmatched still reports the starting Elo
    of 1200, which is indistinguishable in the report from a rating earned
    against opponents. The budget is therefore a ceiling on discrimination,
    not on coverage: it may decide how much a run refines its ordering, but
    never that an idea is ranked without playing.

    The floor is ``TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS`` matches per idea,
    not one. One match is the same failure in a quieter form: from the flat
    seed it has exactly two outcomes, so a run whose budget ran out mid-pool
    reported a dozen ideas tied at the same two numbers. This is the number
    the matchmaker already tries to reach (``MatchmakingWeights.min_coverage``
    -- the same constant), and funding less than it asks for is what left the
    ideas evolution and the later generation waves add on exactly one match.

    Counted over rankable hypotheses only. Quarantined and undermined ideas
    are excluded from the tournament by design, so counting them would hold
    the floor permanently above zero and loop the orchestrator on ranking
    forever. Bounded by the distinct pairs the pool admits for the same
    reason -- a floor the pool cannot satisfy never falls.
    """
    rankable = [h for h in hypotheses if h.is_rankable()]
    if len(rankable) < 2:
        return 0
    owed = sum(
        max(0, TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS - h.total_matches)
        for h in rankable
    )
    if not owed:
        return 0
    max_pairs = len(rankable) * (len(rankable) - 1) // 2
    # Each match settles two of the owed slots.
    return min((owed + 1) // 2, max_pairs)


def _tournament_budget(
    state: WorkflowState, hypotheses: list[Hypothesis]
) -> int:
    """Resolves the run's whole-run match budget for the current pool.

    Two numbers bound it, and the larger wins. ``tournament_pairs`` comes
    from the run-tier config (6/12/20/32 pairs for
    express/default/extended/ultra); the "or len(hypotheses)" fallback only
    applies if it is missing/zero (e.g. ad-hoc/test state). On its own that
    is a *flat* ceiling, and the pool it has to cover is not flat: evolution
    keeps adding ideas after the first ranking cycle, so the tier number was
    spent on the ideas that existed first and every idea added later got only
    the coverage floor's single match. See
    ``TOURNAMENT_MATCHES_PER_HYPOTHESIS`` for what that did to the ratings.

    The second number therefore scales with the rankable pool, at
    ``TOURNAMENT_MATCHES_PER_HYPOTHESIS`` matches per idea (each match covers
    two of them, hence the halving). It is what actually binds on any pool
    larger than the tier's own idea count.
    """
    configured = max(1, int(state.get("tournament_pairs") or len(hypotheses)))
    rankable = sum(1 for h in hypotheses if h.is_rankable())
    scaled = (rankable * TOURNAMENT_MATCHES_PER_HYPOTHESIS + 1) // 2
    return max(configured, scaled)


def _tournament_round_count(
    state: WorkflowState, hypotheses: list[Hypothesis]
) -> int:
    """Resolves the run's *remaining* tournament round allowance.

    The budget is a whole-run one, not a per-invocation one: it used to be
    spent in full by every ranking invocation, and the scheduler runs ranking
    once per cycle -- so a standard run configured for 12 matches judged
    about 22, and an ultra run far more. Each match is real model work on the
    run's serial spine.

    The budget never suppresses a hypothesis's first match: a spent budget
    still yields enough rounds to cover ideas that have never played, since
    an unmatched idea would otherwise report its starting rating as a
    tournament result.

    Returns:
        Matches still affordable this run, or the coverage floor if that is
        larger; zero once the budget is spent and every rankable hypothesis
        has played.
    """
    budget = _tournament_budget(state, hypotheses)
    remaining = max(0, budget - consumed_tournament_rounds(state))
    floor = _coverage_floor(hypotheses)
    if floor > remaining:
        logger.info(
            "Tournament budget spent (%s of %s), but %s round(s) still owed "
            "to hypotheses that have never been matched",
            remaining,
            budget,
            floor,
        )
        return floor
    logger.info(
        "Tournament budget: %s of %s rounds remaining", remaining, budget
    )
    return remaining


async def _prepare_ranking_round(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
) -> tuple[int, _TournamentGuidance]:
    """Sorts the pool and gathers the cross-node tournament context.

    Also emits the start-of-tournament progress event. The returned
    context is threaded into every judged matchup.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool entering the tournament; sorted in
            place by review score (text as tiebreaker for determinism).

    Returns:
        Tuple of (tournament_rounds, tournament guidance bundle).
    """
    _sort_hypotheses_for_tournament(hypotheses)

    await emit_progress(
        state,
        "tournament_start",
        f"Running tournament with {len(hypotheses)} hypotheses...",
        PROGRESS_TOURNAMENT_START,
    )

    tournament_rounds = _tournament_round_count(state, hypotheses)
    return tournament_rounds, _gather_tournament_context(state)


def _sort_hypotheses_by_elo(
    hypotheses: list[Hypothesis],
) -> list[Hypothesis]:
    """Sorts the pool by Elo rating (highest first), unrankable ones last.

    The Elo comparison is ``models.rank_by_elo``, the canonical ordering every
    other node reads, and the unrankable-last rule is a stable partition
    composed on top of it rather than a second comparison. Written as its own
    key the two drifted: this one negated Elo and score to sort ascending,
    which left its ``text`` tiebreak ascending, while ``rank_by_elo`` reverses
    a whole key and so breaks the same tie descending. Ties are the common
    case at the flat seed rating, so for exactly the hypotheses no tournament
    had separated, this node's own output order and the top-k the research
    overview re-derived from it were reverses of each other.
    """
    return sorted(rank_by_elo(hypotheses), key=lambda h: not h.is_rankable())


async def _finalize_ranking_result(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    matchup_details: list[dict[str, Any]],
    tournament_rounds: int,
    total_llm_calls: int,
) -> dict[str, Any]:
    """Applies matchup results and builds the ranking_node state delta.

    The hypothesis pool is re-ranked by Elo before the delta is built.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool that was paired for this tournament.
        matchup_details: Sequentially committed tournament outcomes.
        tournament_rounds: Number of tournament rounds run.
        total_llm_calls: Total judge LLM calls (summed over debate turns).

    Returns:
        The ranking_node state delta dictionary.
    """
    hypotheses = _sort_hypotheses_by_elo(hypotheses)

    logger.info("Tournament complete. Top Elo: %s", hypotheses[0].elo_rating)
    logger.info("Top hypothesis: %s...", hypotheses[0].text[:100])

    await emit_progress(
        state,
        "tournament_complete",
        f"Tournament complete ({tournament_rounds} rounds)",
        PROGRESS_TOURNAMENT_COMPLETE,
        top_elo=hypotheses[0].elo_rating,
        # ``truncate`` rather than a bare slice: this payload reaches the UI,
        # where a cut without the marker reads as a complete short idea.
        top_hypothesis=truncate(hypotheses[0].text),
    )

    return _build_ranking_delta(
        hypotheses, matchup_details, tournament_rounds, total_llm_calls
    )

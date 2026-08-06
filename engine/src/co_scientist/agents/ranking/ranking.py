"""Ranking node - Elo-based pairwise comparison of hypotheses."""

import hashlib
import logging
from typing import Any, NamedTuple

from co_scientist.agents.ranking.ranking_debate import (
    _call_matchup_judge as _call_matchup_judge,
)
from co_scientist.agents.ranking.ranking_debate import (
    _DebateContext as _DebateContext,
)
from co_scientist.agents.ranking.ranking_debate import (
    _matchup_debate_turns as _matchup_debate_turns,
)
from co_scientist.agents.ranking.ranking_debate import (
    _median_elo as _median_elo,
)
from co_scientist.agents.ranking.ranking_debate import (
    judge_matchup as judge_matchup,
)
from co_scientist.agents.ranking.ranking_elo import (
    calculate_elo_update as calculate_elo_update,
)
from co_scientist.agents.ranking.ranking_elo import (
    match_tier as match_tier,
)
from co_scientist.agents.ranking.ranking_lifecycle import (
    _finalize_ranking_result as _finalize_ranking_result,
)
from co_scientist.agents.ranking.ranking_lifecycle import (
    _gather_tournament_context as _gather_tournament_context,
)
from co_scientist.agents.ranking.ranking_lifecycle import (
    _prepare_ranking_round as _prepare_ranking_round,
)
from co_scientist.agents.ranking.ranking_lifecycle import (
    _sort_hypotheses_by_elo as _sort_hypotheses_by_elo,
)
from co_scientist.agents.ranking.ranking_lifecycle import (
    _sort_hypotheses_for_tournament as _sort_hypotheses_for_tournament,
)
from co_scientist.agents.ranking.ranking_lifecycle import (
    _tournament_round_count as _tournament_round_count,
)
from co_scientist.agents.ranking.ranking_lifecycle import (
    _TournamentGuidance as _TournamentGuidance,
)
from co_scientist.agents.ranking.ranking_matchmaking import (
    MatchCandidate,
    build_weighted_pairings,
)
from co_scientist.agents.ranking.ranking_prompt import (
    _build_matchup_prompt as _build_matchup_prompt,
)
from co_scientist.agents.ranking.ranking_prompt import (
    _deep_verification_summary as _deep_verification_summary,
)
from co_scientist.agents.ranking.ranking_prompt import (
    _gather_matchup_summaries as _gather_matchup_summaries,
)
from co_scientist.agents.ranking.ranking_prompt import (
    _log_reflection_coverage as _log_reflection_coverage,
)
from co_scientist.agents.ranking.ranking_prompt import (
    _log_reflection_debug as _log_reflection_debug,
)
from co_scientist.agents.ranking.ranking_prompt import (
    _review_summary as _review_summary,
)
from co_scientist.agents.ranking.ranking_prompt import (
    _warn_if_reflection_notes_dropped as _warn_if_reflection_notes_dropped,
)
from co_scientist.agents.ranking.ranking_results import (
    _apply_matchup_elo as _apply_matchup_elo,
)
from co_scientist.agents.ranking.ranking_results import (
    _build_matchup_detail as _build_matchup_detail,
)
from co_scientist.agents.ranking.ranking_results import (
    _build_ranking_delta as _build_ranking_delta,
)
from co_scientist.agents.ranking.ranking_results import (
    _extract_reasoning as _extract_reasoning,
)
from co_scientist.agents.ranking.ranking_results import (
    _format_judgment_explanation as _format_judgment_explanation,
)
from co_scientist.agents.ranking.ranking_results import (
    _MatchupOutcome as _MatchupOutcome,
)
from co_scientist.constants import (
    ELO_K_FACTOR,
)
from co_scientist.models import BLOCKING_REVIEW_DISPOSITIONS, Hypothesis
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


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


def _build_tournament_pairings(
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


class _TournamentContext(NamedTuple):
    """One tournament's round-invariant inputs, threaded into every round."""

    hypotheses: list[Hypothesis]
    research_goal: str
    current_iteration: int
    supervisor_guidance: dict[str, Any] | None
    tool_registry: Any | None
    meta_review: dict[str, Any] | None
    run_setup_guidance: str | None
    run_focus_guidance: str | None


def _build_tournament_context(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    guidance: _TournamentGuidance,
) -> _TournamentContext:
    """Bundles this tournament's round-invariant inputs into one context."""
    return _TournamentContext(
        hypotheses,
        state["research_goal"],
        state.get("current_iteration", 0),
        guidance.supervisor_guidance,
        guidance.tool_registry,
        guidance.meta_review,
        guidance.run_setup_guidance,
        guidance.run_focus_guidance,
    )


def _select_next_pairing(
    ctx: _TournamentContext,
    index: int,
    judged: set[frozenset[str]],
) -> tuple[Hypothesis, Hypothesis] | None:
    """Selects one round's pairing from comparisons not yet made.

    A distinct deterministic seed plus updated in-memory Elo/match counts
    makes each selection depend on every committed earlier outcome.

    Returns None once every distinct pair has been judged, which ends the
    tournament. This used to fall back to the first candidate when the only
    ones on offer had already been judged, so a pool with a single available
    pair re-judged it for every remaining round: production tournaments ran
    six and twelve rounds on one matchup, ratcheting the winner's rating
    with each replay and reporting it as a rating earned across opponents.

    Only one pairing is requested because only the first is used: the
    ``judged`` exclusion set is what keeps rounds from repeating a
    comparison, so scheduling spare candidates here would just be weighted
    choices thrown away.
    """
    candidates = _build_tournament_pairings(
        ctx.hypotheses,
        1,
        ctx.research_goal,
        ctx.current_iteration * 10_000 + index,
        judged=judged,
    )
    return candidates[0] if candidates else None


async def _judge_and_commit_matchup(
    state: WorkflowState,
    hyp_a: Hypothesis,
    hyp_b: Hypothesis,
    index: int,
    ctx: _TournamentContext,
) -> tuple[dict[str, Any], int]:
    """Judges one pairing and commits its Elo update.

    Returns:
        Tuple of (matchup detail dict, debate depth used).
    """
    depth = _matchup_debate_turns(hyp_a, hyp_b, _median_elo(ctx.hypotheses))
    debate_ctx = _DebateContext(
        hyp_a,
        hyp_b,
        state["research_goal"],
        state["model_name"],
        supervisor_guidance=ctx.supervisor_guidance,
        meta_review=ctx.meta_review,
        tool_registry=ctx.tool_registry,
        run_setup_guidance=ctx.run_setup_guidance,
        run_focus_guidance=ctx.run_focus_guidance,
        run_id=state.get("run_id"),
        matchup_index=index,
        criteria=state.get("criteria"),
    )
    winner, response = await judge_matchup(debate_ctx, debate_turns=depth)
    outcome = _apply_matchup_elo(
        hyp_a,
        hyp_b,
        winner,
        k_factor=int(state.get("elo_k_factor") or ELO_K_FACTOR),
        # Feeds only the margin-scaling reconstruction knob (off by default).
        confidence=response.get("confidence_level"),
    )
    detail = _build_matchup_detail(hyp_a, hyp_b, winner, response, outcome)
    # The turns actually judged, not the depth budgeted: a debate whose
    # majority is decided early stops short of its budget, and this number
    # is metered against the run's LLM allowance.
    return detail, int(response.get("debate_turns", depth))


async def _run_one_round(
    state: WorkflowState,
    index: int,
    judged: set[frozenset[str]],
    ctx: _TournamentContext,
) -> tuple[dict[str, Any], int, frozenset[str]] | None:
    """Selects, judges, and commits one tournament round.

    Returns:
        Tuple of (matchup detail, debate depth used, the pair just
        committed), or None if no unjudged pairing remained.
    """
    pairing = _select_next_pairing(ctx, index, judged)
    if pairing is None:
        return None
    hyp_a, hyp_b = pairing
    detail, depth = await _judge_and_commit_matchup(
        state, hyp_a, hyp_b, index, ctx
    )
    return detail, depth, frozenset({hyp_a.id, hyp_b.id})


async def _execute_tournament_rounds(
    state: WorkflowState, tournament_rounds: int, ctx: _TournamentContext
) -> tuple[list[dict[str, Any]], int]:
    """Runs every tournament round in sequence, committing as it goes.

    Commits each outcome before selecting the next pairing (see
    ``_run_one_round``), so matchmaking observes current ratings rather
    than a stale snapshot.

    Stops early once every distinct pair has been judged: a tournament with
    more rounds than the pool has comparisons has nothing left to learn, and
    spending the remainder re-judging pairs inflates the winner's rating
    without evidence.
    """
    details: list[dict[str, Any]] = []
    total_llm_calls = 0
    judged: set[frozenset[str]] = set()
    for index in range(tournament_rounds):
        round_result = await _run_one_round(state, index, judged, ctx)
        if round_result is None:
            break
        detail, depth, committed = round_result
        judged.add(committed)
        details.append(detail)
        total_llm_calls += depth
    return details, total_llm_calls


async def _run_tournament_matchups(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    tournament_rounds: int,
    guidance: _TournamentGuidance,
) -> tuple[
    list[dict[str, Any]],
    int,
]:
    """Select, judge, and commit tournament matchups sequentially.

    Args:
        state: Current workflow state.
        hypotheses: Hypotheses sorted by review score, eligible for pairing.
        tournament_rounds: Number of pairings to generate and judge.
        guidance: Cross-node context threaded into every judged matchup.

    Returns:
        Tuple of (matchup details, total LLM calls); see
        ``_execute_tournament_rounds`` for the commit ordering.
    """
    ctx = _build_tournament_context(state, hypotheses, guidance)
    return await _execute_tournament_rounds(state, tournament_rounds, ctx)


def _filter_eligible_hypotheses(
    hypotheses: list[Hypothesis],
) -> list[Hypothesis]:
    """Filters to tournament-eligible hypotheses, with startup logging."""
    eligible = [
        hypothesis for hypothesis in hypotheses if hypothesis.is_rankable()
    ]
    logger.info(
        "Ranking tournament: %s of %s hypotheses are rankable",
        len(eligible),
        len(hypotheses),
    )
    _log_reflection_coverage(hypotheses)
    return eligible


def _unrankable_reasons(hypotheses: list[Hypothesis]) -> str:
    """Return why the pool has too few rankable hypotheses to pair up.

    The count alone reads as a contradiction next to a run holding a dozen
    ideas, so the skip names the gates that removed them instead.
    """
    undermined = sum(
        1 for h in hypotheses if h.deep_verification_verdict == "undermined"
    )
    blocked = sum(
        1
        for h in hypotheses
        if h.review_disposition in BLOCKING_REVIEW_DISPOSITIONS
    )
    return (
        f"{undermined} undermined by deep verification, "
        f"{blocked} rejected in review"
    )


async def _run_tournament(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    eligible: list[Hypothesis],
) -> dict[str, Any]:
    """Prepares, runs, and finalizes one ranking tournament round."""
    tournament_rounds, guidance = await _prepare_ranking_round(state, eligible)

    matchup_details, total_llm_calls = await _run_tournament_matchups(
        state, eligible, tournament_rounds, guidance
    )

    return await _finalize_ranking_result(
        state, hypotheses, matchup_details, tournament_rounds, total_llm_calls
    )


async def ranking_node(state: WorkflowState) -> dict[str, Any]:
    """Runs tournament-style pairwise comparisons with Elo rating updates.

    This node schedules weighted pairwise matchups (proximity-, recency-,
    and rank-aware; see ranking_matchmaking) and has an LLM judge which
    hypothesis in each pairing is superior. Elo ratings are updated after
    each matchup, and matchups involving a top-ranked hypothesis run a
    multi-turn scientific debate instead of a single-turn comparison.

    The round count comes from the run tier's tournament_pairs setting,
    falling back to len(hypotheses) when unset. Pairings are seeded from
    research_goal and current_iteration so identical inputs replay
    identical tournaments, keeping LLM cache hits stable across reruns.

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields (hypotheses sorted by Elo)
    """
    hypotheses = state["hypotheses"]
    eligible = _filter_eligible_hypotheses(hypotheses)

    # Edge case: a tournament requires at least two hypotheses to pair up.
    # With fewer, skip the tournament entirely and pass the list through
    # unchanged (Elo ratings stay at their prior/initial values). The pool
    # itself is usually far larger than the rankable count, so the message
    # names both -- "need at least 2" beside a run holding eight ideas
    # reads as a miscount rather than as the gates having emptied the pool.
    if len(eligible) < 2:
        logger.warning(
            "Tournament skipped: %s of %s hypotheses are rankable (%s)",
            len(eligible),
            len(hypotheses),
            _unrankable_reasons(hypotheses),
        )
        return {"hypotheses": hypotheses}

    # tournament_pairs is a whole-run budget. The scheduler asks for ranking
    # once per cycle, so without this the run would keep buying another full
    # tournament every cycle for the life of the run.
    if _tournament_round_count(state, hypotheses) < 1:
        logger.info("Tournament budget spent for this run; skipping")
        return {"hypotheses": hypotheses}

    return await _run_tournament(state, hypotheses, eligible)

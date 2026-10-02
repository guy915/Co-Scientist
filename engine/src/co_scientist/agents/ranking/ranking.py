"""Ranking node - Elo-based pairwise comparison of hypotheses."""

import logging
from dataclasses import replace
from typing import Any, NamedTuple

from co_scientist.agents.ranking.operations import (
    RankingPromptContext,
    apply_ranking_matchup,
    judge_ranking_matchup,
    prepare_ranking_judging_context,
    prepare_ranking_prompt_context,
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
    _TournamentGuidance as _TournamentGuidance,
)
from co_scientist.agents.ranking.ranking_lifecycle import (
    finalize_ranking,
    prepare_ranking_round,
    remaining_ranking_rounds,
)
from co_scientist.agents.ranking.ranking_pairings import (
    build_tournament_pairings,
)
from co_scientist.constants import (
    ELO_K_FACTOR,
)
from co_scientist.models import BLOCKING_REVIEW_DISPOSITIONS, Hypothesis
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


class _TournamentContext(NamedTuple):
    """One tournament's round-invariant inputs, threaded into every round."""

    hypotheses: list[Hypothesis]
    research_goal: str
    current_iteration: int
    prompt: RankingPromptContext


def _build_tournament_context(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    guidance: _TournamentGuidance,
) -> _TournamentContext:
    """Capture prompt inputs once; preserve the prepared guidance snapshot."""
    prompt = prepare_ranking_prompt_context(
        state, preferences=state.get("preferences")
    )
    return _TournamentContext(
        hypotheses,
        state["research_goal"],
        state.get("current_iteration", 0),
        replace(prompt, guidance=guidance),
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
    candidates = build_tournament_pairings(
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
    """Refresh the Elo context, judge, and commit one graph matchup."""
    pair = (hyp_a, hyp_b)
    context = prepare_ranking_judging_context(ctx.prompt, ctx.hypotheses)
    judgement = await judge_ranking_matchup(pair, context, index)
    result = apply_ranking_matchup(
        pair,
        judgement,
        k_factor=int(state.get("elo_k_factor") or ELO_K_FACTOR),
        current_iteration=int(state.get("current_iteration", 0)),
    )
    return result.detail, result.llm_calls


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
    return eligible


def _unrankable_reasons(hypotheses: list[Hypothesis]) -> str:
    """Return why the pool has too few rankable hypotheses to pair up.

    The count alone reads as a contradiction next to a run holding a dozen
    ideas, so the skip names the gate that removed them instead.

    Only review dispositions are counted, because only they withhold an
    idea now: a deep-verification "undermined" verdict demotes rather than
    excludes (``Hypothesis.is_rankable``), so naming it here would blame a
    thin pool on a gate that let every one of those ideas through.
    """
    blocked = sum(
        1
        for h in hypotheses
        if h.review_disposition in BLOCKING_REVIEW_DISPOSITIONS
    )
    return f"{blocked} rejected in review"


async def _run_tournament(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    eligible: list[Hypothesis],
) -> dict[str, Any]:
    """Prepares, runs, and finalizes one ranking tournament round."""
    tournament_rounds, guidance = await prepare_ranking_round(state, eligible)

    matchup_details, total_llm_calls = await _run_tournament_matchups(
        state, eligible, tournament_rounds, guidance
    )

    return await finalize_ranking(
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
    if remaining_ranking_rounds(state, hypotheses) < 1:
        logger.info("Tournament budget spent for this run; skipping")
        return {"hypotheses": hypotheses}

    return await _run_tournament(state, hypotheses, eligible)


_build_tournament_pairings = build_tournament_pairings

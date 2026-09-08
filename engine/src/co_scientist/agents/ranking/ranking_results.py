"""Applying judged matchup results: Elo updates, details, and state delta."""

import logging
from typing import Any, NamedTuple

from co_scientist.agents.ranking.ranking_debate_turns import _verdict_number
from co_scientist.agents.ranking.ranking_elo import (
    calculate_elo_update,
    effective_k_factor,
    match_tier,
)
from co_scientist.constants import ELO_K_FACTOR, truncate
from co_scientist.models import (
    ExecutionMetrics,
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    phase_message,
)
from co_scientist.schemas.ranking import RANKING_COMPARISON_CRITERIA

logger = logging.getLogger(__name__)


def _format_judgment_explanation(judgment: dict[str, Any]) -> str:
    """Combine a judgment_explanation dict's truthy values into one line."""
    return " | ".join(f"{k}: {v}" for k, v in judgment.items() if v)


def _extract_criteria_comparisons(
    response: dict[str, Any],
) -> dict[str, str]:
    """Collects the judge's per-aspect assessments for the record.

    The prompt collects one comparison per published evaluation aspect
    under judgment_explanation, but nothing read them back before (audit
    E17); the match record now carries them so a verdict is inspectable
    aspect by aspect. Only the canonical keys are kept -- a
    closed schema means anything else is model invention -- and empty
    assessments are dropped.

    Args:
        response: Full judge response for one matchup.

    Returns:
        Criterion-name -> assessment, possibly empty.
    """
    explanation = response.get("judgment_explanation")
    if not isinstance(explanation, dict):
        return {}
    return {
        name: str(explanation[name])
        for name in RANKING_COMPARISON_CRITERIA
        if explanation.get(name)
    }


def _extract_reasoning(response: dict[str, Any]) -> str:
    """Extracts the judge's reasoning text from a matchup response.

    Args:
        response: Full LLM response from judge_matchup.

    Returns:
        Reasoning text: decision_summary if present, otherwise a
        judgment_explanation fallback, otherwise a placeholder.
    """
    reasoning: str = response.get("decision_summary", "")
    if not reasoning and "judgment_explanation" in response:
        # Fallback: combine judgment details if decision_summary is missing
        reasoning = _format_judgment_explanation(
            response["judgment_explanation"]
        )
    if not reasoning:
        reasoning = "No reasoning provided"
    return reasoning


class _MatchupOutcome(NamedTuple):
    """Pre/post Elo ratings for one judged matchup's winner and loser."""

    winner_hyp: Hypothesis
    loser_hyp: Hypothesis
    winner_elo_before: int
    winner_elo_after: int
    loser_elo_before: int
    loser_elo_after: int


def _compute_elo_update(
    winner_hyp: Hypothesis,
    loser_hyp: Hypothesis,
    k_factor: int | None,
    confidence: str | None = None,
) -> tuple[int, int]:
    """Computes and applies the post-match Elo ratings, logging the update.

    Mutates winner_hyp/loser_hyp's elo_rating and win/loss counters in
    place. Each side's update is scaled by its own effective K-factor
    (``ranking_elo.effective_k_factor``): the K-annealing and margin-scaling
    reconstruction knobs, both off by default, so with them off both sides
    use exactly the run's configured K and the update is the historical one.
    """
    base_k = k_factor if k_factor is not None else ELO_K_FACTOR
    winner_k = effective_k_factor(base_k, winner_hyp.total_matches, confidence)
    loser_k = effective_k_factor(base_k, loser_hyp.total_matches, confidence)
    new_winner_elo, new_loser_elo = calculate_elo_update(
        winner_elo=winner_hyp.elo_rating,
        loser_elo=loser_hyp.elo_rating,
        k_factor=winner_k,
        loser_k_factor=loser_k,
    )
    logger.debug(
        "Matchup result: Winner %s -> %s, Loser %s -> %s",
        winner_hyp.elo_rating,
        new_winner_elo,
        loser_hyp.elo_rating,
        new_loser_elo,
    )
    winner_hyp.elo_rating = new_winner_elo
    loser_hyp.elo_rating = new_loser_elo
    winner_hyp.win_count += 1
    loser_hyp.loss_count += 1
    return new_winner_elo, new_loser_elo


def _resolve_matchup_sides(
    hyp_a: Hypothesis, hyp_b: Hypothesis, winner: str
) -> tuple[Hypothesis, Hypothesis]:
    """Resolves (winner, loser) based on the judge's "a"/"b" side."""
    return (hyp_a, hyp_b) if winner == "a" else (hyp_b, hyp_a)


def _apply_matchup_elo(
    hyp_a: Hypothesis,
    hyp_b: Hypothesis,
    winner: str,
    *,
    k_factor: int | None = None,
    confidence: str | None = None,
) -> _MatchupOutcome:
    """Resolves the winner/loser of one matchup and applies its Elo update.

    Mutates winner_hyp and loser_hyp in place (elo_rating and win/loss
    counters), so these updates are visible on the same objects held by the
    caller's hypothesis list without needing to rebuild it.

    Args:
        hyp_a: First hypothesis in the pairing.
        hyp_b: Second hypothesis in the pairing.
        winner: Side the judge picked, "a" or "b".
        k_factor: Optional run-specific Elo sensitivity.
        confidence: The judge's confidence level for the verdict, if any.
            Feeds only the margin-scaling reconstruction knob (off by
            default), so it is inert unless that knob is enabled.

    Returns:
        The pre/post Elo ratings for the winner and loser.
    """
    winner_hyp, loser_hyp = _resolve_matchup_sides(hyp_a, hyp_b, winner)
    old_winner_elo = winner_hyp.elo_rating
    old_loser_elo = loser_hyp.elo_rating

    new_winner_elo, new_loser_elo = _compute_elo_update(
        winner_hyp, loser_hyp, k_factor, confidence
    )

    return _MatchupOutcome(
        winner_hyp,
        loser_hyp,
        old_winner_elo,
        new_winner_elo,
        old_loser_elo,
        new_loser_elo,
    )


def _debate_provenance_fields(
    response: dict[str, Any], winner: str
) -> dict[str, Any]:
    """Extracts one matchup's debate provenance for its detail dict.

    Depth (1 = single-turn comparison, >1 = multi-turn scientific debate),
    the turn-by-turn transcript, the published verdict number that closes
    it, and the judge model (Milestone 3). ``debate_verdict`` falls back
    to the winner this detail is being built with, so a response from
    before the judge recorded it still names a verdict.
    """
    return {
        "debate_turns": response.get("debate_turns", 1),
        "debate_transcript": response.get("debate_transcript", []),
        "debate_verdict": response.get("debate_verdict")
        or _verdict_number(winner),
        "judge_model": response.get("judge_model"),
        "consensus_votes": response.get("consensus_votes", [winner]),
        "position_balanced": response.get("position_balanced", False),
        "invalid_output_fallback": response.get(
            "invalid_output_fallback", False
        ),
    }


def _elo_transition_fields(outcome: _MatchupOutcome) -> dict[str, Any]:
    """Extracts the pre/post Elo fields for one matchup's detail dict."""
    return {
        "winner_elo_before": outcome.winner_elo_before,
        "winner_elo_after": outcome.winner_elo_after,
        "loser_elo_before": outcome.loser_elo_before,
        "loser_elo_after": outcome.loser_elo_after,
    }


def _build_matchup_detail(
    pair: tuple[Hypothesis, Hypothesis],
    winner: str,
    response: dict[str, Any],
    outcome: _MatchupOutcome,
    iteration: int,
) -> dict[str, Any]:
    """Builds one matchup's detail dict for the UI's tournament view.

    The two sides arrive as one pairing rather than two arguments so the
    cycle fits within the five-argument ceiling; the pairing is what both
    execution paths already hold (the durable wave judges a list of them).

    Args:
        pair: The pairing judged, as (side a, side b).
        winner: Side the judge picked, "a" or "b".
        response: Full judge response for this matchup.
        outcome: Elo outcome produced by _apply_matchup_elo.
        iteration: Run cycle this matchup was judged in. Stamped here, at
            the one place a detail is built, because it is the only moment
            the cycle is still known: the drain persists the accumulated
            matchups of every cycle at once from the final state, so a
            match that did not carry its own iteration was written as
            iteration 0 -- which is what every match of every run was
            until this field existed.

    Returns:
        Matchup detail dict for this pairing, for the UI's "Performance
        against other ideas" view. ``criteria_comparisons`` carries the
        judge's per-aspect assessments (audit E17).
    """
    hyp_a, hyp_b = pair
    return {
        "iteration": int(iteration),
        "hypothesis_a": truncate(hyp_a.text),
        "hypothesis_b": truncate(hyp_b.text),
        # Stable ids alongside the truncated text so downstream consumers
        # can resolve identity exactly instead of by text-prefix matching.
        "hypothesis_a_id": hyp_a.id,
        "hypothesis_b_id": hyp_b.id,
        "winner_id": outcome.winner_hyp.id,
        "winner": winner,
        "reasoning": _extract_reasoning(response),
        "confidence": response.get("confidence_level", "Unknown"),
        "tier": match_tier(
            outcome.winner_elo_before,
            outcome.loser_elo_before,
            response.get("confidence_level", ""),
        ),
        "criteria_comparisons": _extract_criteria_comparisons(response),
        **_debate_provenance_fields(response, winner),
        **_elo_transition_fields(outcome),
    }


def _ranking_metrics_update(
    matches_judged: int, total_llm_calls: int | None
) -> ExecutionMetrics:
    """Builds the ranking_node metrics delta (llm calls + tournament count).

    Counted in matches actually judged, never in rounds the tournament was
    offered. ``tournaments_count`` is the run's whole-run consumption meter
    (``ranking_lifecycle.consumed_tournament_rounds``, whose own contract is
    "matches this run has already judged"), and a tournament stops early
    whenever the pool's distinct pairs run out before the budget does.
    Charging the offered count bills the run for matches nobody judged:
    production extended run bc77950f entered its first tournament with four
    rankable ideas against a 20-round budget, judged the six distinct pairs
    those four admit, and was charged 20 -- spending 70% of the whole-run
    allowance before evolution had added an idea. Every later cycle then ran
    on the coverage floor alone, which funds only ideas that have never
    played, so the run finished with 23 matches over 20 ideas and an Elo
    spread of 1165-1224.

    A multi-turn debate makes several judge calls per match, so llm_calls is
    the summed turn count, not the match count; it defaults to one call per
    match when the caller has no summed count.
    """
    llm_calls = (
        total_llm_calls if total_llm_calls is not None else matches_judged
    )
    metrics = create_metrics_update(
        deltas=MetricDeltas(llm_calls=llm_calls, tournaments=matches_judged)
    )
    logger.debug(
        "ranking node creating metrics delta: tournaments=%s, llm_calls=%s",
        matches_judged,
        llm_calls,
    )
    return metrics


def _build_ranking_delta(
    hypotheses: list[Hypothesis],
    matchup_details: list[dict[str, Any]],
    tournament_rounds: int,
    total_llm_calls: int | None = None,
) -> dict[str, Any]:
    """Builds the ranking_node state delta after Elo updates are applied.

    Args:
        hypotheses: Hypotheses sorted by Elo rating (highest first).
        matchup_details: Per-round matchup detail dicts.
        tournament_rounds: Rounds the tournament was offered; reported only
            as the allowance the pass ran against.
        total_llm_calls: Total judge LLM calls (summed over debate turns);
            defaults to one call per match when omitted.

    Returns:
        The ranking_node state delta dictionary. Merged back into
        WorkflowState by the graph runner: hypotheses carries forward with
        updated Elo/win/loss fields for downstream nodes (e.g. meta-review,
        evolve), tournament_matchups feeds the UI's "Performance against
        other ideas" view, and metrics/messages accumulate via their
        respective reducers rather than overwriting prior state.

    Everything counted here counts judged matches, not offered rounds; see
    ``_ranking_metrics_update`` for what the two numbers diverging cost.
    """
    matches_judged = len(matchup_details)
    metrics = _ranking_metrics_update(matches_judged, total_llm_calls)

    return {
        "hypotheses": hypotheses,  # Now sorted by Elo rating
        "tournament_matchups": matchup_details,
        "metrics": metrics,
        "messages": phase_message(
            "ranking",
            f"Judged {matches_judged} of {tournament_rounds} tournament rounds",
            rounds=matches_judged,
            top_elo=hypotheses[0].elo_rating,
        ),
    }

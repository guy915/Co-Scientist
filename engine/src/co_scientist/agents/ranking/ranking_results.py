"""Applying judged matchup results: Elo updates, details, and state delta."""

import logging
from typing import Any, NamedTuple

from co_scientist.agents.ranking.ranking_elo import (
    calculate_elo_update,
    match_tier,
)
from co_scientist.constants import truncate
from co_scientist.models import (
    Hypothesis,
    create_metrics_update,
    phase_message,
)

logger = logging.getLogger(__name__)


def _format_judgment_explanation(judgment: dict[str, Any]) -> str:
    """Combine a judgment_explanation dict's truthy values into one line."""
    return " | ".join(f"{k}: {v}" for k, v in judgment.items() if v)


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


def _apply_matchup_elo(
    hyp_a: Hypothesis,
    hyp_b: Hypothesis,
    winner: str,
    *,
    k_factor: int | None = None,
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

    Returns:
        The pre/post Elo ratings for the winner and loser.
    """
    # Resolve which Hypothesis object actually won this pairing based on the
    # "a"/"b" side the judge picked.
    winner_hyp, loser_hyp = (hyp_a, hyp_b) if winner == "a" else (hyp_b, hyp_a)
    old_winner_elo = winner_hyp.elo_rating
    old_loser_elo = loser_hyp.elo_rating

    elo_kwargs = {"k_factor": k_factor} if k_factor is not None else {}
    new_winner_elo, new_loser_elo = calculate_elo_update(
        winner_elo=winner_hyp.elo_rating,
        loser_elo=loser_hyp.elo_rating,
        **elo_kwargs,
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

    return _MatchupOutcome(
        winner_hyp,
        loser_hyp,
        old_winner_elo,
        new_winner_elo,
        old_loser_elo,
        new_loser_elo,
    )


def _build_matchup_detail(
    hyp_a: Hypothesis,
    hyp_b: Hypothesis,
    winner: str,
    response: dict[str, Any],
    outcome: _MatchupOutcome,
) -> dict[str, Any]:
    """Builds one matchup's detail dict for the UI's tournament view.

    Args:
        hyp_a: First hypothesis in the pairing.
        hyp_b: Second hypothesis in the pairing.
        winner: Side the judge picked, "a" or "b".
        response: Full judge response for this matchup.
        outcome: Elo outcome produced by _apply_matchup_elo.

    Returns:
        Matchup detail dict for this pairing, for the UI's "Performance
        against other ideas" view.
    """
    return {
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
        # Debate provenance (Milestone 3): depth (1 = single-turn comparison,
        # >1 = multi-turn scientific debate), the turn-by-turn transcript, and
        # the judge model.
        "debate_turns": response.get("debate_turns", 1),
        "debate_transcript": response.get("debate_transcript", []),
        "judge_model": response.get("judge_model"),
        "consensus_votes": response.get("consensus_votes", [winner]),
        "position_balanced": response.get("position_balanced", False),
        "invalid_output_fallback": response.get(
            "invalid_output_fallback", False
        ),
        "winner_elo_before": outcome.winner_elo_before,
        "winner_elo_after": outcome.winner_elo_after,
        "loser_elo_before": outcome.loser_elo_before,
        "loser_elo_after": outcome.loser_elo_after,
    }


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
        tournament_rounds: Number of tournament rounds run.
        total_llm_calls: Total judge LLM calls (summed over debate turns);
            defaults to one call per round when omitted.

    Returns:
        The ranking_node state delta dictionary. Merged back into
        WorkflowState by the graph runner: hypotheses carries forward with
        updated Elo/win/loss fields for downstream nodes (e.g. meta-review,
        evolve), tournament_matchups feeds the UI's "Performance against
        other ideas" view, and metrics/messages accumulate via their
        respective reducers rather than overwriting prior state.
    """
    # Update metrics (deltas only, merge_metrics will add to existing state).
    # A multi-turn debate makes several judge calls per round, so llm_calls is
    # the summed turn count, not the round count.
    llm_calls = (
        total_llm_calls if total_llm_calls is not None else tournament_rounds
    )
    metrics = create_metrics_update(
        llm_calls_delta=llm_calls, tournaments_count_delta=tournament_rounds
    )
    logger.debug(
        "ranking node creating metrics delta: tournaments=%s, llm_calls=%s",
        tournament_rounds,
        llm_calls,
    )

    return {
        "hypotheses": hypotheses,  # Now sorted by Elo rating
        "tournament_matchups": matchup_details,
        "metrics": metrics,
        "messages": phase_message(
            "ranking",
            f"Completed {tournament_rounds} tournament rounds",
            rounds=tournament_rounds,
            top_elo=hypotheses[0].elo_rating,
        ),
    }

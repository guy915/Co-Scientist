"""Ranking node - Elo-based pairwise comparison of hypotheses."""

import asyncio
import hashlib
import logging
import random
from typing import Any

from co_scientist.constants import (
    ELO_K_FACTOR,
    ELO_UPSET_MARGIN,
    THINKING_MAX_TOKENS,
    LOW_TEMPERATURE,
    MAX_CONCURRENT_LLM_CALLS,
    truncate,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import (Hypothesis, create_metrics_update,
                                 phase_message, rank_by_elo)
from co_scientist.nodes.progress import emit_progress
from co_scientist.prompts import get_ranking_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Semaphore to limit concurrent LLM calls (avoid rate limits)
_ranking_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)


def calculate_elo_update(winner_elo: int,
                         loser_elo: int,
                         k_factor: int = ELO_K_FACTOR) -> tuple[int, int]:
    """Calculates updated Elo ratings for winner and loser.

    Args:
        winner_elo: Current Elo rating of winner
        loser_elo: Current Elo rating of loser
        k_factor: K-factor for Elo calculation (default 24)

    Returns:
        Tuple of (new_winner_elo, new_loser_elo)
    """
    # Calculate expected scores
    expected_winner = 1 / (1 + 10**((loser_elo - winner_elo) / 400))
    expected_loser = 1 / (1 + 10**((winner_elo - loser_elo) / 400))

    # Calculate new ratings
    new_winner_elo = winner_elo + k_factor * (1 - expected_winner)
    new_loser_elo = loser_elo + k_factor * (0 - expected_loser)

    return int(new_winner_elo), int(new_loser_elo)


def match_tier(winner_elo_before: int, loser_elo_before: int,
               confidence: str) -> str:
    """Classifies how decisive a judged matchup was.

    Derived deterministically (no extra LLM call) from the pre-match Elo gap
    and the judge's stated confidence, mirroring the reference product's
    per-match ``tier`` label in "Performance against other ideas".

    Args:
        winner_elo_before: Winner's Elo rating before the match.
        loser_elo_before: Loser's Elo rating before the match.
        confidence: Judge confidence level ("High"/"Medium"/"Low").

    Returns:
        One of "upset" (a lower-rated hypothesis won), "decisive",
        "clear", or "narrow".
    """
    if loser_elo_before - winner_elo_before >= ELO_UPSET_MARGIN:
        return "upset"
    normalized = confidence.strip().lower()
    if normalized == "high":
        return "decisive"
    if normalized == "medium":
        return "clear"
    return "narrow"


def _review_summary(hypothesis: Hypothesis) -> dict[str, Any] | None:
    """Extracts the latest review scores for a matchup prompt.

    Args:
        hypothesis: Hypothesis to summarize

    Returns:
        Review summary dict, or None if the hypothesis has no reviews
    """
    if not hypothesis.reviews:
        return None
    latest_review = hypothesis.reviews[-1]
    return {
        "scores": latest_review.scores,
        "overall_score": latest_review.overall_score,
    }


def _deep_verification_summary(hypothesis: Hypothesis) -> dict[str, Any] | None:
    """Extracts deep-verification probes for a matchup prompt.

    Args:
        hypothesis: Hypothesis to summarize

    Returns:
        Deep-verification summary dict, or None if no probes are present
    """
    if not hypothesis.deep_verification_probes:
        return None
    return {
        "probes": hypothesis.deep_verification_probes,
        "verdict": hypothesis.deep_verification_verdict,
    }


def _log_reflection_debug(label: str, reflection_notes: str | None) -> None:
    """Logs reflection-note availability for one side of a matchup.

    Args:
        label: Display label for the hypothesis ("A" or "B")
        reflection_notes: Reflection notes for that hypothesis, if any
    """
    if not reflection_notes:
        logger.debug("hypothesis %s: missing reflection notes", label)
        return
    # Extract classification from notes
    classification = "unknown"
    if "Classification:" in reflection_notes:
        classification = (reflection_notes.split("Classification:")
                          [-1].strip().split("\n")[0])
    logger.debug("hypothesis %s: has reflection (%s chars, classification: %s)",
                 label, len(reflection_notes), classification)
    logger.debug("hypothesis %s reflection: %s...", label,
                 reflection_notes[:200])


async def judge_matchup(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    research_goal: str,
    model_name: str,
    supervisor_guidance: dict[str, Any] | None = None,
    run_id: str | None = None,
    matchup_index: int | None = None,
    tool_registry: Any | None = None,
    meta_review: dict[str, Any] | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Has an LLM judge which hypothesis is superior.

    Args:
        hypothesis_a: First hypothesis
        hypothesis_b: Second hypothesis
        research_goal: Research goal for context
        model_name: LLM model to use
        supervisor_guidance: Optional planning guidance from the supervisor
        run_id: Optional run ID for saving prompts
        matchup_index: Optional index for naming saved prompts
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        meta_review: Optional cross-iteration meta-review feedback

    Returns:
        Tuple of (winner, full_response) where winner is "a" or "b"
    """
    # Extract review data if available
    review_a = _review_summary(hypothesis_a)
    review_b = _review_summary(hypothesis_b)

    # Extract reflection notes if available
    reflection_notes_a = hypothesis_a.reflection_notes
    reflection_notes_b = hypothesis_b.reflection_notes

    # Extract deep-verification probes if available (populated after the first
    # tournament, once the deep_verification node has run on the leaders).
    deep_verification_a = _deep_verification_summary(hypothesis_a)
    deep_verification_b = _deep_verification_summary(hypothesis_b)

    logger.debug("\n→ Ranking Tournament Matchup")
    _log_reflection_debug("A", reflection_notes_a)
    _log_reflection_debug("B", reflection_notes_b)

    prompt, schema = get_ranking_prompt(
        research_goal=research_goal,
        hypothesis_a=hypothesis_a.text,
        hypothesis_b=hypothesis_b.text,
        supervisor_guidance=supervisor_guidance,
        review_a=review_a,
        review_b=review_b,
        reflection_notes_a=reflection_notes_a,
        reflection_notes_b=reflection_notes_b,
        deep_verification_a=deep_verification_a,
        deep_verification_b=deep_verification_b,
        meta_review=meta_review,
        tool_registry=tool_registry,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
    )

    if reflection_notes_a or reflection_notes_b:
        if "Reflection Notes" in prompt:
            logger.debug("prompt includes 'Reflection Notes' section")
        else:
            logger.debug(
                "warning: Reflection notes provided but not found in prompt")

    prompt_name = (f"ranking_matchup_{matchup_index}"
                   if matchup_index is not None else "ranking_matchup")

    # Use semaphore to limit concurrent calls (avoid rate limits)
    async with _ranking_semaphore:
        response = await call_llm_json(
            prompt=prompt,
            model_name=model_name,
            max_tokens=THINKING_MAX_TOKENS,
            temperature=LOW_TEMPERATURE,
            json_schema=schema,
            run_id=run_id,
            prompt_name=prompt_name,
            prompt_metadata={
                "matchup_index": matchup_index,
                "prompt_length_chars": len(prompt),
                "has_reflection_a": bool(reflection_notes_a),
                "has_reflection_b": bool(reflection_notes_b),
            },
        )

    winner = response.get("winner", "a").lower()
    if winner not in ["a", "b"]:
        logger.warning("Invalid winner '%s', defaulting to 'a'", winner)
        winner = "a"

    return winner, response


async def ranking_node(state: WorkflowState) -> dict[str, Any]:
    """Runs tournament-style pairwise comparisons with Elo rating updates.

    This node runs multiple rounds of random pairwise matchups where an LLM
    judges which hypothesis is superior. Elo ratings are updated after each
    matchup to reflect relative quality.

    Tournament rounds = len(hypotheses) * 1 (can be adjusted)

    deterministic seeding: the random pairings are seeded using research_goal
    and current_iteration to ensure cache consistency across runs. this allows
    identical inputs to produce identical tournament results, enabling proper
    cache hits in subsequent iterations.

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields (hypotheses sorted by Elo)
    """
    hypotheses = state["hypotheses"]
    logger.info("Starting ranking tournament with %s hypotheses",
                len(hypotheses))

    hypotheses_with_reflection = sum(
        1 for h in hypotheses if h.reflection_notes)
    logger.debug("\n=== ranking tournament debug ===")
    logger.debug("total hypotheses: %s", len(hypotheses))
    logger.debug("hypotheses with reflection notes: %s/%s",
                 hypotheses_with_reflection, len(hypotheses))

    if hypotheses_with_reflection == 0:
        logger.debug("warning: No hypotheses have reflection notes!")
    elif hypotheses_with_reflection < len(hypotheses):
        logger.debug("warning: Some hypotheses missing reflection notes")
    else:
        logger.debug("all hypotheses have reflection notes")

    if len(hypotheses) < 2:
        logger.warning("Need at least 2 hypotheses for tournament")
        return {"hypotheses": hypotheses}

    # Sort hypotheses by review score before tournament
    # This provides initial ordering based on review scores
    # Use hypothesis text as tiebreaker for deterministic ordering when scores
    # are equal
    hypotheses.sort(key=lambda h: (h.score, h.text), reverse=True)
    logger.info("Sorted hypotheses by review score (top score: %.2f)",
                hypotheses[0].score)

    # Emit progress
    await emit_progress(
        state, "tournament_start",
        f"Running tournament with {len(hypotheses)} hypotheses...", 65)

    # Calculate number of tier-configured tournament rounds.
    tournament_rounds = max(
        1, int(state.get("tournament_pairs") or len(hypotheses)))
    logger.info("Running %s tournament rounds", tournament_rounds)

    # Get supervisor guidance and tool registry from state
    supervisor_guidance = state.get("supervisor_guidance")
    tool_registry = state.get("tool_registry")
    meta_review = state.get("meta_review")
    run_setup_guidance = state.get("run_setup_guidance")
    run_focus_guidance = state.get("run_focus_guidance")

    # Set deterministic random seed based on research goal and iteration
    # this ensures same inputs produce same tournament pairings for cache
    # consistency use hashlib instead of hash() for deterministic results across
    # python processes
    research_goal = state["research_goal"]
    current_iteration = state.get("current_iteration", 0)
    seed_string = f"{research_goal}_{current_iteration}"
    seed = int(hashlib.md5(seed_string.encode()).hexdigest()[:8], 16)
    random.seed(seed)

    # Prepare all random pairwise matchups and judge them in parallel
    pairings = [
        tuple(random.sample(hypotheses, 2)) for _ in range(tournament_rounds)
    ]
    results = await asyncio.gather(*[
        judge_matchup(
            a,
            b,
            state["research_goal"],
            state["model_name"],
            supervisor_guidance,
            run_id=state.get("run_id"),
            matchup_index=i,
            tool_registry=tool_registry,
            meta_review=meta_review,
            run_setup_guidance=run_setup_guidance,
            run_focus_guidance=run_focus_guidance,
        ) for i, (a, b) in enumerate(pairings)
    ])

    # Apply Elo updates based on judged results and collect matchup details
    llm_calls = tournament_rounds
    matchup_details = []

    for (hyp_a, hyp_b), (winner, response) in zip(pairings, results):
        winner_hyp, loser_hyp = (hyp_a, hyp_b) if winner == "a" else (hyp_b,
                                                                      hyp_a)
        old_winner_elo = winner_hyp.elo_rating
        old_loser_elo = loser_hyp.elo_rating

        new_winner_elo, new_loser_elo = calculate_elo_update(
            winner_elo=winner_hyp.elo_rating, loser_elo=loser_hyp.elo_rating)
        logger.debug("Matchup result: Winner %s -> %s, Loser %s -> %s",
                     winner_hyp.elo_rating, new_winner_elo,
                     loser_hyp.elo_rating, new_loser_elo)

        # Store matchup details for display
        # Extract reasoning from response (can be decision_summary or
        # judgment_explanation)
        reasoning = response.get("decision_summary", "")
        if not reasoning and "judgment_explanation" in response:
            # Fallback: combine judgment details if decision_summary is missing
            judgment = response["judgment_explanation"]
            reasoning = " | ".join(
                [f"{k}: {v}" for k, v in judgment.items() if v])
        if not reasoning:
            reasoning = "No reasoning provided"

        matchup_details.append({
            "hypothesis_a":
                truncate(hyp_a.text),
            "hypothesis_b":
                truncate(hyp_b.text),
            # Stable ids alongside the truncated text so downstream consumers can
            # resolve identity exactly instead of by text-prefix matching.
            "hypothesis_a_id":
                hyp_a.id,
            "hypothesis_b_id":
                hyp_b.id,
            "winner_id":
                winner_hyp.id,
            "winner":
                winner,
            "reasoning":
                reasoning,
            "confidence":
                response.get("confidence_level", "Unknown"),
            "tier":
                match_tier(old_winner_elo, old_loser_elo,
                           response.get("confidence_level", "")),
            "winner_elo_before":
                old_winner_elo,
            "winner_elo_after":
                new_winner_elo,
            "loser_elo_before":
                old_loser_elo,
            "loser_elo_after":
                new_loser_elo,
        })

        winner_hyp.elo_rating = new_winner_elo
        loser_hyp.elo_rating = new_loser_elo
        winner_hyp.win_count += 1
        loser_hyp.loss_count += 1

    # Sort hypotheses by Elo rating (highest first), with score then text as
    # deterministic tiebreakers when Elo ratings are equal.
    hypotheses = rank_by_elo(hypotheses)

    logger.info("Tournament complete. Top Elo: %s", hypotheses[0].elo_rating)
    logger.info("Top hypothesis: %s...", hypotheses[0].text[:100])

    # Emit progress
    await emit_progress(state,
                        "tournament_complete",
                        f"Tournament complete ({tournament_rounds} rounds)",
                        80,
                        top_elo=hypotheses[0].elo_rating,
                        top_hypothesis=hypotheses[0].text[:200])

    # Update metrics (deltas only, merge_metrics will add to existing state)
    metrics = create_metrics_update(llm_calls_delta=llm_calls,
                                    tournaments_count_delta=tournament_rounds)
    logger.debug(
        "ranking node creating metrics delta: tournaments=%s, llm_calls=%s",
        tournament_rounds, llm_calls)

    return {
        "hypotheses":
            hypotheses,  # Now sorted by Elo rating
        "tournament_matchups":
            matchup_details,
        "metrics":
            metrics,
        "messages":
            phase_message("ranking",
                          f"Completed {tournament_rounds} tournament rounds",
                          rounds=tournament_rounds,
                          top_elo=hypotheses[0].elo_rating),
    }

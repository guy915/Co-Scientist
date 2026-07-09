"""Ranking node - Elo-based pairwise comparison of hypotheses."""

import asyncio
import hashlib
import logging
import random
from typing import Any, NamedTuple

from co_scientist.constants import (
    # ELO_K_FACTOR bounds how much a single matchup can move a rating;
    # ELO_UPSET_MARGIN is the pre-match gap that makes a win an "upset".
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
    # Standard Elo expected-score formula: each side's probability of
    # winning given the current rating gap, on the logistic curve with a
    # 400-point scale (a 400-point gap implies a 10x win-odds ratio). The
    # two expected scores always sum to 1.
    expected_winner = 1 / (1 + 10**((loser_elo - winner_elo) / 400))
    expected_loser = 1 / (1 + 10**((winner_elo - loser_elo) / 400))

    # Calculate new ratings
    # Rating update: actual score (1 for the winner, 0 for the loser) minus
    # expected score, scaled by k_factor. An upset (low-rated hypothesis
    # beats a high-rated one) has expected_winner near 0, so the winner
    # gains close to the full k_factor; an expected win moves ratings only
    # slightly.
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
    # "upset" takes priority over the confidence-based tiers below: if the
    # loser was already rated at least ELO_UPSET_MARGIN points above the
    # winner, the outcome is surprising regardless of how confident the
    # judge was.
    if loser_elo_before - winner_elo_before >= ELO_UPSET_MARGIN:
        return "upset"
    # Otherwise the tier reflects how confident the LLM judge was in its
    # verdict; unrecognized/missing confidence values fall through to
    # "narrow" (the least decisive tier) rather than erroring.
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


def _log_reflection_coverage(hypotheses: list[Hypothesis]) -> None:
    """Logs how many hypotheses arrived with reflection notes attached.

    Diagnostic-only bookkeeping: does not affect tournament behavior, only
    the debug logging (helps spot upstream nodes that failed to populate
    reflection_notes before ranking runs).

    Args:
        hypotheses: All hypotheses entering the ranking tournament.
    """
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


def _build_tournament_pairings(
        hypotheses: list[Hypothesis], tournament_rounds: int,
        research_goal: str,
        current_iteration: int) -> list[tuple[Hypothesis, Hypothesis]]:
    """Builds deterministic random pairwise matchups for one tournament.

    The random seed is derived from research_goal and current_iteration to
    ensure cache consistency across runs: identical inputs produce
    identical tournament pairings, enabling proper cache hits in
    subsequent iterations. Uses hashlib instead of hash() so the seed is
    deterministic across python processes.

    random.sample(hypotheses, 2) draws two distinct hypotheses without
    replacement for each round, but rounds themselves are independent, so
    the same hypothesis can appear in multiple pairings (or none) and this
    is not a round-robin/Swiss-style schedule -- coverage is probabilistic.

    Args:
        hypotheses: All hypotheses eligible for pairing.
        tournament_rounds: Number of pairings to generate.
        research_goal: Research goal, used to seed the deterministic RNG.
        current_iteration: Current workflow iteration, used to seed the
            deterministic RNG.

    Returns:
        List of (hypothesis_a, hypothesis_b) pairings, one per round.
    """
    seed_string = f"{research_goal}_{current_iteration}"
    seed = int(hashlib.md5(seed_string.encode()).hexdigest()[:8], 16)
    random.seed(seed)

    pairings: list[tuple[Hypothesis, Hypothesis]] = []
    for _ in range(tournament_rounds):
        hyp_a, hyp_b = random.sample(hypotheses, 2)
        pairings.append((hyp_a, hyp_b))
    return pairings


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
            response["judgment_explanation"])
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


def _apply_matchup_elo(hyp_a: Hypothesis, hyp_b: Hypothesis,
                       winner: str) -> _MatchupOutcome:
    """Resolves the winner/loser of one matchup and applies its Elo update.

    Mutates winner_hyp and loser_hyp in place (elo_rating and win/loss
    counters), so these updates are visible on the same objects held by the
    caller's hypothesis list without needing to rebuild it.

    Args:
        hyp_a: First hypothesis in the pairing.
        hyp_b: Second hypothesis in the pairing.
        winner: Side the judge picked, "a" or "b".

    Returns:
        The pre/post Elo ratings for the winner and loser.
    """
    # Resolve which Hypothesis object actually won this pairing based on the
    # "a"/"b" side the judge picked.
    winner_hyp, loser_hyp = (hyp_a, hyp_b) if winner == "a" else (hyp_b, hyp_a)
    old_winner_elo = winner_hyp.elo_rating
    old_loser_elo = loser_hyp.elo_rating

    new_winner_elo, new_loser_elo = calculate_elo_update(
        winner_elo=winner_hyp.elo_rating, loser_elo=loser_hyp.elo_rating)
    logger.debug("Matchup result: Winner %s -> %s, Loser %s -> %s",
                 winner_hyp.elo_rating, new_winner_elo, loser_hyp.elo_rating,
                 new_loser_elo)

    winner_hyp.elo_rating = new_winner_elo
    loser_hyp.elo_rating = new_loser_elo
    winner_hyp.win_count += 1
    loser_hyp.loss_count += 1

    return _MatchupOutcome(winner_hyp, loser_hyp, old_winner_elo,
                           new_winner_elo, old_loser_elo, new_loser_elo)


def _build_matchup_detail(hyp_a: Hypothesis, hyp_b: Hypothesis, winner: str,
                          response: dict[str, Any],
                          outcome: _MatchupOutcome) -> dict[str, Any]:
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
        "hypothesis_a":
            truncate(hyp_a.text),
        "hypothesis_b":
            truncate(hyp_b.text),
        # Stable ids alongside the truncated text so downstream consumers
        # can resolve identity exactly instead of by text-prefix matching.
        "hypothesis_a_id":
            hyp_a.id,
        "hypothesis_b_id":
            hyp_b.id,
        "winner_id":
            outcome.winner_hyp.id,
        "winner":
            winner,
        "reasoning":
            _extract_reasoning(response),
        "confidence":
            response.get("confidence_level", "Unknown"),
        "tier":
            match_tier(outcome.winner_elo_before, outcome.loser_elo_before,
                       response.get("confidence_level", "")),
        "winner_elo_before":
            outcome.winner_elo_before,
        "winner_elo_after":
            outcome.winner_elo_after,
        "loser_elo_before":
            outcome.loser_elo_before,
        "loser_elo_after":
            outcome.loser_elo_after,
    }


def _apply_matchup_results(
        pairings: list[tuple[Hypothesis, Hypothesis]],
        results: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Applies Elo updates for judged matchups and collects their details.

    Judgments are computed concurrently by the caller (independent of Elo,
    since judge_matchup only sees text/reviews/etc.), but ratings are
    applied here sequentially in pairing order, so a hypothesis appearing
    in multiple pairings picks up each prior update before the next one is
    scored.

    Args:
        pairings: Per-round (hypothesis_a, hypothesis_b) pairs.
        results: Per-round (winner, response) judgments, aligned with
            pairings.

    Returns:
        List of matchup detail dicts, one per round, for the UI's
        "Performance against other ideas" view.
    """
    matchup_details = []
    for (hyp_a, hyp_b), (winner, response) in zip(pairings, results):
        outcome = _apply_matchup_elo(hyp_a, hyp_b, winner)
        matchup_details.append(
            _build_matchup_detail(hyp_a, hyp_b, winner, response, outcome))
    return matchup_details


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


def _gather_matchup_summaries(
    hypothesis_a: Hypothesis, hypothesis_b: Hypothesis
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None,
           dict[str, Any] | None]:
    """Extracts review and deep-verification summaries for both sides.

    Deep-verification probes are only populated after the first tournament,
    once the deep_verification node has run on the leaders.

    Args:
        hypothesis_a: First hypothesis.
        hypothesis_b: Second hypothesis.

    Returns:
        Tuple of (review_a, review_b, deep_verification_a,
        deep_verification_b).
    """
    return (
        _review_summary(hypothesis_a),
        _review_summary(hypothesis_b),
        _deep_verification_summary(hypothesis_a),
        _deep_verification_summary(hypothesis_b),
    )


def _warn_if_reflection_notes_dropped(prompt: str,
                                      reflection_notes_a: str | None,
                                      reflection_notes_b: str | None) -> None:
    """Confirms reflection notes made it into the rendered prompt text.

    Catches silent template regressions where a variable stops being
    interpolated.

    Args:
        prompt: Rendered ranking-matchup prompt.
        reflection_notes_a: Reflection notes for hypothesis A, if any.
        reflection_notes_b: Reflection notes for hypothesis B, if any.
    """
    if not (reflection_notes_a or reflection_notes_b):
        return
    if "Reflection Notes" in prompt:
        logger.debug("prompt includes 'Reflection Notes' section")
    else:
        logger.debug(
            "warning: Reflection notes provided but not found in prompt")


def _build_matchup_prompt(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    research_goal: str,
    supervisor_guidance: dict[str, Any] | None,
    meta_review: dict[str, Any] | None,
    tool_registry: Any | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
) -> tuple[str, dict[str, Any] | None, str | None, str | None]:
    """Assembles the ranking-matchup prompt (and schema) for one pairing.

    Args:
        hypothesis_a: First hypothesis.
        hypothesis_b: Second hypothesis.
        research_goal: Research goal for context.
        supervisor_guidance: Optional planning guidance from the supervisor.
        meta_review: Optional cross-iteration meta-review feedback.
        tool_registry: Optional ToolRegistry for dynamic tool instructions.
        run_setup_guidance: Optional run-setup guidance for the prompt.
        run_focus_guidance: Optional run-focus guidance for the prompt.

    Returns:
        Tuple of (prompt, schema, reflection_notes_a, reflection_notes_b);
        the reflection notes are returned alongside the prompt so the
        caller can fold them into the LLM-call metadata without
        re-reading the hypotheses.
    """
    review_a, review_b, deep_verification_a, deep_verification_b = (
        _gather_matchup_summaries(hypothesis_a, hypothesis_b))

    reflection_notes_a = hypothesis_a.reflection_notes
    reflection_notes_b = hypothesis_b.reflection_notes

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

    _warn_if_reflection_notes_dropped(prompt, reflection_notes_a,
                                      reflection_notes_b)

    return prompt, schema, reflection_notes_a, reflection_notes_b


async def _call_matchup_judge(
    prompt: str,
    schema: dict[str, Any] | None,
    model_name: str,
    run_id: str | None,
    matchup_index: int | None,
    reflection_notes_a: str | None,
    reflection_notes_b: str | None,
) -> dict[str, Any]:
    """Calls the LLM judge for one matchup, bounded by the ranking semaphore.

    Args:
        prompt: Rendered ranking-matchup prompt.
        schema: JSON schema for the expected LLM response.
        model_name: LLM model to use.
        run_id: Optional run ID for saving prompts.
        matchup_index: Optional index for naming saved prompts.
        reflection_notes_a: Reflection notes for hypothesis A, if any.
        reflection_notes_b: Reflection notes for hypothesis B, if any.

    Returns:
        Parsed JSON response from the LLM.
    """
    prompt_name = (f"ranking_matchup_{matchup_index}"
                   if matchup_index is not None else "ranking_matchup")

    # Use semaphore to limit concurrent calls (avoid rate limits)
    async with _ranking_semaphore:
        return await call_llm_json(
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


def _parse_matchup_winner(response: dict[str, Any]) -> str:
    """Extracts and validates the winner side from a judge response.

    Guards against a malformed/off-schema LLM judgment: if the model
    returns anything other than "a" or "b" for the winner field, falls
    back to "a" rather than propagating an invalid value downstream.

    Args:
        response: Parsed JSON response from the judge LLM call.

    Returns:
        "a" or "b".
    """
    winner: str = response.get("winner", "a").lower()
    if winner not in ["a", "b"]:
        logger.warning("Invalid winner '%s', defaulting to 'a'", winner)
        winner = "a"
    return winner


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
        run_setup_guidance: Optional run-setup guidance for the prompt
        run_focus_guidance: Optional run-focus guidance for the prompt

    Returns:
        Tuple of (winner, full_response) where winner is "a" or "b"
    """
    prompt, schema, reflection_notes_a, reflection_notes_b = (
        _build_matchup_prompt(hypothesis_a, hypothesis_b, research_goal,
                              supervisor_guidance, meta_review, tool_registry,
                              run_setup_guidance, run_focus_guidance))

    response = await _call_matchup_judge(prompt, schema, model_name, run_id,
                                         matchup_index, reflection_notes_a,
                                         reflection_notes_b)

    winner = _parse_matchup_winner(response)

    return winner, response


async def _run_tournament_matchups(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    tournament_rounds: int,
    supervisor_guidance: dict[str, Any] | None,
    tool_registry: Any | None,
    meta_review: dict[str, Any] | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
) -> tuple[list[tuple[Hypothesis, Hypothesis]], list[tuple[str, dict[str,
                                                                     Any]]]]:
    """Builds tournament pairings and judges them concurrently.

    Args:
        state: Current workflow state.
        hypotheses: Hypotheses sorted by review score, eligible for pairing.
        tournament_rounds: Number of pairings to generate and judge.
        supervisor_guidance: Optional planning guidance from the supervisor.
        tool_registry: Optional ToolRegistry for dynamic tool instructions.
        meta_review: Optional cross-iteration meta-review feedback.
        run_setup_guidance: Optional run-setup guidance for the prompt.
        run_focus_guidance: Optional run-focus guidance for the prompt.

    Returns:
        Tuple of (pairings, results): the per-round hypothesis pairs and
        their aligned judged (winner, response) outcomes.
    """
    research_goal = state["research_goal"]
    current_iteration = state.get("current_iteration", 0)
    pairings = _build_tournament_pairings(hypotheses, tournament_rounds,
                                          research_goal, current_iteration)
    # Fire all matchup judgments concurrently; judge_matchup's semaphore
    # caps how many LLM calls are actually in flight at once.
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
    return pairings, results


def _gather_tournament_context(
    state: WorkflowState
) -> tuple[dict[str, Any] | None, Any, dict[str, Any] | None, str | None, str |
           None]:
    """Gathers the cross-node context threaded into every judged matchup.

    These are set earlier in the workflow (supervisor planning, a prior
    iteration's meta-review, and the run's setup/focus prompts); threaded
    unchanged into every judged matchup so the judge sees the same context
    for every pairing.

    Args:
        state: Current workflow state.

    Returns:
        Tuple of (supervisor_guidance, tool_registry, meta_review,
        run_setup_guidance, run_focus_guidance).
    """
    return (
        state.get("supervisor_guidance"),
        state.get("tool_registry"),
        state.get("meta_review"),
        state.get("run_setup_guidance"),
        state.get("run_focus_guidance"),
    )


async def _prepare_ranking_round(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
) -> tuple[int, dict[str, Any] | None, Any, dict[str, Any] | None, str | None,
           str | None]:
    """Sorts the pool, emits start-of-tournament progress, and gathers the
    cross-node context threaded into every judged matchup.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool entering the tournament; sorted in
            place by review score (text as tiebreaker for determinism).

    Returns:
        Tuple of (tournament_rounds, supervisor_guidance, tool_registry,
        meta_review, run_setup_guidance, run_focus_guidance).
    """
    # Sort hypotheses by review score before tournament. Use hypothesis text
    # as tiebreaker for deterministic ordering when scores are equal.
    hypotheses.sort(key=lambda h: (h.score, h.text), reverse=True)
    logger.info("Sorted hypotheses by review score (top score: %.2f)",
                hypotheses[0].score)

    await emit_progress(
        state, "tournament_start",
        f"Running tournament with {len(hypotheses)} hypotheses...", 65)

    # Calculate number of tier-configured tournament rounds.
    # tournament_pairs is normally set upstream from the run-tier config
    # (e.g. 6/12/20/32 pairs for express/default/extended/ultra); the
    # "or len(hypotheses)" fallback only applies if it is missing/zero
    # (e.g. ad-hoc/test state).
    tournament_rounds = max(
        1, int(state.get("tournament_pairs") or len(hypotheses)))
    logger.info("Running %s tournament rounds", tournament_rounds)

    (supervisor_guidance, tool_registry, meta_review, run_setup_guidance,
     run_focus_guidance) = _gather_tournament_context(state)

    return (tournament_rounds, supervisor_guidance, tool_registry, meta_review,
            run_setup_guidance, run_focus_guidance)


def _build_ranking_delta(hypotheses: list[Hypothesis],
                         matchup_details: list[dict[str, Any]],
                         tournament_rounds: int) -> dict[str, Any]:
    """Builds the ranking_node state delta after Elo updates are applied.

    Args:
        hypotheses: Hypotheses sorted by Elo rating (highest first).
        matchup_details: Per-round matchup detail dicts.
        tournament_rounds: Number of tournament rounds run.

    Returns:
        The ranking_node state delta dictionary. Merged back into
        WorkflowState by the graph runner: hypotheses carries forward with
        updated Elo/win/loss fields for downstream nodes (e.g. meta-review,
        evolve), tournament_matchups feeds the UI's "Performance against
        other ideas" view, and metrics/messages accumulate via their
        respective reducers rather than overwriting prior state.
    """
    # Update metrics (deltas only, merge_metrics will add to existing state)
    llm_calls = tournament_rounds
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


async def _finalize_ranking_result(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    pairings: list[tuple[Hypothesis, Hypothesis]],
    results: list[tuple[str, dict[str, Any]]],
    tournament_rounds: int,
) -> dict[str, Any]:
    """Applies matchup results, re-ranks by Elo, and builds the
    ranking_node state delta.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool that was paired for this tournament.
        pairings: Per-round (hypothesis_a, hypothesis_b) pairs.
        results: Per-round (winner, response) judgments, aligned with
            pairings.
        tournament_rounds: Number of tournament rounds run.

    Returns:
        The ranking_node state delta dictionary.
    """
    matchup_details = _apply_matchup_results(pairings, results)

    # Sort hypotheses by Elo rating (highest first), with score then text as
    # deterministic tiebreakers when Elo ratings are equal.
    hypotheses = rank_by_elo(hypotheses)

    logger.info("Tournament complete. Top Elo: %s", hypotheses[0].elo_rating)
    logger.info("Top hypothesis: %s...", hypotheses[0].text[:100])

    await emit_progress(state,
                        "tournament_complete",
                        f"Tournament complete ({tournament_rounds} rounds)",
                        80,
                        top_elo=hypotheses[0].elo_rating,
                        top_hypothesis=hypotheses[0].text[:200])

    return _build_ranking_delta(hypotheses, matchup_details, tournament_rounds)


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

    _log_reflection_coverage(hypotheses)

    # Edge case: a tournament requires at least two hypotheses to pair up.
    # With fewer, skip the tournament entirely and pass the list through
    # unchanged (Elo ratings stay at their prior/initial values).
    if len(hypotheses) < 2:
        logger.warning("Need at least 2 hypotheses for tournament")
        return {"hypotheses": hypotheses}

    (tournament_rounds, supervisor_guidance, tool_registry, meta_review,
     run_setup_guidance,
     run_focus_guidance) = await _prepare_ranking_round(state, hypotheses)

    # Prepare all random pairwise matchups and judge them in parallel
    pairings, results = await _run_tournament_matchups(
        state, hypotheses, tournament_rounds, supervisor_guidance,
        tool_registry, meta_review, run_setup_guidance, run_focus_guidance)

    return await _finalize_ranking_result(state, hypotheses, pairings, results,
                                          tournament_rounds)

"""Ranking node - Elo-based pairwise comparison of hypotheses."""

import asyncio
import hashlib
import logging
import random
from typing import Any

from co_scientist.constants import (
    LOW_TEMPERATURE,
    MAX_CONCURRENT_LLM_CALLS,
    THINKING_MAX_TOKENS,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import Hypothesis, rank_by_elo
from co_scientist.nodes.progress import emit_progress
from co_scientist.nodes.ranking_elo import (
    calculate_elo_update as calculate_elo_update,
)
from co_scientist.nodes.ranking_elo import (
    match_tier as match_tier,
)
from co_scientist.nodes.ranking_prompt import (
    _build_matchup_prompt as _build_matchup_prompt,
)
from co_scientist.nodes.ranking_prompt import (
    _deep_verification_summary as _deep_verification_summary,
)
from co_scientist.nodes.ranking_prompt import (
    _gather_matchup_summaries as _gather_matchup_summaries,
)
from co_scientist.nodes.ranking_prompt import (
    _log_reflection_coverage as _log_reflection_coverage,
)
from co_scientist.nodes.ranking_prompt import (
    _log_reflection_debug as _log_reflection_debug,
)
from co_scientist.nodes.ranking_prompt import (
    _review_summary as _review_summary,
)
from co_scientist.nodes.ranking_prompt import (
    _warn_if_reflection_notes_dropped as _warn_if_reflection_notes_dropped,
)
from co_scientist.nodes.ranking_results import (
    _apply_matchup_elo as _apply_matchup_elo,
)
from co_scientist.nodes.ranking_results import (
    _apply_matchup_results as _apply_matchup_results,
)
from co_scientist.nodes.ranking_results import (
    _build_matchup_detail as _build_matchup_detail,
)
from co_scientist.nodes.ranking_results import (
    _build_ranking_delta as _build_ranking_delta,
)
from co_scientist.nodes.ranking_results import (
    _extract_reasoning as _extract_reasoning,
)
from co_scientist.nodes.ranking_results import (
    _format_judgment_explanation as _format_judgment_explanation,
)
from co_scientist.nodes.ranking_results import (
    _MatchupOutcome as _MatchupOutcome,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Semaphore to limit concurrent LLM calls (avoid rate limits)
_ranking_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)


def _build_tournament_pairings(
    hypotheses: list[Hypothesis],
    tournament_rounds: int,
    research_goal: str,
    current_iteration: int,
) -> list[tuple[Hypothesis, Hypothesis]]:
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
    prompt_name = (
        f"ranking_matchup_{matchup_index}"
        if matchup_index is not None
        else "ranking_matchup"
    )

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
        _build_matchup_prompt(
            hypothesis_a,
            hypothesis_b,
            research_goal,
            supervisor_guidance,
            meta_review,
            tool_registry,
            run_setup_guidance,
            run_focus_guidance,
        )
    )

    response = await _call_matchup_judge(
        prompt,
        schema,
        model_name,
        run_id,
        matchup_index,
        reflection_notes_a,
        reflection_notes_b,
    )

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
) -> tuple[
    list[tuple[Hypothesis, Hypothesis]], list[tuple[str, dict[str, Any]]]
]:
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
    pairings = _build_tournament_pairings(
        hypotheses, tournament_rounds, research_goal, current_iteration
    )
    # Fire all matchup judgments concurrently; judge_matchup's semaphore
    # caps how many LLM calls are actually in flight at once.
    results = await asyncio.gather(
        *[
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
            )
            for i, (a, b) in enumerate(pairings)
        ]
    )
    return pairings, results


def _gather_tournament_context(
    state: WorkflowState,
) -> tuple[
    dict[str, Any] | None, Any, dict[str, Any] | None, str | None, str | None
]:
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
) -> tuple[
    int,
    dict[str, Any] | None,
    Any,
    dict[str, Any] | None,
    str | None,
    str | None,
]:
    """Sorts the pool and gathers the cross-node tournament context.

    Also emits the start-of-tournament progress event. The returned
    context is threaded into every judged matchup.

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
    logger.info(
        "Sorted hypotheses by review score (top score: %.2f)",
        hypotheses[0].score,
    )

    await emit_progress(
        state,
        "tournament_start",
        f"Running tournament with {len(hypotheses)} hypotheses...",
        65,
    )

    # Calculate number of tier-configured tournament rounds.
    # tournament_pairs is normally set upstream from the run-tier config
    # (e.g. 6/12/20/32 pairs for express/default/extended/ultra); the
    # "or len(hypotheses)" fallback only applies if it is missing/zero
    # (e.g. ad-hoc/test state).
    tournament_rounds = max(
        1, int(state.get("tournament_pairs") or len(hypotheses))
    )
    logger.info("Running %s tournament rounds", tournament_rounds)

    (
        supervisor_guidance,
        tool_registry,
        meta_review,
        run_setup_guidance,
        run_focus_guidance,
    ) = _gather_tournament_context(state)

    return (
        tournament_rounds,
        supervisor_guidance,
        tool_registry,
        meta_review,
        run_setup_guidance,
        run_focus_guidance,
    )


async def _finalize_ranking_result(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    pairings: list[tuple[Hypothesis, Hypothesis]],
    results: list[tuple[str, dict[str, Any]]],
    tournament_rounds: int,
) -> dict[str, Any]:
    """Applies matchup results and builds the ranking_node state delta.

    The hypothesis pool is re-ranked by Elo before the delta is built.

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

    await emit_progress(
        state,
        "tournament_complete",
        f"Tournament complete ({tournament_rounds} rounds)",
        80,
        top_elo=hypotheses[0].elo_rating,
        top_hypothesis=hypotheses[0].text[:200],
    )

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
    logger.info(
        "Starting ranking tournament with %s hypotheses", len(hypotheses)
    )

    _log_reflection_coverage(hypotheses)

    # Edge case: a tournament requires at least two hypotheses to pair up.
    # With fewer, skip the tournament entirely and pass the list through
    # unchanged (Elo ratings stay at their prior/initial values).
    if len(hypotheses) < 2:
        logger.warning("Need at least 2 hypotheses for tournament")
        return {"hypotheses": hypotheses}

    (
        tournament_rounds,
        supervisor_guidance,
        tool_registry,
        meta_review,
        run_setup_guidance,
        run_focus_guidance,
    ) = await _prepare_ranking_round(state, hypotheses)

    # Prepare all random pairwise matchups and judge them in parallel
    pairings, results = await _run_tournament_matchups(
        state,
        hypotheses,
        tournament_rounds,
        supervisor_guidance,
        tool_registry,
        meta_review,
        run_setup_guidance,
        run_focus_guidance,
    )

    return await _finalize_ranking_result(
        state, hypotheses, pairings, results, tournament_rounds
    )

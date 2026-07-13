"""Ranking node - Elo-based pairwise comparison of hypotheses."""

import asyncio
import hashlib
import logging
import statistics
from typing import Any

from co_scientist.constants import (
    ELO_K_FACTOR,
    LOW_TEMPERATURE,
    MAX_CONCURRENT_LLM_CALLS,
    MULTI_TURN_DEBATE_TURNS,
    SINGLE_TURN_DEBATE_TURNS,
    THINKING_MAX_TOKENS,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import Hypothesis
from co_scientist.nodes.progress import emit_progress
from co_scientist.nodes.ranking_elo import (
    calculate_elo_update as calculate_elo_update,
)
from co_scientist.nodes.ranking_elo import (
    match_tier as match_tier,
)
from co_scientist.nodes.ranking_matchmaking import (
    MatchCandidate,
    build_weighted_pairings,
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

_BLOCKING_REVIEW_DISPOSITIONS = frozenset(
    {
        "inaccurate",
        "non_novel",
        "inaccurate_and_non_novel",
        "evidence_blocked",
    }
)

# Semaphore to limit concurrent LLM calls (avoid rate limits)
_ranking_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)


def _build_tournament_pairings(
    hypotheses: list[Hypothesis],
    tournament_rounds: int,
    research_goal: str,
    current_iteration: int,
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

    Returns:
        List of (hypothesis_a, hypothesis_b) pairings, one per round.
    """
    seed_string = f"{research_goal}_{current_iteration}"
    seed = int(hashlib.md5(seed_string.encode()).hexdigest()[:8], 16)

    by_id = {h.id: h for h in hypotheses}
    candidates = [
        MatchCandidate(
            id=h.id,
            elo=h.elo_rating,
            matches=h.total_matches,
            cluster_id=h.similarity_cluster_id,
        )
        for h in hypotheses
    ]
    id_pairs = build_weighted_pairings(candidates, tournament_rounds, seed)
    return [(by_id[a], by_id[b]) for a, b in id_pairs]


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


def _parse_matchup_winner(
    response: dict[str, Any], *, fallback: str
) -> tuple[str, bool]:
    """Extracts and validates the winner side from a judge response.

    Guards against a malformed/off-schema LLM judgment: if the model
    returns anything other than "a" or "b" for the winner field, uses the
    caller's position-balanced fallback and marks the judgment invalid.

    Args:
        response: Parsed JSON response from the judge LLM call.
        fallback: Position-balanced side used for malformed output.

    Returns:
        The selected side and whether the model output was valid.
    """
    winner = str(response.get("winner") or "").lower()
    if winner not in ["a", "b"]:
        logger.warning("Invalid winner '%s'; using balanced fallback", winner)
        return fallback, False
    return winner, True


def _balanced_invalid_fallback(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    matchup_index: int | None,
) -> str:
    """Choose an identity-stable fallback that alternates across matchups."""
    identity = "|".join(sorted((hypothesis_a.id, hypothesis_b.id)))
    base = int(hashlib.sha256(identity.encode()).hexdigest()[:2], 16) % 2
    parity = base ^ int(matchup_index or 0) % 2
    chosen_id = sorted((hypothesis_a.id, hypothesis_b.id))[parity]
    return "a" if chosen_id == hypothesis_a.id else "b"


def _append_debate_context(
    prompt: str, transcript: list[dict[str, Any]]
) -> str:
    """Append prior debate turns to the judge prompt for a follow-up turn.

    Multi-turn scientific debate: each subsequent turn re-examines the prior
    turns' reasoning before delivering a refined verdict, spending more
    test-time compute on the top-ranked comparisons (SSR §4).
    """
    lines = ["\n\n## Prior Debate Turns (re-examine and refine)\n"]
    for entry in transcript:
        lines.append(
            f"- Turn {entry['turn']} favored hypothesis "
            f"{entry['winner_id']}: "
            f"{entry['reasoning']}\n"
        )
    lines.append(
        "\nWeigh the debate so far, challenge weak arguments, and deliver "
        "your refined final judgment.\n"
    )
    return prompt + "".join(lines)


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
    debate_turns: int = SINGLE_TURN_DEBATE_TURNS,
) -> tuple[str, dict[str, Any]]:
    """Has an LLM judge which hypothesis is superior.

    For ``debate_turns == 1`` (lower-ranked matchups) this is a single-turn
    comparison. For ``debate_turns > 1`` (top-ranked matchups) it runs a
    position-balanced multi-turn scientific debate: each turn re-examines the
    accumulated transcript, alternating A/B presentation order. The majority
    identity-normalized verdict stands. The complete turn-by-turn transcript,
    debate depth, and model provenance are returned for persistence.

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
        debate_turns: Number of debate turns (1 = single-turn comparison).

    Returns:
        Tuple of (winner, full_response) where winner is "a" or "b". The
        response carries ``debate_turns``, ``debate_transcript``, and
        ``judge_model`` provenance keys.
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

    turns = max(SINGLE_TURN_DEBATE_TURNS, debate_turns)
    transcript: list[dict[str, Any]] = []
    votes: list[str] = []
    fallback = _balanced_invalid_fallback(
        hypothesis_a, hypothesis_b, matchup_index
    )
    response: dict[str, Any] = {}
    for turn in range(turns):
        swapped = turn % 2 == 1
        if swapped:
            turn_prompt, turn_schema, turn_notes_a, turn_notes_b = (
                _build_matchup_prompt(
                    hypothesis_b,
                    hypothesis_a,
                    research_goal,
                    supervisor_guidance,
                    meta_review,
                    tool_registry,
                    run_setup_guidance,
                    run_focus_guidance,
                )
            )
        else:
            turn_prompt = prompt
            turn_schema = schema
            turn_notes_a = reflection_notes_a
            turn_notes_b = reflection_notes_b
        turn_prompt = (
            turn_prompt
            if turn == 0
            else _append_debate_context(turn_prompt, transcript)
        )
        response = await _call_matchup_judge(
            turn_prompt,
            turn_schema,
            model_name,
            run_id,
            matchup_index,
            turn_notes_a,
            turn_notes_b,
        )
        raw_fallback = (
            ("b" if fallback == "a" else "a") if swapped else fallback
        )
        raw_winner, valid_output = _parse_matchup_winner(
            response, fallback=raw_fallback
        )
        winner = (
            "b" if raw_winner == "a" else "a"
        ) if swapped else raw_winner
        votes.append(winner)
        transcript.append(
            {
                "turn": turn + 1,
                "winner": winner,
                "winner_id": (
                    hypothesis_a.id if winner == "a" else hypothesis_b.id
                ),
                "reasoning": _extract_reasoning(response),
                "presentation_order": "ba" if swapped else "ab",
                "valid_output": valid_output,
            }
        )

    winner = "a" if votes.count("a") > votes.count("b") else "b"
    if votes.count("a") == votes.count("b"):
        winner = fallback

    # Persist debate provenance on the final response.
    response["debate_turns"] = turns
    response["debate_transcript"] = transcript
    response["judge_model"] = model_name
    response["consensus_votes"] = votes
    response["position_balanced"] = turns > 1
    response["invalid_output_fallback"] = not all(
        turn["valid_output"] for turn in transcript
    )
    return winner, response


def _median_elo(hypotheses: list[Hypothesis]) -> float:
    """Return the median Elo of the pool (the debate-depth threshold)."""
    if not hypotheses:
        return 0.0
    return statistics.median(h.elo_rating for h in hypotheses)


def _matchup_debate_turns(
    hyp_a: Hypothesis, hyp_b: Hypothesis, median_elo: float
) -> int:
    """Return the debate depth for a matchup.

    Top-ranked comparisons (at least one hypothesis at or above the pool's
    median Elo) use a multi-turn scientific debate; comparisons between two
    lower-ranked hypotheses use a single-turn comparison (SSR §4, §12).
    """
    top_ranked = (
        hyp_a.elo_rating >= median_elo or hyp_b.elo_rating >= median_elo
    )
    return MULTI_TURN_DEBATE_TURNS if top_ranked else SINGLE_TURN_DEBATE_TURNS


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
    list[dict[str, Any]],
    int,
]:
    """Select, judge, and commit tournament matchups sequentially.

    Each pairing runs a multi-turn debate when it is top-ranked and a
    single-turn comparison otherwise (depth from the pool's median Elo).

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
        Tuple of (matchup details, total LLM calls). Each outcome is committed
        before the next pairing is selected, so matchmaking observes current
        ratings and coverage rather than a stale pre-round snapshot.
    """
    research_goal = state["research_goal"]
    current_iteration = state.get("current_iteration", 0)
    details: list[dict[str, Any]] = []
    total_llm_calls = 0
    previous_pair: frozenset[str] | None = None
    for index in range(tournament_rounds):
        # A distinct deterministic seed plus updated in-memory Elo/match counts
        # makes each selection depend on every committed earlier outcome.
        candidates = _build_tournament_pairings(
            hypotheses,
            min(3, tournament_rounds),
            research_goal,
            current_iteration * 10_000 + index,
        )
        pairing = next(
            (
                item
                for item in candidates
                if frozenset({item[0].id, item[1].id}) != previous_pair
            ),
            candidates[0] if candidates else None,
        )
        if pairing is None:
            break
        hyp_a, hyp_b = pairing
        depth = _matchup_debate_turns(hyp_a, hyp_b, _median_elo(hypotheses))
        winner, response = await judge_matchup(
            hyp_a,
            hyp_b,
            state["research_goal"],
            state["model_name"],
            supervisor_guidance,
            run_id=state.get("run_id"),
            matchup_index=index,
            tool_registry=tool_registry,
            meta_review=meta_review,
            run_setup_guidance=run_setup_guidance,
            run_focus_guidance=run_focus_guidance,
            debate_turns=depth,
        )
        outcome = _apply_matchup_elo(
            hyp_a,
            hyp_b,
            winner,
            k_factor=int(state.get("elo_k_factor") or ELO_K_FACTOR),
        )
        details.append(
            _build_matchup_detail(hyp_a, hyp_b, winner, response, outcome)
        )
        previous_pair = frozenset({hyp_a.id, hyp_b.id})
        total_llm_calls += depth
    return details, total_llm_calls


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
    # Sort hypotheses by Elo rating (highest first), with score then text as
    # deterministic tiebreakers when Elo ratings are equal.
    hypotheses = sorted(
        hypotheses,
        key=lambda item: (
            item.deep_verification_verdict == "undermined"
            or item.review_disposition in _BLOCKING_REVIEW_DISPOSITIONS,
            -item.elo_rating,
            -item.score,
            item.text,
        ),
    )

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

    return _build_ranking_delta(
        hypotheses, matchup_details, tournament_rounds, total_llm_calls
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
    eligible = [
        hypothesis
        for hypothesis in hypotheses
        if hypothesis.deep_verification_verdict != "undermined"
        and hypothesis.review_disposition not in _BLOCKING_REVIEW_DISPOSITIONS
    ]
    logger.info(
        "Starting ranking tournament with %s hypotheses", len(hypotheses)
    )

    _log_reflection_coverage(hypotheses)

    # Edge case: a tournament requires at least two hypotheses to pair up.
    # With fewer, skip the tournament entirely and pass the list through
    # unchanged (Elo ratings stay at their prior/initial values).
    if len(eligible) < 2:
        logger.warning("Need at least 2 hypotheses for tournament")
        return {"hypotheses": hypotheses}

    (
        tournament_rounds,
        supervisor_guidance,
        tool_registry,
        meta_review,
        run_setup_guidance,
        run_focus_guidance,
    ) = await _prepare_ranking_round(state, eligible)

    matchup_details, total_llm_calls = await _run_tournament_matchups(
        state,
        eligible,
        tournament_rounds,
        supervisor_guidance,
        tool_registry,
        meta_review,
        run_setup_guidance,
        run_focus_guidance,
    )

    return await _finalize_ranking_result(
        state,
        hypotheses,
        matchup_details,
        tournament_rounds,
        total_llm_calls,
    )

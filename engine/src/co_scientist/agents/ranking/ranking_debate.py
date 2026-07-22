"""Single-matchup judging: the scientific-debate LLM judge for ranking.

Owns everything about deciding one pairwise matchup — the per-loop judge
semaphore, the judge LLM call, winner parsing with its position-balanced
fallback, multi-turn debate transcripts, and the debate-depth policy.
Tournament orchestration (pairing selection, Elo commits, the graph node)
stays in ``ranking.py``, which re-exports these names for compatibility.
"""

import asyncio
import hashlib
import logging
import statistics
import weakref
from typing import Any

from co_scientist.agents.ranking.ranking_prompt import _build_matchup_prompt
from co_scientist.agents.ranking.ranking_results import _extract_reasoning
from co_scientist.constants import (
    LOW_TEMPERATURE,
    MAX_CONCURRENT_LLM_CALLS,
    MULTI_TURN_DEBATE_TURNS,
    SINGLE_TURN_DEBATE_TURNS,
    THINKING_MAX_TOKENS,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import Hypothesis

logger = logging.getLogger(__name__)

# Concurrent-judge bound, one per event loop (avoid rate limits).
#
# An asyncio primitive belongs to exactly one event loop: it binds to whichever
# loop first waits on it and raises from every other. The durable worker runs
# each scientific task on its own thread with its own loop, so a single
# module-level semaphore is shared across loops that may never legally share
# it. That stayed hidden only while a tournament judged fewer matchups than
# the semaphore had permits and so never actually waited; once waves filled,
# a production ranking task died on "bound to a different event loop".
#
# Keyed weakly so a finished task's loop does not keep its entry alive. The
# bound is now per task rather than process-wide, which is the meaningful
# unit here anyway -- how many tasks run at once is the worker cohort's job.
_ranking_semaphores: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Semaphore
] = weakref.WeakKeyDictionary()


def _get_ranking_semaphore() -> asyncio.Semaphore:
    """Return the running loop's judge-concurrency bound, creating it once."""
    loop = asyncio.get_running_loop()
    semaphore = _ranking_semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)
        _ranking_semaphores[loop] = semaphore
    return semaphore


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
    async with _get_ranking_semaphore():
        return await call_llm_json(
            prompt=prompt,
            model_name=model_name,
            max_tokens=THINKING_MAX_TOKENS,
            temperature=LOW_TEMPERATURE,
            json_schema=schema,
            run_id=run_id,
            prompt_name=prompt_name,
            # The only engine node that opts out of thinking: the tournament
            # runs one matchup per hypothesis pair, so these calls scale
            # O(n^2) per cycle and their reasoning spend dominates run
            # latency. The prompt already asks for an explicit rationale, so
            # the comparison stays reasoned in the answer itself.
            enable_thinking=False,
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
    # Fold the matchup index into the starting presentation order so that
    # single-turn (lower-ranked) comparisons, which only ever run turn 0, do
    # not always present hypothesis A first — otherwise any residual positional
    # bias in the judge would systematically favor the A slot. Multi-turn
    # debates still alternate every turn; even matchup indices preserve the
    # historical ab/ba/ab ordering.
    start_parity = int(matchup_index or 0) % 2
    for turn in range(turns):
        swapped = (turn + start_parity) % 2 == 1
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
        winner = ("b" if raw_winner == "a" else "a") if swapped else raw_winner
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

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
from typing import Any, NamedTuple

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


def _matchup_prompt_name(matchup_index: int | None) -> str:
    """Builds the saved-prompt name for one matchup judge call."""
    return (
        f"ranking_matchup_{matchup_index}"
        if matchup_index is not None
        else "ranking_matchup"
    )


def _judge_call_metadata(
    matchup_index: int | None,
    prompt: str,
    reflection_notes_a: str | None,
    reflection_notes_b: str | None,
) -> dict[str, Any]:
    """Builds the prompt_metadata dict for one matchup judge call."""
    return {
        "matchup_index": matchup_index,
        "prompt_length_chars": len(prompt),
        "has_reflection_a": bool(reflection_notes_a),
        "has_reflection_b": bool(reflection_notes_b),
    }


async def _invoke_matchup_judge_call(
    prompt: str,
    schema: dict[str, Any] | None,
    model_name: str,
    run_id: str | None,
    prompt_name: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Calls the judge LLM with the tournament's reduced-thinking settings.

    The only engine node that opts out of thinking: the tournament runs one
    matchup per hypothesis pair, so these calls scale O(n^2) per cycle and
    their reasoning spend dominates run latency. The prompt already asks
    for an explicit rationale, so the comparison stays reasoned in the
    answer itself.
    """
    return await call_llm_json(
        prompt=prompt,
        model_name=model_name,
        max_tokens=THINKING_MAX_TOKENS,
        temperature=LOW_TEMPERATURE,
        json_schema=schema,
        run_id=run_id,
        prompt_name=prompt_name,
        enable_thinking=False,
        prompt_metadata=metadata,
    )


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
    prompt_name = _matchup_prompt_name(matchup_index)
    metadata = _judge_call_metadata(
        matchup_index, prompt, reflection_notes_a, reflection_notes_b
    )

    # Use semaphore to limit concurrent calls (avoid rate limits)
    async with _get_ranking_semaphore():
        return await _invoke_matchup_judge_call(
            prompt, schema, model_name, run_id, prompt_name, metadata
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


class _DebateContext(NamedTuple):
    """Immutable per-matchup inputs threaded unchanged through every turn."""

    hypothesis_a: Hypothesis
    hypothesis_b: Hypothesis
    research_goal: str
    supervisor_guidance: dict[str, Any] | None
    meta_review: dict[str, Any] | None
    tool_registry: Any | None
    run_setup_guidance: str | None
    run_focus_guidance: str | None
    model_name: str
    run_id: str | None
    matchup_index: int | None


def _build_matchup_prompt_from_ctx(
    ctx: _DebateContext,
) -> tuple[str, dict[str, Any] | None, str | None, str | None]:
    """Renders the base (unswapped) matchup prompt from the debate context."""
    return _build_matchup_prompt(
        ctx.hypothesis_a,
        ctx.hypothesis_b,
        ctx.research_goal,
        ctx.supervisor_guidance,
        ctx.meta_review,
        ctx.tool_registry,
        ctx.run_setup_guidance,
        ctx.run_focus_guidance,
    )


def _build_turn_prompt(
    ctx: _DebateContext,
    turn: int,
    swapped: bool,
    base_prompt: str,
    base_schema: dict[str, Any] | None,
    base_notes_a: str | None,
    base_notes_b: str | None,
    transcript: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None, str | None, str | None]:
    """Selects and prepares one debate turn's prompt, schema, and notes.

    A swapped turn re-renders the prompt with A/B presentation reversed;
    every turn after the first also carries the accumulated transcript.
    """
    if swapped:
        turn_prompt, turn_schema, turn_notes_a, turn_notes_b = (
            _build_matchup_prompt(
                ctx.hypothesis_b,
                ctx.hypothesis_a,
                ctx.research_goal,
                ctx.supervisor_guidance,
                ctx.meta_review,
                ctx.tool_registry,
                ctx.run_setup_guidance,
                ctx.run_focus_guidance,
            )
        )
    else:
        turn_prompt = base_prompt
        turn_schema = base_schema
        turn_notes_a = base_notes_a
        turn_notes_b = base_notes_b
    if turn > 0:
        turn_prompt = _append_debate_context(turn_prompt, transcript)
    return turn_prompt, turn_schema, turn_notes_a, turn_notes_b


def _resolve_turn_winner(
    response: dict[str, Any], swapped: bool, fallback: str
) -> tuple[str, bool]:
    """Resolves one turn's winner, un-swapping the judge's raw side."""
    raw_fallback = ("b" if fallback == "a" else "a") if swapped else fallback
    raw_winner, valid_output = _parse_matchup_winner(
        response, fallback=raw_fallback
    )
    winner = ("b" if raw_winner == "a" else "a") if swapped else raw_winner
    return winner, valid_output


async def _run_debate_turn(
    ctx: _DebateContext,
    turn: int,
    swapped: bool,
    turn_prompt: str,
    turn_schema: dict[str, Any] | None,
    turn_notes_a: str | None,
    turn_notes_b: str | None,
    fallback: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Judges one debate turn and builds its transcript entry.

    Returns:
        Tuple of (winner, transcript_entry, raw_response).
    """
    response = await _call_matchup_judge(
        turn_prompt,
        turn_schema,
        ctx.model_name,
        ctx.run_id,
        ctx.matchup_index,
        turn_notes_a,
        turn_notes_b,
    )
    winner, valid_output = _resolve_turn_winner(response, swapped, fallback)
    entry = {
        "turn": turn + 1,
        "winner": winner,
        "winner_id": (
            ctx.hypothesis_a.id if winner == "a" else ctx.hypothesis_b.id
        ),
        "reasoning": _extract_reasoning(response),
        "presentation_order": "ba" if swapped else "ab",
        "valid_output": valid_output,
    }
    return winner, entry, response


def _finalize_debate_response(
    response: dict[str, Any],
    votes: list[str],
    transcript: list[dict[str, Any]],
    fallback: str,
    turns: int,
    model_name: str,
) -> str:
    """Determines the debate's overall winner and attaches provenance fields."""
    winner = "a" if votes.count("a") > votes.count("b") else "b"
    if votes.count("a") == votes.count("b"):
        winner = fallback

    response["debate_turns"] = turns
    response["debate_transcript"] = transcript
    response["judge_model"] = model_name
    response["consensus_votes"] = votes
    response["position_balanced"] = turns > 1
    response["invalid_output_fallback"] = not all(
        turn["valid_output"] for turn in transcript
    )
    return winner


async def _execute_debate_turn(
    ctx: _DebateContext,
    turn: int,
    start_parity: int,
    prompt: str,
    schema: dict[str, Any] | None,
    reflection_notes_a: str | None,
    reflection_notes_b: str | None,
    transcript: list[dict[str, Any]],
    fallback: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Builds and judges one debate turn.

    Returns:
        Tuple of (winner, transcript_entry, raw_response).
    """
    swapped = (turn + start_parity) % 2 == 1
    turn_prompt, turn_schema, turn_notes_a, turn_notes_b = _build_turn_prompt(
        ctx,
        turn,
        swapped,
        prompt,
        schema,
        reflection_notes_a,
        reflection_notes_b,
        transcript,
    )
    return await _run_debate_turn(
        ctx,
        turn,
        swapped,
        turn_prompt,
        turn_schema,
        turn_notes_a,
        turn_notes_b,
        fallback,
    )


async def _run_debate_turns(
    ctx: _DebateContext,
    turns: int,
    prompt: str,
    schema: dict[str, Any] | None,
    reflection_notes_a: str | None,
    reflection_notes_b: str | None,
    fallback: str,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Runs every debate turn, alternating A/B presentation order.

    Folds the matchup index into the starting presentation order so a
    single-turn (lower-ranked) comparison does not always present
    hypothesis A first (see ``_execute_debate_turn``).

    Returns:
        Tuple of (votes, transcript, final raw response).
    """
    transcript: list[dict[str, Any]] = []
    votes: list[str] = []
    response: dict[str, Any] = {}
    start_parity = int(ctx.matchup_index or 0) % 2
    for turn in range(turns):
        winner, entry, response = await _execute_debate_turn(
            ctx,
            turn,
            start_parity,
            prompt,
            schema,
            reflection_notes_a,
            reflection_notes_b,
            transcript,
            fallback,
        )
        votes.append(winner)
        transcript.append(entry)
    return votes, transcript, response


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

    Single-turn for ``debate_turns == 1`` (lower-ranked matchups); a
    position-balanced multi-turn scientific debate otherwise (mechanics in
    ``_run_debate_turns``). Returns the majority identity-normalized
    verdict; the full transcript, debate depth, and model provenance are
    attached to the response for persistence.

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
    ctx = _DebateContext(
        hypothesis_a,
        hypothesis_b,
        research_goal,
        supervisor_guidance,
        meta_review,
        tool_registry,
        run_setup_guidance,
        run_focus_guidance,
        model_name,
        run_id,
        matchup_index,
    )
    prompt, schema, reflection_notes_a, reflection_notes_b = (
        _build_matchup_prompt_from_ctx(ctx)
    )
    turns = max(SINGLE_TURN_DEBATE_TURNS, debate_turns)
    fallback = _balanced_invalid_fallback(
        hypothesis_a, hypothesis_b, matchup_index
    )

    votes, transcript, response = await _run_debate_turns(
        ctx,
        turns,
        prompt,
        schema,
        reflection_notes_a,
        reflection_notes_b,
        fallback,
    )

    winner = _finalize_debate_response(
        response, votes, transcript, fallback, turns, model_name
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

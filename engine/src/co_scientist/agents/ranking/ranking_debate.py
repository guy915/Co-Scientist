"""Single-matchup judging: the scientific-debate LLM judge for ranking.

Owns everything about deciding one pairwise matchup — the per-loop judge
semaphore, the judge LLM call, winner parsing with its position-balanced
fallback, multi-turn debate transcripts, and the debate-depth policy.
Tournament orchestration (pairing selection, Elo commits, the graph node)
stays in ``ranking.py``, which re-exports these names for compatibility.
"""

import asyncio
import logging
import statistics
import weakref
from typing import Any

from co_scientist.agents.ranking.ranking_debate_turns import (
    _RANKING_DEBATE_MAX_TURNS as _RANKING_DEBATE_MAX_TURNS,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _append_debate_context as _append_debate_context,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _balanced_invalid_fallback as _balanced_invalid_fallback,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _build_matchup_prompt_from_ctx as _build_matchup_prompt_from_ctx,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _build_turn_prompt as _build_turn_prompt,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _DebateContext as _DebateContext,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _DebateRun as _DebateRun,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _finalize_debate_response as _finalize_debate_response,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _MatchupPrompt as _MatchupPrompt,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _parse_matchup_winner as _parse_matchup_winner,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _ranking_debate_consensus as _ranking_debate_consensus,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _resolve_turn_winner as _resolve_turn_winner,
)
from co_scientist.agents.ranking.ranking_results import _extract_reasoning
from co_scientist.constants import (
    LOW_TEMPERATURE,
    RANKING_WAVE_MIN_SIZE,
    RANKING_WAVE_SIZE,
    SINGLE_TURN_DEBATE_TURNS,
    THINKING_MAX_TOKENS,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
    indexed_prompt_name,
)
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


def effective_ranking_wave_size() -> int:
    """Return the width the next ranking wave should use.

    Full width until the provider starts pushing back, then the floor. A
    wave wider than the provider will serve does not finish sooner: the
    surplus calls spend their time asleep in jittered backoff, and the
    burst is what provoked the throttling to begin with.

    The step down is one-way within a process. Throttling is a property of
    the account and the moment, not of one wave, so widening again on the
    next quiet wave would just re-provoke it.
    """
    from co_scientist.llm_json_retry import rate_limited_attempt_count

    if rate_limited_attempt_count():
        return RANKING_WAVE_MIN_SIZE
    return RANKING_WAVE_SIZE


def _get_ranking_semaphore() -> asyncio.Semaphore:
    """Return the running loop's judge-concurrency bound, creating it once.

    Sized to the wave rather than to MAX_CONCURRENT_LLM_CALLS: the wave is
    the unit of work a single durable task judges, and a semaphore narrower
    than it would quietly serialize the wave into batches, spending the
    task's wall time without any of the parallelism the wave exists for.
    """
    loop = asyncio.get_running_loop()
    semaphore = _ranking_semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(RANKING_WAVE_SIZE)
        _ranking_semaphores[loop] = semaphore
    return semaphore


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
    mp: _MatchupPrompt,
    ctx: _DebateContext,
    prompt_name: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Calls the judge LLM for one matchup.

    Thinking is on, as everywhere else. This is the run's highest-volume
    call -- one matchup per hypothesis pair, scaling O(n^2) per cycle -- so
    it is also where reasoning costs the most wall-clock time; the budget
    below is ``THINKING_MAX_TOKENS`` precisely because the chain of thought
    is drawn from it. The prompt's per-criterion rationale is now the
    reasoning made legible for display, not a substitute for it.
    """
    return await call_llm_json(
        prompt=mp.prompt,
        spec=CompletionSpec(
            model_name=ctx.model_name,
            max_tokens=THINKING_MAX_TOKENS,
            temperature=LOW_TEMPERATURE,
            json_schema=mp.schema,
        ),
        options=LLMCallOptions(
            run_id=ctx.run_id,
            prompt_name=prompt_name,
            prompt_metadata=metadata,
        ),
    )


async def _call_matchup_judge(
    mp: _MatchupPrompt,
    ctx: _DebateContext,
) -> dict[str, Any]:
    """Calls the LLM judge for one matchup, bounded by the ranking semaphore.

    Args:
        mp: Rendered matchup prompt (with schema and per-side notes).
        ctx: Debate context supplying the model, run id, and matchup index.

    Returns:
        Parsed JSON response from the LLM.
    """
    prompt_name = indexed_prompt_name("ranking_matchup", ctx.matchup_index)
    metadata = _judge_call_metadata(
        ctx.matchup_index, mp.prompt, mp.notes_a, mp.notes_b
    )

    # Use semaphore to limit concurrent calls (avoid rate limits)
    async with _get_ranking_semaphore():
        return await _invoke_matchup_judge_call(mp, ctx, prompt_name, metadata)


async def _run_debate_turn(
    ctx: _DebateContext,
    turn: int,
    swapped: bool,
    mp: _MatchupPrompt,
    fallback: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Judges one debate turn and builds its transcript entry.

    Returns:
        Tuple of (winner, transcript_entry, raw_response).
    """
    response = await _call_matchup_judge(mp, ctx)
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


async def _execute_debate_turn(
    ctx: _DebateContext,
    turn: int,
    run: _DebateRun,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Builds and judges one debate turn.

    Returns:
        Tuple of (winner, transcript_entry, raw_response).
    """
    swapped = (turn + run.start_parity) % 2 == 1
    turn_mp = _build_turn_prompt(ctx, turn, swapped, run.base, run.transcript)
    return await _run_debate_turn(ctx, turn, swapped, turn_mp, run.fallback)


async def _run_debate_turns(
    ctx: _DebateContext,
    turns: int,
    base: _MatchupPrompt,
    fallback: str,
) -> tuple[list[str], _DebateRun, dict[str, Any]]:
    """Runs debate turns until consensus is reached, alternating order.

    Deliberate local choice (finding E18): the "debate" is one judge
    re-examining the accumulated verdicts each turn, not distinct
    advocate/opponent personas. The published ranking-05 prompt (App. A,
    docs/CORPUS-EXTRACTION.md:1210-1214) does frame the judge as
    "simulating a panel of domain experts" who "possess no pre-existing
    biases" -- so it names a panel, and this loop implements one voice,
    not a simulated panel of several. What the paper never does, panel
    framing or not, is name distinct advocate/opponent *personas* for
    that panel; the Innovator/Pragmatist/Contrarian persona requirement
    appears solely in the local reference corpus's clone-authored design
    and is not treated as a fidelity target (see FINDINGS.md,
    Corpus-integrity corrections).

    Folds the matchup index into the starting presentation order so a
    single-turn (lower-ranked) comparison does not always present
    hypothesis A first (see ``_execute_debate_turn``).

    Turns are strictly serial -- each one re-examines the transcript so far
    -- so this loop is the deepest part of the run's critical path, and
    ranking is its highest-volume stage. It is adaptive within the paper's
    envelope (typically 3-5 turns, max 10): it stops as soon as
    ``_ranking_debate_consensus`` holds -- at earliest once the
    typical-minimum floor has run, at latest when the budget is spent --
    so a settled verdict retires the remaining judge calls while a
    genuinely contested one buys more depth.

    Returns:
        Tuple of (votes, debate run with the accumulated transcript, final
        raw response).
    """
    run = _DebateRun(
        base=base,
        transcript=[],
        fallback=fallback,
        start_parity=int(ctx.matchup_index or 0) % 2,
    )
    votes: list[str] = []
    response: dict[str, Any] = {}
    for turn in range(turns):
        winner, entry, response = await _execute_debate_turn(ctx, turn, run)
        votes.append(winner)
        run.transcript.append(entry)
        if _ranking_debate_consensus(votes, turn + 1, turns):
            break
    return votes, run, response


async def judge_matchup(
    ctx: _DebateContext,
    debate_turns: int = SINGLE_TURN_DEBATE_TURNS,
) -> tuple[str, dict[str, Any]]:
    """Has an LLM judge which hypothesis is superior.

    Single-turn for ``debate_turns == 1`` (lower-ranked matchups, which
    render published ranking-04); a position-balanced multi-turn
    scientific debate otherwise (published ranking-05; mechanics in
    ``_run_debate_turns``), capped at the paper's envelope maximum of
    ``_RANKING_DEBATE_MAX_TURNS`` judged turns. Returns a
    ``(winner, full_response)`` tuple where winner is "a" or "b" -- the
    majority identity-normalized verdict -- and the response carries
    ``debate_turns``, ``debate_transcript``, and ``judge_model``
    provenance keys for persistence. ``ctx`` bundles the two hypotheses,
    the research goal, model name, and the optional guidance, tool
    registry, evaluation criteria, and prompt-naming
    (``run_id``/``matchup_index``) fields.
    """
    turns = max(SINGLE_TURN_DEBATE_TURNS, debate_turns)
    if turns > SINGLE_TURN_DEBATE_TURNS:
        turns = min(turns, _RANKING_DEBATE_MAX_TURNS)
    # The turn budget selects the published prompt: ranking-05's
    # simulated scientific debate for a multi-turn matchup, ranking-04's
    # single-shot comparison otherwise. Decided once here so every turn
    # of one matchup -- including the swapped re-renders -- agrees.
    ctx = ctx._replace(debate=turns > SINGLE_TURN_DEBATE_TURNS)
    base = _build_matchup_prompt_from_ctx(ctx)
    fallback = _balanced_invalid_fallback(
        ctx.hypothesis_a, ctx.hypothesis_b, ctx.matchup_index
    )
    votes, run, response = await _run_debate_turns(ctx, turns, base, fallback)
    winner = _finalize_debate_response(response, votes, run, ctx.model_name)
    return winner, response


def _median_elo(hypotheses: list[Hypothesis]) -> float:
    """Return the median Elo of the pool (the debate-depth threshold)."""
    if not hypotheses:
        return 0.0
    return statistics.median(h.elo_rating for h in hypotheses)


def _matchup_debate_turns(
    hyp_a: Hypothesis, hyp_b: Hypothesis, median_elo: float
) -> int:
    """Return the debate depth budget for a matchup.

    Top-ranked comparisons (at least one hypothesis at or above the pool's
    median Elo) use a multi-turn scientific debate; comparisons between two
    lower-ranked hypotheses use a single-turn comparison (SSR §4, §12).

    The multi-turn budget is the paper's envelope maximum: the judge loop
    itself is adaptive (see ``_ranking_debate_consensus``) and settles as
    soon as the debate is conclusive, so the budget is a ceiling on
    contested matchups, not the cost of every one.
    """
    top_ranked = (
        hyp_a.elo_rating >= median_elo or hyp_b.elo_rating >= median_elo
    )
    if top_ranked:
        return _RANKING_DEBATE_MAX_TURNS
    return SINGLE_TURN_DEBATE_TURNS

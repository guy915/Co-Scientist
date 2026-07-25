"""Debate-turn primitives for the scientific-debate ranking judge.

Holds the pure per-turn machinery — winner parsing with its
position-balanced fallback, prompt assembly for each turn (including the
A/B swap and prior-transcript append), and the final vote tally. The judge
LLM call, the per-loop semaphore, and the debate-turn orchestration stay
in ``ranking_debate.py``, which re-exports these names for compatibility.
"""

import dataclasses
import hashlib
import logging
from typing import Any, NamedTuple

from co_scientist.agents.ranking.ranking_prompt import (
    _build_matchup_prompt,
    _MatchupPromptContext,
)
from co_scientist.models import Hypothesis

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _MatchupPrompt:
    """A rendered matchup prompt and the per-side reflection notes it used."""

    prompt: str
    schema: dict[str, Any] | None
    notes_a: str | None
    notes_b: str | None


@dataclasses.dataclass(frozen=True)
class _DebateRun:
    """Debate-loop state shared across every turn of one matchup.

    ``transcript`` is the growing list of turn entries -- mutated in place
    as turns complete, so ``base`` (the unswapped turn-0 prompt), the
    position-balanced ``fallback``, and the matchup-derived ``start_parity``
    stay constant while the transcript accumulates.
    """

    base: _MatchupPrompt
    transcript: list[dict[str, Any]]
    fallback: str
    start_parity: int


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
    """Immutable per-matchup inputs threaded unchanged through every turn.

    The trailing guidance/naming fields default to None so a caller (test or
    app) can build a context from the load-bearing identity fields alone.
    """

    hypothesis_a: Hypothesis
    hypothesis_b: Hypothesis
    research_goal: str
    model_name: str
    supervisor_guidance: dict[str, Any] | None = None
    meta_review: dict[str, Any] | None = None
    tool_registry: Any | None = None
    run_setup_guidance: str | None = None
    run_focus_guidance: str | None = None
    run_id: str | None = None
    matchup_index: int | None = None


def _prompt_context(ctx: _DebateContext) -> _MatchupPromptContext:
    """Projects the debate context onto the run-level prompt context."""
    return _MatchupPromptContext(
        research_goal=ctx.research_goal,
        supervisor_guidance=ctx.supervisor_guidance,
        meta_review=ctx.meta_review,
        tool_registry=ctx.tool_registry,
        run_setup_guidance=ctx.run_setup_guidance,
        run_focus_guidance=ctx.run_focus_guidance,
    )


def _render_ordered_prompt(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    ctx: _DebateContext,
) -> _MatchupPrompt:
    """Renders one matchup prompt for the given A/B presentation order."""
    prompt, schema, notes_a, notes_b = _build_matchup_prompt(
        hypothesis_a, hypothesis_b, _prompt_context(ctx)
    )
    return _MatchupPrompt(prompt, schema, notes_a, notes_b)


def _build_matchup_prompt_from_ctx(ctx: _DebateContext) -> _MatchupPrompt:
    """Renders the base (unswapped) matchup prompt from the debate context."""
    return _render_ordered_prompt(ctx.hypothesis_a, ctx.hypothesis_b, ctx)


def _build_turn_prompt(
    ctx: _DebateContext,
    turn: int,
    swapped: bool,
    base: _MatchupPrompt,
    transcript: list[dict[str, Any]],
) -> _MatchupPrompt:
    """Selects and prepares one debate turn's prompt, schema, and notes.

    A swapped turn re-renders the prompt with A/B presentation reversed;
    every turn after the first also carries the accumulated transcript.
    """
    if swapped:
        turn_prompt = _render_ordered_prompt(
            ctx.hypothesis_b, ctx.hypothesis_a, ctx
        )
    else:
        turn_prompt = base
    if turn > 0:
        turn_prompt = dataclasses.replace(
            turn_prompt,
            prompt=_append_debate_context(turn_prompt.prompt, transcript),
        )
    return turn_prompt


def _majority_decided(votes: list[str], turns: int) -> bool:
    """True once no remaining turn can change the majority verdict.

    A debate's winner is the majority of its turn votes, so a side holding
    more than half of the budgeted turns has already won and the turns left
    are pure latency: they cannot flip the verdict, only restate it. This
    matters most in the case it fires on -- turns alternate A/B presentation
    order, so two agreeing turns agreed from *opposite* orders, which is the
    position-bias-free evidence the third turn exists to supply.

    A split (one vote each) is not decided, so the tie-breaking turn still
    runs. Single-turn comparisons are decided by their only turn.
    """
    needed = turns // 2 + 1
    return votes.count("a") >= needed or votes.count("b") >= needed


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


def _finalize_debate_response(
    response: dict[str, Any],
    votes: list[str],
    run: _DebateRun,
    model_name: str,
) -> str:
    """Determines the debate's overall winner and attaches provenance fields.

    ``debate_turns`` records the turns actually judged rather than the depth
    the matchup was budgeted, since a decided majority stops the debate
    early (see ``_majority_decided``). It is persisted as provenance and
    metered as the matchup's LLM spend, so reporting the budget would
    overstate both.
    """
    turns = len(votes)
    winner = "a" if votes.count("a") > votes.count("b") else "b"
    if votes.count("a") == votes.count("b"):
        winner = run.fallback

    response["debate_turns"] = turns
    response["debate_transcript"] = run.transcript
    response["judge_model"] = model_name
    response["consensus_votes"] = votes
    response["position_balanced"] = turns > 1
    response["invalid_output_fallback"] = not all(
        turn["valid_output"] for turn in run.transcript
    )
    return winner

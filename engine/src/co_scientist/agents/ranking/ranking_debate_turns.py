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
import re
from typing import Any, Final, NamedTuple

from co_scientist.agents.ranking.ranking_prompt import (
    _build_matchup_prompt,
    _MatchupPromptContext,
)
from co_scientist.llm_telemetry import record_deterministic_fallback
from co_scientist.models import Hypothesis

logger = logging.getLogger(__name__)

# The paper's tournament-debate turn envelope (SSR note 9.3): the panel
# discussion "typically rang[es] from 3 to 5, with a maximum of 10" and
# ends with a conclusive judgment once sufficient depth is reached. These
# live here, not in constants_tournament.py, because the judge loop
# (ranking_debate.py) and the follow-up-turn prose in
# ``_append_debate_context`` must share a single source -- the panel paces
# itself against whatever number it is told, so a stale figure reads as a
# real instruction. constants_tournament.py keeps the values that size the
# tournament (Elo, match budgets, wave width); this envelope belongs to
# the debate itself.
_RANKING_DEBATE_TYPICAL_MIN_TURNS: Final = 3
"""Turns a top-ranked debate is guaranteed before consensus is honoured."""

_RANKING_DEBATE_TYPICAL_MAX_TURNS: Final = 5
"""Upper end of the paper's typical settlement range for a debate."""

_RANKING_DEBATE_MAX_TURNS: Final = 10
"""Hard ceiling on judged turns for one multi-turn matchup."""


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


# The paper's judge protocol ends the rationale with a literal verdict
# line -- "better idea: <1 or 2>" (the A.4 template also spells it
# "better hypothesis"); the ranking prompt asks for the same line as the
# final line of decision_summary. Case-insensitive; only a lone 1/2/a/b
# token counts, and ``_parse_verdict_line`` reads matches last-first and
# skips the quoted format ("better idea: 1 or 2") so prose describing the
# protocol cannot pose as a verdict.
_VERDICT_LINE_RE = re.compile(
    r"better\s+(?:idea|hypothesis)\s*:\s*([12ab])(?![\w])",
    re.IGNORECASE,
)


# The same verdict line, anchored to the end of a turn's text. Each turn
# answers with its own concluding "better idea: <n>", numbered in *that*
# turn's presentation order -- which the loop alternates -- so a rendered
# transcript that kept them would argue for a different number every turn.
# Only a trailing match is a verdict; a mid-text mention is the judge
# quoting the protocol (the same distinction _parse_verdict_line draws).
_TRAILING_VERDICT_RE = re.compile(
    r"\s*better\s+(?:idea|hypothesis)\s*:\s*[12ab]\W*$",
    re.IGNORECASE,
)


def _verdict_number(side: str) -> str:
    """Name a canonical side by the number the published verdict prints.

    The prompt labels its sides "Hypothesis 1" and "Hypothesis 2"; the
    canonical (un-swapped) side "a" is 1 and "b" is 2.
    """
    return "1" if side == "a" else "2"


def _presented_first(entry: dict[str, Any]) -> str:
    """Name the canonical idea a turn presented as its "Hypothesis 1".

    ``_execute_debate_turn`` alternates which side is presented first and
    records the order it used, so a turn's own prose numbers the two
    ideas by *that* order. A consumer rendering the turns needs the
    mapping stated, or the transcript reads as one judge contradicting
    itself. An entry recorded before the order was kept reads as the
    canonical (un-swapped) one.
    """
    return "2" if str(entry.get("presentation_order") or "ab") == "ba" else "1"


def _turn_argument(reasoning: str) -> str:
    """One turn's argument with its own trailing verdict line removed."""
    return _TRAILING_VERDICT_RE.sub("", (reasoning or "").rstrip()).rstrip()


def debate_transcript_document(
    transcript: list[dict[str, Any]], verdict: str
) -> dict[str, Any]:
    """Project a debate transcript onto the published exemplar's shape.

    Figure A.17 prints a turn-by-turn exchange and closes on one
    ``Better idea: <n>`` line. This returns exactly that -- each turn's
    argument and the numbered idea it favoured, plus the match's single
    verdict -- and nothing a reader never sees, so a consumer persisting
    it stores the debate rather than the loop's bookkeeping.

    Args:
        transcript: Turn entries as ``_run_debate_turn`` records them.
        verdict: The whole match's verdict number ("1" or "2").

    Returns:
        ``{"verdict": str, "turns": [{"turn", "favored", "text",
        "first"}]}`` -- ``favored`` in the match's canonical numbering and
        ``first`` naming the idea that turn's own text calls
        "Hypothesis 1".
    """
    return {
        "verdict": verdict,
        "turns": [
            {
                "turn": int(entry.get("turn") or index),
                "favored": _verdict_number(str(entry.get("winner") or "a")),
                "text": _turn_argument(str(entry.get("reasoning") or "")),
                "first": _presented_first(entry),
            }
            for index, entry in enumerate(transcript, 1)
        ],
    }


def _parse_verdict_line(text: str) -> str | None:
    """Parses the paper's literal verdict line from the judge's text.

    The concluding verdict wins: a rationale may quote the format before
    stating its conclusion, so matches are read last-first; a match
    immediately followed by "or" is the format quoted ("better idea: 1
    or 2"), not a decision, and is skipped (audit E17).

    Args:
        text: The judge's rationale text (its decision_summary).

    Returns:
        The presentation-order side the verdict picks ("a"/"b": the
        prompt's Hypothesis A is 1, Hypothesis B is 2), or None when no
        valid verdict line is present.
    """
    for match in reversed(list(_VERDICT_LINE_RE.finditer(text or ""))):
        if re.match(r"\s*or\b", text[match.end() :], re.IGNORECASE):
            continue
        token = match.group(1).lower()
        return {"1": "a", "2": "b"}.get(token, token)
    return None


def _parse_matchup_winner(
    response: dict[str, Any], *, fallback: str
) -> tuple[str, bool]:
    """Extracts and validates the winner side from a judge response.

    The primary verdict is the paper's literal "better idea: <1 or 2>"
    line concluding the judge's decision_summary (audit E17); the JSON
    "winner" enum is the fallback for responses without the line --
    including the deterministic offline backend, which answers in the
    JSON shape. Guards against a malformed/off-schema judgment either
    way: anything other than a valid verdict picks the caller's
    position-balanced fallback and marks the judgment invalid.

    Args:
        response: Parsed JSON response from the judge LLM call.
        fallback: Position-balanced side used for malformed output.

    Returns:
        The selected side and whether the model output was valid.
    """
    verdict = _parse_verdict_line(str(response.get("decision_summary") or ""))
    if verdict is not None:
        return verdict, True
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


def _presented_number(entry: dict[str, Any], swapped: bool) -> str:
    """Name a past turn's winner by the number *this* turn presents it as.

    ``_run_debate_turn`` records ``winner`` as the canonical, un-swapped
    side and ``winner_id`` as the Hypothesis UUID. The prompt labels its
    two sides "Hypothesis 1" and "Hypothesis 2" and nothing else, so a
    UUID names a side the judge cannot locate, and the canonical letter
    points at the wrong one whenever this turn swapped the presentation
    order (``_execute_debate_turn`` alternates it every turn).
    """
    return "1" if (entry["winner"] == "a") != swapped else "2"


def _prior_turn_order_note(entry: dict[str, Any], swapped: bool) -> str:
    """State how a quoted turn's own numbering relates to this turn's.

    ``_presented_number`` renumbers the *label*, but the turn's quoted
    text still numbers the two hypotheses in the order that turn
    presented them. Left unsaid, the label and the prose disagree on a
    swapped turn and the judge is asked to reconcile them unaided --
    production run f8db4d04 shows one trying: it overturned a prior
    verdict it read as "internally inconsistent" for attributing one
    idea's properties to the other.
    """
    if (_presented_first(entry) == "2") != swapped:
        return (
            " (that turn presented the two hypotheses in the opposite "
            "order to this turn, so where its text says 'hypothesis 1' it "
            "means this turn's hypothesis 2, and vice versa)"
        )
    return " (that turn presented them in the same order as this turn)"


def _append_debate_context(
    prompt: str, transcript: list[dict[str, Any]], *, swapped: bool = False
) -> str:
    """Append prior debate turns to the judge prompt for a follow-up turn.

    Multi-turn scientific debate: each subsequent turn re-examines the prior
    turns' reasoning before delivering a refined verdict, spending more
    test-time compute on the top-ranked comparisons (SSR §4). The turn
    figures are single-sourced from the envelope constants the judge loop
    enforces (see the module comment above).

    ``templates/ranking_debate.md`` carries ranking-05's whole debate
    procedure, on every turn; what only a follow-up turn can carry is the
    prior exchange, which is why this block exists. It repeats
    ranking-05's "Subsequent turns:" first bullet verbatim -- "Pose
    clarifying questions to address any ambiguities or uncertainties"
    (docs/CORPUS-EXTRACTION.md:1244, corpus R8-4, docs/CORPUS-STATUS.md)
    -- and restates the turn envelope, because a turn reading a
    transcript needs both aimed at that transcript; turn 1 renders no
    debate context at all.
    The judge still answers every turn against the same schema (``winner``
    plus a ``decision_summary`` ending in the literal verdict line), so
    this widens what the judge may weigh in that answer without inviting
    it to withhold one.
    """
    lines = ["\n\n## Prior Debate Turns (re-examine and refine)\n"]
    for entry in transcript:
        lines.append(
            f"- Turn {entry['turn']} favored hypothesis "
            f"{_presented_number(entry, swapped)}"
            f"{_prior_turn_order_note(entry, swapped)}: "
            f"{entry['reasoning']}\n"
        )
    lines.append(
        "\nPose clarifying questions to address any ambiguities or "
        "uncertainties. This debate typically settles in "
        f"{_RANKING_DEBATE_TYPICAL_MIN_TURNS}-"
        f"{_RANKING_DEBATE_TYPICAL_MAX_TURNS} turns and never runs past "
        f"{_RANKING_DEBATE_MAX_TURNS}. If the turns above already "
        "establish a clear preference that does not depend on which "
        "hypothesis was presented first, confirm that verdict decisively; "
        "otherwise challenge the weak arguments before deciding.\n"
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
    criteria: list[str] | None = None
    preferences: str | None = None
    # Set by ``judge_matchup`` once the turn budget is known: a
    # multi-turn matchup renders published ranking-05's debate prompt,
    # a single-turn one published ranking-04's.
    debate: bool = False


def _prompt_context(ctx: _DebateContext) -> _MatchupPromptContext:
    """Projects the debate context onto the run-level prompt context."""
    return _MatchupPromptContext(
        research_goal=ctx.research_goal,
        supervisor_guidance=ctx.supervisor_guidance,
        meta_review=ctx.meta_review,
        tool_registry=ctx.tool_registry,
        run_setup_guidance=ctx.run_setup_guidance,
        run_focus_guidance=ctx.run_focus_guidance,
        criteria=ctx.criteria,
        preferences=ctx.preferences,
        debate=ctx.debate,
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
            prompt=_append_debate_context(
                turn_prompt.prompt, transcript, swapped=swapped
            ),
        )
    return turn_prompt


def _ranking_debate_consensus(
    votes: list[str], turns_run: int, turn_budget: int
) -> bool:
    """True once the debate has reached a conclusive judgment.

    Adaptive within the paper's envelope (typically 3-5 turns, max 10):
    turns alternate A/B presentation order, so two CONSECUTIVE agreeing
    votes agreed from *opposite* orders -- the position-bias-free
    evidence the debate exists to produce -- and the verdict is
    conclusive. The typical-minimum floor guarantees a real exchange
    before any consensus is honoured, and a debate that never settles
    runs to the budget (capped at the envelope maximum) and resolves by
    majority of all votes, ties through the balanced fallback.
    """
    if turns_run >= min(turn_budget, _RANKING_DEBATE_MAX_TURNS):
        return True
    if turns_run < min(_RANKING_DEBATE_TYPICAL_MIN_TURNS, turn_budget):
        return False
    return len(votes) >= 2 and votes[-1] == votes[-2]


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
    the matchup was budgeted, since a conclusive consensus stops the debate
    early (see ``_ranking_debate_consensus``). It is persisted as provenance
    and metered as the matchup's LLM spend, so reporting the budget would
    overstate both.
    """
    turns = len(votes)
    winner = "a" if votes.count("a") > votes.count("b") else "b"
    if votes.count("a") == votes.count("b"):
        winner = run.fallback
        record_deterministic_fallback(model_name, "ranking_tied_votes")

    response["debate_turns"] = turns
    response["debate_transcript"] = run.transcript
    # The published closing line's own number, resolved here where the
    # canonical winner is known. The transcript itself stays as recorded;
    # ``debate_transcript_document`` is what shapes the two into the
    # exemplar's form, at the consumer that persists it.
    response["debate_verdict"] = _verdict_number(winner)
    response["judge_model"] = model_name
    response["consensus_votes"] = votes
    response["position_balanced"] = turns > 1
    response["invalid_output_fallback"] = not all(
        turn["valid_output"] for turn in run.transcript
    )
    return winner

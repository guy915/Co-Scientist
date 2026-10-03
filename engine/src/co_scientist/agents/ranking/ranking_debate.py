"""Pairwise tournament debates, verdict projection and Elo updates."""

import asyncio
import dataclasses
import hashlib
import logging
import re
import statistics
import weakref
from typing import Any, Final, NamedTuple

from co_scientist.agents.reflection.review_gate import (
    mature_review_summary,
)
from co_scientist.constants import (
    ELO_K_ANNEALED_MINIMUM,
    ELO_K_ANNEALING_HALF_LIFE,
    # ELO_K_FACTOR bounds how much a single matchup can move a rating;
    # ELO_UPSET_MARGIN is the pre-match gap that makes a win an "upset".
    ELO_K_FACTOR,
    ELO_MARGIN_MULTIPLIER_CAP,
    ELO_MARGIN_VICTORY_SCALE,
    ELO_UPSET_MARGIN,
    LOW_TEMPERATURE,
    RANKING_WAVE_MIN_SIZE,
    RANKING_WAVE_SIZE,
    SINGLE_TURN_DEBATE_TURNS,
    THINKING_MAX_TOKENS,
    truncate,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
    indexed_prompt_name,
    record_deterministic_fallback,
)
from co_scientist.models import (
    ExecutionMetrics,
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    phase_message,
)
from co_scientist.prompts import (
    PromptRunContext,
    RankingSide,
    get_ranking_prompt,
)
from co_scientist.schemas.review import RANKING_COMPARISON_CRITERIA

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _MatchupPromptContext:
    """Run-level context shared by every ranking-matchup prompt.

    These are set earlier in the workflow and threaded unchanged into each
    pairing, independent of which two hypotheses are being compared.
    """

    research_goal: str
    supervisor_guidance: dict[str, Any] | None = None
    meta_review: dict[str, Any] | None = None
    tool_registry: Any | None = None
    run_setup_guidance: str | None = None
    run_focus_guidance: str | None = None
    criteria: list[str] | None = None
    preferences: str | None = None
    # Which published prompt this matchup renders: ranking-05's
    # simulated scientific debate for a top-ranked multi-turn matchup,
    # ranking-04's single-shot comparison otherwise.
    debate: bool = False


def _review_summary(hypothesis: Hypothesis) -> dict[str, Any] | None:
    """Extracts the latest review's scores for a matchup prompt.

    Narrower than Hypothesis.review_summary(): the judge only needs the
    numeric scores, and this is the run's highest-volume call (O(n^2) per
    cycle), so the narrative fields are dropped to keep each prompt terse.

    Args:
        hypothesis: Hypothesis to summarize

    Returns:
        Review summary dict, or None if the hypothesis has no reviews
    """
    summary = hypothesis.review_summary()
    if summary is None:
        return None
    return {
        "scores": summary["scores"],
        "overall_score": summary["overall_score"],
    }


def _ranking_side(hypothesis: Hypothesis) -> RankingSide:
    """Project one idea's review and evidence into the judge's input."""
    return RankingSide(
        text=hypothesis.text,
        review=_review_summary(hypothesis),
        reflection_notes=hypothesis.reflection_notes,
        deep_verification=hypothesis.deep_verification_summary(),
        mature_reviews=mature_review_summary(hypothesis.enrichments),
    )


def _build_matchup_prompt(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    context: _MatchupPromptContext,
) -> tuple[str, dict[str, Any] | None, str | None, str | None]:
    """Render the comparison prompt with each idea's actual review evidence."""
    prompt, schema = get_ranking_prompt(
        research_goal=context.research_goal,
        side_a=_ranking_side(hypothesis_a),
        side_b=_ranking_side(hypothesis_b),
        context=PromptRunContext(
            supervisor_guidance=context.supervisor_guidance,
            meta_review=context.meta_review,
            tool_registry=context.tool_registry,
            run_setup_guidance=context.run_setup_guidance,
            run_focus_guidance=context.run_focus_guidance,
            preferences=context.preferences,
            criteria=context.criteria,
        ),
        debate=context.debate,
    )
    return (
        prompt,
        schema,
        hypothesis_a.reflection_notes,
        hypothesis_b.reflection_notes,
    )


# The paper's tournament-debate turn envelope (SSR note 9.3): the panel
# discussion "typically rang[es] from 3 to 5, with a maximum of 10" and
# ends with a conclusive judgment once sufficient depth is reached. These
# live here, not in constants/tournament.py, because the judge loop
# (ranking_debate.py) and the follow-up-turn prose in
# ``_append_debate_context`` must share a single source -- the panel paces
# itself against whatever number it is told, so a stale figure reads as a
# real instruction. constants/tournament.py keeps the values that size the
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
    """Only follow-up turns can re-examine prior reasoning."""
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


# The K-annealing and margin-scaling knobs are local reconstruction choices
# (paper-unspecified; see constants.tournament for each one's rationale).
# Imported from their home module rather than the constants re-export so the
# tournament-shaping values stay the sole subject of that file.

# Judge confidence levels mapped to a fraction of a full victory margin.
# The judge reports a verdict plus confidence rather than scores, so this is
# the margin-of-victory reconstruction's signal (see ELO_MARGIN_VICTORY_SCALE
# in constants.tournament). Unrecognized values score no margin at all.
_CONFIDENCE_MARGINS = {"high": 1.0, "medium": 0.5}


def annealed_k_factor(
    base_k_factor: int,
    matches_played: int,
    half_life: int | None = None,
) -> int:
    """Return a hypothesis's annealed K-factor from its career match count.

    Local reconstruction choice (paper-unspecified): the reference corpus
    documents a per-hypothesis phase schedule in which K shrinks as a
    hypothesis accumulates matches. This reconstruction halves K once per
    ``half_life`` matches already played, floored so a rating never fully
    freezes. Defaults to the fixed ``base_k_factor`` -- 0 (or a negative)
    half-life disables annealing entirely, preserving historical ratings.

    Args:
        base_k_factor: The run's configured K-factor (the value annealing
            decays from).
        matches_played: Career matches the hypothesis played before this
            match (its win + loss record).
        half_life: Matches per halving; None reads the module constant.

    Returns:
        The effective K-factor for this side of the matchup, at least
        ``ELO_K_ANNEALED_MINIMUM`` when annealing is active.
    """
    if half_life is None:
        half_life = ELO_K_ANNEALING_HALF_LIFE
    if half_life <= 0 or matches_played <= 0:
        return base_k_factor
    halvings = matches_played // half_life
    annealed = base_k_factor / (2**halvings)
    return max(ELO_K_ANNEALED_MINIMUM, int(annealed))


def margin_scaled_k_factor(
    base_k_factor: int,
    confidence: str | None,
    scale: float | None = None,
) -> int:
    """Scale a K-factor by how decisive the judge called its verdict.

    Local reconstruction choice (paper-unspecified): the reference corpus
    scales K by the victory margin between the sides. This tournament's
    judge reports confidence instead of scores, so the margin is mapped from
    confidence (High full, Medium half, otherwise none) and K grows by
    ``scale * margin`` times the base, capped at ``ELO_MARGIN_MULTIPLIER_CAP``
    times it. Defaults to the fixed ``base_k_factor`` -- a 0.0 (or negative)
    scale disables the scaling entirely, preserving historical ratings.

    Args:
        base_k_factor: The K-factor to scale (typically the annealed one).
        confidence: The judge's confidence level for the verdict, if any.
        scale: Margin-of-victory sensitivity; None reads the module
            constant.

    Returns:
        The margin-scaled K-factor, never below ``base_k_factor``.
    """
    if scale is None:
        scale = ELO_MARGIN_VICTORY_SCALE
    if scale <= 0 or not confidence:
        return base_k_factor
    margin = _CONFIDENCE_MARGINS.get(confidence.strip().lower(), 0.0)
    if margin <= 0:
        return base_k_factor
    multiplier = min(ELO_MARGIN_MULTIPLIER_CAP, 1.0 + scale * margin)
    return int(base_k_factor * multiplier)


def effective_k_factor(
    base_k_factor: int,
    matches_played: int,
    confidence: str | None = None,
) -> int:
    """Return one side's effective K for a match: annealed, then scaled.

    Composes the two local reconstruction knobs (both off by default, so the
    result is exactly ``base_k_factor`` unless a deployment opts in).
    Annealing goes first: it models how calibrated the hypothesis's rating
    already is; the margin multiplier then expresses how decisive this
    particular verdict was.

    Args:
        base_k_factor: The run's configured K-factor.
        matches_played: Career matches this side played before the match.
        confidence: The judge's confidence level for the verdict, if any.

    Returns:
        The K-factor this side's rating update is scaled by.
    """
    annealed = annealed_k_factor(base_k_factor, matches_played)
    return margin_scaled_k_factor(annealed, confidence)


def calculate_elo_update(
    winner_elo: int,
    loser_elo: int,
    k_factor: int = ELO_K_FACTOR,
    *,
    loser_k_factor: int | None = None,
) -> tuple[int, int]:
    """Calculates updated Elo ratings for winner and loser.

    Args:
        winner_elo: Current Elo rating of winner
        loser_elo: Current Elo rating of loser
        k_factor: K-factor for Elo calculation (default 24)
        loser_k_factor: Optional distinct K-factor for the loser's update.
            Defaults to ``k_factor``: one shared K is the historical
            behavior. A distinct value lets a per-side schedule (K-factor
            annealing) weight the two updates differently; with the two
            K-factors apart, the update is no longer exactly point-
            conserving before truncation.

    Returns:
        Tuple of (new_winner_elo, new_loser_elo)
    """
    loser_k = k_factor if loser_k_factor is None else loser_k_factor
    # Calculate expected scores
    # Standard Elo expected-score formula: each side's probability of
    # winning given the current rating gap, on the logistic curve with a
    # 400-point scale (a 400-point gap implies a 10x win-odds ratio). The
    # two expected scores always sum to 1.
    expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_loser = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))

    # Calculate new ratings
    # Rating update: actual score (1 for the winner, 0 for the loser) minus
    # expected score, scaled by k_factor. An upset (low-rated hypothesis
    # beats a high-rated one) has expected_winner near 0, so the winner
    # gains close to the full k_factor; an expected win moves ratings only
    # slightly.
    new_winner_elo = winner_elo + k_factor * (1 - expected_winner)
    new_loser_elo = loser_elo + loser_k * (0 - expected_loser)

    return int(new_winner_elo), int(new_loser_elo)


def match_tier(
    winner_elo_before: int, loser_elo_before: int, confidence: str
) -> str:
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


def _format_judgment_explanation(judgment: dict[str, Any]) -> str:
    """Combine a judgment_explanation dict's truthy values into one line."""
    return " | ".join(f"{k}: {v}" for k, v in judgment.items() if v)


def _extract_criteria_comparisons(
    response: dict[str, Any],
) -> dict[str, str]:
    """Collects the judge's per-aspect assessments for the record.

    The prompt collects one comparison per published evaluation aspect
    under judgment_explanation, but nothing read them back before (audit
    E17); the match record now carries them so a verdict is inspectable
    aspect by aspect. Only the canonical keys are kept -- a
    closed schema means anything else is model invention -- and empty
    assessments are dropped.

    Args:
        response: Full judge response for one matchup.

    Returns:
        Criterion-name -> assessment, possibly empty.
    """
    explanation = response.get("judgment_explanation")
    if not isinstance(explanation, dict):
        return {}
    return {
        name: str(explanation[name])
        for name in RANKING_COMPARISON_CRITERIA
        if explanation.get(name)
    }


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


def _compute_elo_update(
    winner_hyp: Hypothesis,
    loser_hyp: Hypothesis,
    k_factor: int | None,
    confidence: str | None = None,
) -> tuple[int, int]:
    """Computes and applies the post-match Elo ratings, logging the update.

    Mutates winner_hyp/loser_hyp's elo_rating and win/loss counters in
    place. Each side's update is scaled by its own effective K-factor
    (``ranking_elo.effective_k_factor``): the K-annealing and margin-scaling
    reconstruction knobs, both off by default, so with them off both sides
    use exactly the run's configured K and the update is the historical one.
    """
    base_k = k_factor if k_factor is not None else ELO_K_FACTOR
    winner_k = effective_k_factor(base_k, winner_hyp.total_matches, confidence)
    loser_k = effective_k_factor(base_k, loser_hyp.total_matches, confidence)
    new_winner_elo, new_loser_elo = calculate_elo_update(
        winner_elo=winner_hyp.elo_rating,
        loser_elo=loser_hyp.elo_rating,
        k_factor=winner_k,
        loser_k_factor=loser_k,
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
    return new_winner_elo, new_loser_elo


def _resolve_matchup_sides(
    hyp_a: Hypothesis, hyp_b: Hypothesis, winner: str
) -> tuple[Hypothesis, Hypothesis]:
    """Resolves (winner, loser) based on the judge's "a"/"b" side."""
    return (hyp_a, hyp_b) if winner == "a" else (hyp_b, hyp_a)


def _apply_matchup_elo(
    hyp_a: Hypothesis,
    hyp_b: Hypothesis,
    winner: str,
    *,
    k_factor: int | None = None,
    confidence: str | None = None,
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
        confidence: The judge's confidence level for the verdict, if any.
            Feeds only the margin-scaling reconstruction knob (off by
            default), so it is inert unless that knob is enabled.

    Returns:
        The pre/post Elo ratings for the winner and loser.
    """
    winner_hyp, loser_hyp = _resolve_matchup_sides(hyp_a, hyp_b, winner)
    old_winner_elo = winner_hyp.elo_rating
    old_loser_elo = loser_hyp.elo_rating

    new_winner_elo, new_loser_elo = _compute_elo_update(
        winner_hyp, loser_hyp, k_factor, confidence
    )

    return _MatchupOutcome(
        winner_hyp,
        loser_hyp,
        old_winner_elo,
        new_winner_elo,
        old_loser_elo,
        new_loser_elo,
    )


def _debate_provenance_fields(
    response: dict[str, Any], winner: str
) -> dict[str, Any]:
    """Extracts one matchup's debate provenance for its detail dict.

    Depth (1 = single-turn comparison, >1 = multi-turn scientific debate),
    the turn-by-turn transcript, the published verdict number that closes
    it, and the judge model (Milestone 3). ``debate_verdict`` falls back
    to the winner this detail is being built with, so a response from
    before the judge recorded it still names a verdict.
    """
    return {
        "debate_turns": response.get("debate_turns", 1),
        "debate_transcript": response.get("debate_transcript", []),
        "debate_verdict": response.get("debate_verdict")
        or _verdict_number(winner),
        "judge_model": response.get("judge_model"),
        "consensus_votes": response.get("consensus_votes", [winner]),
        "position_balanced": response.get("position_balanced", False),
        "invalid_output_fallback": response.get(
            "invalid_output_fallback", False
        ),
    }


def _elo_transition_fields(outcome: _MatchupOutcome) -> dict[str, Any]:
    """Extracts the pre/post Elo fields for one matchup's detail dict."""
    return {
        "winner_elo_before": outcome.winner_elo_before,
        "winner_elo_after": outcome.winner_elo_after,
        "loser_elo_before": outcome.loser_elo_before,
        "loser_elo_after": outcome.loser_elo_after,
    }


def _build_matchup_detail(
    pair: tuple[Hypothesis, Hypothesis],
    winner: str,
    response: dict[str, Any],
    outcome: _MatchupOutcome,
    iteration: int,
) -> dict[str, Any]:
    """Builds one matchup's detail dict for the UI's tournament view.

    The two sides arrive as one pairing rather than two arguments so the
    cycle fits within the five-argument ceiling; the pairing is what both
    execution paths already hold (the durable wave judges a list of them).

    Args:
        pair: The pairing judged, as (side a, side b).
        winner: Side the judge picked, "a" or "b".
        response: Full judge response for this matchup.
        outcome: Elo outcome produced by _apply_matchup_elo.
        iteration: Run cycle this matchup was judged in. Stamped here, at
            the one place a detail is built, because it is the only moment
            the cycle is still known: the drain persists the accumulated
            matchups of every cycle at once from the final state, so a
            match that did not carry its own iteration was written as
            iteration 0 -- which is what every match of every run was
            until this field existed.

    Returns:
        Matchup detail dict for this pairing, for the UI's "Performance
        against other ideas" view. ``criteria_comparisons`` carries the
        judge's per-aspect assessments (audit E17).
    """
    hyp_a, hyp_b = pair
    return {
        "iteration": int(iteration),
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
        "criteria_comparisons": _extract_criteria_comparisons(response),
        **_debate_provenance_fields(response, winner),
        **_elo_transition_fields(outcome),
    }


def _ranking_metrics_update(
    matches_judged: int, total_llm_calls: int | None
) -> ExecutionMetrics:
    """Builds the ranking_node metrics delta (llm calls + tournament count).

    Counted in matches actually judged, never in rounds the tournament was
    offered. ``tournaments_count`` is the run's whole-run consumption meter
    (``ranking_lifecycle.consumed_tournament_rounds``, whose own contract is
    "matches this run has already judged"), and a tournament stops early
    whenever the pool's distinct pairs run out before the budget does.
    Charging the offered count bills the run for matches nobody judged:
    production extended run bc77950f entered its first tournament with four
    rankable ideas against a 20-round budget, judged the six distinct pairs
    those four admit, and was charged 20 -- spending 70% of the whole-run
    allowance before evolution had added an idea. Every later cycle then ran
    on the coverage floor alone, which funds only ideas that have never
    played, so the run finished with 23 matches over 20 ideas and an Elo
    spread of 1165-1224.

    A multi-turn debate makes several judge calls per match, so llm_calls is
    the summed turn count, not the match count; it defaults to one call per
    match when the caller has no summed count.
    """
    llm_calls = (
        total_llm_calls if total_llm_calls is not None else matches_judged
    )
    metrics = create_metrics_update(
        deltas=MetricDeltas(llm_calls=llm_calls, tournaments=matches_judged)
    )
    logger.debug(
        "ranking node creating metrics delta: tournaments=%s, llm_calls=%s",
        matches_judged,
        llm_calls,
    )
    return metrics


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
        tournament_rounds: Rounds the tournament was offered; reported only
            as the allowance the pass ran against.
        total_llm_calls: Total judge LLM calls (summed over debate turns);
            defaults to one call per match when omitted.

    Returns:
        The ranking_node state delta dictionary. Merged back into
        WorkflowState by the graph runner: hypotheses carries forward with
        updated Elo/win/loss fields for downstream nodes (e.g. meta-review,
        evolve), tournament_matchups feeds the UI's "Performance against
        other ideas" view, and metrics/messages accumulate via their
        respective reducers rather than overwriting prior state.

    Everything counted here counts judged matches, not offered rounds; see
    ``_ranking_metrics_update`` for what the two numbers diverging cost.
    """
    matches_judged = len(matchup_details)
    metrics = _ranking_metrics_update(matches_judged, total_llm_calls)

    return {
        "hypotheses": hypotheses,  # Now sorted by Elo rating
        "tournament_matchups": matchup_details,
        "metrics": metrics,
        "messages": phase_message(
            "ranking",
            f"Judged {matches_judged} of {tournament_rounds} tournament rounds",
            rounds=matches_judged,
            top_elo=hypotheses[0].elo_rating,
        ),
    }


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
    from co_scientist.llm import rate_limited_attempt_count

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
    if not valid_output:
        record_deterministic_fallback(ctx.model_name, "ranking_invalid_turn")
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
    """Turns must be serial: each judge re-examines the prior transcript."""
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

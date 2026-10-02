"""Tests for the tournament debate judge (Milestone 3).

Paper invariant (SSR §4, §12): top-ranked comparisons run a multi-turn
scientific debate; lower-ranked comparisons run a single-turn comparison.
The multi-turn loop is adaptive within the paper's envelope (typically
3-5 turns, max 10 -- SSR note 9.3): it settles on a position-balanced
consensus and caps at the envelope maximum. Both end in a winner verdict,
and the complete debate turns plus provenance are persisted on the
matchup detail.
"""

import pathlib
import re
from typing import Any

import pytest

from co_scientist.agents.ranking import ranking_debate
from co_scientist.agents.ranking.ranking_debate import (
    _RANKING_DEBATE_MAX_TURNS,
    _DebateContext,
    _matchup_debate_turns,
    _median_elo,
    judge_matchup,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _append_debate_context,
)
from co_scientist.constants import SINGLE_TURN_DEBATE_TURNS
from tests._state import make_hypothesis


def test_median_elo_of_pool() -> None:
    """Median Elo is computed over the pool (even and odd sizes)."""
    a = make_hypothesis(text="a")
    b = make_hypothesis(text="b")
    c = make_hypothesis(text="c")
    a.elo_rating, b.elo_rating, c.elo_rating = 1000, 1200, 1400
    assert _median_elo([a, b, c]) == 1200
    assert _median_elo([a, c]) == 1200.0


def test_top_ranked_matchup_budgets_the_envelope_maximum() -> None:
    """A top-ranked matchup budgets the envelope max; the loop adapts.

    The depth handed to the judge is a ceiling (paper: max 10), not a
    quota -- consensus stops the debate early (finding E13).
    """
    top = make_hypothesis(text="top")
    low = make_hypothesis(text="low")
    top.elo_rating, low.elo_rating = 1400, 1000
    assert _matchup_debate_turns(top, low, median_elo=1200.0) == (
        _RANKING_DEBATE_MAX_TURNS
    )


def test_lower_ranked_matchup_uses_single_turn() -> None:
    """A matchup between two below-median hypotheses uses single-turn."""
    a = make_hypothesis(text="a")
    b = make_hypothesis(text="b")
    a.elo_rating, b.elo_rating = 1000, 1100
    assert (
        _matchup_debate_turns(a, b, median_elo=1200.0)
        == SINGLE_TURN_DEBATE_TURNS
    )


async def test_judge_semaphore_admits_a_whole_wave() -> None:
    """The judge bound must not be narrower than the wave it bounds.

    One durable task judges a whole wave concurrently. A semaphore smaller
    than the wave silently splits it into batches, so the task spends the
    wall time of several sequential rounds while still looking like one
    wide wave -- the exact serialization the wave exists to remove.
    """
    from co_scientist.constants import RANKING_WAVE_SIZE

    semaphore = ranking_debate._get_ranking_semaphore()

    admitted = 0
    for _ in range(RANKING_WAVE_SIZE):
        if semaphore.locked():
            break
        await semaphore.acquire()
        admitted += 1

    assert admitted == RANKING_WAVE_SIZE


def test_wave_narrows_once_the_provider_throttles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A throttled provider gets a narrower wave, not more parallel waiting.

    Beyond what the provider will serve, extra calls do not finish sooner --
    they sleep in jittered backoff, and the burst is what provoked the
    throttling to begin with.
    """
    from co_scientist.constants import RANKING_WAVE_MIN_SIZE, RANKING_WAVE_SIZE
    from co_scientist.llm.attempts import retry

    monkeypatch.setattr(retry, "_rate_limited_attempts", 0)
    assert ranking_debate.effective_ranking_wave_size() == RANKING_WAVE_SIZE

    monkeypatch.setattr(retry, "_rate_limited_attempts", 1)
    assert ranking_debate.effective_ranking_wave_size() == RANKING_WAVE_MIN_SIZE


async def test_judge_prompt_carries_scientist_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scientist's criteria govern the judge when supplied (A2/K4).

    Absent criteria must leave the prompt unchanged, so the offline
    pipeline and criteria-free runs keep their historical behavior.
    """
    prompts: list[str] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        prompts.append(str(kwargs["prompt"]))
        return {"winner": "a", "confidence_level": "High"}

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    ctx = _DebateContext(
        make_hypothesis(text="alpha"),
        make_hypothesis(text="beta"),
        "goal",
        "fake/model",
        criteria=["Cost of the experimental validation"],
    )

    await judge_matchup(ctx, debate_turns=1)

    assert "Scientist Evaluation Criteria (governing)" in prompts[0]
    assert "Cost of the experimental validation" in prompts[0]

    prompts.clear()
    plain_ctx = _DebateContext(
        make_hypothesis(text="alpha"),
        make_hypothesis(text="beta"),
        "goal",
        "fake/model",
    )
    await judge_matchup(plain_ctx, debate_turns=1)

    assert "Scientist Evaluation Criteria" not in prompts[0]
    assert "{{MISSING" not in prompts[0]


async def test_judge_prompt_carries_scientist_preferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Published ranking-04/05 both surface {preferences} to the judge (MP-6).

    Threaded the same way evolution maps the paper's {preferences} slot
    (commits 563e9501/8ee02acc): our ``preferences: str`` field, formatted
    by ``format_preferences``. This is additional to, not a replacement
    for, the scientist-supplied ``criteria`` list above (finding A2/K4).
    """
    prompts: list[str] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        prompts.append(str(kwargs["prompt"]))
        return {"winner": "a", "confidence_level": "High"}

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    ctx = _DebateContext(
        make_hypothesis(text="alpha"),
        make_hypothesis(text="beta"),
        "goal",
        "fake/model",
        preferences="prioritize wet-lab feasibility over novelty",
    )

    await judge_matchup(ctx, debate_turns=1)

    assert "prioritize wet-lab feasibility over novelty" in prompts[0]

    prompts.clear()
    plain_ctx = _DebateContext(
        make_hypothesis(text="alpha"),
        make_hypothesis(text="beta"),
        "goal",
        "fake/model",
    )
    await judge_matchup(plain_ctx, debate_turns=1)

    assert "Focus on novelty, testability, and potential impact." in prompts[0]
    assert "{{MISSING" not in prompts[0]


async def test_followup_turns_carry_the_envelope_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Follow-up judge turns state the envelope the loop enforces (E13).

    The figures are asserted against the same constants the loop uses,
    so a drift between prose and behavior fails here.
    """
    from co_scientist.agents.ranking.ranking_debate_turns import (
        _RANKING_DEBATE_MAX_TURNS as MAX_TURNS,
    )
    from co_scientist.agents.ranking.ranking_debate_turns import (
        _RANKING_DEBATE_TYPICAL_MAX_TURNS as TYPICAL_MAX,
    )
    from co_scientist.agents.ranking.ranking_debate_turns import (
        _RANKING_DEBATE_TYPICAL_MIN_TURNS as TYPICAL_MIN,
    )

    prompts: list[str] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        prompts.append(str(kwargs["prompt"]))
        return {"winner": "a", "confidence_level": "High"}

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    ctx = _DebateContext(
        make_hypothesis(text="alpha"),
        make_hypothesis(text="beta"),
        "goal",
        "fake/model",
    )

    await judge_matchup(ctx, debate_turns=MAX_TURNS)

    # The first turn carries no prior context; every follow-up does.
    assert "Prior Debate Turns" not in prompts[0]
    # ...but turn 1 does see ranking-05's own debate procedure, which
    # before the template split reached the judge on no turn at all.
    assert "Debate procedure:" in prompts[0]
    assert "Turn 1: begin with a concise summary" in prompts[0]
    guidance = (
        f"typically settles in {TYPICAL_MIN}-{TYPICAL_MAX} turns and "
        f"never runs past {MAX_TURNS}"
    )
    assert all(guidance in prompt for prompt in prompts[1:])


# --- "Pose clarifying questions" (corpus R8-4) --------------------------

_CORPUS_EXTRACTION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "docs"
    / "CORPUS-EXTRACTION.md"
)


def _published_subsequent_turns_first_bullet() -> str:
    """Reads ranking-05's "Subsequent turns:" first bullet off disk.

    ``docs/CORPUS-EXTRACTION.md`` is committed repo content, not the
    optional ``references/`` corpus this module must never touch (see
    ``_published_corpus.py``), so there is nothing to skip -- it is always
    present in any checkout that has this test (same reasoning as
    ``app/tests/test_published_plan_config_criteria.py``, which reads the
    same file). Anchored on the literal "Subsequent turns:" header so this
    cannot match generation-02's near-duplicate sibling instruction
    ("Pose clarifying questions if ambiguities or uncertainties arise.",
    docs/CORPUS-EXTRACTION.md:1099) elsewhere in the same appendix.

    Returns:
        The bullet's text, verbatim, without its leading "* " marker.
    """
    text = _CORPUS_EXTRACTION.read_text(encoding="utf-8")
    match = re.search(r"^Subsequent turns:\n {4}\* (.+)$", text, re.M)
    assert match is not None, (
        "docs/CORPUS-EXTRACTION.md lost ranking-05's 'Subsequent turns:' bullet"
    )
    return match.group(1)


def test_followup_turns_pose_clarifying_questions() -> None:
    """Follow-up turns carry ranking-05's own first "Subsequent turns" ask.

    Read directly out of ``docs/CORPUS-EXTRACTION.md`` rather than
    restated inline, so a future edit to that appendix cannot drift from
    this assertion unnoticed.
    """
    instruction = _published_subsequent_turns_first_bullet()
    entry: dict[str, Any] = {"turn": 1, "winner": "a", "reasoning": "r"}
    appended = _append_debate_context("base prompt", [entry])
    assert instruction in appended


def test_a_prior_turn_judged_the_other_way_round_says_so() -> None:
    """The judge is told when a quoted turn used the opposite numbering.

    A prior turn's text numbers the two hypotheses in the order that turn
    presented them, so on a swapped follow-up turn the quoted prose and
    the block's own "favored hypothesis N" label disagree. Production run
    f8db4d04 shows the judge trying to reconcile them unaided: "I must
    overturn the Turn 1 verdict, which was internally inconsistent (it
    attributed colchicine's ... properties to 'Hypothesis 1' when those
    belong to Hypothesis 2)".
    """
    entry = {
        "turn": 1,
        "winner": "a",
        "reasoning": "Hypothesis 1 states the pilot readout.",
        "presentation_order": "ab",
    }

    opposite = _append_debate_context("base", [entry], swapped=True)
    same = _append_debate_context("base", [entry], swapped=False)

    assert "opposite order" in opposite
    assert "opposite order" not in same
    assert "same order" in same

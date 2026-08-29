"""Tests for the tournament debate judge (Milestone 3).

Paper invariant (SSR §4, §12): top-ranked comparisons run a multi-turn
scientific debate; lower-ranked comparisons run a single-turn comparison.
The multi-turn loop is adaptive within the paper's envelope (typically
3-5 turns, max 10 -- SSR note 9.3): it settles on a position-balanced
consensus and caps at the envelope maximum. Both end in a winner verdict,
and the complete debate turns plus provenance are persisted on the
matchup detail.
"""

from typing import Any

import pytest

from co_scientist.agents.ranking import ranking_debate
from co_scientist.agents.ranking.ranking_debate import (
    _RANKING_DEBATE_MAX_TURNS,
    _balanced_invalid_fallback,
    _DebateContext,
    _matchup_debate_turns,
    _median_elo,
    judge_matchup,
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


def _stub_turn_counter(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Patch call_llm_json to count invocations and return a valid judgment."""
    calls: list[int] = []

    async def fake(**_: Any) -> dict[str, Any]:
        calls.append(1)
        return {
            "winner": "a",
            "decision_summary": f"turn {len(calls)} reasoning",
            "confidence_level": "High",
        }

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    return calls


async def test_multi_turn_debate_runs_multiple_calls_and_persists_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A multi-turn debate makes one LLM call per turn and records each.

    The scripted raw winners flip with the presentation order, so every
    turn votes for the same hypothesis; the unanimous consensus settles
    the debate at the envelope's typical-minimum floor.
    """
    calls = _stub_fixed_winners(monkeypatch, ["a", "b", "a"])
    a = make_hypothesis(text="alpha hypothesis")
    b = make_hypothesis(text="beta hypothesis")

    ctx = _DebateContext(a, b, "goal", "fake/model")
    winner, response = await judge_matchup(
        ctx, debate_turns=_RANKING_DEBATE_MAX_TURNS
    )

    assert winner == "a"
    assert len(calls) == 3
    assert response["debate_turns"] == 3
    transcript = response["debate_transcript"]
    assert len(transcript) == 3
    assert [t["turn"] for t in transcript] == [1, 2, 3]
    # Alternating presentation orders: the agreement is position-bias-free.
    assert [t["presentation_order"] for t in transcript] == [
        "ab",
        "ba",
        "ab",
    ]
    assert response["consensus_votes"] == ["a", "a", "a"]
    assert response["position_balanced"] is True
    assert response["judge_model"] == "fake/model"


def _stub_fixed_winners(
    monkeypatch: pytest.MonkeyPatch, raw_winners: list[str]
) -> list[int]:
    """Patch call_llm_json to return a scripted raw winner per turn."""
    calls: list[int] = []

    async def fake(**_: Any) -> dict[str, Any]:
        raw = raw_winners[len(calls)]
        calls.append(1)
        return {
            "winner": raw,
            "decision_summary": f"turn {len(calls)} reasoning",
            "confidence_level": "High",
        }

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    return calls


async def test_consensus_ends_the_debate_long_before_its_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A conclusive consensus retires the rest of the envelope budget.

    Every scripted turn votes the same hypothesis (raw winners flip with
    the alternating presentation order), so the debate settles at the
    typical-minimum floor -- three turns -- rather than spending the
    ten-turn ceiling. Two consecutive agreeing votes are agreement from
    opposite A/B orders, the position-bias-free consensus the loop waits
    for (findings E13/E16).
    """
    calls = _stub_fixed_winners(monkeypatch, ["a", "b", "a", "b", "a"])
    ctx = _DebateContext(
        make_hypothesis(text="alpha"),
        make_hypothesis(text="beta"),
        "goal",
        "fake/model",
    )

    winner, response = await judge_matchup(
        ctx, debate_turns=_RANKING_DEBATE_MAX_TURNS
    )

    assert winner == "a"
    assert len(calls) == 3
    assert response["consensus_votes"] == ["a", "a", "a"]
    # Provenance and the LLM meter report the turns judged, not the budget.
    assert response["debate_turns"] == 3
    assert len(response["debate_transcript"]) == 3
    # Consecutive turns alternated presentation order, so the consensus is
    # position-balanced despite stopping early.
    assert response["position_balanced"] is True


async def test_contested_debate_extends_past_the_typical_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A judge that keeps flipping with the order runs deeper.

    The scripted votes alternate sides, so no two consecutive turns ever
    agree and consensus is never reached: the debate runs its whole
    budget and resolves through the identity-stable balanced fallback,
    exactly as the pre-envelope tie did -- just deeper in the envelope.
    """
    alpha = make_hypothesis(text="alpha")
    beta = make_hypothesis(text="beta")
    # Raw "a" every turn votes alternately a/b/a/b... under the swap.
    calls = _stub_fixed_winners(monkeypatch, ["a"] * 10)
    ctx = _DebateContext(alpha, beta, "goal", "fake/model")

    winner, response = await judge_matchup(
        ctx, debate_turns=_RANKING_DEBATE_MAX_TURNS
    )

    assert len(calls) == _RANKING_DEBATE_MAX_TURNS
    assert response["debate_turns"] == _RANKING_DEBATE_MAX_TURNS
    assert response["consensus_votes"] == ["a", "b"] * 5
    assert winner == _balanced_invalid_fallback(alpha, beta, None)
    assert response["invalid_output_fallback"] is False


async def test_split_turns_still_run_the_tiebreaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A split verdict spends its whole budget; the consensus rule adapts.

    Depth is passed explicitly so this pins the loop at a caller-chosen
    budget: a one-all split never puts two consecutive votes on one side,
    so every budgeted turn runs and the majority picks the winner.
    """
    calls = _stub_fixed_winners(monkeypatch, ["a", "a", "a"])
    ctx = _DebateContext(
        make_hypothesis(text="alpha"),
        make_hypothesis(text="beta"),
        "goal",
        "fake/model",
    )

    _, response = await judge_matchup(ctx, debate_turns=3)

    assert len(calls) == 3
    assert response["consensus_votes"] == ["a", "b", "a"]
    assert response["debate_turns"] == 3


async def test_a_split_at_the_configured_depth_falls_back_balanced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At an even depth a tie resolves through the balanced fallback.

    This is what the third turn used to settle. The fallback is stable for a
    given pair and alternates with the matchup index, so a tie costs the
    tournament nothing systematic in either hypothesis's favour.
    """
    _stub_fixed_winners(monkeypatch, ["a", "a"])
    alpha = make_hypothesis(text="alpha")
    beta = make_hypothesis(text="beta")
    ctx = _DebateContext(alpha, beta, "goal", "fake/model")

    winner, response = await judge_matchup(ctx, debate_turns=2)

    # Turn 2 is presented swapped, so a raw "a" both times is a one-all split.
    assert response["consensus_votes"] == ["a", "b"]
    assert winner == _balanced_invalid_fallback(alpha, beta, None)


async def test_single_turn_debate_runs_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single-turn comparison makes exactly one LLM call."""
    calls = _stub_turn_counter(monkeypatch)
    a = make_hypothesis(text="alpha")
    b = make_hypothesis(text="beta")

    ctx = _DebateContext(a, b, "goal", "fake/model")
    _, response = await judge_matchup(ctx, debate_turns=1)

    assert len(calls) == 1
    assert response["debate_turns"] == 1
    assert len(response["debate_transcript"]) == 1


async def test_single_turn_alternates_presentation_order_across_matchups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-turn comparisons must not always present hypothesis A first.

    A single-turn matchup only runs turn 0, so with a fixed starting order it
    would always show the A slot first and any residual positional bias in the
    judge would systematically favor it (audit E18). The starting order folds
    in the matchup index, so even/odd matchups present ab/ba.
    """
    a = make_hypothesis(text="alpha")
    b = make_hypothesis(text="beta")

    orders = []
    for index in (0, 1, 2, 3):
        _stub_turn_counter(monkeypatch)
        ctx = _DebateContext(a, b, "goal", "fake/model", matchup_index=index)
        _, response = await judge_matchup(ctx, debate_turns=1)
        orders.append(response["debate_transcript"][0]["presentation_order"])

    assert orders == ["ab", "ba", "ab", "ba"]


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
    from co_scientist import llm_json_retry
    from co_scientist.constants import RANKING_WAVE_MIN_SIZE, RANKING_WAVE_SIZE

    monkeypatch.setattr(llm_json_retry, "_rate_limited_attempts", 0)
    assert ranking_debate.effective_ranking_wave_size() == RANKING_WAVE_SIZE

    monkeypatch.setattr(llm_json_retry, "_rate_limited_attempts", 1)
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
    guidance = (
        f"typically settles in {TYPICAL_MIN}-{TYPICAL_MAX} turns and "
        f"never runs past {MAX_TURNS}"
    )
    assert all(guidance in prompt for prompt in prompts[1:])

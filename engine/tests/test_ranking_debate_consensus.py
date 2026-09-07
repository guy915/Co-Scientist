"""Tests for the multi-turn debate loop's consensus and turn-ordering.

Split out of ``test_ranking_debate.py`` (file-length ceiling): these tests
cover how ``judge_matchup`` accumulates turns, alternates presentation
order, and settles on a winner via consensus, a split-vote tiebreak, or
the balanced fallback. See that file's module docstring for the paper
invariant (SSR §4, §12) both files pin.
"""

from typing import Any

import pytest

from co_scientist.agents.ranking import ranking_debate
from co_scientist.agents.ranking.ranking_debate import (
    _RANKING_DEBATE_MAX_TURNS,
    _balanced_invalid_fallback,
    _DebateContext,
    judge_matchup,
)
from tests._state import make_hypothesis


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

from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.ranking import ranking_debate
from co_scientist.agents.ranking.ranking_debate import (
    _RANKING_DEBATE_MAX_TURNS,
    _balanced_invalid_fallback,
    _DebateContext,
    _matchup_debate_turns,
    debate_transcript_document,
    judge_matchup,
)
from tests._state import make_hypothesis


@pytest.mark.parametrize(
    ("elos", "turns"),
    [((1400, 1000), _RANKING_DEBATE_MAX_TURNS), ((1000, 1100), 1)],
)
def test_only_top_ranked_matchups_budget_a_full_debate(
    elos: tuple[int, int], turns: int
) -> None:
    a = make_hypothesis(text="a", elo_rating=elos[0])
    b = make_hypothesis(text="b", elo_rating=elos[1])
    assert _matchup_debate_turns(a, b, median_elo=1200.0) == turns


def test_wave_narrows_once_the_provider_throttles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.constants import RANKING_WAVE_MIN_SIZE, RANKING_WAVE_SIZE
    from co_scientist.llm.attempts import retry

    monkeypatch.setattr(retry, "_rate_limited_attempts", 0)
    assert ranking_debate.effective_ranking_wave_size() == RANKING_WAVE_SIZE

    monkeypatch.setattr(retry, "_rate_limited_attempts", 1)
    assert ranking_debate.effective_ranking_wave_size() == RANKING_WAVE_MIN_SIZE


@pytest.mark.parametrize(
    ("option", "given", "marker", "default_marker"),
    [
        (
            "criteria",
            ["Cost of the experimental validation"],
            "Cost of the experimental validation",
            "Scientist Evaluation Criteria",
        ),
        (
            "preferences",
            "prioritize wet-lab feasibility over novelty",
            "prioritize wet-lab feasibility over novelty",
            "Focus on novelty, testability, and potential impact.",
        ),
    ],
)
async def test_judge_prompt_carries_scientist_criteria_and_preferences(
    monkeypatch: pytest.MonkeyPatch,
    option: str,
    given: Any,
    marker: str,
    default_marker: str,
) -> None:
    prompts: list[str] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        prompts.append(str(kwargs["prompt"]))
        return {"winner": "a", "confidence_level": "High"}

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    alpha = make_hypothesis(text="alpha")
    beta = make_hypothesis(text="beta")

    for options in ({option: given}, {}):
        ctx = _DebateContext(alpha, beta, "goal", "fake/model", **options)
        await judge_matchup(ctx, debate_turns=1)

    assert marker in prompts[0]
    assert ("Scientist Evaluation Criteria (governing)" in prompts[0]) == (
        option == "criteria"
    )
    assert (default_marker in prompts[1]) == (option == "preferences")
    assert marker not in prompts[1]
    assert not any("{{MISSING" in prompt for prompt in prompts)


def _stub_fixed_winners(
    monkeypatch: pytest.MonkeyPatch, raw_winners: list[str]
) -> list[int]:
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
    assert response["debate_turns"] == 3
    assert len(response["debate_transcript"]) == 3
    assert response["position_balanced"] is True


async def test_contested_debate_extends_past_the_typical_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = make_hypothesis(text="alpha")
    beta = make_hypothesis(text="beta")
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
    _stub_fixed_winners(monkeypatch, ["a", "a"])
    alpha = make_hypothesis(text="alpha")
    beta = make_hypothesis(text="beta")
    ctx = _DebateContext(alpha, beta, "goal", "fake/model")

    winner, response = await judge_matchup(ctx, debate_turns=2)

    assert response["consensus_votes"] == ["a", "b"]
    assert winner == _balanced_invalid_fallback(alpha, beta, None)


async def test_single_turn_alternates_presentation_order_across_matchups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = make_hypothesis(text="alpha")
    b = make_hypothesis(text="beta")

    orders = []
    for index in (0, 1, 2, 3):
        _stub_fixed_winners(monkeypatch, ["a"])
        ctx = _DebateContext(a, b, "goal", "fake/model", matchup_index=index)
        _, response = await judge_matchup(ctx, debate_turns=1)
        orders.append(response["debate_transcript"][0]["presentation_order"])

    assert orders == ["ab", "ba", "ab", "ba"]


def _entry(turn: int, winner: str, reasoning: str) -> dict[str, Any]:
    return {
        "turn": turn,
        "winner": winner,
        "winner_id": f"h-{winner}",
        "reasoning": reasoning,
        "presentation_order": "ab" if turn % 2 else "ba",
        "valid_output": True,
    }


def test_document_carries_every_turn_and_one_closing_verdict() -> None:
    transcript = [
        _entry(1, "a", "Idea 1 is better grounded. better idea: 1"),
        _entry(2, "a", "The mechanism holds up. Better idea: 2"),
    ]

    document = debate_transcript_document(transcript, "1")

    assert document["verdict"] == "1"
    assert [turn["turn"] for turn in document["turns"]] == [1, 2]
    assert [turn["favored"] for turn in document["turns"]] == ["1", "1"]
    assert document["turns"][0]["text"] == "Idea 1 is better grounded."
    assert document["turns"][1]["text"] == "The mechanism holds up."


def test_a_mid_text_verdict_mention_survives() -> None:
    transcript = [
        _entry(
            1,
            "b",
            "The panel is asked to end on better idea: 1 or 2. "
            "Idea 2 wins on feasibility.",
        )
    ]

    [turn] = debate_transcript_document(transcript, "2")["turns"]

    assert turn["text"].endswith("Idea 2 wins on feasibility.")
    assert "better idea: 1 or 2" in turn["text"]
    assert turn["favored"] == "2"

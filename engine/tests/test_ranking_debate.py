from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.ranking import ranking_debate
from co_scientist.agents.ranking.ranking_debate import (
    _RANKING_DEBATE_MAX_TURNS,
    _DebateContext,
    _matchup_debate_turns,
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


def _entry(turn: int, winner: str, reasoning: str) -> dict[str, Any]:
    return {
        "turn": turn,
        "winner": winner,
        "winner_id": f"h-{winner}",
        "reasoning": reasoning,
        "presentation_order": "ab" if turn % 2 else "ba",
        "valid_output": True,
    }

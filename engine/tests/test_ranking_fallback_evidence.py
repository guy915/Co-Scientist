"""Ranking artifacts disclose substitutions without changing their winner."""

from typing import Any

import pytest

from co_scientist.agents.ranking import ranking_debate
from co_scientist.llm_telemetry import scoped_telemetry
from co_scientist.models import Hypothesis


@pytest.mark.parametrize(
    ("answer", "turns", "expected"),
    [
        ({"winner": "invalid"}, 1, {"ranking_invalid_turn": 1}),
        ({"winner": "a"}, 2, {"ranking_tied_votes": 1}),
        ({"winner": "a"}, 1, {}),
    ],
)
async def test_judge_discloses_invalid_and_tied_decisions(
    monkeypatch: pytest.MonkeyPatch,
    answer: dict[str, Any],
    turns: int,
    expected: dict[str, int],
) -> None:
    async def completion(**kwargs: Any) -> dict[str, Any]:
        return dict(answer)

    monkeypatch.setattr(ranking_debate, "call_llm_json", completion)
    ctx = ranking_debate._DebateContext(
        Hypothesis(text="Candidate one"),
        Hypothesis(text="Candidate two"),
        "Public research goal",
        "test-model",
    )
    with scoped_telemetry("ranking") as telemetry:
        winner, response = await ranking_debate.judge_matchup(ctx, turns)
    assert winner in {"a", "b"}
    assert response["debate_turns"] == turns
    events = telemetry.snapshot().get("ranking::test-model", {})
    assert events.get("deterministic_fallbacks", {}) == expected
    assert events.get("calls", 0) == 0

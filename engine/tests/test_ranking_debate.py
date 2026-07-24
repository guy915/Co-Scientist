"""Tests for tournament debate depth (Milestone 3).

Paper invariant (SSR §4, §12): top-ranked comparisons run a multi-turn
scientific debate; lower-ranked comparisons run a single-turn comparison. Both
end in a winner verdict, and the complete debate turns plus provenance are
persisted on the matchup detail.
"""

from typing import Any

import pytest

from co_scientist.agents.ranking import ranking_debate
from co_scientist.agents.ranking.ranking_debate import (
    _DebateContext,
    _matchup_debate_turns,
    _median_elo,
    judge_matchup,
)
from co_scientist.constants import (
    MULTI_TURN_DEBATE_TURNS,
    SINGLE_TURN_DEBATE_TURNS,
)
from tests._state import make_hypothesis


def test_median_elo_of_pool() -> None:
    """Median Elo is computed over the pool (even and odd sizes)."""
    a = make_hypothesis(text="a")
    b = make_hypothesis(text="b")
    c = make_hypothesis(text="c")
    a.elo_rating, b.elo_rating, c.elo_rating = 1000, 1200, 1400
    assert _median_elo([a, b, c]) == 1200
    assert _median_elo([a, c]) == 1200.0


def test_top_ranked_matchup_uses_multi_turn() -> None:
    """A matchup with a hypothesis at/above the median uses multi-turn."""
    top = make_hypothesis(text="top")
    low = make_hypothesis(text="low")
    top.elo_rating, low.elo_rating = 1400, 1000
    assert (
        _matchup_debate_turns(top, low, median_elo=1200.0)
        == MULTI_TURN_DEBATE_TURNS
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
    """A multi-turn debate makes one LLM call per turn and records each."""
    calls = _stub_turn_counter(monkeypatch)
    a = make_hypothesis(text="alpha hypothesis")
    b = make_hypothesis(text="beta hypothesis")

    ctx = _DebateContext(a, b, "goal", "fake/model")
    winner, response = await judge_matchup(
        ctx, debate_turns=MULTI_TURN_DEBATE_TURNS
    )

    assert winner == "a"
    assert len(calls) == MULTI_TURN_DEBATE_TURNS
    assert response["debate_turns"] == MULTI_TURN_DEBATE_TURNS
    transcript = response["debate_transcript"]
    assert len(transcript) == MULTI_TURN_DEBATE_TURNS
    assert [t["turn"] for t in transcript] == [1, 2, 3]
    assert [t["presentation_order"] for t in transcript] == ["ab", "ba", "ab"]
    assert response["consensus_votes"] == ["a", "b", "a"]
    assert response["position_balanced"] is True
    assert response["judge_model"] == "fake/model"


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

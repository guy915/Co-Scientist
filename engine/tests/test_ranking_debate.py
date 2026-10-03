from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.ranking import ranking_debate
from co_scientist.agents.ranking.ranking_debate import (
    _RANKING_DEBATE_MAX_TURNS,
    _append_debate_context,
    _balanced_invalid_fallback,
    _debate_provenance_fields,
    _DebateContext,
    _matchup_debate_turns,
    _median_elo,
    debate_transcript_document,
    judge_matchup,
)
from co_scientist.constants import SINGLE_TURN_DEBATE_TURNS
from tests._state import make_hypothesis


def test_median_elo_of_pool() -> None:
    a = make_hypothesis(text="a")
    b = make_hypothesis(text="b")
    c = make_hypothesis(text="c")
    a.elo_rating, b.elo_rating, c.elo_rating = 1000, 1200, 1400
    assert _median_elo([a, b, c]) == 1200
    assert _median_elo([a, c]) == 1200.0


def test_top_ranked_matchup_budgets_the_envelope_maximum() -> None:
    top = make_hypothesis(text="top")
    low = make_hypothesis(text="low")
    top.elo_rating, low.elo_rating = 1400, 1000
    assert _matchup_debate_turns(top, low, median_elo=1200.0) == (
        _RANKING_DEBATE_MAX_TURNS
    )


def test_lower_ranked_matchup_uses_single_turn() -> None:
    a = make_hypothesis(text="a")
    b = make_hypothesis(text="b")
    a.elo_rating, b.elo_rating = 1000, 1100
    assert (
        _matchup_debate_turns(a, b, median_elo=1200.0)
        == SINGLE_TURN_DEBATE_TURNS
    )


async def test_judge_semaphore_admits_a_whole_wave() -> None:
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
    from co_scientist.constants import RANKING_WAVE_MIN_SIZE, RANKING_WAVE_SIZE
    from co_scientist.llm.attempts import retry

    monkeypatch.setattr(retry, "_rate_limited_attempts", 0)
    assert ranking_debate.effective_ranking_wave_size() == RANKING_WAVE_SIZE

    monkeypatch.setattr(retry, "_rate_limited_attempts", 1)
    assert ranking_debate.effective_ranking_wave_size() == RANKING_WAVE_MIN_SIZE


async def test_judge_prompt_carries_scientist_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    from co_scientist.agents.ranking.ranking_debate import (
        _RANKING_DEBATE_MAX_TURNS as MAX_TURNS,
    )
    from co_scientist.agents.ranking.ranking_debate import (
        _RANKING_DEBATE_TYPICAL_MAX_TURNS as TYPICAL_MAX,
    )
    from co_scientist.agents.ranking.ranking_debate import (
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

    assert "Prior Debate Turns" not in prompts[0]
    assert "Debate procedure:" in prompts[0]
    assert "Turn 1: begin with a concise summary" in prompts[0]
    guidance = (
        f"typically settles in {TYPICAL_MIN}-{TYPICAL_MAX} turns and "
        f"never runs past {MAX_TURNS}"
    )
    assert all(guidance in prompt for prompt in prompts[1:])


def test_followup_turns_pose_clarifying_questions() -> None:
    entry: dict[str, Any] = {"turn": 1, "winner": "a", "reasoning": "r"}
    appended = _append_debate_context("base prompt", [entry])
    assert "clarifying questions" in appended
    assert "ambiguities or uncertainties" in appended


def test_a_prior_turn_judged_the_other_way_round_says_so() -> None:
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


def _stub_turn_counter(monkeypatch: pytest.MonkeyPatch) -> list[int]:
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


async def test_single_turn_debate_runs_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    a = make_hypothesis(text="alpha")
    b = make_hypothesis(text="beta")

    orders = []
    for index in (0, 1, 2, 3):
        _stub_turn_counter(monkeypatch)
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


def test_each_turn_records_which_idea_it_presented_first() -> None:
    transcript = [
        _entry(1, "a", "Idea 1 is better grounded."),
        _entry(2, "a", "The mechanism holds up."),
    ]

    document = debate_transcript_document(transcript, "1")

    assert [turn["first"] for turn in document["turns"]] == ["1", "2"]


def test_a_turn_with_no_recorded_order_documents_the_canonical_one() -> None:
    entry = {"turn": 1, "winner": "a", "reasoning": "Idea 1 wins."}

    [turn] = debate_transcript_document([entry], "1")["turns"]

    assert turn["first"] == "1"


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


def test_an_empty_transcript_documents_no_turns() -> None:
    assert debate_transcript_document([], "1") == {
        "verdict": "1",
        "turns": [],
    }


def test_provenance_keeps_explicit_verdict_and_falls_back_to_winner() -> None:
    assert (
        _debate_provenance_fields({"debate_verdict": "2"}, "a")[
            "debate_verdict"
        ]
        == "2"
    )
    assert _debate_provenance_fields({}, "b")["debate_verdict"] == "2"
    assert _debate_provenance_fields({}, "a")["debate_verdict"] == "1"

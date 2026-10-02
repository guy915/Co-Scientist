"""Shared scientific contracts for graph tournaments and durable waves."""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from co_scientist.agents.ranking import (
    RankingJudgement,
    RankingMatchResult,
    TournamentGuidance,
    apply_ranking_matchup,
    build_tournament_pairings,
    finalize_ranking,
    judge_ranking_matchup,
    prepare_ranking_judging_context,
    prepare_ranking_prompt_context,
    prepare_ranking_round,
    ranking_debate,
    ranking_elo,
    remaining_ranking_rounds,
)
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models import ExecutionMetrics
from tests._state import make_hypothesis, make_review, make_state


def test_pairings_are_deterministic_and_exclude_judged_pairs() -> None:
    pool = [make_hypothesis(id=str(i), text=f"idea {i}") for i in range(5)]
    excluded = {frozenset({"0", "1"}), frozenset({"2", "3"})}
    first = build_tournament_pairings(pool, 10, "goal", 17, excluded)
    assert first == build_tournament_pairings(pool, 10, "goal", 17, excluded)
    identities = [frozenset({a.id, b.id}) for a, b in first]
    assert len(identities) == len(set(identities)) == 8
    assert not excluded.intersection(identities)


@pytest.mark.asyncio
async def test_prepare_admits_sorts_and_emits_progress() -> None:
    low = make_hypothesis(text="low", score=2, elo_rating=0)
    high = make_hypothesis(text="high", score=9, elo_rating=0)
    pool = [low, high]
    events: list[Any] = []

    async def progress(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    state = make_state(
        hypotheses=pool,
        progress_callback=progress,
        supervisor_guidance={"strategy": "test"},
        run_focus_guidance="focus",
    )
    rounds, guidance = await prepare_ranking_round(state, pool)
    assert pool == [high, low]
    assert low.elo_rating == high.elo_rating == INITIAL_ELO_RATING
    assert rounds == remaining_ranking_rounds(state, pool)
    assert guidance.supervisor_guidance == {"strategy": "test"}
    assert tuple(guidance) == ({"strategy": "test"}, None, {}, None, "focus")
    assert isinstance(guidance, TournamentGuidance)
    assert events[0][0] == "tournament_start"


def test_remaining_budget_funds_only_peer_reviewed_coverage() -> None:
    pool = [make_hypothesis(reviews=[make_review()]) for _ in range(3)]
    state = make_state(
        hypotheses=pool, metrics=ExecutionMetrics(tournaments_count=100)
    )
    assert remaining_ranking_rounds(state, pool) == 3
    for hypothesis in pool:
        hypothesis.reviews = []
    assert remaining_ranking_rounds(state, pool) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("preferences", [None, "scientist preferences"])
async def test_judging_keeps_criteria_and_explicit_preferences(
    monkeypatch: pytest.MonkeyPatch,
    preferences: str | None,
) -> None:
    from co_scientist.agents.ranking import operations

    pair = (make_hypothesis(), make_hypothesis())
    state = make_state(
        preferences="scientist preferences",
        criteria=["feasibility"],
        run_setup_guidance="setup",
        run_focus_guidance="focus",
    )
    captured: list[Any] = []

    async def judge(ctx: Any, debate_turns: int) -> tuple[str, dict[str, Any]]:
        captured.append(ctx)
        return "b", {"debate_turns": 2, "judge_model": "test"}

    monkeypatch.setattr(operations, "judge_matchup", judge)
    prompt = prepare_ranking_prompt_context(state, preferences=preferences)
    context = prepare_ranking_judging_context(prompt, list(pair))
    judgement = await judge_ranking_matchup(pair, context, 7)
    assert captured[0].criteria == ["feasibility"]
    assert captured[0].preferences == preferences
    assert captured[0].run_setup_guidance == "setup"
    assert captured[0].run_focus_guidance == "focus"
    assert captured[0].matchup_index == 7
    assert judgement.budgeted_turns == 10
    result = apply_ranking_matchup(
        pair, judgement, k_factor=24, current_iteration=3
    )
    assert result.llm_calls == 2
    assert result.detail["iteration"] == 3
    assert result.detail["judge_model"] == "test"
    for value, field, replacement in [
        (prompt, "preferences", "changed"),
        (context, "median_elo", 0),
        (judgement, "winner", "a"),
        (result, "llm_calls", 99),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)
    assert isinstance(result, RankingMatchResult)


@pytest.mark.asyncio
async def test_public_judge_meters_real_early_consensus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    async def completion(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(1)
        winner = "a" if len(calls) % 2 else "b"
        return {"winner": winner, "decision_summary": "same winner"}

    monkeypatch.setattr(ranking_debate, "call_llm_json", completion)
    pair = (make_hypothesis(text="a"), make_hypothesis(text="b"))
    prompt = prepare_ranking_prompt_context(make_state())
    context = prepare_ranking_judging_context(prompt, list(pair))
    judgement = await judge_ranking_matchup(pair, context, 0)
    result = apply_ranking_matchup(
        pair, judgement, k_factor=24, current_iteration=0
    )
    assert judgement.budgeted_turns == 10
    assert judgement.winner == "a"
    assert result.llm_calls == len(calls) < judgement.budgeted_turns


def test_apply_preserves_confidence_knobs_and_budget_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking_elo, "ELO_MARGIN_VICTORY_SCALE", 1.0)
    pair = (make_hypothesis(), make_hypothesis())
    judgement = RankingJudgement("a", {"confidence_level": "High"}, 10)
    result = apply_ranking_matchup(
        pair, judgement, k_factor=24, current_iteration=4
    )
    assert result.llm_calls == 10
    assert pair[0].elo_rating == 1224
    assert pair[1].elo_rating == 1176
    assert result.detail["confidence"] == "High"
    assert result.detail["winner_elo_before"] == 1200


@pytest.mark.asyncio
async def test_finalize_orders_bands_and_charges_judged_matches() -> None:
    low = make_hypothesis(text="low", elo_rating=1100)
    top = make_hypothesis(text="top", elo_rating=1400)
    blocked = make_hypothesis(
        text="blocked", elo_rating=1800, review_disposition="inaccurate"
    )
    update = await finalize_ranking(
        make_state(), [low, blocked, top], [{"winner": "a"}], 12, 3
    )
    assert update["hypotheses"] == [top, low, blocked]
    assert update["metrics"].tournaments_count == 1
    assert update["metrics"].llm_calls == 3


@pytest.mark.asyncio
async def test_graph_captures_prompt_once_and_refreshes_sorted_pool_each_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.agents.ranking import operations, ranking

    pool = [make_hypothesis(id=str(i), text=str(i), score=i) for i in range(3)]
    a, b, c = pool
    pairs = [(a, b), (b, c), (a, c)]
    snapshots: list[Any] = []
    captured: list[Any] = []
    prompts: list[Any] = []
    median = ranking_debate._median_elo
    prepare = prepare_ranking_prompt_context

    def record_median(hypotheses: list[Any]) -> float:
        snapshots.append([(h.id, h.elo_rating) for h in hypotheses])
        return median(hypotheses)

    def record_prompt(*args: Any, **kwargs: Any) -> Any:
        prompts.append(1)
        return prepare(*args, **kwargs)

    async def judge(ctx: Any, debate_turns: int) -> tuple[str, dict[str, Any]]:
        captured.append(ctx)
        return "a", {"debate_turns": 1}

    monkeypatch.setattr(operations, "_median_elo", record_median)
    monkeypatch.setattr(operations, "judge_matchup", judge)
    monkeypatch.setattr(
        ranking, "prepare_ranking_prompt_context", record_prompt
    )
    monkeypatch.setattr(
        ranking,
        "build_tournament_pairings",
        lambda *args, **kwargs: [pairs.pop(0)] if pairs else [],
    )
    state = make_state(
        hypotheses=pool, criteria=["feasible"], preferences="preferences"
    )
    await ranking.ranking_node(state)
    assert len(prompts) == 1
    assert len(snapshots) == 3
    assert all(
        [item[0] for item in snapshot] == ["2", "1", "0"]
        for snapshot in snapshots
    )
    assert snapshots[0] != snapshots[1] != snapshots[2]
    assert [ctx.preferences for ctx in captured] == ["preferences"] * 3
    assert [ctx.criteria for ctx in captured] == [["feasible"]] * 3

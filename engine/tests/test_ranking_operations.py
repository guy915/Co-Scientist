from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.ranking import (
    TournamentGuidance,
    apply_ranking_matchup,
    build_tournament_pairings,
    finalize_ranking,
    judge_ranking_matchup,
    prepare_ranking_judging_context,
    prepare_ranking_prompt_context,
    prepare_ranking_round,
    ranking_debate,
    remaining_ranking_rounds,
)
from co_scientist.agents.ranking.ranking_debate import (
    _build_matchup_prompt,
    _DebateContext,
    _extract_criteria_comparisons,
    _MatchupPromptContext,
    _parse_verdict_line,
    judge_matchup,
)
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models import ExecutionMetrics
from co_scientist.schemas.review import (
    RANKING_COMPARISON_CRITERIA,
)
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


def _matchup_context() -> _MatchupPromptContext:
    return _MatchupPromptContext(research_goal="test goal")


def test_matchup_prompt_surfaces_fatal_mature_review_findings() -> None:
    """Paid-for mature findings must reach the judge rather than remain
    write-only."""
    hypothesis_a = make_hypothesis(text="idea A")
    hypothesis_a.enrichments["full"] = {
        "verdict": "rejected",
        "justification": "the proposed pathway is circular",
        "retrieved_articles": [{"title": "never shown to a judge"}],
    }
    hypothesis_a.enrichments["simulation"] = {
        "verdict": "breaks_down",
        "decisive_step": "ligand binding never occurs",
        "failure_points": ["step two"],
    }
    hypothesis_b = make_hypothesis(text="idea B")

    prompt, _, _, _ = _build_matchup_prompt(
        hypothesis_a, hypothesis_b, _matchup_context()
    )

    assert "Hypothesis 1 Mature Review Findings" in prompt
    assert "Full review verdict: rejected" in prompt
    assert "the proposed pathway is circular" in prompt
    assert "Simulation review verdict: breaks_down" in prompt
    assert "ligand binding never occurs" in prompt
    assert "Hypothesis 2 Mature Review Findings" not in prompt
    assert "never shown to a judge" not in prompt


def test_matchup_prompt_keeps_reflection_and_verification() -> None:
    hypothesis_a = make_hypothesis(
        text="idea A",
        reflection_notes="Measured flux from pathway A.",
        deep_verification_probes=[
            {
                "question": "Does the flux persist?",
                "answer": "Yes, under the measured condition.",
                "reasoning": "The control confirms it.",
                "assumption_is_fundamental": True,
            }
        ],
        deep_verification_verdict="holds",
    )
    hypothesis_b = make_hypothesis(text="idea B")
    prompt, _, notes_a, notes_b = _build_matchup_prompt(
        hypothesis_a, hypothesis_b, _matchup_context()
    )
    assert "Measured flux from pathway A." in prompt
    assert "Does the flux persist?" in prompt
    assert "Yes, under the measured condition." in prompt
    assert notes_a == hypothesis_a.reflection_notes
    assert notes_b is None


async def test_judge_matchup_parses_the_literal_verdict_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def fake(**_: Any) -> dict[str, Any]:
        return {
            "winner": "a",
            "decision_summary": "B is stronger.\nbetter idea: 2",
            "confidence_level": "High",
        }

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    ctx = _DebateContext(
        make_hypothesis(text="alpha"),
        make_hypothesis(text="beta"),
        "goal",
        "fake/model",
    )

    winner, response = await judge_matchup(ctx, debate_turns=1)

    assert winner == "b"
    assert response["consensus_votes"] == ["b"]


@pytest.mark.parametrize(
    ("text", "side"),
    [
        ("... better idea: 1", "a"),
        ("BETTER IDEA:2", "b"),
        ("better hypothesis: 2", "b"),
        ("better idea: A", "a"),
        ("End with better idea: 1 or 2. Prevails.\n\nbetter idea: 2", "b"),
        ("conclude with better idea: 1 or 2", None),
        ("better idea: 3", None),
        ("", None),
    ],
)
def test_verdict_line_is_the_concluding_better_idea_statement(
    text: str, side: str | None
) -> None:
    assert _parse_verdict_line(text) == side


def test_criteria_comparisons_keep_only_the_canonical_nonempty_axes() -> None:
    explanation = {
        **{name: f"assesses {name}" for name in RANKING_COMPARISON_CRITERIA},
        "invented_extra_comparison": "not in the closed schema",
        "feasibility_comparison": "",
    }
    comparisons = _extract_criteria_comparisons(
        {"judgment_explanation": explanation}
    )
    assert set(comparisons) == set(RANKING_COMPARISON_CRITERIA) - {
        "feasibility_comparison"
    }
    assert _extract_criteria_comparisons({}) == {}

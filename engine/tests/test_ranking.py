from __future__ import annotations

import logging
from typing import Any

import pytest

from co_scientist.agents.ranking import (
    ranking,
    ranking_debate,
    remaining_ranking_rounds,
)
from co_scientist.agents.ranking.ranking import (
    calculate_elo_update,
    ranking_node,
)
from co_scientist.agents.ranking.ranking_debate import (
    _RANKING_DEBATE_MAX_TURNS,
    _build_matchup_prompt,
    _DebateContext,
    _matchup_debate_turns,
    _MatchupPromptContext,
    _parse_verdict_line,
    annealed_k_factor,
    judge_matchup,
    margin_scaled_k_factor,
)
from co_scientist.agents.ranking.ranking_lifecycle import add_to_tournament
from co_scientist.agents.ranking.ranking_matchmaking import (
    MatchCandidate,
    build_weighted_pairings,
)
from co_scientist.constants import ELO_UPSET_MARGIN, INITIAL_ELO_RATING
from co_scientist.models import ExecutionMetrics, Hypothesis
from tests._llm_fake import stub_call_llm_json
from tests._state import (
    make_hypothesis,
    make_ranking_response,
    make_review,
    make_state,
)


async def test_skipped_tournament_names_the_pool_and_the_gates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    kept = make_hypothesis(text="the one survivor TXT alpha")
    rejected = make_hypothesis(text="rejected idea TXT gamma")
    rejected.review_disposition = "inaccurate"
    also_rejected = make_hypothesis(text="rejected idea TXT delta")
    also_rejected.review_disposition = "evidence_blocked"
    state = make_state(hypotheses=[kept, rejected, also_rejected])

    with caplog.at_level(logging.WARNING):
        result = await ranking_node(state)

    assert "tournament_matchups" not in result
    message = caplog.text
    assert "1 of 3 hypotheses are rankable" in message
    assert "2 rejected in review" in message
    # Verification demotes rather than excludes; it cannot explain a thin pool.
    assert "undermined" not in message


def _record_matchup_prompts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen_prompts: list[str] = []

    async def fake(*, prompt: str, **_: Any) -> dict[str, Any]:
        seen_prompts.append(prompt)
        return make_ranking_response("a", decision_summary="A wins.")

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    return seen_prompts


async def test_a_rejected_hypothesis_cannot_enter_tournament(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_novel = make_hypothesis(
        text="already established mechanism",
        review_disposition="non_novel",
        elo_rating=1700,
    )
    eligible_a = make_hypothesis(text="supported mechanism alpha")
    eligible_b = make_hypothesis(text="supported mechanism beta")
    seen_prompts = _record_matchup_prompts(monkeypatch)
    state = make_state(
        hypotheses=[non_novel, eligible_a, eligible_b],
        tournament_pairs=2,
    )

    result = await ranking_node(state)

    assert all(
        "already established mechanism" not in prompt for prompt in seen_prompts
    )
    assert non_novel.total_matches == 0
    assert result["hypotheses"][-1].id == non_novel.id


def _hyp(text: str = "a hypothesis", **overrides: Any) -> Hypothesis:
    """Tournament entrants require completed review stamps."""
    return make_hypothesis(text=text, reviews=[make_review()], **overrides)


def test_tournament_budget_is_spent_across_the_whole_run() -> None:
    """Invoking ranking in a later cycle must not recharge its allowance."""
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import ExecutionMetrics

    hypotheses = [
        _hyp(text=f"h{i}", win_count=1, loss_count=1) for i in range(4)
    ]

    fresh = make_state(hypotheses=hypotheses, tournament_pairs=12)
    assert _tournament_round_count(fresh, hypotheses) == 12

    partway = make_state(
        hypotheses=hypotheses,
        tournament_pairs=12,
        metrics=ExecutionMetrics(tournaments_count=9),
    )
    assert _tournament_round_count(partway, hypotheses) == 3

    spent = make_state(
        hypotheses=hypotheses,
        tournament_pairs=12,
        metrics=ExecutionMetrics(tournaments_count=12),
    )
    assert _tournament_round_count(spent, hypotheses) == 0


async def test_ranking_node_is_a_no_op_once_the_budget_is_spent() -> None:
    from co_scientist.models import ExecutionMetrics

    hypotheses = [
        _hyp(text=f"h{i}", win_count=1, loss_count=1) for i in range(4)
    ]
    state = make_state(
        hypotheses=hypotheses,
        tournament_pairs=6,
        metrics=ExecutionMetrics(tournaments_count=6),
    )

    result = await ranking_node(state)

    assert result == {"hypotheses": hypotheses}


def test_unrankable_ideas_do_not_hold_the_coverage_floor_open() -> None:
    """Gated ideas can never settle match debt."""
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import ExecutionMetrics

    hypotheses = [
        _hyp(text="played", win_count=1, loss_count=1),
        _hyp(text="blocked", review_disposition="evidence_blocked"),
        _hyp(text="rejected", review_disposition="non_novel"),
    ]
    spent = make_state(
        hypotheses=hypotheses,
        tournament_pairs=6,
        metrics=ExecutionMetrics(tournaments_count=6),
    )

    assert _tournament_round_count(spent, hypotheses) == 0


async def test_budget_is_charged_for_matches_judged_not_rounds_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distinct-pair ceiling can leave offered rounds unused."""
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import merge_metrics

    hypotheses = [_hyp(text=f"pool {i} TXT") for i in range(3)]

    stub_call_llm_json(
        monkeypatch,
        ranking_debate,
        make_ranking_response("a"),
        copy_response=True,
    )

    state = make_state(hypotheses=hypotheses, tournament_pairs=20)
    result = await ranking_node(state)

    assert len(result["tournament_matchups"]) == 3
    assert result["metrics"].tournaments_count == 3

    state["metrics"] = merge_metrics(state["metrics"], result["metrics"])
    assert _tournament_round_count(state, hypotheses) == 17


@pytest.mark.parametrize(
    ("rating", "admitted", "after"),
    [(0, True, INITIAL_ELO_RATING), (1350, False, 1350)],
)
def test_entry_rates_an_unrated_hypothesis_once(
    rating: int, admitted: bool, after: int
) -> None:
    hypothesis = Hypothesis(text="An idea.", elo_rating=rating)
    assert add_to_tournament(hypothesis) is admitted
    assert hypothesis.elo_rating == after


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


def test_remaining_budget_funds_only_peer_reviewed_coverage() -> None:
    pool = [make_hypothesis(reviews=[make_review()]) for _ in range(3)]
    state = make_state(
        hypotheses=pool, metrics=ExecutionMetrics(tournaments_count=100)
    )
    assert remaining_ranking_rounds(state, pool) == 3
    for hypothesis in pool:
        hypothesis.reviews = []
    assert remaining_ranking_rounds(state, pool) == 0


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


_RATING_PAIRS = [
    (1200, 1200),
    (1000, 1400),
    (1400, 1000),
    (1300, 1100),
    (1100, 1300),
    (1500, 1400),
    (1000, 1100),
    (1100, 1000),
    (987, 1456),
    (1456, 987),
    (800, 2000),
    (2000, 800),
]


@pytest.mark.parametrize("winner_elo, loser_elo", _RATING_PAIRS)
def test_winner_never_decreases_loser_never_increases(
    winner_elo: int, loser_elo: int
) -> None:
    new_winner, new_loser = calculate_elo_update(winner_elo, loser_elo, 24)
    assert new_winner >= winner_elo
    assert new_loser <= loser_elo


def test_annealing_halves_k_per_half_life_down_to_a_floor() -> None:
    assert annealed_k_factor(24, 29, half_life=30) == 24
    assert annealed_k_factor(24, 30, half_life=30) == 12
    assert annealed_k_factor(24, 60, half_life=30) == 6
    assert annealed_k_factor(24, 10_000, half_life=30) == 6
    assert annealed_k_factor(24, 500) == 24


def test_margin_scaling_is_capped_at_the_multiplier_ceiling() -> None:
    assert margin_scaled_k_factor(24, "High", scale=100.0) == 24 * 5


@pytest.mark.parametrize(
    ("winner_elo", "loser_elo", "confidence", "tier"),
    [
        (1200, 1200 + ELO_UPSET_MARGIN, "Low", "upset"),
        (1300, 1200, "High", "decisive"),
        (1300, 1200, "Medium", "clear"),
        (1300, 1200, "Low", "narrow"),
        (1300, 1200, "", "narrow"),
    ],
)
def test_match_tier_marks_upsets_then_maps_confidence(
    winner_elo: int, loser_elo: int, confidence: str, tier: str
) -> None:
    assert ranking.match_tier(winner_elo, loser_elo, confidence) == tier


def _cands(*specs: tuple[str, int, int, str | None]) -> list[MatchCandidate]:
    return [MatchCandidate(i, e, m, c) for (i, e, m, c) in specs]


def test_a_pair_is_never_scheduled_twice_in_one_build() -> None:
    """A single Elo snapshot supplies no new information for repeated
    comparisons."""
    candidates = _cands(
        ("a", 1200, 0, None),
        ("b", 1200, 0, None),
        ("c", 1200, 0, None),
        ("d", 1200, 0, None),
    )
    pairs = build_weighted_pairings(candidates, rounds=50, seed=3)

    assert len(pairs) == len({frozenset(pair) for pair in pairs})
    assert len(pairs) == 6

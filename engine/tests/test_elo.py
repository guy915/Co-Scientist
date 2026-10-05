from __future__ import annotations

import itertools
from collections import Counter
from typing import Any

import pytest

import co_scientist.agents.ranking.ranking_debate as origin_ranking_debate
import co_scientist.agents.ranking.ranking_debate as ranking_elo
from co_scientist.agents.ranking import operations, ranking, ranking_debate
from co_scientist.agents.ranking.ranking import (
    calculate_elo_update,
    ranking_node,
)
from co_scientist.agents.ranking.ranking_debate import (
    _apply_matchup_elo,
    annealed_k_factor,
    effective_k_factor,
    margin_scaled_k_factor,
)
from co_scientist.agents.ranking.ranking_lifecycle import (
    _sort_hypotheses_by_elo,
)
from co_scientist.agents.ranking.ranking_matchmaking import (
    MatchCandidate,
    MatchmakingWeights,
    build_weighted_pairings,
)
from co_scientist.constants import (
    ELO_UPSET_MARGIN,
    INITIAL_ELO_RATING,
    MAX_CONCURRENT_LLM_CALLS,
)
from co_scientist.models import Hypothesis, rank_by_elo
from tests._state import make_hypothesis, make_review, make_state


@pytest.mark.parametrize(
    "winner_elo, loser_elo, k_factor, expected",
    [
        (1200, 1200, 24, (1212, 1188)),
        (1200, 1200, 32, (1216, 1184)),
        (1000, 1400, 24, (1021, 1378)),
        (1400, 1000, 24, (1402, 997)),
        (1300, 1100, 24, (1305, 1094)),
        (1100, 1300, 24, (1118, 1281)),
        (1100, 1000, 24, (1108, 991)),
        (1000, 1100, 24, (1015, 1084)),
        (1500, 1400, 24, (1508, 1391)),
        (1300, 1100, 0, (1300, 1100)),
    ],
)
def test_exact_integer_outputs(
    winner_elo: int, loser_elo: int, k_factor: int, expected: tuple[int, int]
) -> None:
    assert calculate_elo_update(winner_elo, loser_elo, k_factor) == expected


def test_matchup_applies_run_specific_k_factor() -> None:
    hypothesis_a = Hypothesis(text="A")
    hypothesis_b = Hypothesis(text="B")

    outcome = _apply_matchup_elo(hypothesis_a, hypothesis_b, "a", k_factor=40)

    assert outcome.winner_elo_after == 1220
    assert outcome.loser_elo_after == 1180


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


@pytest.mark.parametrize("winner_elo, loser_elo", _RATING_PAIRS)
def test_total_points_conserved_within_truncation_error(
    winner_elo: int, loser_elo: int
) -> None:
    k_factor = 24
    new_winner, new_loser = calculate_elo_update(
        winner_elo, loser_elo, k_factor
    )

    old_total = winner_elo + loser_elo
    new_total = new_winner + new_loser
    drift = old_total - new_total

    assert 0 <= drift <= 2


# These optional reconstruction knobs default off to preserve existing ratings.


def test_annealing_halves_k_per_half_life_down_to_a_floor() -> None:
    assert annealed_k_factor(24, 29, half_life=30) == 24
    assert annealed_k_factor(24, 30, half_life=30) == 12
    assert annealed_k_factor(24, 60, half_life=30) == 6
    assert annealed_k_factor(24, 10_000, half_life=30) == 6
    assert annealed_k_factor(24, 500) == 24


def test_margin_scaling_grows_k_with_decisiveness() -> None:
    assert margin_scaled_k_factor(24, "High") == 24
    assert margin_scaled_k_factor(24, None, scale=1.0) == 24
    assert margin_scaled_k_factor(24, "High", scale=1.0) == 48
    assert margin_scaled_k_factor(24, "Medium", scale=1.0) == 36
    assert margin_scaled_k_factor(24, "Low", scale=1.0) == 24
    assert margin_scaled_k_factor(24, "Unknown", scale=1.0) == 24


def test_margin_scaling_is_capped_at_the_multiplier_ceiling() -> None:
    assert margin_scaled_k_factor(24, "High", scale=100.0) == 24 * 5


def test_effective_k_anneals_then_scales() -> None:
    assert effective_k_factor(24, 30, confidence="High") == (
        margin_scaled_k_factor(annealed_k_factor(24, 30), "High")
    )


def test_per_side_k_factor_updates_each_side_independently() -> None:
    new_winner, new_loser = calculate_elo_update(
        1200, 1200, 24, loser_k_factor=12
    )
    assert (new_winner, new_loser) == (1212, 1194)


def test_annealing_applies_per_side_from_each_own_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking_elo, "ELO_K_ANNEALING_HALF_LIFE", 2)
    winner = Hypothesis(text="fresh winner")
    loser = Hypothesis(text="veteran loser")
    loser.win_count = 2
    loser.loss_count = 0

    outcome = _apply_matchup_elo(winner, loser, "a", k_factor=24)

    assert outcome.winner_elo_after == 1212
    assert outcome.loser_elo_after == 1194


def test_margin_scaling_applies_from_the_verdict_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking_elo, "ELO_MARGIN_VICTORY_SCALE", 1.0)
    decisive_a = Hypothesis(text="decisive A")
    decisive_b = Hypothesis(text="decisive B")
    outcome = _apply_matchup_elo(
        decisive_a, decisive_b, "a", k_factor=24, confidence="High"
    )
    assert outcome.winner_elo_after == 1224
    assert outcome.loser_elo_after == 1176

    narrow_a = Hypothesis(text="narrow A")
    narrow_b = Hypothesis(text="narrow B")
    narrow = _apply_matchup_elo(
        narrow_a, narrow_b, "a", k_factor=24, confidence="Low"
    )
    assert narrow.winner_elo_after == 1212
    assert narrow.loser_elo_after == 1188


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


def test_equal_elo_orders_the_same_way_everywhere() -> None:
    """Early ranking and the overview must agree on the strongest tied idea."""
    tied = [make_hypothesis(text=text) for text in ("alpha", "gamma", "beta")]
    assert {h.elo_rating for h in tied} == {INITIAL_ELO_RATING}
    assert {h.score for h in tied} == {0.0}

    node_order = [h.text for h in _sort_hypotheses_by_elo(tied)]

    assert node_order == [h.text for h in rank_by_elo(tied)]
    assert node_order == ["gamma", "beta", "alpha"]


def test_an_undermined_idea_sorts_below_every_sound_one() -> None:
    """A leader may have earned high Elo before deep verification demoted it."""
    undermined = make_hypothesis(
        text="yankee",
        deep_verification_verdict="undermined",
        elo_rating=INITIAL_ELO_RATING + 300,
    )
    blocked = make_hypothesis(
        text="zeta", review_disposition="evidence_blocked"
    )
    rankable = [make_hypothesis(text=text) for text in ("alpha", "beta")]

    ordered = _sort_hypotheses_by_elo([blocked, undermined, *rankable])

    assert [h.text for h in ordered] == ["beta", "alpha", "yankee", "zeta"]


def _hyp(text: str = "a hypothesis", **overrides: Any) -> Hypothesis:
    """Tournament entrants require completed review stamps."""
    return make_hypothesis(text=text, reviews=[make_review()], **overrides)


def test_matchup_judging_survives_more_than_one_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async concurrency primitives cannot be shared across event loops."""
    import asyncio

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"winner": "A", "reasoning": "because"}

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake_call_llm_json)

    hyp_a = _hyp(text="a")
    hyp_b = _hyp(text="b")

    async def judge_a_full_wave() -> None:
        mp = ranking_debate._MatchupPrompt("prompt", None, None, None)
        await asyncio.gather(
            *(
                origin_ranking_debate._call_matchup_judge(
                    mp,
                    ranking_debate._DebateContext(
                        hyp_a, hyp_b, "goal", "model", matchup_index=index
                    ),
                )
                # More waiters than permits, so acquisition must block.
                for index in range(MAX_CONCURRENT_LLM_CALLS * 2)
            )
        )

    asyncio.run(judge_a_full_wave())
    # A second task, on a second loop, is the case that broke.
    asyncio.run(judge_a_full_wave())


async def test_every_rankable_idea_reaches_the_minimum_match_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.constants import TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS
    from co_scientist.models import ExecutionMetrics

    fresh = _hyp(text="fresh mechanism")
    covered = [
        _hyp(text=f"covered mechanism {i}", win_count=1, loss_count=1)
        for i in range(4)
    ]
    hypotheses = [fresh, *covered]

    async def fake_judge(*_: Any, **__: Any) -> tuple[str, dict[str, Any]]:
        return "a", {
            "decision_summary": "A wins.",
            "confidence_level": "High",
            "debate_turns": 1,
        }

    monkeypatch.setattr(operations, "judge_matchup", fake_judge)
    # Budget already spent by earlier cycles: only the coverage floor can
    # grant rounds now, which isolates the floor's sizing of the pass.
    state = make_state(
        hypotheses=hypotheses,
        tournament_pairs=6,
        metrics=ExecutionMetrics(tournaments_count=99),
    )

    result = await ranking_node(state)

    for hypothesis in result["hypotheses"]:
        if hypothesis.is_rankable():
            assert hypothesis.total_matches >= (
                TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS
            ), f"{hypothesis.text} left short of the minimum"


async def test_matchups_carry_the_iteration_they_were_judged_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persisted Elo history needs the actual cycle, not a constant."""
    hypotheses = [
        _hyp(text="iteration alpha TXT"),
        _hyp(text="iteration beta TXT"),
    ]

    async def fake(**_: Any) -> dict[str, Any]:
        return {
            "winner": "a",
            "decision_summary": "stub decision",
            "confidence_level": "High",
        }

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)

    state = make_state(hypotheses=hypotheses, tournament_pairs=1)
    state["current_iteration"] = 2
    result = await ranking_node(state)

    assert [m["iteration"] for m in result["tournament_matchups"]] == [2]


def _cands(*specs: tuple[str, int, int, str | None]) -> list[MatchCandidate]:
    return [MatchCandidate(i, e, m, c) for (i, e, m, c) in specs]


def test_no_self_or_immediate_duplicate_matches() -> None:
    candidates = _cands(
        ("a", 1200, 0, None),
        ("b", 1200, 0, None),
        ("c", 1200, 0, None),
        ("d", 1200, 0, None),
    )
    pairs = build_weighted_pairings(candidates, rounds=12, seed=7)
    for x, y in pairs:
        assert x != y
    for prev, cur in itertools.pairwise(pairs):
        assert set(prev) != set(cur)


def test_newer_hypotheses_are_prioritized() -> None:
    candidates = _cands(
        ("veteran", 1200, 20, None),
        ("newA", 1200, 0, None),
        ("newB", 1200, 0, None),
        ("newC", 1200, 0, None),
    )
    pairs = build_weighted_pairings(candidates, rounds=30, seed=11)
    played: Counter[str] = Counter()
    for x, y in pairs:
        played[x] += 1
        played[y] += 1
    fresh = played["newA"] + played["newB"] + played["newC"]
    assert fresh > played["veteran"] * 2


def test_top_ranked_hypotheses_are_prioritized() -> None:
    """Exhaustive all-pairs scheduling would hide the selection bias under
    test."""
    candidates = _cands(
        ("top", 1600, 5, None),
        ("midA", 1200, 5, None),
        ("midB", 1200, 5, None),
        ("midC", 1200, 5, None),
        ("low", 800, 5, None),
    )
    played: Counter[str] = Counter()
    for seed in range(10):
        for x, y in build_weighted_pairings(candidates, rounds=4, seed=seed):
            played[x] += 1
            played[y] += 1
    assert played["top"] > played["low"]


def test_similar_hypotheses_are_preferred() -> None:
    """The round ceiling must bind; exhaustive scheduling would hide partner
    bias."""
    candidates = _cands(
        ("a1", 1200, 5, "cluster-1"),
        ("a2", 1200, 5, "cluster-1"),
        ("a3", 1200, 5, "cluster-1"),
        ("b1", 1200, 5, "cluster-2"),
        ("b2", 1200, 5, "cluster-2"),
        ("b3", 1200, 5, "cluster-2"),
    )
    same_cluster = cross_cluster = 0
    for seed in range(10):
        pairs = build_weighted_pairings(
            candidates,
            rounds=6,
            seed=seed,
            weights=MatchmakingWeights(similarity_bonus=5.0),
        )
        same = sum(1 for x, y in pairs if x[0] == y[0])
        same_cluster += same
        cross_cluster += len(pairs) - same
    assert same_cluster > cross_cluster


def test_close_elo_hypotheses_are_preferred() -> None:
    """Zero rank weight isolates Elo-distance preference from higher-rating
    bias."""
    candidates = _cands(
        ("a1", 1200, 5, None),
        ("a2", 1210, 5, None),
        ("a3", 1220, 5, None),
        ("b1", 1600, 5, None),
        ("b2", 1610, 5, None),
        ("b3", 1620, 5, None),
    )
    same_group = cross_group = 0
    for seed in range(10):
        pairs = build_weighted_pairings(
            candidates,
            rounds=6,
            seed=seed,
            weights=MatchmakingWeights(rank=0.0, elo_closeness=5.0),
        )
        same = sum(1 for x, y in pairs if x[0] == y[0])
        same_group += same
        cross_group += len(pairs) - same
    assert same_group > cross_group


def test_deterministic_for_fixed_seed() -> None:
    candidates = _cands(
        ("a", 1300, 2, "c1"),
        ("b", 1200, 4, "c1"),
        ("c", 1100, 1, "c2"),
        ("d", 1000, 3, "c2"),
    )
    first = build_weighted_pairings(candidates, rounds=15, seed=42)
    second = build_weighted_pairings(candidates, rounds=15, seed=42)
    assert first == second
    other = build_weighted_pairings(candidates, rounds=15, seed=43)
    assert other != first


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

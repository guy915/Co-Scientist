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
    _finalize_ranking_result,
    _sort_hypotheses_by_elo,
)
from co_scientist.agents.ranking.ranking_matchmaking import (
    MatchCandidate,
    MatchmakingWeights,
    build_weighted_pairings,
)
from co_scientist.constants import (
    ELO_K_FACTOR,
    INITIAL_ELO_RATING,
    MAX_CONCURRENT_LLM_CALLS,
)
from co_scientist.models import Hypothesis, rank_by_elo
from tests._state import make_hypothesis, make_review, make_state


def _reference_elo_update(
    winner_elo: int, loser_elo: int, k_factor: int
) -> tuple[int, int]:
    """An independent standard formula avoids mirroring the production
    implementation."""
    expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_loser = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))
    new_winner = winner_elo + k_factor * (1 - expected_winner)
    new_loser = loser_elo + k_factor * (0 - expected_loser)
    return int(new_winner), int(new_loser)


def test_initial_elo_rating_constant() -> None:
    assert INITIAL_ELO_RATING == 1200


def test_elo_k_factor_constant() -> None:
    assert ELO_K_FACTOR == 24


def test_default_k_factor_matches_constant() -> None:
    assert calculate_elo_update(1200, 1200) == calculate_elo_update(
        1200, 1200, ELO_K_FACTOR
    )


def test_equal_ratings_split_symmetrically() -> None:
    new_winner, new_loser = calculate_elo_update(1200, 1200, 24)
    assert (new_winner, new_loser) == (1212, 1188)


def test_equal_ratings_winner_gains_loser_loses() -> None:
    new_winner, new_loser = calculate_elo_update(1500, 1500, 24)
    assert new_winner > 1500
    assert new_loser < 1500


def test_equal_ratings_magnitude_is_symmetric() -> None:
    start = 1200
    new_winner, new_loser = calculate_elo_update(start, start, 24)
    assert new_winner - start == start - new_loser == 12


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
    ],
)
def test_exact_integer_outputs(
    winner_elo: int, loser_elo: int, k_factor: int, expected: tuple[int, int]
) -> None:
    assert calculate_elo_update(winner_elo, loser_elo, k_factor) == expected


@pytest.mark.parametrize(
    "winner_elo, loser_elo, k_factor",
    [
        (1200, 1200, 24),
        (1000, 1400, 24),
        (1400, 1000, 24),
        (1300, 1100, 16),
        (1100, 1300, 32),
        (987, 1456, 24),
        (1456, 987, 40),
    ],
)
def test_matches_standard_elo_formula(
    winner_elo: int, loser_elo: int, k_factor: int
) -> None:
    assert calculate_elo_update(
        winner_elo, loser_elo, k_factor
    ) == _reference_elo_update(winner_elo, loser_elo, k_factor)


def test_underdog_win_swings_more_than_favorite_win() -> None:
    underdog_winner, _ = calculate_elo_update(1000, 1400, 24)
    favorite_winner, _ = calculate_elo_update(1400, 1000, 24)

    underdog_gain = underdog_winner - 1000
    favorite_gain = favorite_winner - 1400

    assert underdog_gain > favorite_gain
    assert underdog_gain == 21
    assert favorite_gain == 2


def test_higher_k_factor_produces_larger_change() -> None:
    small_k_winner, _ = calculate_elo_update(1200, 1200, 16)
    large_k_winner, _ = calculate_elo_update(1200, 1200, 48)

    assert large_k_winner - 1200 > small_k_winner - 1200


def test_matchup_applies_run_specific_k_factor() -> None:
    hypothesis_a = Hypothesis(text="A")
    hypothesis_b = Hypothesis(text="B")

    outcome = _apply_matchup_elo(hypothesis_a, hypothesis_b, "a", k_factor=40)

    assert outcome.winner_elo_after == 1220
    assert outcome.loser_elo_after == 1180


def test_zero_k_factor_produces_no_change() -> None:
    assert calculate_elo_update(1300, 1100, 0) == (1300, 1100)


def test_zero_k_factor_no_change_for_equal_ratings() -> None:
    assert calculate_elo_update(1200, 1200, 0) == (1200, 1200)


def test_results_are_truncated_not_rounded() -> None:
    new_winner, new_loser = calculate_elo_update(1500, 1400, 24)

    assert new_winner == 1508
    assert new_loser == 1391

    raw_winner = 1500 + 24 * (1 - 1 / (1 + 10 ** ((1400 - 1500) / 400)))
    raw_loser = 1400 + 24 * (0 - 1 / (1 + 10 ** ((1500 - 1400) / 400)))
    assert round(raw_winner) == 1509
    assert int(raw_winner) == new_winner
    assert int(raw_loser) == new_loser


def test_truncation_can_break_winner_loser_symmetry() -> None:
    """Independent integer truncation can lose points on both sides."""
    new_winner, new_loser = calculate_elo_update(1000, 1400, 24)
    winner_gain = new_winner - 1000
    loser_drop = 1400 - new_loser
    assert winner_gain == 21
    assert loser_drop == 22
    assert winner_gain != loser_drop


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


@pytest.mark.parametrize("winner_elo, loser_elo", _RATING_PAIRS)
def test_returns_two_python_ints(winner_elo: int, loser_elo: int) -> None:
    result = calculate_elo_update(winner_elo, loser_elo, 24)
    assert isinstance(result, tuple)
    assert len(result) == 2
    new_winner, new_loser = result
    assert isinstance(new_winner, int)
    assert isinstance(new_loser, int)


# These optional reconstruction knobs default off to preserve existing ratings.


def test_knobs_default_to_off_and_preserve_the_fixed_k() -> None:
    assert annealed_k_factor(24, matches_played=500) == 24
    assert margin_scaled_k_factor(24, "High") == 24
    assert margin_scaled_k_factor(24, None) == 24
    assert effective_k_factor(24, matches_played=500, confidence="High") == 24


def test_annealing_disabled_by_a_nonpositive_half_life() -> None:
    assert annealed_k_factor(24, 100, half_life=0) == 24
    assert annealed_k_factor(24, 100, half_life=-5) == 24
    assert annealed_k_factor(24, 0, half_life=30) == 24


def test_annealing_halves_k_per_half_life_of_matches() -> None:
    assert annealed_k_factor(24, 0, half_life=30) == 24
    assert annealed_k_factor(24, 29, half_life=30) == 24
    assert annealed_k_factor(24, 30, half_life=30) == 12
    assert annealed_k_factor(24, 59, half_life=30) == 12
    assert annealed_k_factor(24, 60, half_life=30) == 6


def test_annealing_floors_at_the_annealed_minimum() -> None:
    assert annealed_k_factor(24, 90, half_life=30) == 6
    assert annealed_k_factor(24, 10_000, half_life=30) == 6


def test_margin_scaling_disabled_by_a_nonpositive_scale() -> None:
    assert margin_scaled_k_factor(24, "High", scale=0.0) == 24
    assert margin_scaled_k_factor(24, "High", scale=-1.0) == 24
    assert margin_scaled_k_factor(24, None, scale=1.0) == 24
    assert margin_scaled_k_factor(24, "", scale=1.0) == 24


def test_margin_scaling_grows_k_with_decisiveness() -> None:
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


def test_apply_matchup_elo_default_is_unchanged_with_confidence() -> None:
    hyp_a = Hypothesis(text="A")
    hyp_b = Hypothesis(text="B")
    outcome = _apply_matchup_elo(
        hyp_a, hyp_b, "a", k_factor=24, confidence="High"
    )
    assert (outcome.winner_elo_after, outcome.loser_elo_after) == (1212, 1188)


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


def test_equal_elo_orders_the_same_way_everywhere() -> None:
    """Early ranking and the overview must agree on the strongest tied idea."""
    tied = [make_hypothesis(text=text) for text in ("alpha", "gamma", "beta")]
    assert {h.elo_rating for h in tied} == {INITIAL_ELO_RATING}
    assert {h.score for h in tied} == {0.0}

    node_order = [h.text for h in _sort_hypotheses_by_elo(tied)]

    assert node_order == [h.text for h in rank_by_elo(tied)]
    assert node_order == ["gamma", "beta", "alpha"]


def test_unrankable_ideas_sort_last_without_a_second_comparison() -> None:
    blocked = make_hypothesis(
        text="zeta", review_disposition="evidence_blocked"
    )
    rankable = [make_hypothesis(text=text) for text in ("alpha", "beta")]

    ordered = _sort_hypotheses_by_elo([blocked, *rankable])

    assert [h.text for h in ordered] == ["beta", "alpha", "zeta"]


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


def test_elo_outranks_the_text_tiebreak() -> None:
    pool = [
        make_hypothesis(text="alpha", elo_rating=1400),
        make_hypothesis(text="zeta", elo_rating=1200),
    ]

    assert [h.text for h in _sort_hypotheses_by_elo(pool)] == ["alpha", "zeta"]
    assert [h.text for h in rank_by_elo(pool)] == ["alpha", "zeta"]


async def test_tournament_complete_marks_a_truncated_winner() -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    async def callback(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    long_winner = make_hypothesis(text="w" * 260, elo_rating=1400)
    short_runner_up = make_hypothesis(text="a short idea", elo_rating=1200)
    state = make_state(progress_callback=callback)

    await _finalize_ranking_result(
        state, [long_winner, short_runner_up], [], 1, 1
    )

    event, payload = events[-1]
    assert event == "tournament_complete"
    assert payload["top_hypothesis"] == "w" * 200 + "..."


def _hyp(text: str = "a hypothesis", **overrides: Any) -> Hypothesis:
    """Tournament entrants require completed review stamps."""
    return make_hypothesis(text=text, reviews=[make_review()], **overrides)


def test_match_tier_upset_when_loser_outrated_winner() -> None:
    from co_scientist.constants import ELO_UPSET_MARGIN

    assert ranking.match_tier(1200, 1200 + ELO_UPSET_MARGIN, "High") == "upset"
    assert ranking.match_tier(1200, 1200 + ELO_UPSET_MARGIN, "Low") == "upset"


def test_match_tier_maps_confidence_when_not_an_upset() -> None:
    assert ranking.match_tier(1300, 1200, "High") == "decisive"
    assert ranking.match_tier(1300, 1200, "Medium") == "clear"
    assert ranking.match_tier(1300, 1200, "Low") == "narrow"


def test_match_tier_confidence_is_case_insensitive_with_narrow_fallback() -> (
    None
):
    assert ranking.match_tier(1300, 1200, "high") == "decisive"
    assert ranking.match_tier(1300, 1200, "") == "narrow"
    assert ranking.match_tier(1300, 1200, "Unknown") == "narrow"


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


def test_minimum_coverage_reached_no_starvation() -> None:
    candidates = _cands(
        ("a", 1400, 0, None),
        ("b", 1200, 0, None),
        ("c", 1100, 0, None),
        ("d", 1000, 0, None),
        ("e", 900, 0, None),
    )
    pairs = build_weighted_pairings(
        candidates,
        rounds=6,
        seed=3,
        weights=MatchmakingWeights(min_coverage=1),
    )
    played: Counter[str] = Counter()
    for x, y in pairs:
        played[x] += 1
        played[y] += 1
    for c in candidates:
        assert played[c.id] >= 1, f"{c.id} was starved"


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


def test_fewer_than_two_candidates_yields_no_pairs() -> None:
    assert build_weighted_pairings(_cands(("a", 1200, 0, None)), 5, 1) == []
    assert build_weighted_pairings([], 5, 1) == []


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


def test_two_rankable_ideas_yield_one_match_not_a_ratchet() -> None:
    """Repeated judgments of one pair inflate ratings without new opponents."""
    candidates = _cands(("a", 1200, 0, None), ("b", 1200, 0, None))

    pairs = build_weighted_pairings(candidates, rounds=6, seed=1)

    assert pairs == [("a", "b")] or pairs == [("b", "a")]


def test_every_candidate_is_matched_when_rounds_allow() -> None:
    """An unmatched seed rating must not appear earned."""
    candidates = _cands(
        ("a", 1500, 0, None),
        ("b", 1400, 0, None),
        ("c", 1300, 0, None),
        ("d", 800, 0, None),
        ("e", 700, 0, None),
        ("f", 600, 0, None),
    )
    for seed in range(10):
        pairs = build_weighted_pairings(candidates, rounds=3, seed=seed)
        matched = {name for pair in pairs for name in pair}
        assert matched == {c.id for c in candidates}, f"seed {seed}"

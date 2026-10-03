"""Offline contracts for elo."""

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
    """Independent reimplementation of the standard Elo update formula.

    Mirrors the math the production function should be performing, including
    the ``int()`` truncation of the final ratings. Used to cross-check that the
    production implementation matches the textbook formula.

    Args:
      winner_elo: Current Elo rating of the winner.
      loser_elo: Current Elo rating of the loser.
      k_factor: K-factor governing the magnitude of the update.

    Returns:
      Tuple of ``(new_winner_elo, new_loser_elo)`` as truncated integers.
    """
    expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_loser = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))
    new_winner = winner_elo + k_factor * (1 - expected_winner)
    new_loser = loser_elo + k_factor * (0 - expected_loser)
    return int(new_winner), int(new_loser)


# --- Constants -------------------------------------------------------------


def test_initial_elo_rating_constant() -> None:
    """``INITIAL_ELO_RATING`` is locked to 1200."""
    assert INITIAL_ELO_RATING == 1200


def test_elo_k_factor_constant() -> None:
    """``ELO_K_FACTOR`` is locked to 24."""
    assert ELO_K_FACTOR == 24


def test_default_k_factor_matches_constant() -> None:
    """The function's default k-factor is exactly ``ELO_K_FACTOR``."""
    assert calculate_elo_update(1200, 1200) == calculate_elo_update(
        1200, 1200, ELO_K_FACTOR
    )


# --- Equal ratings ---------------------------------------------------------


def test_equal_ratings_split_symmetrically() -> None:
    """Equal 1200 v 1200 at k=24 yields (1212, 1188)."""
    new_winner, new_loser = calculate_elo_update(1200, 1200, 24)
    assert (new_winner, new_loser) == (1212, 1188)


def test_equal_ratings_winner_gains_loser_loses() -> None:
    """With equal ratings the winner gains and the loser loses points."""
    new_winner, new_loser = calculate_elo_update(1500, 1500, 24)
    assert new_winner > 1500
    assert new_loser < 1500


def test_equal_ratings_magnitude_is_symmetric() -> None:
    """With equal ratings the gain and loss have equal magnitude.

    At equal ratings the expected score is exactly 0.5 and the raw deltas are
    whole numbers (12 at k=24), so truncation does not break the symmetry.
    """
    start = 1200
    new_winner, new_loser = calculate_elo_update(start, start, 24)
    assert new_winner - start == start - new_loser == 12


# --- Exact integer outputs (hand-computed against the formula) -------------


@pytest.mark.parametrize(
    "winner_elo, loser_elo, k_factor, expected",
    [
        # Equal ratings, default-style k.
        (1200, 1200, 24, (1212, 1188)),
        # Higher equal ratings, larger k.
        (1200, 1200, 32, (1216, 1184)),
        # Underdog (much weaker) wins -> large swing.
        (1000, 1400, 24, (1021, 1378)),
        # Favorite (much stronger) wins -> small swing.
        (1400, 1000, 24, (1402, 997)),
        # 200-point gap, favorite wins.
        (1300, 1100, 24, (1305, 1094)),
        # 200-point gap, underdog wins.
        (1100, 1300, 24, (1118, 1281)),
        # 100-point gap, favorite wins.
        (1100, 1000, 24, (1108, 991)),
        # 100-point gap, underdog wins.
        (1000, 1100, 24, (1015, 1084)),
    ],
)
def test_exact_integer_outputs(
    winner_elo: int, loser_elo: int, k_factor: int, expected: tuple[int, int]
) -> None:
    """Hand-computed cases match the production function exactly."""
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
    """Output matches an independent implementation of the Elo formula.

    Confirms the production function uses ``expected = 1/(1+10**((loser-winner)/
    400))`` and ``new = old + k*(score - expected)`` followed by ``int()``
    truncation.
    """
    assert calculate_elo_update(
        winner_elo, loser_elo, k_factor
    ) == _reference_elo_update(winner_elo, loser_elo, k_factor)


# --- Underdog vs favorite swing --------------------------------------------


def test_underdog_win_swings_more_than_favorite_win() -> None:
    """An upset moves ratings more than an expected result does.

    When the weaker hypothesis (1000) beats the stronger (1400) the winner
    gains far more than when the stronger (1400) beats the weaker (1000).
    """
    underdog_winner, _ = calculate_elo_update(1000, 1400, 24)
    favorite_winner, _ = calculate_elo_update(1400, 1000, 24)

    underdog_gain = underdog_winner - 1000
    favorite_gain = favorite_winner - 1400

    assert underdog_gain > favorite_gain
    assert underdog_gain == 21
    assert favorite_gain == 2


# --- K-factor behavior -----------------------------------------------------


def test_higher_k_factor_produces_larger_change() -> None:
    """A larger k-factor produces a larger rating change for equal ratings."""
    small_k_winner, _ = calculate_elo_update(1200, 1200, 16)
    large_k_winner, _ = calculate_elo_update(1200, 1200, 48)

    assert large_k_winner - 1200 > small_k_winner - 1200


def test_matchup_applies_run_specific_k_factor() -> None:
    """A committed real-engine matchup honors its run's K-factor."""
    hypothesis_a = Hypothesis(text="A")
    hypothesis_b = Hypothesis(text="B")

    outcome = _apply_matchup_elo(hypothesis_a, hypothesis_b, "a", k_factor=40)

    assert outcome.winner_elo_after == 1220
    assert outcome.loser_elo_after == 1180


def test_zero_k_factor_produces_no_change() -> None:
    """A k-factor of 0 leaves both ratings unchanged."""
    assert calculate_elo_update(1300, 1100, 0) == (1300, 1100)


def test_zero_k_factor_no_change_for_equal_ratings() -> None:
    """A k-factor of 0 leaves equal ratings unchanged."""
    assert calculate_elo_update(1200, 1200, 0) == (1200, 1200)


# --- Integer truncation (not rounding) -------------------------------------


def test_results_are_truncated_not_rounded() -> None:
    """Ratings are truncated with ``int()``, not rounded.

    For 1500 beating 1400 at k=24 the raw winner rating is ~1508.64 and the raw
    loser rating is ~1391.36. Rounding would give 1509 / 1391; truncation
    toward zero gives 1508 / 1391. The winner value is the observable case: it
    lands on 1508, proving truncation rather than rounding.
    """
    new_winner, new_loser = calculate_elo_update(1500, 1400, 24)

    assert new_winner == 1508  # round() would give 1509
    assert new_loser == 1391

    # Cross-check the raw (pre-truncation) values to document the intent.
    raw_winner = 1500 + 24 * (1 - 1 / (1 + 10 ** ((1400 - 1500) / 400)))
    raw_loser = 1400 + 24 * (0 - 1 / (1 + 10 ** ((1500 - 1400) / 400)))
    assert round(raw_winner) == 1509
    assert int(raw_winner) == new_winner
    assert int(raw_loser) == new_loser


def test_truncation_can_break_winner_loser_symmetry() -> None:
    """Truncation can make the winner's gain differ from the loser's loss.

    With unequal ratings the raw deltas are non-integer, so ``int()``
    truncation of each rating independently can yield asymmetric integer
    swings. For an upset (1000 beats 1400) the winner gains 21 but the loser
    drops 22.
    """
    new_winner, new_loser = calculate_elo_update(1000, 1400, 24)
    winner_gain = new_winner - 1000
    loser_drop = 1400 - new_loser
    assert winner_gain == 21
    assert loser_drop == 22
    assert winner_gain != loser_drop


# --- Property-style checks -------------------------------------------------

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
    """Across many pairs the winner's rating is >= old, loser's is <= old."""
    new_winner, new_loser = calculate_elo_update(winner_elo, loser_elo, 24)
    assert new_winner >= winner_elo
    assert new_loser <= loser_elo


@pytest.mark.parametrize("winner_elo, loser_elo", _RATING_PAIRS)
def test_total_points_conserved_within_truncation_error(
    winner_elo: int, loser_elo: int
) -> None:
    """Total points are conserved up to the truncation error.

    The raw (float) Elo update is exactly point-conserving: the winner's gain
    equals the loser's loss. After independent ``int()`` truncation of each
    rating, the total can drop by at most 2 (each rating truncates down by less
    than 1). Total can never increase.
    """
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
    """The function returns a 2-tuple of plain Python ints."""
    result = calculate_elo_update(winner_elo, loser_elo, 24)
    assert isinstance(result, tuple)
    assert len(result) == 2
    new_winner, new_loser = result
    assert isinstance(new_winner, int)
    assert isinstance(new_loser, int)


# --- K-annealing and margin-scaling reconstruction knobs --------------------
#
# Both knobs are paper-unspecified local reconstruction choices (the paper
# names neither a K-factor nor any schedule for it). They default to OFF so
# every rating a run produces today is byte-for-byte unchanged; the tests
# below pin both the off-default and the opt-in behavior.


def test_knobs_default_to_off_and_preserve_the_fixed_k() -> None:
    """With both knobs at their defaults the effective K is the base K.

    This is the default-preserving guarantee: a deployment that never touches
    the knobs computes exactly the historical update for every match.
    """
    assert annealed_k_factor(24, matches_played=500) == 24
    assert margin_scaled_k_factor(24, "High") == 24
    assert margin_scaled_k_factor(24, None) == 24
    assert effective_k_factor(24, matches_played=500, confidence="High") == 24


def test_annealing_disabled_by_a_nonpositive_half_life() -> None:
    """An explicit 0 (or negative) half-life leaves K untouched."""
    assert annealed_k_factor(24, 100, half_life=0) == 24
    assert annealed_k_factor(24, 100, half_life=-5) == 24
    # No matches played means nothing to anneal against either.
    assert annealed_k_factor(24, 0, half_life=30) == 24


def test_annealing_halves_k_per_half_life_of_matches() -> None:
    """Enabled annealing decays K as a hypothesis accumulates matches."""
    assert annealed_k_factor(24, 0, half_life=30) == 24
    assert annealed_k_factor(24, 29, half_life=30) == 24
    assert annealed_k_factor(24, 30, half_life=30) == 12
    assert annealed_k_factor(24, 59, half_life=30) == 12
    assert annealed_k_factor(24, 60, half_life=30) == 6


def test_annealing_floors_at_the_annealed_minimum() -> None:
    """Annealing never freezes a rating: K stops at the documented floor."""
    # 24 -> 12 -> 6; the floor is 6, so further halvings stay put.
    assert annealed_k_factor(24, 90, half_life=30) == 6
    assert annealed_k_factor(24, 10_000, half_life=30) == 6


def test_margin_scaling_disabled_by_a_nonpositive_scale() -> None:
    """An explicit 0 (or negative) scale leaves K untouched at any verdict."""
    assert margin_scaled_k_factor(24, "High", scale=0.0) == 24
    assert margin_scaled_k_factor(24, "High", scale=-1.0) == 24
    # No confidence reported means no margin signal either.
    assert margin_scaled_k_factor(24, None, scale=1.0) == 24
    assert margin_scaled_k_factor(24, "", scale=1.0) == 24


def test_margin_scaling_grows_k_with_decisiveness() -> None:
    """Enabled scaling weights a decisive verdict more than a narrow one."""
    assert margin_scaled_k_factor(24, "High", scale=1.0) == 48
    assert margin_scaled_k_factor(24, "Medium", scale=1.0) == 36
    # Low / unrecognized confidence carries no margin.
    assert margin_scaled_k_factor(24, "Low", scale=1.0) == 24
    assert margin_scaled_k_factor(24, "Unknown", scale=1.0) == 24


def test_margin_scaling_is_capped_at_the_multiplier_ceiling() -> None:
    """A decisive verdict cannot move a rating past the capped multiplier."""
    # scale 100 would be 1 + 100*1.0 without the cap; the cap is 5x.
    assert margin_scaled_k_factor(24, "High", scale=100.0) == 24 * 5


def test_effective_k_anneals_then_scales() -> None:
    """Composition: annealing first, the margin multiplier second."""
    # 30 matches halves 24 to 12; a High verdict at scale 1.0 doubles it.
    assert effective_k_factor(24, 30, confidence="High") == (
        margin_scaled_k_factor(annealed_k_factor(24, 30), "High")
    )


def test_apply_matchup_elo_default_is_unchanged_with_confidence() -> None:
    """Passing a verdict confidence does nothing while the knobs are off."""
    hyp_a = Hypothesis(text="A")
    hyp_b = Hypothesis(text="B")
    outcome = _apply_matchup_elo(
        hyp_a, hyp_b, "a", k_factor=24, confidence="High"
    )
    assert (outcome.winner_elo_after, outcome.loser_elo_after) == (1212, 1188)


def test_per_side_k_factor_updates_each_side_independently() -> None:
    """A distinct loser K-factor weights only the loser's update.

    Winner at K=24 and loser at K=12 from equal ratings: the winner still
    gains the full 12 (24 * 0.5) while the loser drops only 6 (12 * 0.5).
    """
    new_winner, new_loser = calculate_elo_update(
        1200, 1200, 24, loser_k_factor=12
    )
    assert (new_winner, new_loser) == (1212, 1194)


def test_annealing_applies_per_side_from_each_own_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With annealing on, each side's update uses its own match count.

    A well-played loser (rating already settled) moves less than a fresh
    winner, because the loser's K has annealed while the winner's has not.
    """
    monkeypatch.setattr(ranking_elo, "ELO_K_ANNEALING_HALF_LIFE", 2)
    winner = Hypothesis(text="fresh winner")  # 0 matches -> K stays 24
    loser = Hypothesis(text="veteran loser")
    loser.win_count = 2  # 2 matches -> one halving -> K drops to 12
    loser.loss_count = 0

    outcome = _apply_matchup_elo(winner, loser, "a", k_factor=24)

    # Winner gains the full equal-rating step (24 * 0.5 = 12).
    assert outcome.winner_elo_after == 1212
    # Loser drops half as much (12 * 0.5 = 6) because its K annealed.
    assert outcome.loser_elo_after == 1194


def test_margin_scaling_applies_from_the_verdict_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With margin scaling on, a decisive verdict moves ratings further."""
    monkeypatch.setattr(ranking_elo, "ELO_MARGIN_VICTORY_SCALE", 1.0)
    decisive_a = Hypothesis(text="decisive A")
    decisive_b = Hypothesis(text="decisive B")
    outcome = _apply_matchup_elo(
        decisive_a, decisive_b, "a", k_factor=24, confidence="High"
    )
    # High confidence doubles the effective K (24 -> 48): equal ratings now
    # swing 24 points instead of 12.
    assert outcome.winner_elo_after == 1224
    assert outcome.loser_elo_after == 1176

    # A narrow verdict (no margin) keeps the base K even while enabled.
    narrow_a = Hypothesis(text="narrow A")
    narrow_b = Hypothesis(text="narrow B")
    narrow = _apply_matchup_elo(
        narrow_a, narrow_b, "a", k_factor=24, confidence="Low"
    )
    assert narrow.winner_elo_after == 1212
    assert narrow.loser_elo_after == 1188


def test_equal_elo_orders_the_same_way_everywhere() -> None:
    """Untouched hypotheses order identically wherever they are ranked.

    Every hypothesis leaves generation at the same seed rating and score, so
    until a tournament separates them the text tiebreak decides the whole
    order. The ranking node publishes one order and the research overview
    re-derives its top-k with ``rank_by_elo``; when the two tiebreaks ran in
    opposite directions those lists were reverses of each other, and the run
    reported a different "strongest idea" depending on which surface asked.
    """
    tied = [make_hypothesis(text=text) for text in ("alpha", "gamma", "beta")]
    assert {h.elo_rating for h in tied} == {INITIAL_ELO_RATING}
    assert {h.score for h in tied} == {0.0}

    node_order = [h.text for h in _sort_hypotheses_by_elo(tied)]

    assert node_order == [h.text for h in rank_by_elo(tied)]
    assert node_order == ["gamma", "beta", "alpha"]


def test_unrankable_ideas_sort_last_without_a_second_comparison() -> None:
    """The tournament's extra rule is a partition over the shared ordering.

    ``zeta`` would lead on the text tiebreak, so a quarantined idea sinking
    to the bottom is the rule doing work rather than the tiebreak happening
    to agree with it -- and the rankable ideas it leaves above keep exactly
    the order ``rank_by_elo`` gave them.
    """
    blocked = make_hypothesis(
        text="zeta", review_disposition="evidence_blocked"
    )
    rankable = [make_hypothesis(text=text) for text in ("alpha", "beta")]

    ordered = _sort_hypotheses_by_elo([blocked, *rankable])

    assert [h.text for h in ordered] == ["beta", "alpha", "zeta"]


def test_an_undermined_idea_sorts_below_every_sound_one() -> None:
    """Deep verification demotes an idea; it no longer removes it.

    An undermined idea ranks and publishes, so nothing else keeps it off
    the top of the list -- and it reached deep verification precisely by
    leading the tournament, which means the Elo it carries would otherwise
    put it first. ``yankee`` here holds the pool's highest rating and still
    lands below both sound ideas, above only the idea a gate refused
    outright.
    """
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
    """The tiebreak only decides ties, in both orderings.

    A guard on the composition: sorting the shared ordering by rankability
    must be stable, or the Elo ranking it was handed would be re-shuffled.
    """
    pool = [
        make_hypothesis(text="alpha", elo_rating=1400),
        make_hypothesis(text="zeta", elo_rating=1200),
    ]

    assert [h.text for h in _sort_hypotheses_by_elo(pool)] == ["alpha", "zeta"]
    assert [h.text for h in rank_by_elo(pool)] == ["alpha", "zeta"]


async def test_tournament_complete_marks_a_truncated_winner() -> None:
    """A cut idea reaches the UI as cut, not as a complete short one.

    ``top_hypothesis`` is a 200-character window onto the winning idea, and a
    bare slice leaves nothing to tell a long idea's opening 200 characters
    from a short idea stated in full.
    """
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
    """A peer-reviewed hypothesis, as every idea a tournament sees is.

    The coverage floor is owed only to ideas the run has already reviewed
    (``ranking_lifecycle._coverage_floor``), and the graph routes review
    before ranking, so a fixture with no review is not a pool this node
    ever meets.
    """
    return make_hypothesis(text=text, reviews=[make_review()], **overrides)


def test_match_tier_upset_when_loser_outrated_winner() -> None:
    """A deep-underdog win is an upset regardless of confidence.

    Specifically, a win by a hypothesis rated >= ELO_UPSET_MARGIN below
    the loser.
    """
    from co_scientist.constants import ELO_UPSET_MARGIN

    assert ranking.match_tier(1200, 1200 + ELO_UPSET_MARGIN, "High") == "upset"
    assert ranking.match_tier(1200, 1200 + ELO_UPSET_MARGIN, "Low") == "upset"


def test_match_tier_maps_confidence_when_not_an_upset() -> None:
    """Absent an upset, tier follows the judge's confidence level."""
    assert ranking.match_tier(1300, 1200, "High") == "decisive"
    assert ranking.match_tier(1300, 1200, "Medium") == "clear"
    assert ranking.match_tier(1300, 1200, "Low") == "narrow"


def test_match_tier_confidence_is_case_insensitive_with_narrow_fallback() -> (
    None
):
    """Casing is ignored and an unknown confidence falls back to 'narrow'."""
    assert ranking.match_tier(1300, 1200, "high") == "decisive"
    assert ranking.match_tier(1300, 1200, "") == "narrow"
    assert ranking.match_tier(1300, 1200, "Unknown") == "narrow"


def test_matchup_judging_survives_more_than_one_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The judge's concurrency bound must not be shared across event loops.

    The durable worker runs each scientific task on its own thread with its
    own event loop, so an ``asyncio.Semaphore`` created once at import time
    binds to whichever loop first waits on it and then raises
    "is bound to a different event loop" from every other. It only stayed
    hidden while the tournament judged fewer matchups than the semaphore had
    permits and therefore never actually waited; once a wave filled, a real
    ranking task died on it in production.
    """
    import asyncio

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"winner": "A", "reasoning": "because"}

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake_call_llm_json)

    hyp_a = _hyp(text="a")
    hyp_b = _hyp(text="b")

    async def judge_a_full_wave() -> None:
        """Force real contention so the semaphore has to wait."""
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


# --- coverage guarantee: no rankable idea leaves the tournament short ------


async def test_every_rankable_idea_reaches_the_minimum_match_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduling honors the coverage minimum instead of stopping early.

    Reproduced the audit shape: a pool where one idea has never played and the
    rest already carry a win-loss record. The coverage floor used to fund that
    idea a single round (``ceil(2/2)``), it played once, and the tournament
    stopped with it one match short of the minimum -- a rating indistinguish-
    able from a coin flip. The floor now counts the idea's own two rounds, so
    the tournament keeps going until every rankable idea has a record.
    """
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
    """Each matchup records the cycle it was judged in, not a constant.

    The persisted match row has an ``iteration`` column and nothing on
    either execution path ever filled it: production extended run bc77950f
    ran three iterations and every one of its 23 matches stored iteration
    0, so the Elo history could not be read back by cycle.
    """
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
    """Build candidates from (id, elo, matches, cluster) tuples."""
    return [MatchCandidate(i, e, m, c) for (i, e, m, c) in specs]


def test_no_self_or_immediate_duplicate_matches() -> None:
    """No pairing pits a hypothesis against itself; no back-to-back rematch."""
    candidates = _cands(
        ("a", 1200, 0, None),
        ("b", 1200, 0, None),
        ("c", 1200, 0, None),
        ("d", 1200, 0, None),
    )
    pairs = build_weighted_pairings(candidates, rounds=12, seed=7)
    for x, y in pairs:
        assert x != y  # no self-match
    # No identical pair appears twice in a row.
    for prev, cur in itertools.pairwise(pairs):
        assert set(prev) != set(cur)


def test_minimum_coverage_reached_no_starvation() -> None:
    """Every hypothesis reaches the minimum match coverage before extras."""
    candidates = _cands(
        ("a", 1400, 0, None),
        ("b", 1200, 0, None),
        ("c", 1100, 0, None),
        ("d", 1000, 0, None),
        ("e", 900, 0, None),
    )
    # Exactly enough rounds to cover 5 hypotheses at 1 match each needs at
    # least ceil(5/2)=3 rounds; give a few more and require full coverage.
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
    """Hypotheses with fewer prior matches play more, all else equal."""
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
    # The three fresh hypotheses collectively play more than the veteran.
    fresh = played["newA"] + played["newB"] + played["newC"]
    assert fresh > played["veteran"] * 2


def test_top_ranked_hypotheses_are_prioritized() -> None:
    """Higher-Elo hypotheses are matched more often, coverage being equal.

    Scheduled well under the pool's distinct-pair ceiling (4 of a possible
    10), because that is the only regime where the weights decide anything:
    a build allowed to schedule every pair matches everyone equally by
    construction. Summed over seeds so the claim is about the weighting and
    not about one lucky draw.
    """
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
    """Partners in the same proximity cluster are compared more often.

    Two clusters of three, so 6 of the 15 distinct pairs are same-cluster
    and 9 are cross-cluster: preferring similarity has to beat those odds.
    Scheduled at 6 rounds rather than exhaustively, since a build that
    takes every pair takes all 9 cross-cluster ones too.
    """
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
        # ids share their first letter within a cluster
        same = sum(1 for x, y in pairs if x[0] == y[0])
        same_cluster += same
        cross_cluster += len(pairs) - same
    assert same_cluster > cross_cluster


def test_close_elo_hypotheses_are_preferred() -> None:
    """Partners with a closer Elo rating are compared more often.

    Mirrors ``test_similar_hypotheses_are_preferred``'s two-group design,
    grouping by Elo distance instead of proximity cluster: a1-a3 sit
    within 20 points of each other, b1-b3 within 20 points of each other,
    and the two groups sit 400 points apart. ``rank`` is zeroed so the
    existing higher-Elo-wins-more-matches bias (which would otherwise
    over-select the b-group on both sides of a match regardless of any
    closeness term) cannot produce this result on its own -- only
    ``elo_closeness`` can. Prioritizing close Elo ratings (Nature SI
    Note 8, 04-ranking.md: "or those with similar Elo ratings") should
    pull matches toward the 6 in-group pairs over the 9 cross-group ones.
    """
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
    """A fixed seed replays the identical schedule."""
    candidates = _cands(
        ("a", 1300, 2, "c1"),
        ("b", 1200, 4, "c1"),
        ("c", 1100, 1, "c2"),
        ("d", 1000, 3, "c2"),
    )
    first = build_weighted_pairings(candidates, rounds=15, seed=42)
    second = build_weighted_pairings(candidates, rounds=15, seed=42)
    assert first == second
    # A different seed generally yields a different schedule.
    other = build_weighted_pairings(candidates, rounds=15, seed=43)
    assert other != first


def test_fewer_than_two_candidates_yields_no_pairs() -> None:
    """A single-candidate (or empty) pool cannot be paired."""
    assert build_weighted_pairings(_cands(("a", 1200, 0, None)), 5, 1) == []
    assert build_weighted_pairings([], 5, 1) == []


def test_a_pair_is_never_scheduled_twice_in_one_build() -> None:
    """One build picks every matchup from a single Elo snapshot.

    Re-scheduling a pair it has already chosen therefore replays a
    comparison rather than making one, and moves the winner's rating for
    it. Asking for far more rounds than the pool has pairs must yield the
    pairs it has, not repeats.
    """
    candidates = _cands(
        ("a", 1200, 0, None),
        ("b", 1200, 0, None),
        ("c", 1200, 0, None),
        ("d", 1200, 0, None),
    )
    pairs = build_weighted_pairings(candidates, rounds=50, seed=3)

    assert len(pairs) == len({frozenset(pair) for pair in pairs})
    # 4 candidates admit exactly 4*3/2 distinct pairs.
    assert len(pairs) == 6


def test_two_rankable_ideas_yield_one_match_not_a_ratchet() -> None:
    """The production failure: a two-idea pool judged one pair six times.

    Every run in production spent its whole tournament this way, and the
    winner was reported at 1259 as though it had beaten six opponents when
    it had beaten one opponent six times.
    """
    candidates = _cands(("a", 1200, 0, None), ("b", 1200, 0, None))

    pairs = build_weighted_pairings(candidates, rounds=6, seed=1)

    assert pairs == [("a", "b")] or pairs == [("b", "a")]


def test_every_candidate_is_matched_when_rounds_allow() -> None:
    """No hypothesis leaves a build unmatched while rounds remain.

    An unmatched hypothesis keeps its starting rating, which then reads as
    a tournament result it never earned.
    """
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

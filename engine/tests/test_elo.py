from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.ranking import ranking
from co_scientist.agents.ranking.ranking import (
    calculate_elo_update,
)
from co_scientist.agents.ranking.ranking_debate import (
    annealed_k_factor,
    margin_scaled_k_factor,
)
from co_scientist.agents.ranking.ranking_matchmaking import (
    MatchCandidate,
    build_weighted_pairings,
)
from co_scientist.constants import (
    ELO_UPSET_MARGIN,
)
from co_scientist.models import Hypothesis
from tests._state import make_hypothesis, make_review

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


# These optional reconstruction knobs default off to preserve existing ratings.


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


def _hyp(text: str = "a hypothesis", **overrides: Any) -> Hypothesis:
    """Tournament entrants require completed review stamps."""
    return make_hypothesis(text=text, reviews=[make_review()], **overrides)


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

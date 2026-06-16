# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for the Elo/ranking pure logic and rating constants.

These tests lock in the *current* behavior of ``calculate_elo_update`` and the
Elo rating constants as a regression net for upcoming refactors. They exercise
only pure functions - no LLM calls and therefore no mocking are involved.
"""

import pytest

from co_scientist.constants import ELO_K_FACTOR
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.nodes.ranking import calculate_elo_update


def _reference_elo_update(winner_elo: int, loser_elo: int,
                          k_factor: int) -> tuple[int, int]:
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
    expected_winner = 1 / (1 + 10**((loser_elo - winner_elo) / 400))
    expected_loser = 1 / (1 + 10**((winner_elo - loser_elo) / 400))
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
    assert (calculate_elo_update(1200, 1200) == calculate_elo_update(
        1200, 1200, ELO_K_FACTOR))


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
def test_exact_integer_outputs(winner_elo: int, loser_elo: int, k_factor: int,
                               expected: tuple[int, int]) -> None:
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
def test_matches_standard_elo_formula(winner_elo: int, loser_elo: int,
                                      k_factor: int) -> None:
    """Output matches an independent implementation of the Elo formula.

    Confirms the production function uses ``expected = 1/(1+10**((loser-winner)/
    400))`` and ``new = old + k*(score - expected)`` followed by ``int()``
    truncation.
    """
    assert (calculate_elo_update(winner_elo, loser_elo,
                                 k_factor) == _reference_elo_update(
                                     winner_elo, loser_elo, k_factor))


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
    raw_winner = 1500 + 24 * (1 - 1 / (1 + 10**((1400 - 1500) / 400)))
    raw_loser = 1400 + 24 * (0 - 1 / (1 + 10**((1500 - 1400) / 400)))
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
def test_winner_never_decreases_loser_never_increases(winner_elo: int,
                                                      loser_elo: int) -> None:
    """Across many pairs the winner's rating is >= old, loser's is <= old."""
    new_winner, new_loser = calculate_elo_update(winner_elo, loser_elo, 24)
    assert new_winner >= winner_elo
    assert new_loser <= loser_elo


@pytest.mark.parametrize("winner_elo, loser_elo", _RATING_PAIRS)
def test_total_points_conserved_within_truncation_error(winner_elo: int,
                                                        loser_elo: int) -> None:
    """Total points are conserved up to the truncation error.

    The raw (float) Elo update is exactly point-conserving: the winner's gain
    equals the loser's loss. After independent ``int()`` truncation of each
    rating, the total can drop by at most 2 (each rating truncates down by less
    than 1). Total can never increase.
    """
    k_factor = 24
    new_winner, new_loser = calculate_elo_update(winner_elo, loser_elo,
                                                 k_factor)

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

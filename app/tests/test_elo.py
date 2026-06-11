"""Elo invariants: initial rating, expected score, configurable K factor, symmetric update."""
from __future__ import annotations

from app.elo import DEFAULT_K_FACTOR, INITIAL_ELO, expected_score, update_pair


def test_initial_elo_is_1200():
    assert INITIAL_ELO == 1200


def test_expected_score_equal_ratings_is_half():
    assert expected_score(1500, 1500) == 0.5


def test_expected_score_higher_player_above_half():
    e = expected_score(1600, 1400)
    assert 0.5 < e < 1.0
    # 200-point gap → ~0.76 by standard Elo
    assert abs(e - 0.7597) < 0.01


def test_update_pair_zero_sum_in_integer_form():
    w, l = update_pair(1200, 1200)
    # Equal ratings → winner gains K/2, loser loses K/2
    assert w + l == 2400  # zero-sum
    assert w == 1212
    assert l == 1188


def test_update_pair_respects_k_factor():
    w_default, _ = update_pair(1200, 1200)
    w_high, _ = update_pair(1200, 1200, k_factor=64)
    assert w_high - 1200 > w_default - 1200
    assert w_default - 1200 == DEFAULT_K_FACTOR // 2


def test_update_pair_upset_amplifies_change():
    """Beating a much stronger opponent yields a larger swing than peer wins."""
    w_upset, l_upset = update_pair(1400, 1600)
    w_peer, _ = update_pair(1200, 1200)
    assert (w_upset - 1400) > (w_peer - 1200)

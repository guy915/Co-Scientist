"""Elo invariants.

The actual Elo update math lives in the engine
(``co_scientist.agents.ranking.ranking.calculate_elo_update``); this only
covers the app-owned initial rating constant.
"""

from __future__ import annotations

from app.elo import INITIAL_ELO


def test_initial_elo_is_1200() -> None:
    assert INITIAL_ELO == 1200

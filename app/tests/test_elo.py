"""Elo defaults and ordering agree with the engine."""

from __future__ import annotations

import pytest

from app import elo
from app.elo import INITIAL_ELO


def test_initial_elo_is_1200() -> None:
    assert INITIAL_ELO == 1200


def test_leaderboard_ranks_played_ideas_above_unplayed_ones() -> None:
    """Never having competed must not outrank having competed and lost.

    Every hypothesis starts at INITIAL_ELO, so a pure Elo sort promotes the
    ideas the tournament never reached. A production run led its standings
    with six unplayed ideas at 1200 and put the genuine runner-up, which had
    actually lost a match at 1136, beneath all of them.
    """
    from app.elo import live_leaderboard

    rows = live_leaderboard(
        [
            {"id": "unplayed", "title": "Never matched", "elo_rating": 1200},
            {
                "id": "loser",
                "title": "Lost a match",
                "elo_rating": 1136,
                "loss_count": 1,
            },
            {
                "id": "winner",
                "title": "Won a match",
                "elo_rating": 1259,
                "win_count": 1,
            },
        ]
    )

    assert [row["id"] for row in rows] == ["winner", "loser", "unplayed"]


constants = pytest.importorskip("co_scientist.constants")


def test_elo_constants_match_engine() -> None:
    """The app's default Elo tuning mirrors the engine's constants."""
    assert elo.INITIAL_ELO == constants.INITIAL_ELO_RATING
    assert elo.DEFAULT_K_FACTOR == constants.ELO_K_FACTOR

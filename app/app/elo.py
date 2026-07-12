"""Pure-Python Elo helpers used by the mock workflow and tests.

Mirrors the formula in `co_scientist.nodes.ranking.calculate_elo_update`
so the clone's tournament behaviour is consistent across mock and real paths.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.text_utils import coalesce, hypothesis_id, hypothesis_title

# All three constants are sourced from Settings (not hardcoded here) so the
# mock and the real engine can be tuned from the same env-driven config.
INITIAL_ELO: int = settings.elo_initial
DEFAULT_K_FACTOR: int = settings.elo_k_factor
# Pre-match Elo gap at which a lower-rated winner counts as an upset. Mirrors
# the engine's ELO_UPSET_MARGIN (constants.py).
UPSET_MARGIN: int = settings.elo_upset_margin

# Canonical per-match decisiveness labels, mirroring the engine's
# ``ranking.match_tier`` outputs. The app owns this vocabulary; the mock
# workflow unpacks it for its tier labels and test_elo_engine_parity guards it
# against engine drift.
MATCH_TIERS: tuple[str, ...] = ("upset", "decisive", "clear", "narrow")


def expected_score(player_elo: float, opponent_elo: float) -> float:
    """Standard Elo expected score for `player` against `opponent`."""
    # Logistic curve; 400 is the standard Elo scaling constant (a 400-point
    # rating gap implies a 10:1 expected-score ratio between the players).
    result: float = 1.0 / (1.0 + 10.0 ** ((opponent_elo - player_elo) / 400.0))
    return result


def update_pair(
    winner_elo: int,
    loser_elo: int,
    k_factor: int = DEFAULT_K_FACTOR,
) -> tuple[int, int]:
    """Return integer-rounded post-match Elo for (winner, loser)."""
    e_win = expected_score(winner_elo, loser_elo)
    e_lose = expected_score(loser_elo, winner_elo)
    # Actual score is 1 for the winner and 0 for the loser; k_factor scales
    # how far the rating moves toward that actual outcome from expectation.
    new_winner = winner_elo + k_factor * (1.0 - e_win)
    new_loser = loser_elo + k_factor * (0.0 - e_lose)
    return round(new_winner), round(new_loser)


def _leaderboard_row(rank: int, h: dict[str, Any]) -> dict[str, Any]:
    """Format one hypothesis as a compact leaderboard standings row.

    Args:
        rank: The hypothesis's 1-based Elo rank within the leaderboard.
        h: A hypothesis dict carrying ``elo_rating``, ``win_count``,
            ``loss_count``, and a title under ``title`` or ``text``.

    Returns:
        A ``{rank, id, title, elo, wins, losses}`` dict.
    """
    return {
        "rank": rank,
        "id": hypothesis_id(h),
        "title": hypothesis_title(h),
        "elo": int(
            coalesce(h.get("elo_rating", INITIAL_ELO), default=INITIAL_ELO)
        ),
        "wins": int(coalesce(h.get("win_count", 0), default=0)),
        "losses": int(coalesce(h.get("loss_count", 0), default=0)),
    }


def live_leaderboard(
    hyps: list[dict[str, Any]], cap: int = 10
) -> list[dict[str, Any]]:
    """Compact Elo standings snapshot carried on workflow event payloads.

    Shared by the engine adapter and the mock workflow so the frontend's
    live-standings reader sees one payload shape across providers.

    Args:
        hyps: Hypothesis dicts carrying ``elo_rating``, ``win_count``,
            ``loss_count``, and a title under ``title`` or ``text``.
        cap: Maximum number of standings to include.

    Returns:
        A list of ``{rank, id, title, elo, wins, losses}`` dicts, Elo-sorted.
    """
    # Descending Elo sort; falsy ratings (0/None) fall back to INITIAL_ELO
    # rather than sorting an unranked hypothesis to the very top.
    ordered = sorted(
        hyps,
        key=lambda h: -int(h.get("elo_rating", INITIAL_ELO) or INITIAL_ELO),
    )
    return [
        _leaderboard_row(rank, h)
        for rank, h in enumerate(ordered[:cap], start=1)
    ]

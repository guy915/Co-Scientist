"""Pure-Python Elo helpers used by the mock workflow and tests.

Mirrors the formula in `co_scientist.nodes.ranking.calculate_elo_update`
so the clone's tournament behaviour is consistent across mock and real paths.
"""

from __future__ import annotations

import os
from typing import Any


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


INITIAL_ELO: int = _env_int("ELO_INITIAL", 1200)
DEFAULT_K_FACTOR: int = _env_int("ELO_K_FACTOR", 24)
# Pre-match Elo gap at which a lower-rated winner counts as an upset. Mirrors
# the engine's ELO_UPSET_MARGIN (constants.py).
UPSET_MARGIN: int = _env_int("ELO_UPSET_MARGIN", 100)


def expected_score(player_elo: float, opponent_elo: float) -> float:
    """Standard Elo expected score for `player` against `opponent`."""
    result: float = 1.0 / (1.0 + 10.0**((opponent_elo - player_elo) / 400.0))
    return result


def update_pair(
    winner_elo: int,
    loser_elo: int,
    k_factor: int = DEFAULT_K_FACTOR,
) -> tuple[int, int]:
    """Return integer-rounded post-match Elo for (winner, loser)."""
    e_win = expected_score(winner_elo, loser_elo)
    e_lose = expected_score(loser_elo, winner_elo)
    new_winner = winner_elo + k_factor * (1.0 - e_win)
    new_loser = loser_elo + k_factor * (0.0 - e_lose)
    return int(round(new_winner)), int(round(new_loser))


def live_leaderboard(hyps: list[dict[str, Any]],
                     cap: int = 10) -> list[dict[str, Any]]:
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
    ordered = sorted(
        hyps,
        key=lambda h: -int(h.get("elo_rating", INITIAL_ELO) or INITIAL_ELO))
    out: list[dict[str, Any]] = []
    for rank, h in enumerate(ordered[:cap], start=1):
        title = str(h.get("title") or h.get("text") or "Untitled")
        out.append({
            "rank": rank,
            "id": str(h.get("id") or h.get("hypothesis_id") or title),
            "title": title[:140],
            "elo": int(h.get("elo_rating", INITIAL_ELO) or INITIAL_ELO),
            "wins": int(h.get("win_count", 0) or 0),
            "losses": int(h.get("loss_count", 0) or 0),
        })
    return out

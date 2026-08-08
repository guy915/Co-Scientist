"""Elo leaderboard helpers shared by the engine adapter and the frontend.

The engine is the only workflow provider; it owns the actual Elo update math
(``co_scientist.agents.ranking.ranking.calculate_elo_update``). What remains
here is the app-side leaderboard projection both the live event payloads and
the final report render from.
"""

from __future__ import annotations

from typing import Any

from co_scientist.constants import INITIAL_ELO_RATING

from app.config import settings
from app.text_utils import coalesce, hypothesis_id, hypothesis_title

# Re-exports the engine's constant so the initial rating has a single home;
# DEFAULT_K_FACTOR stays app-owned (sourced from Settings) so per-deployment
# tuning does not require an engine change.
INITIAL_ELO: int = INITIAL_ELO_RATING
DEFAULT_K_FACTOR: int = settings.elo_k_factor


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


def rank_for_publication(
    hyps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Order hypothesis rows the way a reader should meet them.

    Every reader-facing surface has to agree on this, or the same run tells
    two stories: the store returns rows by raw Elo, so the report body and
    the standings beside it would open with different ideas.

    Args:
        hyps: Hypothesis dicts carrying ``elo_rating``, ``win_count``,
            ``loss_count``, and ``verification_verdict``.

    Returns:
        The same rows, sound played hypotheses first, then sound unplayed
        ones, then the ideas deep verification undermined, each group by
        descending Elo.
    """

    def _played(h: dict[str, Any]) -> int:
        return int(h.get("win_count") or 0) + int(h.get("loss_count") or 0)

    def _undermined(h: dict[str, Any]) -> int:
        return 1 if h.get("verification_verdict") == "undermined" else 0

    # Undermined ideas sort below everything, mirroring the engine's
    # rank_for_publication. They publish, but their Elo argues the opposite
    # of their verdict: deep verification only probes the ideas leading the
    # tournament, and the verdict lands after the matches that put them
    # there, so on rating alone the run's most doubted idea heads its own
    # standings.
    #
    # Then hypotheses that played at least one match rank above those that
    # did not, whatever the ratings say. Every hypothesis starts at
    # INITIAL_ELO, so a pure Elo sort puts an idea that never entered the
    # tournament above one that entered and lost: a run led its standings
    # with six unplayed ideas at 1200 and buried the real runner-up at 1136
    # beneath them. Falsy ratings (0/None) still fall back to INITIAL_ELO
    # rather than sorting to the very bottom.
    return sorted(
        hyps,
        key=lambda h: (
            _undermined(h),
            0 if _played(h) else 1,
            -int(h.get("elo_rating", INITIAL_ELO) or INITIAL_ELO),
        ),
    )


def live_leaderboard(
    hyps: list[dict[str, Any]], cap: int = 10
) -> list[dict[str, Any]]:
    """Compact Elo standings snapshot carried on workflow event payloads.

    The one payload shape the frontend's live-standings reader relies on.

    Args:
        hyps: Hypothesis dicts carrying ``elo_rating``, ``win_count``,
            ``loss_count``, and a title under ``title`` or ``text``.
        cap: Maximum number of standings to include.

    Returns:
        A list of ``{rank, id, title, elo, wins, losses}`` dicts in
        ``rank_for_publication`` order.
    """
    ordered = rank_for_publication(hyps)
    return [
        _leaderboard_row(rank, h)
        for rank, h in enumerate(ordered[:cap], start=1)
    ]

from __future__ import annotations

from typing import Any

from co_scientist.constants import INITIAL_ELO_RATING

from app.config import settings
from app.text_utils import coalesce, hypothesis_id, hypothesis_title

# Initial Elo stays engine-owned; the app owns deployment-tunable K-factor.
INITIAL_ELO: int = INITIAL_ELO_RATING
DEFAULT_K_FACTOR: int = settings.elo_k_factor


def _leaderboard_row(rank: int, h: dict[str, Any]) -> dict[str, Any]:
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
    """Every reader-facing surface must use the same order; raw store Elo
    alone can put an undermined or unplayed idea first.
    """

    # Verification follows tournament wins, so raw Elo can lead with an
    # undermined idea; unplayed baseline ratings also must not outrank tested
    # candidates.
    return sorted(
        hyps,
        key=lambda h: (
            1 if h.get("verification_verdict") == "undermined" else 0,
            0
            if int(h.get("win_count") or 0) + int(h.get("loss_count") or 0)
            else 1,
            -int(h.get("elo_rating", INITIAL_ELO) or INITIAL_ELO),
        ),
    )


def live_leaderboard(
    hyps: list[dict[str, Any]], cap: int = 10
) -> list[dict[str, Any]]:
    ordered = rank_for_publication(hyps)
    return [
        _leaderboard_row(rank, h)
        for rank, h in enumerate(ordered[:cap], start=1)
    ]

"""Cross-check the app's Elo tuning and tier vocabulary against the engine.

The app deliberately re-declares Elo constants (``app/elo.py``) and the mock
workflow's tier labels so the viewer can run without the engine installed.
That duplication is intentional, but it must not silently drift: these tests
pin the app-side values to the engine's owners. They skip when the engine is
not importable (e.g. the mock-only deployment the duplication exists for).
"""

from __future__ import annotations

import pytest

from app import elo

constants = pytest.importorskip("co_scientist.constants")
ranking = pytest.importorskip("co_scientist.nodes.ranking")


def test_elo_constants_match_engine() -> None:
    """The app's default Elo tuning mirrors the engine's constants."""
    assert elo.INITIAL_ELO == constants.INITIAL_ELO_RATING
    assert elo.DEFAULT_K_FACTOR == constants.ELO_K_FACTOR
    assert elo.UPSET_MARGIN == constants.ELO_UPSET_MARGIN


def test_match_tier_labels_match_engine() -> None:
    """Every label the engine's match_tier can emit is in the app's set."""
    gap = constants.ELO_UPSET_MARGIN
    produced = {
        # upset: loser rated far above winner
        ranking.match_tier(1200, 1200 + gap, "high"),
        # decisive / clear / narrow: no upset gap, keyed on confidence
        ranking.match_tier(1200, 1200, "high"),
        ranking.match_tier(1200, 1200, "medium"),
        ranking.match_tier(1200, 1200, "low"),
    }
    assert produced == set(elo.MATCH_TIERS)

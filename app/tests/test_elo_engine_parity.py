"""Cross-check the app's Elo tuning against the engine.

``app/elo.py``'s ``INITIAL_ELO`` is a direct re-export of the engine's
constant, so it cannot drift; ``DEFAULT_K_FACTOR`` stays independently
app-owned (env-tunable per deployment), so this pins it to the engine's
default. Skips when the engine is not importable.
"""

from __future__ import annotations

import pytest

from app import elo

constants = pytest.importorskip("co_scientist.constants")


def test_elo_constants_match_engine() -> None:
    """The app's default Elo tuning mirrors the engine's constants."""
    assert elo.INITIAL_ELO == constants.INITIAL_ELO_RATING
    assert elo.DEFAULT_K_FACTOR == constants.ELO_K_FACTOR

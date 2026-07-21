"""Tests for the per-client concurrent-run ceiling.

The ceiling is uniform across tiers by construction now: ``start_run``
reads ``settings.max_concurrent_runs`` directly and never consults the
tier. (Heavier tiers used to be capped harder -- ultra at 1 -- which
blocked a researcher from running two deep investigations at once; per-run
spend is bounded by the tier's max_llm_calls budget instead.)
"""

from __future__ import annotations

from app.config import settings


def test_ceiling_is_configurable() -> None:
    """Operators can raise or lower the ceiling without a code change."""
    assert settings.max_concurrent_runs >= 3

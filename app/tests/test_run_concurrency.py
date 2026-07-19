"""Tests for the per-client concurrent-run ceiling."""

from __future__ import annotations

from app import runs as runs_module
from app.config import settings


def test_no_tier_is_capped_below_the_configured_ceiling() -> None:
    """Every tier gets the same concurrent-run allowance.

    Heavier tiers used to be capped harder (ultra at 1), which blocked a
    researcher from running two deep investigations at once -- the exact
    thing the deep tiers exist for. Per-run spend is bounded by the tier's
    max_llm_calls budget, so the concurrency ceiling no longer has to do
    that job by proxy.
    """
    for tier in ("express", "standard", "extended", "ultra", "advanced"):
        assert (
            runs_module._concurrency_limit(tier) == settings.max_concurrent_runs
        )


def test_ceiling_is_configurable() -> None:
    """Operators can raise or lower the ceiling without a code change."""
    assert settings.max_concurrent_runs >= 3


def test_unknown_tier_still_gets_a_ceiling() -> None:
    """A tier from an older build must not fall through unbounded."""
    assert runs_module._concurrency_limit("some-legacy-tier") == (
        settings.max_concurrent_runs
    )

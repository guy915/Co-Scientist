"""The research-overview accuracy review is funded by tier.

The review checks the terminal synthesis against this run's own material
-- extra LLM calls on top of the terminal synthesis -- so it is funded
the same way the executed simulation review is: the deep tiers only, and
the toggle is a ceiling the engine may still refuse (offline backend).
"""

from typing import Any

import pytest

from app.engine_adapter.opts import _resolve_overview_review_toggle


def _cfg(tier: str | None) -> dict[str, Any]:
    """A resolved run config carrying only the tier under test."""
    return {"tier": tier}


@pytest.mark.parametrize("tier", ["extended", "ultra"])
def test_deep_tiers_fund_an_overview_review(tier: str) -> None:
    assert _resolve_overview_review_toggle(_cfg(tier)) is True


@pytest.mark.parametrize("tier", ["express", "standard"])
def test_fast_tiers_publish_unreviewed(tier: str) -> None:
    assert _resolve_overview_review_toggle(_cfg(tier)) is False


def test_an_unset_tier_falls_back_to_the_default_tier() -> None:
    assert _resolve_overview_review_toggle(_cfg(None)) is False
    assert _resolve_overview_review_toggle({}) is False


def test_a_legacy_tier_name_resolves_before_the_gate() -> None:
    assert _resolve_overview_review_toggle(_cfg("advanced")) is True

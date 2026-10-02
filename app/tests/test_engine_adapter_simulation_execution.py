"""The executed simulation review is funded by tier, like the draft path.

The simulation review can build and run a model of a hypothesis's
mechanism instead of stepping through it mentally. That is a tool loop
per hypothesis, so its cost is a product with the pool size rather than a
fixed addition -- the same shape as tool-calling generation, and the same
answer: the deep tiers, which have already traded turnaround for depth.
These tests pin which runs make it, and that the toggle is only ever a
ceiling.
"""

from typing import Any

import pytest

from app.engine_adapter.opts import _apply_capability_opts


def _enabled(tier: str | None) -> bool:
    """Read the capability the opts builder actually sends to the engine."""
    opts: dict[str, Any] = {}
    _apply_capability_opts(opts, {"tier": tier} if tier is not None else {})
    return bool(opts["enable_simulation_execution"])


@pytest.mark.parametrize("tier", ["extended", "ultra"])
def test_deep_tiers_fund_an_executed_simulation(tier: str) -> None:
    assert _enabled(tier) is True


@pytest.mark.parametrize("tier", ["express", "standard"])
def test_fast_tiers_review_by_mental_simulation(tier: str) -> None:
    """The review still happens on every tier -- it just does not run."""
    assert _enabled(tier) is False


def test_an_unset_tier_falls_back_to_the_default_tier() -> None:
    # Older persisted rows and direct API callers land on standard, and
    # must not inherit the expensive path by omission.
    assert _enabled(None) is False


def test_a_legacy_tier_name_resolves_before_the_gate() -> None:
    assert _enabled("advanced") is True

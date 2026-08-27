"""Tests for run-mode setup config and guidance."""

from __future__ import annotations

from app import run_modes


def test_every_tier_caps_its_llm_call_spend() -> None:
    """No tier may run without a hard ceiling on provider calls.

    Before this, ``max_iterations`` was the only bound the scheduler could
    terminate on, and iterations only advance on work tasks -- so a run that
    kept looping on maintenance work had no ceiling at all and burned provider
    spend until someone noticed. ``_budget_termination`` checks this before
    scheduling any task, so an exhausted run stops with a recorded reason.
    """
    ceilings = {
        tier: cfg["max_llm_calls"]
        for tier, cfg in run_modes.RUN_TIER_DEFAULTS.items()
    }
    assert all(value > 0 for value in ceilings.values())
    # Deeper tiers do strictly more work, so their ceilings must not invert.
    ordered = ["express", "standard", "extended", "ultra"]
    assert [ceilings[tier] for tier in ordered] == sorted(
        ceilings[tier] for tier in ordered
    )


def test_resolved_config_carries_the_tier_call_ceiling() -> None:
    """The ceiling reaches the persisted run config, not just the table."""
    config = run_modes.resolved_run_config({"tier": "express"})
    assert (
        config["max_llm_calls"]
        == (run_modes.RUN_TIER_DEFAULTS["express"]["max_llm_calls"])
    )

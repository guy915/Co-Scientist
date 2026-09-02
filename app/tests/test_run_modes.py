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


def test_default_criteria_are_named_settings_with_values() -> None:
    """R12-4: the default shape is name/value pairs, not free prose."""
    for pair in run_modes.DEFAULT_CRITERIA:
        assert set(pair) == {"name", "value"}
        assert pair["name"] and pair["value"]


def test_setup_config_defaults_criteria_to_independent_copies() -> None:
    """Two runs never share a mutable default-criteria dict."""
    first = run_modes.setup_config(research_goal="goal one")
    second = run_modes.setup_config(research_goal="goal two")
    assert first["criteria"] == list(run_modes.DEFAULT_CRITERIA)
    first["criteria"][0]["value"] = "mutated"
    assert second["criteria"][0]["value"] != "mutated"


def test_setup_config_keeps_accepting_legacy_free_string_criteria() -> None:
    """A caller still supplying prose criteria (CLI, demo seeding) works."""
    spec = run_modes.setup_config(
        research_goal="goal",
        lists=run_modes.PlanningLists(criteria=["Causal specificity", ""]),
    )
    assert spec["criteria"] == ["Causal specificity"]


def test_criteria_display_strings_renders_both_stored_shapes() -> None:
    """Back-compat: legacy strings and R12-4 pairs render the same way."""
    assert run_modes.criteria_display_strings(["Scientific soundness"]) == [
        "Scientific soundness"
    ]
    assert run_modes.criteria_display_strings(
        [{"name": "Idea correctness", "value": "Required"}]
    ) == ["Idea correctness: Required"]
    # A malformed/legacy dict with no value still renders the bare name.
    assert run_modes.criteria_display_strings([{"name": "Impact"}]) == [
        "Impact"
    ]
    assert run_modes.criteria_display_strings(None) == []


def test_setup_guidance_renders_criteria_for_both_stored_shapes() -> None:
    """The engine-facing prompt guidance reads a legacy or new-shape run."""
    legacy = run_modes.setup_guidance(
        {
            "criteria": ["Scientific soundness"],
            "focus": "balance",
            "tier": "standard",
        }
    )
    assert "- Criteria:\n  - Scientific soundness" in legacy

    current = run_modes.setup_guidance(
        run_modes.setup_config(research_goal="goal")
    )
    assert "- Criteria:\n  - Idea correctness: Required" in current

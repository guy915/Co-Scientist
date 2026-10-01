"""Tests for run-mode setup config and guidance."""

from __future__ import annotations

from app import run_modes
from app.run_modes import attributes as run_modes_attributes_mod
from app.run_modes import criteria as run_modes_criteria


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


def test_default_attributes_are_goal_agnostic_scaled_axes() -> None:
    """R12-5: the default shape is a scaled axis, not free prose.

    No categorical default exists -- the published block's own categorical
    axis (Target Area) is goal-derived, so nothing goal-agnostic to put
    here (see ``run_modes.attributes``'s module docstring). The categorical
    shape itself is still fully supported; pinned on stored producer input
    by ``test_setup_config_keeps_accepting_a_categorical_attribute`` below.
    """
    for attribute in run_modes_attributes_mod.DEFAULT_ATTRIBUTES:
        assert set(attribute) == {"name", "scale"}
        assert attribute["name"]
        assert set(attribute["scale"]) == {"1", "3", "5"}
        assert all(attribute["scale"].values())


def test_setup_config_defaults_attributes_to_independent_copies() -> None:
    """Two runs never share a mutable default-attribute dict."""
    first = run_modes.setup_config(research_goal="goal one")
    second = run_modes.setup_config(research_goal="goal two")
    assert first["attributes"] == list(
        run_modes_attributes_mod.DEFAULT_ATTRIBUTES
    )
    first["attributes"][0]["scale"]["1"] = "mutated"
    assert second["attributes"][0]["scale"]["1"] != "mutated"


def test_setup_config_keeps_accepting_legacy_free_string_attributes() -> None:
    """A caller still supplying prose attributes (CLI, an interview) works."""
    spec = run_modes.setup_config(
        research_goal="goal",
        lists=run_modes.PlanningLists(attributes=["Spatially resolved", ""]),
    )
    assert spec["attributes"] == ["Spatially resolved"]


def test_setup_config_keeps_accepting_a_categorical_attribute() -> None:
    """A producer may still supply the categorical shape directly."""
    spec = run_modes.setup_config(
        research_goal="goal",
        lists=run_modes.PlanningLists(
            attributes=[
                {
                    "name": "Target Area",
                    "values": ["Epigenetics", "Stromal-Immune Crosstalk"],
                }
            ]
        ),
    )
    assert spec["attributes"] == [
        {
            "name": "Target Area",
            "values": ["Epigenetics", "Stromal-Immune Crosstalk"],
        }
    ]


def test_attribute_display_strings_renders_every_stored_shape() -> None:
    """Back-compat: legacy strings, scaled axes, and categorical axes."""
    assert run_modes.attribute_display_strings(
        ["Mechanistically specific"]
    ) == ["Mechanistically specific"]
    assert run_modes.attribute_display_strings(
        [{"name": "Mechanism Novelty", "scale": {"1": "Low", "5": "High"}}]
    ) == ["Mechanism Novelty: 1-5 scale (1: Low, 5: High)"]
    assert run_modes.attribute_display_strings(
        [{"name": "Target Area", "values": ["A", "B", "C"]}]
    ) == ["Target Area (A, B, or C)"]
    # A malformed/legacy dict with neither scale nor values still renders
    # the bare name, matching criteria_display_strings' own forgiving rule.
    assert run_modes.attribute_display_strings([{"name": "Impact"}]) == [
        "Impact"
    ]
    assert run_modes.attribute_display_strings(None) == []


def test_setup_guidance_renders_attributes_for_both_stored_shapes() -> None:
    """The engine-facing prompt guidance reads a legacy or new-shape run."""
    legacy = run_modes.setup_guidance(
        {
            "attributes": ["Mechanistically specific"],
            "focus": "balance",
            "tier": "standard",
        }
    )
    assert "- Attributes:\n  - Mechanistically specific" in legacy

    current = run_modes.setup_guidance(
        run_modes.setup_config(research_goal="goal")
    )
    assert "- Attributes:\n  - Mechanistic specificity: 1-5 scale" in current


def test_default_criteria_are_named_settings_with_values() -> None:
    """R12-4: the default shape is name/value pairs, not free prose."""
    for pair in run_modes_criteria.DEFAULT_CRITERIA:
        assert set(pair) == {"name", "value"}
        assert pair["name"] and pair["value"]


def test_setup_config_defaults_criteria_to_independent_copies() -> None:
    """Two runs never share a mutable default-criteria dict."""
    first = run_modes.setup_config(research_goal="goal one")
    second = run_modes.setup_config(research_goal="goal two")
    assert first["criteria"] == list(run_modes_criteria.DEFAULT_CRITERIA)
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

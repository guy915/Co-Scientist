"""Legacy and structured run attributes and criteria reach engine prompts."""

from __future__ import annotations

from app.engine_adapter.opts import _setup_opts_from_cfg
from app.run_modes import setup_config


def test_legacy_free_string_attributes_reach_the_engine_as_is() -> None:
    """A run persisted before R12-5 still hands the engine its own prose."""
    opts = _setup_opts_from_cfg(
        {"attributes": ["Mechanistically specific", "  "], "focus": "balance"}
    )
    assert opts["attributes"] == ["Mechanistically specific"]


def test_published_default_attributes_reach_the_engine_as_bare_names() -> None:
    """A new run's structured attributes reach the engine by name only.

    The anchored rubric text (with its own internal commas) is deliberately
    dropped here -- it would otherwise land inside a comma-joined prompt
    slot and read as extra list items (see ``attribute_names``).
    """
    setup = setup_config(research_goal="goal")
    opts = _setup_opts_from_cfg(setup)
    assert opts["attributes"] == [
        "Mechanistic specificity",
        "Evidence grounding",
        "Experimental readiness",
    ]


def test_a_missing_setup_carries_no_attributes() -> None:
    """No setup block (an older/partial run config) yields an empty opts."""
    assert _setup_opts_from_cfg(None) == {}


def test_legacy_free_string_criteria_reach_the_engine_as_is() -> None:
    """A run persisted before R12-4 still hands the engine its own prose."""
    opts = _setup_opts_from_cfg(
        {"criteria": ["Scientific soundness", "  "], "focus": "balance"}
    )
    assert opts["criteria"] == ["Scientific soundness"]


def test_published_default_criteria_reach_the_engine_as_name_value_lines() -> (
    None
):
    """A new run's named-setting criteria render as one line each."""
    setup = setup_config(research_goal="goal")
    opts = _setup_opts_from_cfg(setup)
    assert opts["criteria"] == [
        "Idea correctness: Required",
        "Idea novelty: Required",
        "Maximize impact: Yes",
    ]


def test_a_missing_setup_carries_no_criteria() -> None:
    """No setup block (an older/partial run config) yields an empty opts."""
    assert _setup_opts_from_cfg(None) == {}

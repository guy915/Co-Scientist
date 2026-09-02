"""R12-4: the stored setup's criteria reach the engine as display strings.

The engine's ``criteria`` state field is ``list[str] | None`` (planning,
ranking, and review-gate prompt text -- see ``co_scientist.state``); the
app's ``setup.criteria`` may hold either the legacy free-prose list or the
R12-4 ``{"name", "value"}`` pair list. ``_setup_opts_from_cfg`` is the one
seam where a stored run's criteria, whichever shape, become the flat
strings the engine actually consumes.
"""

from __future__ import annotations

from app.engine_adapter.opts import _setup_opts_from_cfg
from app.run_modes import setup_config


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

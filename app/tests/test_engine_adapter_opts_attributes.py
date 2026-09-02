"""R12-5: the stored setup's attributes reach the engine as bare names.

The engine's ``attributes`` state field is ``list[str] | None``, and several
of its prompt formatters comma-join the list (``_format_debate_attributes``,
the csv-joined slot in ``prompts/planning.py``/``prompts/literature.py``).
The app's ``setup.attributes`` may hold either the legacy free-prose list or
the R12-5 structured axis list; ``_setup_opts_from_cfg`` is the one seam
where a stored run's attributes, whichever shape, become the bare names the
engine's comma-joined prompt slots actually consume. The full anchored
rubric still reaches the engine separately, bulleted, via
``run_setup_guidance`` -- see ``test_setup_guidance_renders_attributes_for_
both_stored_shapes`` in ``test_run_modes.py``.
"""

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

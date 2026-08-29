"""R12-17: the drain hands the Supervisor's attributes to the report.

The Supervisor already synthesizes ``config_synthesis.attributes`` -- up to
three named 1-5 rating scales, mirroring the published MASH plan's
``Attributes`` section (``docs/CORPUS-EXTRACTION.md`` R12-17) -- and
``drain_supervisor_plan.py`` already persists them into the
``supervisor_plan`` table. But the drain never handed them to the report
path, so the markdown renderer had nothing to read. This pins that the
drain now reads the same ``supervisor_guidance.config_synthesis.attributes``
slice into ``report_inputs``, and that an old-shaped or absent
``supervisor_guidance`` degrades to an empty list rather than an error.
"""

from __future__ import annotations

from app import engine_adapter, store
from tests._drain_helpers import _final_state_with_features


def test_drain_result_carries_stratification_attributes(
    isolated_db: str,
) -> None:
    """The drain hands the Supervisor's synthesized attributes to the report."""
    run = store.create_run("attributes goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["supervisor_guidance"] = {
        "config_synthesis": {
            "attributes": [
                {
                    "name": "Mechanism Novelty",
                    "rubric": (
                        "1: Well-established pathway, 3: New application of"
                        " a known mechanism, 5: Highly novel and"
                        " paradigm-shifting."
                    ),
                }
            ]
        }
    }

    drained = engine_adapter._persist_final_state(
        run_id=run.id, final_state=state, db_path=isolated_db
    )

    assert drained.report_inputs["attributes"] == [
        {
            "name": "Mechanism Novelty",
            "rubric": (
                "1: Well-established pathway, 3: New application of a known"
                " mechanism, 5: Highly novel and paradigm-shifting."
            ),
        }
    ]


def test_drain_result_defaults_to_no_attributes(isolated_db: str) -> None:
    """A run with no supervisor guidance reports an empty list, not a crash."""
    run = store.create_run("no guidance goal", "standard", "engine", {})

    drained = engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    assert drained.report_inputs["attributes"] == []


def test_drain_result_ignores_malformed_config_synthesis(
    isolated_db: str,
) -> None:
    """A non-dict config_synthesis (an old or malformed checkpoint) degrades."""
    run = store.create_run("malformed goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["supervisor_guidance"] = {"config_synthesis": "not a dict"}

    drained = engine_adapter._persist_final_state(
        run_id=run.id, final_state=state, db_path=isolated_db
    )

    assert drained.report_inputs["attributes"] == []

"""R12-18: the drain hands the Supervisor's evaluation criteria to the report.

The Supervisor already synthesizes ``workflow_plan.review_phase.
critical_criteria`` -- goal-specific criteria reviewers should emphasize,
mirroring the published MASH plan's "Evaluation Criteria" section
(``docs/CORPUS-EXTRACTION.md``, MASH body, ``## **2. Evaluation
Criteria**``) -- and ``prompts/review.py`` already injects it into every
reviewer prompt as "Critical Criteria to Emphasize". But the drain never
handed it to the report path, so the markdown renderer had nothing to
read. This pins that the drain now reads the same
``supervisor_guidance.workflow_plan.review_phase.critical_criteria`` slice
into ``report_inputs``, and that an old-shaped or absent
``supervisor_guidance`` degrades to an empty list rather than an error.
"""

from __future__ import annotations

from app import store
from tests._drain_helpers import _final_state_with_features, _persist


def test_drain_result_carries_critical_criteria(isolated_db: str) -> None:
    """The drain hands the Supervisor's synthesized criteria to the report."""
    run = store.create_run("criteria goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["supervisor_guidance"] = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    "Kinetic Feasibility and Experimental Readouts",
                    "Human Data Integration and Accuracy",
                ]
            }
        }
    }

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs["critical_criteria"] == [
        "Kinetic Feasibility and Experimental Readouts",
        "Human Data Integration and Accuracy",
    ]


def test_drain_result_defaults_to_no_critical_criteria(
    isolated_db: str,
) -> None:
    """A run with no supervisor guidance reports an empty list, not a crash."""
    run = store.create_run("no guidance goal", "standard", "engine", {})

    drained = _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    assert drained.report_inputs["critical_criteria"] == []


def test_drain_result_carries_structured_critical_criteria(
    isolated_db: str,
) -> None:
    """R12-23: the richer {name, questions} shape passes through unfiltered.

    ``critical_criteria`` used to be typed (and filtered) as a bare list of
    strings, so a well-formed structured answer -- every item a dict, none
    a str -- was silently dropped to an empty list here even though the
    Supervisor produced it correctly.
    """
    run = store.create_run("structured criteria goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["supervisor_guidance"] = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    {
                        "name": "Kinetic Feasibility",
                        "questions": [
                            {
                                "name": "Biological Timeframe Consistency",
                                "question": "Does the design fit the kinetics?",
                            }
                        ],
                    }
                ]
            }
        }
    }

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs["critical_criteria"] == [
        {
            "name": "Kinetic Feasibility",
            "questions": [
                {
                    "name": "Biological Timeframe Consistency",
                    "question": "Does the design fit the kinetics?",
                }
            ],
        }
    ]


def test_drain_result_drops_non_str_non_dict_criteria_entries(
    isolated_db: str,
) -> None:
    """A list mixing valid entries with garbage keeps only the valid ones."""
    run = store.create_run("mixed criteria goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["supervisor_guidance"] = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    "novelty",
                    {"name": "Kinetic Feasibility", "questions": []},
                    42,
                    None,
                    ["not", "a", "criterion"],
                ]
            }
        }
    }

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs["critical_criteria"] == [
        "novelty",
        {"name": "Kinetic Feasibility", "questions": []},
    ]


def test_drain_result_ignores_malformed_review_phase(isolated_db: str) -> None:
    """A non-dict review_phase (an old or malformed checkpoint) degrades."""
    run = store.create_run("malformed goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["supervisor_guidance"] = {
        "workflow_plan": {"review_phase": "not a dict"}
    }

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs["critical_criteria"] == []

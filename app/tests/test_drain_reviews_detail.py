"""The drain persists every field the per-idea review block renders.

Reviews were generated, paid for, and persisted -- and then the report
showed none of them. Three families of content were reachable only as
flat prose or not at all:

* the initial review's **eight axis scores**, of which only three ever
  reached a column (``novelty``, ``plausibility`` -- which actually holds
  ``scientific_soundness`` -- and ``testability``), and its six per-axis
  prose feedback fields, which reached nothing;
* the full/recurrent review's assumptions and prose, flattened into the
  ``critique`` text where no renderer can find the parts again;
* deep verification's probes, likewise flattened.

Each now travels as structured ``detail_json`` beside the prose, which is
left untouched so the workbench keeps reading what it always did.
"""

from __future__ import annotations

import json
from typing import Any

from app.engine_adapter.drain.review_detail import (
    _deep_verification_detail,
    _initial_review_detail,
    _mature_review_detail,
)


def _engine_review() -> dict[str, Any]:
    """One initial-review payload as ``REVIEW_SCHEMA`` shapes it."""
    return {
        "review_summary": "Sound but narrow.",
        "scores": {
            "scientific_soundness": 8,
            "plausibility": 7,
            "novelty": 6,
            "testability": 9,
            "potential_impact": 5,
            "relevance": 4,
            "safety": 10,
            "clarity": 3,
        },
        "detailed_feedback": {
            "scientific_soundness": "The mechanism is internally consistent.",
            "novelty": "The pairing is unusual.",
            "testability": "A pilot assay would settle it.",
            "potential_impact": "Would change first-line practice.",
            "relevance": "Squarely on the research goal.",
            "clarity": "Precisely stated.",
        },
        "constructive_feedback": "Name the control arm.",
        "already_explored": ["Target engagement is documented."],
        "novel_aspects": ["The stress-induced modification is new."],
    }


def test_initial_review_detail_persists_all_eight_axis_scores() -> None:
    """The five axes no column holds must survive the drain.

    ``novelty``/``plausibility``/``testability`` have columns (the
    ``plausibility`` column holding ``scientific_soundness``, a name
    mismatch the renderer must never inherit), so the report's per-axis
    ``Answer: N`` line had no source for the other five at all.
    """
    detail = _initial_review_detail(_engine_review())

    assert detail["scores"] == {
        "scientific_soundness": 8,
        "plausibility": 7,
        "novelty": 6,
        "testability": 9,
        "potential_impact": 5,
        "relevance": 4,
        "safety": 10,
        "clarity": 3,
    }


def test_initial_review_detail_persists_per_axis_feedback() -> None:
    """Per-axis prose reached no column and no JSON before this."""
    detail = _initial_review_detail(_engine_review())

    assert detail["detailed_feedback"]["novelty"] == "The pairing is unusual."
    assert len(detail["detailed_feedback"]) == 6
    # The published Correctness axis prints these as its own "Suggested
    # Improvements"; they used to reach only the flat critique prose.
    assert detail["constructive_feedback"] == "Name the control arm."


def test_initial_review_detail_persists_the_novelty_two_lists() -> None:
    """MO-3's two named lists, structured rather than baked into prose."""
    detail = _initial_review_detail(_engine_review())

    assert detail["already_explored"] == ["Target engagement is documented."]
    assert detail["novel_aspects"] == [
        "The stress-induced modification is new."
    ]


def test_initial_review_detail_is_empty_when_the_review_said_nothing() -> None:
    """An empty result must persist as no row detail, not ``"{}"``."""
    assert _initial_review_detail({}) == {}


def test_initial_review_detail_drops_unknown_and_out_of_range_axes() -> None:
    """A json_object downgrade can answer with anything at all."""
    detail = _initial_review_detail(
        {"scores": {"novelty": 7, "vibes": 11, "clarity": "high"}}
    )

    assert detail["scores"] == {"novelty": 7}


def test_mature_review_detail_carries_assumptions_and_prose() -> None:
    """MO-9's per-assumption reasoning, reachable as parts again."""
    detail = _mature_review_detail(
        {
            "correctness": "The logic holds.",
            "quality_and_novelty": "A genuine contribution.",
            "literature_grounding": "Two cohort studies agree.",
            "justification": "Worth a pilot.",
            "assumptions": [
                {
                    "assumption": "The receptor is expressed.",
                    "reasoning": "Two cohorts detect it directly.",
                    "support": "supported",
                },
                {"assumption": "", "reasoning": "dropped"},
            ],
            "go_no_go_recommendation": "Go - pursue validation.",
            "time_to_verdict": "2-4 weeks",
        }
    )

    assert detail["correctness"] == "The logic holds."
    assert detail["go_no_go"] == "Go - pursue validation."
    assert detail["assumptions"] == [
        {
            "assumption": "The receptor is expressed.",
            "reasoning": "Two cohorts detect it directly.",
            "support": "Plausible",
        }
    ]


def test_mature_review_detail_carries_the_eight_part_reviews_summary() -> None:
    """R14-14: the published executive block, part by part."""
    detail = _mature_review_detail(
        {
            "reviews_summary": {
                "executive_verdict": "The index is well conceived.",
                "critical_flaws": ["The pore benchmark is wrong."],
                "addressed_objections": ["Modelling reliability was met."],
                "validated_risks": ["Parameter covariance is untreated."],
                "supporting_arguments": ["The theoretical basis is right."],
                "alignment_and_novelty": ["Squarely on the goal."],
                "feasibility_assessment": ["Moderate resource intensity."],
                "conclusion": "Recalibrate before testing.",
            }
        }
    )

    summary = detail["reviews_summary"]
    assert summary["executive_verdict"] == "The index is well conceived."
    assert summary["critical_flaws"] == ["The pore benchmark is wrong."]
    assert summary["conclusion"] == "Recalibrate before testing."


def test_mature_review_detail_omits_an_absent_reviews_summary() -> None:
    """A review that answered no part of it adds no key.

    Required on the schema now, but a json_object-downgrade answer
    reaches the drain back-filled with empty parts, and an empty scaffold
    in the column reads as "this review had a summary and it said
    nothing" rather than as "this review has none".
    """
    detail = _mature_review_detail({"correctness": "Holds."})

    assert "reviews_summary" not in detail


def test_mature_review_detail_carries_the_per_axis_sub_parts() -> None:
    """R14-17: the five published sub-parts, drained beside the prose.

    Same call, same row, no extra plumbing: the full review's whole raw
    response already reaches the drain, so these travel exactly as
    ``correctness`` and ``literature_grounding`` always have.
    """
    detail = _mature_review_detail(
        {
            "comparison_with_knowledge_base": "Agrees with the canon.",
            "goal_requirements_assessment": "Meets every requirement.",
            "feasibility_steps": ["Run the pilot.", "Read out at day 30."],
            "feasibility_reasoning": "Both steps use standard assays.",
            "impact_assessment": "Would change first-line practice.",
        }
    )

    assert detail["comparison_with_knowledge_base"] == "Agrees with the canon."
    assert detail["goal_requirements_assessment"] == "Meets every requirement."
    assert detail["feasibility_steps"] == [
        "Run the pilot.",
        "Read out at day 30.",
    ]
    assert detail["feasibility_reasoning"] == "Both steps use standard assays."
    assert detail["impact_assessment"] == "Would change first-line practice."


def test_mature_review_detail_omits_absent_per_axis_sub_parts() -> None:
    """A resumed run's old-shaped review carries none of them.

    And crashes on none of them: every field is read with ``get`` and
    dropped when it is empty, so a review written before these existed
    drains exactly as it always did.
    """
    detail = _mature_review_detail({"correctness": "Holds."})

    assert detail == {"correctness": "Holds."}


def test_deep_verification_detail_carries_the_published_probe_triple() -> None:
    """R14-15's probes as parts, not as one indented prose blob.

    ``format_deep_verification_critique`` renders the same content into
    the row's ``critique``, but two-space-indented under a probe header,
    which collapses into one paragraph wherever markdown renders it.
    """
    detail = _deep_verification_detail(
        [
            {
                "question": "Is CXCR1/2 inhibition alone sufficient?",
                "answer": "It targets a key node of the microenvironment.",
                "reasoning": "The idea is not incoherent but needs care.",
                "assumption_is_fundamental": True,
            },
            {"question": "", "answer": "dropped"},
        ],
        "weakened",
    )

    assert detail["verdict"] == "weakened"
    assert detail["probes"] == [
        {
            "question": "Is CXCR1/2 inhibition alone sufficient?",
            "answer": "It targets a key node of the microenvironment.",
            "reasoning": "The idea is not incoherent but needs care.",
            "fundamental": True,
        }
    ]


def test_deep_verification_detail_is_empty_without_probes() -> None:
    """No probe means no row detail at all, verdict or not."""
    assert _deep_verification_detail([], "holds") == {}


def test_persisted_rows_carry_the_detail_json(isolated_db: str) -> None:
    """End to end: the drain writes the structured detail beside the prose."""
    from app import store
    from tests._drain_helpers import _engine_hypothesis, _persist

    hypothesis = _engine_hypothesis(
        "h-1",
        "A hypothesis.",
        reviews=[_engine_review()],
    )
    hypothesis["deep_verification_probes"] = [
        {
            "question": "Does the receptor bind?",
            "answer": "Yes, at nanomolar affinity.",
            "reasoning": "Two structures show the contact.",
            "assumption_is_fundamental": True,
        }
    ]
    hypothesis["deep_verification_verdict"] = "holds"
    hypothesis["enrichments"] = {
        "full": {
            "verdict": "sound",
            "correctness": "The logic holds.",
            "reviews_summary": {"conclusion": "Worth testing."},
        }
    }
    run = store.create_run("detail goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state={
            "hypotheses": [hypothesis],
            "articles": [],
            "tournament_matchups": [],
            "meta_review": {},
            "evolution_details": [],
            "research_overview": {},
        },
        db_path=isolated_db,
    )

    by_agent = {
        row["reviewer_agent"]: json.loads(row["detail_json"] or "{}")
        for row in store.list_reviews(run.id, db_path=isolated_db)
    }
    assert by_agent["review"]["scores"]["potential_impact"] == 5
    assert by_agent["deep_verification"]["probes"][0]["fundamental"] is True
    assert (
        by_agent["full_review"]["reviews_summary"]["conclusion"]
        == "Worth testing."
    )


def test_review_axes_match_the_engine_score_criteria() -> None:
    """The app's copy of the axis list must not drift from the engine's.

    ``drain.review_detail._REVIEW_AXES`` and the report's own
    ``_AXIS_SECTIONS`` name the axes rather than importing them, so a
    drained row can be read without an engine schema import at runtime.
    An axis added or reordered engine-side would otherwise silently stop
    being persisted, and stop being rendered, with every test still
    green -- the same drift the engine already pins for the offline
    backend's copy of this list.
    """
    from co_scientist.schemas.review import _SCORE_CRITERIA

    from app.engine_adapter.drain.review_detail import _REVIEW_AXES
    from app.report.markdown.review_block import _AXIS_SECTIONS

    assert _REVIEW_AXES == _SCORE_CRITERIA
    assert [axis for axis, _ in _AXIS_SECTIONS] == list(_SCORE_CRITERIA)

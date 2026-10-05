from __future__ import annotations

import json
from typing import Any

import pytest

from app.engine_adapter.drain import final_state as drain_final_state
from app.engine_adapter.drain.final_state import fold_grounding_telemetry
from app.engine_adapter.drain.reviews import (
    _deep_verification_detail,
    _initial_review_detail,
    _mature_review_detail,
)
from app.report import build as report_build
from app.report import finalize as report_finalize
from app.store import db, records, reports
from app.store import hypotheses as store_hypotheses
from app.store.hypotheses import NewHypothesis
from app.store.records import NewClaimEvidence
from tests._client import drain as _drain
from tests._drain_helpers import (
    _build_report,
    _engine_hypothesis,
    _final_state_with_features,
    _final_state_with_lineage,
    _persist,
    _persist_and_finalize,
    emit_event,
)
from tests._store_helpers import seed_run


def test_drain_result_carries_critical_criteria(isolated_db: str) -> None:
    run = seed_run("criteria goal")
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


@pytest.mark.parametrize("key", ["critical_criteria", "attributes"])
def test_drain_result_defaults_to_no_guidance(
    isolated_db: str,
    key: str,
) -> None:
    run = seed_run("no guidance goal")

    drained = _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    assert drained.report_inputs[key] == []


def test_drain_result_carries_structured_critical_criteria(
    isolated_db: str,
) -> None:
    # Structured criterion objects are valid guidance; string-only filtering
    # silently discards them.
    run = seed_run("structured criteria goal")
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
    run = seed_run("mixed criteria goal")
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
    run = seed_run("malformed goal")
    state = _final_state_with_features()
    state["supervisor_guidance"] = {
        "workflow_plan": {"review_phase": "not a dict"}
    }

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs["critical_criteria"] == []


def _engine_review() -> dict[str, Any]:
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
    # Legacy plausibility holds scientific_soundness; persist the other axes in
    # detail rather than infer scores.
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
    detail = _initial_review_detail(_engine_review())

    assert detail["detailed_feedback"]["novelty"] == "The pairing is unusual."
    assert len(detail["detailed_feedback"]) == 6
    assert detail["constructive_feedback"] == "Name the control arm."


def test_initial_review_detail_persists_the_novelty_two_lists() -> None:
    detail = _initial_review_detail(_engine_review())

    assert detail["already_explored"] == ["Target engagement is documented."]
    assert detail["novel_aspects"] == [
        "The stress-induced modification is new."
    ]


def test_initial_review_detail_is_empty_when_the_review_said_nothing() -> None:
    assert _initial_review_detail({}) == {}


def test_initial_review_detail_drops_unknown_and_out_of_range_axes() -> None:
    detail = _initial_review_detail(
        {"scores": {"novelty": 7, "vibes": 11, "clarity": "high"}}
    )

    assert detail["scores"] == {"novelty": 7}


def test_mature_review_detail_carries_assumptions_and_prose() -> None:
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
    # Empty backfilled scaffolds must not imply a review actually supplied a
    # summary.
    detail = _mature_review_detail({"correctness": "Holds."})

    assert "reviews_summary" not in detail


def test_mature_review_detail_carries_the_per_axis_sub_parts() -> None:
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
    detail = _mature_review_detail({"correctness": "Holds."})

    assert detail == {"correctness": "Holds."}


def test_deep_verification_detail_carries_the_published_probe_triple() -> None:
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
    assert _deep_verification_detail([], "holds") == {}


def test_persisted_rows_carry_the_detail_json(isolated_db: str) -> None:
    from app.store import records as store
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
    run = seed_run("detail goal")
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
    # App axis copies avoid runtime schema imports but must track engine
    # additions and order.
    from co_scientist.schemas.review import _SCORE_CRITERIA

    from app.engine_adapter.drain.reviews import _REVIEW_AXES
    from app.report.markdown.hypothesis import _AXIS_SECTIONS

    assert _REVIEW_AXES == _SCORE_CRITERIA
    assert [axis for axis, _ in _AXIS_SECTIONS] == list(_SCORE_CRITERIA)


def test_drain_result_carries_stratification_attributes(
    isolated_db: str,
) -> None:
    run = seed_run("attributes goal")
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

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs["attributes"] == [
        {
            "name": "Mechanism Novelty",
            "rubric": (
                "1: Well-established pathway, 3: New application of a known"
                " mechanism, 5: Highly novel and paradigm-shifting."
            ),
        }
    ]


def test_drain_result_ignores_malformed_config_synthesis(
    isolated_db: str,
) -> None:
    run = seed_run("malformed goal")
    state = _final_state_with_features()
    state["supervisor_guidance"] = {"config_synthesis": "not a dict"}

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs["attributes"] == []


def test_grounding_telemetry_is_folded_into_plain_metrics() -> None:
    final_state: dict[str, Any] = {
        "metrics": {"llm_calls": 3, "model_usage": {}}
    }
    usage = {
        "claim_grounding::llm:test-model": {
            "calls": 5,
            "prompt_tokens": 50,
        }
    }

    fold_grounding_telemetry(final_state, usage)

    metrics = final_state["metrics"]
    assert metrics["llm_calls"] == 8
    entry = metrics["model_usage"]["claim_grounding::llm:test-model"]
    assert entry["calls"] == 5
    assert entry["prompt_tokens"] == 50


def test_grounding_telemetry_handles_missing_metrics_key() -> None:
    final_state: dict[str, Any] = {}
    usage = {"claim_grounding::llm:test-model": {"calls": 2}}

    fold_grounding_telemetry(final_state, usage)

    metrics = final_state["metrics"]
    assert metrics["llm_calls"] == 2


def test_a_grounding_pass_that_made_no_calls_charges_nothing() -> None:
    final_state: dict[str, Any] = {"metrics": {"llm_calls": 4}}

    fold_grounding_telemetry(final_state, {})

    assert final_state["metrics"] == {"llm_calls": 4}


def _assert_features_proximity_edge(run_id: str, db_path: str) -> None:
    edges = records.list_proximity_edges(run_id, db_path=db_path)
    hypotheses = store_hypotheses.list_hypotheses(run_id, db_path=db_path)
    hypothesis_ids = {hypothesis["id"] for hypothesis in hypotheses}
    assert len(edges) == 1
    edge = edges[0]
    assert edge["source_hypothesis_id"] in hypothesis_ids
    assert edge["target_hypothesis_id"] in hypothesis_ids
    assert edge["source_hypothesis_id"] != edge["target_hypothesis_id"]
    assert edge["similarity"] == 0.82
    assert edge["degree"] == "high"
    assert edge["cluster_id"] == "cluster-1"
    assert edge["method"] == "llm_cluster_pairwise_graph"
    assert edge["version"] == "1"
    assert edge["model"] == "fixture-model"
    assert edge["updated_at"] == 1234.5


def _seed_safe_and_unsafe(run: Any, db_path: str) -> tuple[str, str]:
    safe_id = store_hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="Safe idea",
            statement=(
                "Inhibiting kinase X reduces AML tumor growth via apoptosis."
            ),
        ),
        db_path=db_path,
    )
    unsafe_id = store_hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="Unsafe idea",
            statement=(
                "Weaponize the pathogen to enhance transmissibility in humans."
            ),
        ),
        db_path=db_path,
    )
    records.add_claim_evidence(
        NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=safe_id,
            claim="Inhibiting kinase X reduces AML tumor growth via apoptosis.",
            label="supports",
            supporting=["A source-supported safe mechanism."],
            contradicting=[],
            assessor="fixture",
            claim_role="speculative",
        ),
        db_path=db_path,
    )
    records.add_claim_evidence(
        NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=unsafe_id,
            claim=(
                "Weaponize the pathogen to enhance transmissibility in humans."
            ),
            label="supports",
            supporting=[
                "A source span is present so the safety gate decides "
                "this fixture."
            ],
            contradicting=[],
            assessor="fixture",
        ),
        db_path=db_path,
    )
    return safe_id, unsafe_id


def _archived_parent_state() -> dict[str, Any]:
    state = _final_state_with_lineage()
    parent = state["hypotheses"][0]
    state["hypotheses"] = [state["hypotheses"][1]]
    state["removed_duplicates"] = [
        {
            "text": parent["text"],
            "cluster_id": "cluster-1",
            "reason": "high_similarity_duplicate",
            "kept_hypothesis_id": "child-1",
            "kept_instead": "Child hypothesis",
            "hypothesis": parent,
        }
    ]
    state["tournament_matchups"] = [
        {
            "hypothesis_a_id": "parent-1",
            "hypothesis_b_id": "child-1",
            "winner_id": "child-1",
            "reasoning": "The child is more specific.",
            "confidence": "High",
        }
    ]
    return state


def test_persist_writes_research_overview_into_report(isolated_db: str) -> None:
    run = seed_run("CSC goal")
    _persist_and_finalize(run, _final_state_with_features(), isolated_db)

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    overview = report["payload"].get("research_overview")
    assert overview is not None
    assert overview["overview"]["summary"].startswith("Targeting CXCR1")
    first_aim = overview["nih_specific_aims"]["aims"][0]
    assert first_aim["overarching_goal"].startswith("Aim 1")

    markdown = report["markdown_text"]
    assert "## Research Overview" in markdown
    assert "Dual CXCR1/CXCR2 blockade" in markdown
    assert "Combine reparixin with a CXCR2 antagonist." in markdown
    assert "## NIH Specific Aims" in markdown
    assert "Aim 1: Quantify CXCR1 dependence." in markdown
    assert "Could yield a combination therapy for TNBC." in markdown

    evidence = records.list_evidence(run.id, db_path=isolated_db)
    retracted = next(
        item for item in evidence if item["title"] == "Retracted CXCR1 report"
    )
    assert retracted["available"] == 0

    _assert_features_proximity_edge(run.id, isolated_db)


def test_drain_persists_explicit_lineage(isolated_db: str) -> None:
    # Lineage is explicit and append-only; do not infer it from evolution
    # history.
    run = seed_run("kinase goal")
    _persist(
        run_id=run.id,
        final_state=_final_state_with_lineage(),
        db_path=isolated_db,
    )

    hyps = store_hypotheses.list_hypotheses(run.id, db_path=isolated_db)
    by_id = {h["id"]: h for h in hyps}
    assert set(by_id) == {"parent-1", "child-1"}

    parent = by_id["parent-1"]
    child = by_id["child-1"]
    assert parent["parent_id"] is None
    assert parent["generation"] == 0
    assert parent["created_by_agent"] == "generation"
    assert child["parent_id"] == "parent-1"
    assert child["generation"] == 1
    assert child["created_by_agent"] == "evolution"


def test_drain_drops_orphaned_parent_reference(isolated_db: str) -> None:
    # A pruned parent must not leave a dangling foreign key that aborts the
    # whole drain.
    state = _final_state_with_lineage()
    state["hypotheses"] = [
        h for h in state["hypotheses"] if h["id"] != "parent-1"
    ]
    run = seed_run("kinase goal")
    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    hyps = store_hypotheses.list_hypotheses(run.id, db_path=isolated_db)
    assert len(hyps) == 1
    assert hyps[0]["id"] == "child-1"
    assert hyps[0]["parent_id"] is None
    assert hyps[0]["generation"] == 1


def test_drain_preserves_proximity_pruned_parent_as_a_duplicate(
    isolated_db: str,
) -> None:
    # Duplicates were folded into peers without judgment; rejection would
    # misrepresent their science.
    state = _archived_parent_state()
    run = seed_run("kinase archive goal")

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store_hypotheses.list_hypotheses(
            run.id, db_path=isolated_db
        )
    }
    assert by_id["parent-1"]["status"] == "duplicate"
    assert by_id["child-1"]["parent_id"] == "parent-1"
    [match] = records.list_matches(run.id, db_path=isolated_db)
    assert match["winner_id"] == "child-1"
    assert match["loser_id"] == "parent-1"


def test_drain_persists_evidence_quarantine_as_rejected(
    isolated_db: str,
) -> None:
    state = _final_state_with_lineage()
    state["hypotheses"][0]["review_disposition"] = "evidence_blocked"
    run = seed_run("grounded archive goal")

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store_hypotheses.list_hypotheses(
            run.id, db_path=isolated_db
        )
    }
    assert by_id["parent-1"]["status"] == "rejected"
    assert by_id["child-1"]["status"] == "active"


def test_drain_publishes_an_undermined_idea_but_records_the_verdict(
    isolated_db: str,
) -> None:
    # Undermined ideas still publish, so persist the verdict that distinguishes
    # them from sound ideas.
    state = _final_state_with_lineage()
    state["hypotheses"][0]["deep_verification_verdict"] = "undermined"
    run = seed_run("undermined archive goal")

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store_hypotheses.list_hypotheses(
            run.id, db_path=isolated_db
        )
    }
    assert by_id["parent-1"]["status"] == "active"
    assert by_id["parent-1"]["verification_verdict"] == "undermined"
    assert by_id["child-1"]["status"] == "active"
    assert by_id["child-1"]["verification_verdict"] is None


async def test_unsafe_hypothesis_excluded_from_synthesis(
    isolated_db: str,
) -> None:
    run = seed_run("safety goal")
    safe_id, _unsafe_id = _seed_safe_and_unsafe(run, isolated_db)

    payload, markdown = await _build_report(run, isolated_db)

    assert payload["hypothesis_count"] == 1
    leaderboard_ids = {row["id"] for row in payload["leaderboard"]}
    assert leaderboard_ids == {safe_id}
    assert "Weaponize" not in markdown

    decisions = records.list_safety_decisions(run.id, db_path=isolated_db)
    assert any(
        d["stage"] == "hypothesis" and d["decision"] == "block"
        for d in decisions
    )


def test_resumed_finalize_does_not_double_publish(isolated_db: str) -> None:
    run = seed_run("CSC goal")
    drained = _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    def _finalize(resumed: bool) -> list[Any]:
        return _drain(
            report_finalize.finalize_report(
                run.id,
                report_build.ReportRequest(
                    research_goal=run.research_goal,
                    run_mode="standard",
                    provider="engine",
                    execution_time=1.0,
                    db_path=isolated_db,
                    **drained.report_inputs,
                ),
                emit_event,
                resumed=resumed,
            )
        )

    first = _finalize(resumed=False)
    second = _finalize(resumed=True)

    assert any(e["type"] == "report" for e in first)
    assert second == []
    with db.connect(isolated_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE run_id=?", (run.id,)
        ).fetchone()[0]
    assert count == 1


def test_persist_passes_engine_ids_through_to_store(isolated_db: str) -> None:
    run = seed_run("CSC goal")
    _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    hyps = store_hypotheses.list_hypotheses(run.id, db_path=isolated_db)
    ids = {h["id"] for h in hyps}
    assert ids == {"eng-hyp-a", "eng-hyp-b"}


def test_persist_writes_scene_setting_onto_the_hypothesis_row(
    isolated_db: str,
) -> None:
    run = seed_run("CSC goal")
    final_state = {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-scene",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                introduction=(
                    "Breast cancer stem cells drive relapse and resistance."
                ),
                recent_findings=(
                    "CXCR1 is enriched in the stem-like subpopulation."
                ),
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }
    _persist(
        run_id=run.id,
        final_state=final_state,
        db_path=isolated_db,
    )

    hyps = store_hypotheses.list_hypotheses(run.id, db_path=isolated_db)
    assert len(hyps) == 1
    assert hyps[0]["introduction"] == (
        "Breast cancer stem cells drive relapse and resistance."
    )
    assert hyps[0]["recent_findings"] == (
        "CXCR1 is enriched in the stem-like subpopulation."
    )


def test_persist_matches_resolve_by_engine_id(isolated_db: str) -> None:
    # Evolution can change matchup display text; identity must resolve by id
    # rather than text prefixes.
    state = _final_state_with_features()
    state["tournament_matchups"][0]["hypothesis_a"] = "drifted text A"
    state["tournament_matchups"][0]["hypothesis_b"] = "drifted text B"
    run = seed_run("CSC goal")
    _persist(
        run_id=run.id,
        final_state=state,
        db_path=isolated_db,
    )

    matches = records.list_matches(run.id, db_path=isolated_db)
    assert len(matches) == 1
    match = matches[0]
    assert match["winner_id"] == "eng-hyp-a"
    assert match["loser_id"] == "eng-hyp-b"
    assert (
        store_hypotheses.get_hypothesis("eng-hyp-a", db_path=isolated_db)
        is not None
    )
    assert (
        store_hypotheses.get_hypothesis("eng-hyp-b", db_path=isolated_db)
        is not None
    )


def test_persist_skips_matchup_with_unresolved_id(isolated_db: str) -> None:
    # Dropped participant ids must not produce dangling persisted matches.
    state = _final_state_with_features()
    state["tournament_matchups"][0]["hypothesis_b_id"] = "eng-hyp-gone"
    state["tournament_matchups"][0]["winner_id"] = "eng-hyp-gone"
    run = seed_run("CSC goal")
    _persist(
        run_id=run.id,
        final_state=state,
        db_path=isolated_db,
    )

    assert records.list_matches(run.id, db_path=isolated_db) == []


def test_persist_handles_missing_research_overview(isolated_db: str) -> None:
    state = _final_state_with_features()
    del state["research_overview"]
    run = seed_run("No overview")
    _persist_and_finalize(run, state, isolated_db)

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert not report["payload"].get("research_overview")
    assert "## Research Overview" not in report["markdown_text"]
    assert "## NIH Specific Aims" not in report["markdown_text"]


def test_persist_handles_empty_research_overview(isolated_db: str) -> None:
    state = _final_state_with_features()
    state["research_overview"] = {"overview": {}, "nih_specific_aims": {}}
    run = seed_run("Empty overview")
    _persist_and_finalize(run, state, isolated_db)

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert "## Research Overview" not in report["markdown_text"]
    assert "## NIH Specific Aims" not in report["markdown_text"]


def test_persist_writes_deep_verification_reviews(isolated_db: str) -> None:
    run = seed_run("CSC goal")
    _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    reviews = records.list_reviews(run.id, db_path=isolated_db)
    deep = [r for r in reviews if r["reviewer_agent"] == "deep_verification"]
    assert len(deep) == 1
    critique = deep[0]["critique"]
    assert "Does CXCR1 signaling drive the stem-cell phenotype?" in critique
    assert "CXCR2 can compensate when CXCR1 is blocked." in critique
    assert (
        "weakened" in deep[0]["summary"].lower()
        or "weakened" in critique.lower()
    )
    assert deep[0]["novelty"] is None
    assert deep[0]["overall"] is None


def _final_state_with_novelty_review() -> dict[str, Any]:
    return {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-n",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                reviews=[
                    {
                        "review_summary": "Sound, moderately novel.",
                        "scores": {"novelty": 6},
                        "safety_ethical_concerns": "",
                        "detailed_feedback": {},
                        "constructive_feedback": "Tighten the controls.",
                        "overall_score": 6.0,
                        "already_explored": [
                            "CXCR1 is a known breast-CSC marker."
                        ],
                        "novel_aspects": ["The proposed feedback loop is new."],
                    }
                ],
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }


def test_persist_writes_novelty_review_lists_into_critique(
    isolated_db: str,
) -> None:
    run = seed_run("CSC goal")
    _persist(
        run_id=run.id,
        final_state=_final_state_with_novelty_review(),
        db_path=isolated_db,
    )

    reviews = records.list_reviews(run.id, db_path=isolated_db)
    review = next(r for r in reviews if r["reviewer_agent"] == "review")
    assert "Aspects already explored:" in review["critique"]
    assert "CXCR1 is a known breast-CSC marker." in review["critique"]
    assert "Novel Aspects:" in review["critique"]
    assert "The proposed feedback loop is new." in review["critique"]
    assert "Tighten the controls." in review["critique"]


def _final_state_with_mature_reviews() -> dict[str, Any]:
    return {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-m",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                enrichments={
                    "full": {
                        "verdict": "rejected",
                        "correctness": "The pathway claim is circular.",
                        "quality_and_novelty": "Incremental.",
                        "literature_grounding": "Thin.",
                        "justification": "Circular pathway reasoning.",
                        "assumptions": [
                            {
                                "assumption": "CXCR1 is the only driver",
                                "reasoning": (
                                    "Two other chemokine receptors are"
                                    " independently sufficient."
                                ),
                                "support": "likely_false",
                            }
                        ],
                        "retrieved_articles": [{"title": "not persisted"}],
                    },
                    "simulation": {
                        "verdict": "breaks_down",
                        "model": "Xenograft simulation",
                        "steps": [{"step": "ligand binds", "plausible": False}],
                        "failure_points": ["binding never occurs"],
                        "robustness": "Fragile.",
                        "decisive_step": "Step one fails.",
                    },
                    "recurrent": {
                        "verdict": "needs_revision",
                        "justification": "Still circular after review.",
                    },
                },
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }


def test_persist_writes_distinct_mature_review_rows(isolated_db: str) -> None:
    run = seed_run("CSC goal")
    _persist(
        run_id=run.id,
        final_state=_final_state_with_mature_reviews(),
        db_path=isolated_db,
    )

    reviews = records.list_reviews(run.id, db_path=isolated_db)
    by_agent = {r["reviewer_agent"]: r for r in reviews}
    assert set(by_agent) == {
        "full_review",
        "simulation_review",
        "recurrent_review",
    }
    assert by_agent["full_review"]["summary"] == (
        "Full review verdict: rejected"
    )
    assert "Circular pathway reasoning." in by_agent["full_review"]["critique"]
    assert "CXCR1 is the only driver" in by_agent["full_review"]["critique"]
    assert (
        "Two other chemokine receptors are independently sufficient."
        in by_agent["full_review"]["critique"]
    )
    assert by_agent["simulation_review"]["summary"] == (
        "Simulation review verdict: breaks_down"
    )
    assert "binding never occurs" in by_agent["simulation_review"]["critique"]
    assert by_agent["recurrent_review"]["summary"] == (
        "Recurrent review verdict: needs_revision"
    )
    assert "not persisted" not in str(by_agent)


def _citations_citation_map() -> dict[str, Any]:
    return {
        "C1": {
            "type": "paper",
            "title": "CXCR1 drives CSC renewal",
            "url": "https://example.org/c1",
            "authors": ["Smith"],
            "year": 2023,
        },
        "C2": {
            "type": "paper",
            "title": "Unrelated off-target study",
            "url": "https://example.org/c2",
            "authors": ["Doe"],
            "year": 2021,
        },
        "C3": {
            "type": "knowledge_graph",
            "display": "INDRA: CXCR1 -> STAT3",
        },
    }


def _final_state_with_citations() -> dict[str, Any]:
    grounding = "CXCR1 signaling drives breast cancer stem cell renewal"
    return {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-a",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                literature_grounding=grounding,
                citation_map=_citations_citation_map(),
            )
        ],
        "articles": [
            {
                "title": "CXCR1 drives CSC renewal",
                "url": "https://example.org/c1",
                "abstract": "CXCR1 signaling drives breast cancer stem "
                "cell renewal across xenograft models.",
                "authors": ["Smith"],
                "year": 2023,
            }
        ],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }


def test_persist_classifies_citations_via_shared_classifier(
    isolated_db: str,
) -> None:
    run = seed_run("CSC goal")
    _persist(
        run_id=run.id,
        final_state=_final_state_with_citations(),
        db_path=isolated_db,
    )

    citations = records.list_citations(run.id, db_path=isolated_db)
    states = {c["claim"]: c["state"] for c in citations}
    assert states == {
        "[C1] cited in hypothesis": "verified",
        "[C2] cited in hypothesis": "unsupported",
        "[C3] cited in hypothesis": "unavailable",
    }


def test_a_knowledge_graph_citations_evidence_row_keeps_its_display_text(
    isolated_db: str,
) -> None:
    # Non-paper citations use display rather than title; falling back to the
    # citation key loses source identity.
    run = seed_run("CSC goal")
    _persist(
        run_id=run.id,
        final_state=_final_state_with_citations(),
        db_path=isolated_db,
    )

    evidence = records.list_evidence(run.id, db_path=isolated_db)
    kg_row = next(e for e in evidence if e["source"] == "knowledge_graph")
    assert kg_row["title"] == "INDRA: CXCR1 -> STAT3"


async def test_the_rendered_report_resolves_the_grounding_text_citation_keys(
    isolated_db: str,
) -> None:
    run = seed_run("CSC goal")
    await drain_final_state.persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_citations(),
        db_path=isolated_db,
    )

    _payload, markdown = await _build_report(run, isolated_db)

    assert "#### References" in markdown
    section = markdown.split("#### References", 1)[1]
    assert "CXCR1 drives CSC renewal" in section
    assert "INDRA: CXCR1 -> STAT3" in section
    assert "cited in hypothesis" not in section


def _final_state_with_multi_source_grounding() -> dict[str, Any]:
    # Multiple sentences distinguish per-citation support from whole-paragraph
    # lexical dilution.
    grounding = (
        "CXCR1 signaling drives breast cancer stem cell renewal [C1]. "
        "Hypoxia-inducible factor stabilization expands the perivascular "
        "niche in glioma [C2]. "
        "The proposed coupling between the two is an extension of both."
    )
    return {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-a",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                literature_grounding=grounding,
                citation_map={
                    "C1": {
                        "type": "paper",
                        "title": "CXCR1 drives CSC renewal",
                        "url": "https://example.org/c1",
                    },
                    "C2": {
                        "type": "paper",
                        "title": "HIF expands the glioma niche",
                        "url": "https://example.org/c2",
                    },
                },
            )
        ],
        "articles": [
            {
                "title": "CXCR1 drives CSC renewal",
                "url": "https://example.org/c1",
                "abstract": (
                    "CXCR1 signaling drives breast cancer stem cell renewal "
                    "across xenograft models."
                ),
            },
            {
                "title": "HIF expands the glioma niche",
                "url": "https://example.org/c2",
                "abstract": (
                    "Hypoxia-inducible factor stabilization expands the "
                    "perivascular niche in glioma xenografts."
                ),
            },
        ],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }


def test_each_citation_is_scored_against_the_sentence_that_cites_it(
    isolated_db: str,
) -> None:
    # Classify each cited sentence; unrelated source vocabulary can make the
    # support threshold unreachable.
    run = seed_run("CSC goal")
    _persist(
        run_id=run.id,
        final_state=_final_state_with_multi_source_grounding(),
        db_path=isolated_db,
    )

    citations = records.list_citations(run.id, db_path=isolated_db)
    states = {c["claim"]: c["state"] for c in citations}
    assert states == {
        "[C1] cited in hypothesis": "verified",
        "[C2] cited in hypothesis": "verified",
    }

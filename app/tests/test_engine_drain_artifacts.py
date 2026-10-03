"""Tests for engine drain 1."""

from __future__ import annotations

import json
from typing import Any

from app import store
from app.engine_adapter.drain import final_state as drain_final_state
from app.engine_adapter.drain.final_state import fold_grounding_telemetry
from app.engine_adapter.drain.reviews import (
    _deep_verification_detail,
    _initial_review_detail,
    _mature_review_detail,
)
from app.report import build as report_build
from app.report import finalize as report_finalize
from tests._client import drain as _drain
from tests._drain_helpers import (
    _build_report,
    _engine_hypothesis,
    _final_state_with_features,
    _final_state_with_lineage,
    _persist,
    _persist_and_finalize,
)


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


# The drain persists every field the per-idea review block renders.
#
# Reviews were generated, paid for, and persisted -- and then the report
# showed none of them. Three families of content were reachable only as
# flat prose or not at all:
#
# * the initial review's **eight axis scores**, of which only three ever
#   reached a column (``novelty``, ``plausibility`` -- which actually holds
#   ``scientific_soundness`` -- and ``testability``), and its six per-axis
#   prose feedback fields, which reached nothing;
# * the full/recurrent review's assumptions and prose, flattened into the
#   ``critique`` text where no renderer can find the parts again;
# * deep verification's probes, likewise flattened.
#
# Each now travels as structured ``detail_json`` beside the prose, which is
# left untouched so the workbench keeps reading what it always did.


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

    from app.engine_adapter.drain.reviews import _REVIEW_AXES
    from app.report.markdown.hypothesis import _AXIS_SECTIONS

    assert _REVIEW_AXES == _SCORE_CRITERIA
    assert [axis for axis, _ in _AXIS_SECTIONS] == list(_SCORE_CRITERIA)


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


def test_drain_result_defaults_to_no_attributes(isolated_db: str) -> None:
    """A run with no supervisor guidance reports an empty list, not a crash."""
    run = store.create_run("no guidance goal", "standard", "engine", {})

    drained = _persist(
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

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs["attributes"] == []


# Unit tests for folding the finalize grounding pass's LLM telemetry.
#
# The real caller (``drain.persist_final_state``) always hands
# ``fold_grounding_telemetry`` an already-plain ``final_state`` -- its
# own caller runs ``_plain_final_state`` first, which serializes
# ``metrics`` to a dict before drain ever sees it -- so these tests cover
# that plain-dict shape, both empty and pre-populated.


def test_grounding_telemetry_is_folded_into_plain_metrics() -> None:
    """Non-empty usage merges into an existing plain-dict metrics field."""
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
    """A final_state with no prior metrics key still folds cleanly."""
    final_state: dict[str, Any] = {}
    usage = {"claim_grounding::llm:test-model": {"calls": 2}}

    fold_grounding_telemetry(final_state, usage)

    metrics = final_state["metrics"]
    assert metrics["llm_calls"] == 2


def test_a_grounding_pass_that_made_no_calls_charges_nothing() -> None:
    """A fully-reused grounding pass must not manufacture a metrics key."""
    final_state: dict[str, Any] = {"metrics": {"llm_calls": 4}}

    fold_grounding_telemetry(final_state, {})

    assert final_state["metrics"] == {"llm_calls": 4}


# Tests for the real-engine final-state drain in engine_adapter.
#
# The drain runs only on the real-engine branch, which the mock-forced test
# fixtures never reach. To keep it verifiable without an LLM, the drain is a
# module-level helper (`persist_final_state`) that takes a synthetic final
# state and writes hypotheses, evidence, matches, and reviews into the store,
# returning the report inputs. The report itself is built and persisted by the
# shared ``report.finalize.finalize_report`` path.
#
# This module holds the core drain, research-overview, lineage, matchup, and
# synthesis-exclusion cases. Multi-parent (combination) lineage lives in
# ``test_engine_drain_lineage.py``; citation classification and
# deep-verification reviews live in ``test_engine_drain_citations.py``; the
# pre-tournament safety screen and rank-and-publish gating live in
# ``test_engine_drain_safety.py``.
# Shared synthetic-state builders live in ``tests/_drain_helpers.py``. The
# adapter's canonical event vocabulary is covered separately in
# ``test_engine_adapter_events``.


async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A plain-dict event emitter for finalize paths that need no event log."""
    return {"type": type_, "payload": payload}


def _assert_features_proximity_edge(run_id: str, db_path: str) -> None:
    """The single feature-fixture proximity edge is persisted intact."""
    edges = store.list_proximity_edges(run_id, db_path=db_path)
    hypotheses = store.list_hypotheses(run_id, db_path=db_path)
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
    """Add one safe and one unsafe hypothesis, each with claim evidence."""
    safe_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Safe idea",
            statement=(
                "Inhibiting kinase X reduces AML tumor growth via apoptosis."
            ),
        ),
        db_path=db_path,
    )
    unsafe_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Unsafe idea",
            statement=(
                "Weaponize the pathogen to enhance transmissibility in humans."
            ),
        ),
        db_path=db_path,
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
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
    store.add_claim_evidence(
        store.NewClaimEvidence(
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
    """A lineage state whose parent is archived as a proximity duplicate."""
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
    """The research overview rides the report payload and markdown."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    _persist_and_finalize(run, _final_state_with_features(), isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
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

    evidence = store.list_evidence(run.id, db_path=isolated_db)
    retracted = next(
        item for item in evidence if item["title"] == "Retracted CXCR1 report"
    )
    assert retracted["available"] == 0

    _assert_features_proximity_edge(run.id, isolated_db)


def test_drain_persists_explicit_lineage(isolated_db: str) -> None:
    """The drain carries parent_id/generation/origin from the engine fields.

    Both parent and child survive (append semantics, no discard), the child
    links to its parent, and generation/created_by_agent reflect the explicit
    lineage rather than an evolution_history inference.
    """
    run = store.create_run("kinase goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=_final_state_with_lineage(),
        db_path=isolated_db,
    )

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    by_id = {h["id"]: h for h in hyps}
    assert set(by_id) == {"parent-1", "child-1"}  # both kept

    parent = by_id["parent-1"]
    child = by_id["child-1"]
    assert parent["parent_id"] is None
    assert parent["generation"] == 0
    assert parent["created_by_agent"] == "generation"
    assert child["parent_id"] == "parent-1"
    assert child["generation"] == 1
    assert child["created_by_agent"] == "evolution"


def test_drain_drops_orphaned_parent_reference(isolated_db: str) -> None:
    """A child whose parent is not persisted is stored as a root (FK-safe).

    Guards the hypotheses.parent_id foreign key: a dangling reference (e.g. a
    parent pruned by proximity) must not abort the drain transaction.
    """
    state = _final_state_with_lineage()
    # Drop the parent from the persisted set, leaving the child dangling.
    state["hypotheses"] = [
        h for h in state["hypotheses"] if h["id"] != "parent-1"
    ]
    run = store.create_run("kinase goal", "standard", "engine", {})
    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    assert len(hyps) == 1
    # The orphaned child is stored with parent_id cleared, generation intact.
    assert hyps[0]["id"] == "child-1"
    assert hyps[0]["parent_id"] is None
    assert hyps[0]["generation"] == 1


def test_drain_preserves_proximity_pruned_parent_as_a_duplicate(
    isolated_db: str,
) -> None:
    """A duplicate archive retains lineage and is marked as a duplicate.

    Not "rejected": nothing judged this idea, a higher-ranked one simply
    said the same thing. Recording both outcomes as "rejected" made the UI
    label a deduplicated idea "Disqualified", which reads as a verdict on
    the science -- one run showed twenty ideas that way.
    """
    state = _archived_parent_state()
    run = store.create_run("kinase archive goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    assert by_id["parent-1"]["status"] == "duplicate"
    assert by_id["child-1"]["parent_id"] == "parent-1"
    [match] = store.list_matches(run.id, db_path=isolated_db)
    assert match["winner_id"] == "child-1"
    assert match["loser_id"] == "parent-1"


def test_drain_persists_evidence_quarantine_as_rejected(
    isolated_db: str,
) -> None:
    """The pre-ranking evidence gate maps to the Non-Viable archive."""
    state = _final_state_with_lineage()
    state["hypotheses"][0]["review_disposition"] = "evidence_blocked"
    run = store.create_run("grounded archive goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    assert by_id["parent-1"]["status"] == "rejected"
    assert by_id["child-1"]["status"] == "active"


def test_drain_publishes_an_undermined_idea_but_records_the_verdict(
    isolated_db: str,
) -> None:
    """Deep verification demotes on the merits; it no longer disqualifies.

    An undermined idea now ranks and publishes, so ``status`` says
    ``active`` like any other. That is exactly why the verdict has to be
    persisted alongside it: it is the only remaining record that the idea
    is doubted, and without it a published idea reaches the reader looking
    indistinguishable from a sound one.
    """
    state = _final_state_with_lineage()
    state["hypotheses"][0]["deep_verification_verdict"] = "undermined"
    run = store.create_run("undermined archive goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    assert by_id["parent-1"]["status"] == "active"
    assert by_id["parent-1"]["verification_verdict"] == "undermined"
    assert by_id["child-1"]["status"] == "active"
    assert by_id["child-1"]["verification_verdict"] is None


async def test_unsafe_hypothesis_excluded_from_synthesis(
    isolated_db: str,
) -> None:
    """A hypothesis a per-hypothesis review blocks never reaches the report.

    Milestone 6/M9: the report synthesis excludes prohibited/ethical/uncertain
    hypotheses from the leaderboard and top ideas, recording an audit decision.
    """
    run = store.create_run("safety goal", "standard", "engine", {})
    safe_id, _unsafe_id = _seed_safe_and_unsafe(run, isolated_db)

    payload, markdown = await _build_report(run, isolated_db)

    # Only the safe hypothesis is synthesized.
    assert payload["hypothesis_count"] == 1
    leaderboard_ids = {row["id"] for row in payload["leaderboard"]}
    assert leaderboard_ids == {safe_id}
    assert "Weaponize" not in markdown

    # The exclusion is recorded as a per-hypothesis safety audit decision.
    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    assert any(
        d["stage"] == "hypothesis" and d["decision"] == "block"
        for d in decisions
    )


def test_resumed_finalize_does_not_double_publish(isolated_db: str) -> None:
    """A resumed run that finalizes twice publishes exactly one report.

    Milestone 4 idempotency: the single-publish guard (gated on ``resumed``)
    makes a second finalize a no-op once a report exists.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
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
                _emit,
                resumed=resumed,
            )
        )

    first = _finalize(resumed=False)
    # A resumed second finalize is a no-op: no new events, one report only.
    second = _finalize(resumed=True)

    assert any(e["type"] == "report" for e in first)
    assert second == []
    with store.connect(isolated_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE run_id=?", (run.id,)
        ).fetchone()[0]
    assert count == 1


def test_persist_passes_engine_ids_through_to_store(isolated_db: str) -> None:
    """Hypothesis rows carry the engine's stable id (id pass-through)."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    ids = {h["id"] for h in hyps}
    assert ids == {"eng-hyp-a", "eng-hyp-b"}


def test_persist_writes_scene_setting_onto_the_hypothesis_row(
    isolated_db: str,
) -> None:
    """Introduction/Recent findings (MO-6) persist on the hypothesis row."""
    run = store.create_run("CSC goal", "standard", "engine", {})
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

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    assert len(hyps) == 1
    assert hyps[0]["introduction"] == (
        "Breast cancer stem cells drive relapse and resistance."
    )
    assert hyps[0]["recent_findings"] == (
        "CXCR1 is enriched in the stem-like subpopulation."
    )


def test_persist_matches_resolve_by_engine_id(isolated_db: str) -> None:
    """Tournament matches resolve by id even when the matchup text has drifted.

    The matchup's ``hypothesis_a``/``hypothesis_b`` display text is deliberately
    made to NOT match the persisted hypothesis statements (as happens when
    evolve mutates a hypothesis's text after ranking recorded the matchup). The
    old text-prefix matching would drop such a match; id-based resolution must
    still find it.
    """
    state = _final_state_with_features()
    state["tournament_matchups"][0]["hypothesis_a"] = "drifted text A"
    state["tournament_matchups"][0]["hypothesis_b"] = "drifted text B"
    run = store.create_run("CSC goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=state,
        db_path=isolated_db,
    )

    matches = store.list_matches(run.id, db_path=isolated_db)
    assert len(matches) == 1
    match = matches[0]
    # Ids flow straight through: the persisted match points at the engine ids.
    assert match["winner_id"] == "eng-hyp-a"
    assert match["loser_id"] == "eng-hyp-b"
    # And those ids are real hypothesis rows for the run.
    assert store.get_hypothesis("eng-hyp-a", db_path=isolated_db) is not None
    assert store.get_hypothesis("eng-hyp-b", db_path=isolated_db) is not None


def test_persist_skips_matchup_with_unresolved_id(isolated_db: str) -> None:
    """A matchup referencing a dropped hypothesis id is skipped, not persisted.

    Evolution discards lower-ranked hypotheses, so a final matchup can reference
    an id absent from the final set. Such a matchup must be skipped rather than
    persisted with a bad reference.
    """
    state = _final_state_with_features()
    state["tournament_matchups"][0]["hypothesis_b_id"] = "eng-hyp-gone"
    state["tournament_matchups"][0]["winner_id"] = "eng-hyp-gone"
    run = store.create_run("CSC goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=state,
        db_path=isolated_db,
    )

    assert store.list_matches(run.id, db_path=isolated_db) == []


def test_persist_handles_missing_research_overview(isolated_db: str) -> None:
    """Older runs without a research overview do not crash or emit a header."""
    state = _final_state_with_features()
    del state["research_overview"]
    run = store.create_run("No overview", "standard", "engine", {})
    _persist_and_finalize(run, state, isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert not report["payload"].get("research_overview")
    assert "## Research Overview" not in report["markdown_text"]
    assert "## NIH Specific Aims" not in report["markdown_text"]


def test_persist_handles_empty_research_overview(isolated_db: str) -> None:
    """An overview with empty sub-dicts emits no empty headers."""
    state = _final_state_with_features()
    state["research_overview"] = {"overview": {}, "nih_specific_aims": {}}
    run = store.create_run("Empty overview", "standard", "engine", {})
    _persist_and_finalize(run, state, isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert "## Research Overview" not in report["markdown_text"]
    assert "## NIH Specific Aims" not in report["markdown_text"]


# Engine-drain tests for citations and deep-verification reviews.
#
# Split out of ``test_engine_drain.py`` by concern. These cover the drain's
# citation classification through the shared four-state classifier and the
# persistence of deep-verification probes as review rows. Shared builders live
# in
# ``tests/_drain_helpers.py``.


def test_persist_writes_deep_verification_reviews(isolated_db: str) -> None:
    """Hypotheses with probes get a deep_verification review row."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    reviews = store.list_reviews(run.id, db_path=isolated_db)
    deep = [r for r in reviews if r["reviewer_agent"] == "deep_verification"]
    # Only the first hypothesis has probes.
    assert len(deep) == 1
    critique = deep[0]["critique"]
    assert "Does CXCR1 signaling drive the stem-cell phenotype?" in critique
    assert "CXCR2 can compensate when CXCR1 is blocked." in critique
    assert (
        "weakened" in deep[0]["summary"].lower()
        or "weakened" in critique.lower()
    )
    # Score columns are not produced by deep verification.
    assert deep[0]["novelty"] is None
    assert deep[0]["overall"] is None


def _final_state_with_novelty_review() -> dict[str, Any]:
    """A final state whose hypothesis carries the published novelty review."""
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
    """Already-explored/novel-aspects lists reach the reader (MO-3)."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=_final_state_with_novelty_review(),
        db_path=isolated_db,
    )

    reviews = store.list_reviews(run.id, db_path=isolated_db)
    review = next(r for r in reviews if r["reviewer_agent"] == "review")
    assert "Aspects already explored:" in review["critique"]
    assert "CXCR1 is a known breast-CSC marker." in review["critique"]
    assert "Novel Aspects:" in review["critique"]
    assert "The proposed feedback loop is new." in review["critique"]
    # The plain constructive-feedback content is preserved too.
    assert "Tighten the controls." in review["critique"]


def _final_state_with_mature_reviews() -> dict[str, Any]:
    """A final state whose hypothesis carries all three mature reviews."""
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
    """Full/simulation/recurrent results reach the reader as labeled rows.

    They used to stop at the engine's enrichments (audit E1): nothing the
    report reader could see. Each becomes its own review row under a
    distinct reviewer_agent, with the verdict as the summary.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=_final_state_with_mature_reviews(),
        db_path=isolated_db,
    )

    reviews = store.list_reviews(run.id, db_path=isolated_db)
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
    # The published free-text reasoning paragraph (MO-9) rides alongside
    # the assumption and its support verdict.
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
    # Retrieval bookkeeping never reaches the persisted row.
    assert "not persisted" not in str(by_agent)


def _citations_citation_map() -> dict[str, Any]:
    """Three citations engineered to land in three distinct citation states.

    Once routed through ``classify_citation``: a retrieved paper whose abstract
    overlaps the grounding (verified), a paper with a URL but no retrieved
    abstract (unsupported), and a knowledge-graph source with no URL
    (unavailable).
    """
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
    """A minimal final state whose hypothesis cites three distinct sources."""
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
    """Engine citations run through classify_citation, not a hardcoded state.

    Regression guard: the drain previously stamped every citation "verified",
    leaving the four-state citation UI dead for real runs. Each source must now
    resolve to the state its content warrants.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=_final_state_with_citations(),
        db_path=isolated_db,
    )

    citations = store.list_citations(run.id, db_path=isolated_db)
    states = {c["claim"]: c["state"] for c in citations}
    assert states == {
        "[C1] cited in hypothesis": "verified",
        "[C2] cited in hypothesis": "unsupported",
        "[C3] cited in hypothesis": "unavailable",
    }


def test_a_knowledge_graph_citations_evidence_row_keeps_its_display_text(
    isolated_db: str,
) -> None:
    """A non-paper citation's evidence title must not become its bare key.

    ``_persist_one_citation`` fell back to the [C*] key itself
    (``cite_info.get("title", cite_key)``) whenever a source carried no
    "title" -- true of every non-paper source, which is keyed by "display"
    instead (see ``citations._enrichment_reference_entries``). A run citing
    an INDRA statement therefore persisted an evidence row titled literally
    "C3" rather than the statement it names.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=_final_state_with_citations(),
        db_path=isolated_db,
    )

    evidence = store.list_evidence(run.id, db_path=isolated_db)
    kg_row = next(e for e in evidence if e["source"] == "knowledge_graph")
    assert kg_row["title"] == "INDRA: CXCR1 -> STAT3"


async def test_the_rendered_report_resolves_the_grounding_text_citation_keys(
    isolated_db: str,
) -> None:
    """End to end: a drained run's report resolves its own [C*] keys.

    The generation prompt writes [C1]/[C2]/[C3] into the mechanism text; the
    drain persists the engine's citation_map into citations+evidence; the
    report must join the two back together rather than leaving the reader
    with bracketed keys that resolve to nothing.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
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
    # The filler claim text a citation row carries for classification
    # purposes must never leak into the reader-facing reference line.
    assert "cited in hypothesis" not in section


def _final_state_with_multi_source_grounding() -> dict[str, Any]:
    """A run-shaped grounding: several sentences, each citing its own paper.

    The single-sentence fixture above cannot distinguish a citation matched
    against the sentence that cites it from one matched against the whole
    paragraph, because there is only one sentence. A real grounding is a
    synthesis paragraph spanning every source, and each abstract restates
    only its own sentence.
    """
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
    """A multi-source grounding must not make every citation unsupported.

    Coverage is measured over the claim's own vocabulary, so handing the
    classifier the whole grounding paragraph divides each source's real
    overlap by every other source's words too. In one live run the best of
    27 citations scored 0.23 against a 0.30 "partial" line, so a run whose
    every citation was retrieved and on-point still reported 0 verified,
    0 partial, 33 unsupported -- the same unreachable-upper-states failure
    the Jaccard fix removed, arriving by a different route.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=_final_state_with_multi_source_grounding(),
        db_path=isolated_db,
    )

    citations = store.list_citations(run.id, db_path=isolated_db)
    states = {c["claim"]: c["state"] for c in citations}
    assert states == {
        "[C1] cited in hypothesis": "verified",
        "[C2] cited in hypothesis": "verified",
    }

from __future__ import annotations

import json
from typing import Any

import pytest

from app.engine_adapter.drain import final_state as drain_final_state
from app.engine_adapter.drain.final_state import fold_grounding_telemetry
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


@pytest.mark.parametrize(
    ("guidance", "key", "expected"),
    [
        (None, "critical_criteria", []),
        (None, "attributes", []),
        (
            {"workflow_plan": {"review_phase": {"critical_criteria": ["a"]}}},
            "critical_criteria",
            ["a"],
        ),
        # Structured criteria are valid guidance; string-only filtering would
        # silently discard them.
        (
            {
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
            },
            "critical_criteria",
            ["novelty", {"name": "Kinetic Feasibility", "questions": []}],
        ),
        (
            {"workflow_plan": {"review_phase": "not a dict"}},
            "critical_criteria",
            [],
        ),
        (
            {
                "config_synthesis": {
                    "attributes": [
                        {"name": "Mechanism Novelty", "rubric": "1-5"}
                    ]
                }
            },
            "attributes",
            [{"name": "Mechanism Novelty", "rubric": "1-5"}],
        ),
        ({"config_synthesis": "not a dict"}, "attributes", []),
    ],
)
def test_drain_result_carries_supervisor_guidance_into_report_inputs(
    isolated_db: str,
    guidance: dict[str, Any] | None,
    key: str,
    expected: list[Any],
) -> None:
    run = seed_run("guidance goal")
    state = _final_state_with_features()
    if guidance is not None:
        state["supervisor_guidance"] = guidance

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs[key] == expected


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


def test_persisted_review_rows_carry_the_structured_detail(
    isolated_db: str,
) -> None:
    hypothesis = _engine_hypothesis(
        "h-1",
        "A hypothesis.",
        reviews=[_engine_review()],
        deep_verification_probes=[
            {
                "question": "Does the receptor bind?",
                "answer": "Yes, at nanomolar affinity.",
                "reasoning": "Two structures show the contact.",
                "assumption_is_fundamental": True,
            },
            {"question": "", "answer": "dropped"},
        ],
        deep_verification_verdict="holds",
        enrichments={
            "full": {
                "verdict": "sound",
                "correctness": "The logic holds.",
                "assumptions": [
                    {
                        "assumption": "The receptor is expressed.",
                        "reasoning": "Two cohorts detect it directly.",
                        "support": "supported",
                    },
                    {"assumption": "", "reasoning": "dropped"},
                ],
                "reviews_summary": {"conclusion": "Worth testing."},
                "feasibility_steps": ["Run the pilot."],
            }
        },
    )
    hypothesis["reviews"][0]["scores"]["vibes"] = 11
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
        for row in records.list_reviews(run.id, db_path=isolated_db)
    }
    review = by_agent["review"]
    assert review["scores"] == _engine_review()["scores"]
    assert len(review["detailed_feedback"]) == 6
    assert review["constructive_feedback"] == "Name the control arm."
    assert review["already_explored"] == ["Target engagement is documented."]
    assert review["novel_aspects"] == [
        "The stress-induced modification is new."
    ]
    assert by_agent["deep_verification"]["probes"] == [
        {
            "question": "Does the receptor bind?",
            "answer": "Yes, at nanomolar affinity.",
            "reasoning": "Two structures show the contact.",
            "fundamental": True,
        }
    ]
    full = by_agent["full_review"]
    assert full["reviews_summary"]["conclusion"] == "Worth testing."
    assert full["assumptions"] == [
        {
            "assumption": "The receptor is expressed.",
            "reasoning": "Two cohorts detect it directly.",
            "support": "Plausible",
        }
    ]
    assert full["feasibility_steps"] == ["Run the pilot."]


@pytest.mark.parametrize(
    ("final_state", "usage", "calls"),
    [
        (
            {"metrics": {"llm_calls": 3, "model_usage": {}}},
            {"g::m": {"calls": 5}},
            8,
        ),
        ({}, {"g::m": {"calls": 2}}, 2),
        ({"metrics": {"llm_calls": 4}}, {}, 4),
    ],
)
def test_grounding_telemetry_is_charged_once_into_plain_metrics(
    final_state: dict[str, Any], usage: dict[str, Any], calls: int
) -> None:
    fold_grounding_telemetry(final_state, usage)

    metrics = final_state["metrics"]
    assert metrics["llm_calls"] == calls
    assert ("g::m" in metrics.get("model_usage", {})) is bool(usage)


def test_review_axes_match_the_engine_score_criteria() -> None:
    # App axis copies avoid runtime schema imports but must track engine
    # additions and order.
    from co_scientist.schemas.review import _SCORE_CRITERIA

    from app.engine_adapter.drain.reviews import _REVIEW_AXES
    from app.report.markdown.hypothesis import _AXIS_SECTIONS

    assert _REVIEW_AXES == _SCORE_CRITERIA
    assert [axis for axis, _ in _AXIS_SECTIONS] == list(_SCORE_CRITERIA)


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


@pytest.mark.parametrize(
    ("overrides", "status", "verdict"),
    [
        ({"review_disposition": "evidence_blocked"}, "rejected", None),
        # Undermined ideas still publish, so the verdict is what distinguishes
        # them from sound ideas.
        ({"deep_verification_verdict": "undermined"}, "active", "undermined"),
    ],
)
def test_drain_maps_evidence_outcomes_onto_publication_status(
    isolated_db: str,
    overrides: dict[str, Any],
    status: str,
    verdict: str | None,
) -> None:
    state = _final_state_with_lineage()
    state["hypotheses"][0].update(overrides)
    run = seed_run("archive goal")

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store_hypotheses.list_hypotheses(
            run.id, db_path=isolated_db
        )
    }
    assert by_id["parent-1"]["status"] == status
    assert by_id["parent-1"]["verification_verdict"] == verdict
    assert by_id["child-1"]["status"] == "active"


@pytest.mark.parametrize(
    "research_overview", [None, {"overview": {}, "nih_specific_aims": {}}]
)
def test_persist_omits_research_overview_sections_when_there_is_none(
    isolated_db: str, research_overview: dict[str, Any] | None
) -> None:
    state = _final_state_with_features()
    if research_overview is None:
        del state["research_overview"]
    else:
        state["research_overview"] = research_overview
    run = seed_run("No overview")
    _persist_and_finalize(run, state, isolated_db)

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert "## Research Overview" not in report["markdown_text"]
    assert "## NIH Specific Aims" not in report["markdown_text"]


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
    # Non-paper citations use display rather than title; falling back to the
    # citation key loses source identity.
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

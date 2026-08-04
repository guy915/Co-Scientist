"""Tests for the real-engine final-state drain in engine_adapter.

The drain runs only on the real-engine branch, which the mock-forced test
fixtures never reach. To keep it verifiable without an LLM, the drain is a
module-level helper (`_persist_final_state`) that takes a synthetic final
state and writes hypotheses, evidence, matches, and reviews into the store,
returning the report inputs. The report itself is built and persisted by the
shared ``report_render.finalize_report`` path.

This module holds the core drain, research-overview, lineage, matchup, and
synthesis-exclusion cases. Citation classification and deep-verification
reviews live in ``test_engine_drain_citations.py``; the pre-tournament safety
screen and rank-and-publish gating live in ``test_engine_drain_safety.py``.
Shared synthetic-state builders live in ``tests/_drain_helpers.py``. The
adapter's canonical event vocabulary is covered separately in
``test_engine_adapter_events``.
"""

from __future__ import annotations

from typing import Any

from app import engine_adapter, report_render, store
from tests._client import drain as _drain
from tests._drain_helpers import (
    _build_report,
    _final_state_with_features,
    _final_state_with_lineage,
    _persist_and_finalize,
)


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
    assert overview["nih_specific_aims"]["aims"][0]["aim"].startswith("Aim 1")

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
    engine_adapter._persist_final_state(
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
    engine_adapter._persist_final_state(
        run_id=run.id, final_state=state, db_path=isolated_db
    )

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

    engine_adapter._persist_final_state(
        run_id=run.id, final_state=state, db_path=isolated_db
    )

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

    engine_adapter._persist_final_state(
        run_id=run.id, final_state=state, db_path=isolated_db
    )

    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    assert by_id["parent-1"]["status"] == "rejected"
    assert by_id["child-1"]["status"] == "active"


def test_drain_persists_undermined_verdict_as_rejected(
    isolated_db: str,
) -> None:
    """Deep verification excludes on the merits, so it is not "Unranked".

    The UI reads ``status`` to tell "Disqualified" from "Unranked". An idea
    deep verification undermined never enters the tournament, so recorded as
    active it shows as merely unranked -- the conflation the status removes.
    """
    state = _final_state_with_lineage()
    state["hypotheses"][0]["deep_verification_verdict"] = "undermined"
    run = store.create_run("undermined archive goal", "standard", "engine", {})

    engine_adapter._persist_final_state(
        run_id=run.id, final_state=state, db_path=isolated_db
    )

    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    assert by_id["parent-1"]["status"] == "rejected"
    assert by_id["child-1"]["status"] == "active"


def test_unsafe_hypothesis_excluded_from_synthesis(isolated_db: str) -> None:
    """A hypothesis a per-hypothesis review blocks never reaches the report.

    Milestone 6/M9: the report synthesis excludes prohibited/ethical/uncertain
    hypotheses from the leaderboard and top ideas, recording an audit decision.
    """
    run = store.create_run("safety goal", "standard", "engine", {})
    safe_id, _unsafe_id = _seed_safe_and_unsafe(run, isolated_db)

    payload, markdown = _build_report(run, isolated_db)

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
    drained = engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    def _finalize(resumed: bool) -> list[Any]:
        return _drain(
            report_render.finalize_report(
                run.id,
                report_render.ReportRequest(
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
    engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    ids = {h["id"] for h in hyps}
    assert ids == {"eng-hyp-a", "eng-hyp-b"}


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
    engine_adapter._persist_final_state(
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
    engine_adapter._persist_final_state(
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

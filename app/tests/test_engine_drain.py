"""Tests for the real-engine final-state drain in engine_adapter.

The drain runs only on the real-engine branch, which the mock-forced test
fixtures never reach. To keep it verifiable without an LLM, the drain is a
module-level helper (`_persist_final_state`) that takes a synthetic final
state and writes hypotheses, evidence, matches, and reviews into the store,
returning the report inputs. The report itself is built and persisted by the
shared ``report_render.finalize_report`` path. These tests exercise the
canonical-fidelity additions:

- The research overview is written into the report payload and markdown.
- Each hypothesis's deep-verification probes are written into the reviews
  table as ``reviewer_agent="deep_verification"`` rows.
- Citations are classified through the shared four-state classifier.

The adapter's streamed event vocabulary is covered separately in
``test_engine_adapter_events``, which imports the shared ``_drain`` helper from
here to avoid duplicating setup.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app import engine_adapter, report_render, store


def _final_state_with_features() -> dict[str, Any]:
    """Build a synthetic engine final state carrying the new features."""
    return {
        "hypotheses": [
            {
                "id": "eng-hyp-a",
                "text": "Reparixin inhibits CXCR1 to suppress breast cancer "
                "stem cells.",
                "explanation": "Blocking CXCR1 reduces the stem-cell pool.",
                "literature_grounding": "CXCR1 is enriched in breast CSCs.",
                "experiment": "Treat patient-derived xenografts with "
                "reparixin.",
                "elo_rating": 1320,
                "win_count": 4,
                "loss_count": 1,
                "score": 0.8,
                "reviews": [],
                "citation_map": {},
                "evolution_history": [],
                "deep_verification_probes": [
                    {
                        "question": "Does CXCR1 signaling drive the stem-cell "
                        "phenotype?",
                        "answer": "Partially; redundant chemokine receptors "
                        "exist.",
                        "reasoning": "CXCR2 can compensate when CXCR1 "
                        "is blocked.",
                        "assumption_is_fundamental": True,
                    },
                    {
                        "question": "Is reparixin selective for CXCR1?",
                        "answer": "It also antagonizes CXCR2 at high doses.",
                        "reasoning": "Off-target effects may confound.",
                        "assumption_is_fundamental": False,
                    },
                ],
                "deep_verification_verdict": "weakened",
            },
            {
                "id": "eng-hyp-b",
                "text": "A control hypothesis with no probes.",
                "explanation": "",
                "literature_grounding": "",
                "experiment": "",
                "elo_rating": 1180,
                "win_count": 1,
                "loss_count": 3,
                "reviews": [],
                "citation_map": {},
                "evolution_history": [],
                "deep_verification_probes": [],
                "deep_verification_verdict": None,
            },
        ],
        "articles": [],
        "tournament_matchups": [
            {
                "hypothesis_a": "Reparixin inhibits CXCR1 to suppress "
                "breast cancer stem cells.",
                "hypothesis_b": "A control hypothesis with no probes.",
                "hypothesis_a_id": "eng-hyp-a",
                "hypothesis_b_id": "eng-hyp-b",
                "winner_id": "eng-hyp-a",
                "winner": "a",
                "reasoning": "A is better grounded.",
                "confidence": "High",
                "winner_elo_before": 1300,
                "winner_elo_after": 1320,
                "loser_elo_before": 1200,
                "loser_elo_after": 1180,
            },
        ],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {
            "overview": {
                "summary": "Targeting CXCR1 is a promising but "
                "redundant pathway.",
                "research_directions": [
                    {
                        "title": "Dual CXCR1/CXCR2 blockade",
                        "importance": "Overcomes compensatory signaling.",
                        "suggested_experiments": [
                            "Combine reparixin with a CXCR2 antagonist.",
                            "Measure CSC frequency by flow cytometry.",
                        ],
                    },
                ],
            },
            "nih_specific_aims": {
                "introduction": "Breast cancer stem cells drive recurrence.",
                "aims": [
                    {
                        "aim": "Aim 1: Quantify CXCR1 dependence.",
                        "rationale": "Establish the mechanistic baseline.",
                        "approach": "shRNA knockdown in PDX models.",
                    },
                ],
                "impact": "Could yield a combination therapy for TNBC.",
            },
        },
    }


def _drain(gen: AsyncIterator[Any]) -> list[Any]:

    async def _run() -> list[Any]:
        return [e async for e in gen]

    return asyncio.run(_run())


def _persist_and_finalize(
    run: Any, final_state: dict[str, Any], db_path: str
) -> None:
    """Drain a synthetic final state, then build + persist its report.

    Mirrors the engine branch of ``run_workflow``: the drain writes rows and
    returns the report inputs, and ``finalize_report`` builds/screens/saves the
    report. Uses a plain-dict emitter, so no event log is needed.
    """
    report_inputs = engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=final_state,
        db_path=db_path,
    )

    async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"type": type_, "payload": payload}

    _drain(
        report_render.finalize_report(
            run_id=run.id,
            research_goal=run.research_goal,
            run_mode="standard",
            provider="engine",
            emit=_emit,
            execution_time=1.0,
            db_path=db_path,
            **report_inputs,
        )
    )


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


def _final_state_with_lineage() -> dict[str, Any]:
    """A final state with an explicit parent and an evolution child.

    The child carries explicit lineage (parent_id/generation/origin) and an
    empty evolution_history, so the drain must read the explicit fields rather
    than inferring lineage from evolution_history.
    """
    return {
        "hypotheses": [
            {
                "id": "parent-1",
                "text": "Parent hypothesis about kinase X.",
                "parent_id": None,
                "generation": 0,
                "origin": "generation",
                "elo_rating": 1200,
                "win_count": 0,
                "loss_count": 0,
                "reviews": [],
                "citation_map": {},
                "evolution_history": [],
                "deep_verification_probes": [],
                "deep_verification_verdict": None,
            },
            {
                "id": "child-1",
                "text": "Child hypothesis: kinase X plus cofactor W.",
                "parent_id": "parent-1",
                "generation": 1,
                "origin": "evolution",
                # Explicitly empty: lineage must come from the fields above.
                "evolution_history": [],
                "elo_rating": 1200,
                "win_count": 0,
                "loss_count": 0,
                "reviews": [],
                "citation_map": {},
                "deep_verification_probes": [],
                "deep_verification_verdict": None,
            },
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


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


def test_unsafe_hypothesis_excluded_from_synthesis(isolated_db: str) -> None:
    """A hypothesis a per-hypothesis review blocks never reaches the report.

    Milestone 6/M9: the report synthesis excludes prohibited/ethical/uncertain
    hypotheses from the leaderboard and top ideas, recording an audit decision.
    """
    run = store.create_run("safety goal", "standard", "engine", {})
    safe_id = store.add_hypothesis(
        run.id,
        title="Safe idea",
        statement="Inhibiting kinase X reduces AML tumor growth via apoptosis.",
        db_path=isolated_db,
    )
    store.add_hypothesis(
        run.id,
        title="Unsafe idea",
        statement=(
            "Weaponize the pathogen to enhance transmissibility in humans."
        ),
        db_path=isolated_db,
    )

    payload, markdown = report_render._build_report_content(
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode="standard",
        provider="engine",
        citation_summary=None,
        meta_review=None,
        research_overview=None,
        execution_time=1.0,
        summary=None,
        db_path=isolated_db,
    )

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


def test_drain_screens_hypotheses_before_finalize(isolated_db: str) -> None:
    """The drain persists each hypothesis's safety_status and blocks unsafe.

    Milestone 6/M9: the per-hypothesis safety screen runs inside the drain
    (before the report is built), so an unsafe hypothesis is marked and audited
    at persistence time -- not only filtered out later at report synthesis.
    """
    run = store.create_run("safety goal", "standard", "engine", {})
    state: dict[str, Any] = {
        "hypotheses": [
            {
                "id": "safe-1",
                "text": "Inhibiting kinase X reduces AML growth via apoptosis.",
                "parent_id": None,
                "generation": 0,
                "origin": "generation",
                "elo_rating": 1200,
                "win_count": 0,
                "loss_count": 0,
                "reviews": [],
                "citation_map": {},
                "evolution_history": [],
                "deep_verification_probes": [],
                "deep_verification_verdict": None,
            },
            {
                "id": "unsafe-1",
                "text": "Weaponize the pathogen to enhance transmissibility.",
                "parent_id": None,
                "generation": 0,
                "origin": "generation",
                "elo_rating": 1200,
                "win_count": 0,
                "loss_count": 0,
                "reviews": [],
                "citation_map": {},
                "evolution_history": [],
                "deep_verification_probes": [],
                "deep_verification_verdict": None,
            },
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }

    engine_adapter._persist_final_state(
        run_id=run.id, final_state=state, db_path=isolated_db
    )

    # safety_status is persisted for every hypothesis by the drain itself.
    by_text = {h["statement"][:8]: h for h in store.list_hypotheses(run.id)}
    assert by_text["Inhibiti"]["safety_status"] == "allow"
    assert by_text["Weaponiz"]["safety_status"] == "prohibited"

    # A blocking audit row was recorded during the drain (pre-finalize).
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
    inputs = engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"type": type_, "payload": payload}

    def _finalize(resumed: bool) -> list[Any]:
        return _drain(
            report_render.finalize_report(
                run_id=run.id,
                research_goal=run.research_goal,
                run_mode="standard",
                provider="engine",
                emit=_emit,
                execution_time=1.0,
                resumed=resumed,
                db_path=isolated_db,
                **inputs,
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


def test_persist_writes_deep_verification_reviews(isolated_db: str) -> None:
    """Hypotheses with probes get a deep_verification review row."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(
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


def _final_state_with_citations() -> dict[str, Any]:
    """A minimal final state whose hypothesis cites three distinct sources.

    The three citations are engineered to land in three different citation
    states once routed through ``classify_citation``: a retrieved paper whose
    abstract overlaps the grounding (verified), a paper with a URL but no
    retrieved abstract (unsupported), and a knowledge-graph source with no URL
    (unavailable).
    """
    grounding = "CXCR1 signaling drives breast cancer stem cell renewal"
    return {
        "hypotheses": [
            {
                "id": "eng-hyp-a",
                "text": "Blocking CXCR1 suppresses breast cancer stem cells.",
                "literature_grounding": grounding,
                "citation_map": {
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
                },
            }
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
    engine_adapter._persist_final_state(
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

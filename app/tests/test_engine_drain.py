"""Tests for the real-engine final-state drain in engine_adapter.

The drain runs only on the real-engine branch, which the mock-forced test
fixtures never reach. To keep it verifiable without an LLM, the drain is a
module-level helper (`_persist_final_state`) that takes a synthetic final
state and writes hypotheses, evidence, matches, reviews, and the report into
the store. These tests exercise the two canonical-fidelity additions:

- The research overview is written into the report payload and markdown.
- Each hypothesis's deep-verification probes are written into the reviews
  table as ``reviewer_agent="deep_verification"`` rows.
"""
from __future__ import annotations

from typing import Any

from app import engine_adapter, store


def _final_state_with_features() -> dict[str, Any]:
    """Build a synthetic engine final state carrying the new features."""
    return {
        "hypotheses": [
            {
                "text":
                    "Reparixin inhibits CXCR1 to suppress breast cancer "
                    "stem cells.",
                "explanation":
                    "Blocking CXCR1 reduces the stem-cell pool.",
                "literature_grounding":
                    "CXCR1 is enriched in breast CSCs.",
                "experiment":
                    "Treat patient-derived xenografts with reparixin.",
                "elo_rating":
                    1320,
                "win_count":
                    4,
                "loss_count":
                    1,
                "score":
                    0.8,
                "reviews": [],
                "citation_map": {},
                "evolution_history": [],
                "deep_verification_probes": [
                    {
                        "question":
                            "Does CXCR1 signaling drive the stem-cell "
                            "phenotype?",
                        "answer":
                            "Partially; redundant chemokine receptors "
                            "exist.",
                        "reasoning":
                            "CXCR2 can compensate when CXCR1 is blocked.",
                        "assumption_is_fundamental":
                            True,
                    },
                    {
                        "question": "Is reparixin selective for CXCR1?",
                        "answer": "It also antagonizes CXCR2 at high doses.",
                        "reasoning": "Off-target effects may confound.",
                        "assumption_is_fundamental": False,
                    },
                ],
                "deep_verification_verdict":
                    "weakened",
            },
            {
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
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {
            "overview": {
                "summary":
                    "Targeting CXCR1 is a promising but redundant pathway.",
                "research_directions": [{
                    "title":
                        "Dual CXCR1/CXCR2 blockade",
                    "importance":
                        "Overcomes compensatory signaling.",
                    "suggested_experiments": [
                        "Combine reparixin with a CXCR2 antagonist.",
                        "Measure CSC frequency by flow cytometry.",
                    ],
                },],
            },
            "nih_specific_aims": {
                "introduction": "Breast cancer stem cells drive recurrence.",
                "aims": [{
                    "aim": "Aim 1: Quantify CXCR1 dependence.",
                    "rationale": "Establish the mechanistic baseline.",
                    "approach": "shRNA knockdown in PDX models.",
                },],
                "impact": "Could yield a combination therapy for TNBC.",
            },
        },
    }


def test_persist_writes_research_overview_into_report(isolated_db: str) -> None:
    """The research overview rides the report payload and markdown."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(  # pylint: disable=protected-access
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode="standard",
        final_state=_final_state_with_features(),
        execution_time=1.0,
        db_path=isolated_db,
    )

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


def test_persist_writes_deep_verification_reviews(isolated_db: str) -> None:
    """Hypotheses with probes get a deep_verification review row."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(  # pylint: disable=protected-access
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode="standard",
        final_state=_final_state_with_features(),
        execution_time=1.0,
        db_path=isolated_db,
    )

    reviews = store.list_reviews(run.id, db_path=isolated_db)
    deep = [r for r in reviews if r["reviewer_agent"] == "deep_verification"]
    # Only the first hypothesis has probes.
    assert len(deep) == 1
    critique = deep[0]["critique"]
    assert "Does CXCR1 signaling drive the stem-cell phenotype?" in critique
    assert "CXCR2 can compensate when CXCR1 is blocked." in critique
    assert "weakened" in deep[0]["summary"].lower(
    ) or "weakened" in critique.lower()
    # Score columns are not produced by deep verification.
    assert deep[0]["novelty"] is None
    assert deep[0]["overall"] is None


def test_persist_handles_missing_research_overview(isolated_db: str) -> None:
    """Older runs without a research overview do not crash or emit a header."""
    state = _final_state_with_features()
    del state["research_overview"]
    run = store.create_run("No overview", "standard", "engine", {})
    engine_adapter._persist_final_state(  # pylint: disable=protected-access
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode="standard",
        final_state=state,
        execution_time=1.0,
        db_path=isolated_db,
    )

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
    engine_adapter._persist_final_state(  # pylint: disable=protected-access
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode="standard",
        final_state=state,
        execution_time=1.0,
        db_path=isolated_db,
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert "## Research Overview" not in report["markdown_text"]
    assert "## NIH Specific Aims" not in report["markdown_text"]

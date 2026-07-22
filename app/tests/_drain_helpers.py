"""Shared builders for the engine-drain test modules.

Not a test module (underscore prefix), so pytest does not collect it. The
synthetic engine-final-state builders and the persist+finalize helper live here
because they are shared across ``test_engine_drain.py`` and its sibling
concern-clustered modules (``test_engine_drain_citations.py``).
"""

from __future__ import annotations

from typing import Any

from app import engine_adapter, report_render
from tests._client import drain as _drain


def _engine_hypothesis(
    hyp_id: str, text: str, **overrides: Any
) -> dict[str, Any]:
    """Build a synthetic engine hypothesis with the drain's optional keys.

    The drain reads Elo, win/loss counts, reviews, citations, evolution
    history, and deep-verification fields via ``.get(key, default)``, so a
    fixture only needs to spell out the fields under test; the rest default
    here instead of being repeated in every hypothesis literal.
    """
    return {
        "id": hyp_id,
        "text": text,
        "elo_rating": 1200,
        "win_count": 0,
        "loss_count": 0,
        "reviews": [],
        "citation_map": {},
        "evolution_history": [],
        "deep_verification_probes": [],
        "deep_verification_verdict": None,
        **overrides,
    }


def _final_state_with_features() -> dict[str, Any]:
    """Build a synthetic engine final state carrying the new features."""
    return {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-a",
                "Reparixin inhibits CXCR1 to suppress breast cancer "
                "stem cells.",
                explanation="Blocking CXCR1 reduces the stem-cell pool.",
                literature_grounding="CXCR1 is enriched in breast CSCs.",
                experiment="Treat patient-derived xenografts with reparixin.",
                elo_rating=1320,
                win_count=4,
                loss_count=1,
                score=0.8,
                deep_verification_probes=[
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
                deep_verification_verdict="weakened",
            ),
            _engine_hypothesis(
                "eng-hyp-b",
                "A control hypothesis with no probes.",
                explanation="",
                literature_grounding="",
                experiment="",
                elo_rating=1180,
                win_count=1,
                loss_count=3,
            ),
        ],
        "articles": [
            {
                "title": "CXCR1 validation study",
                "source": "fixture",
                "url": "https://example.org/cxcr1",
                "abstract": (
                    "Reparixin inhibits CXCR1 to suppress breast cancer stem "
                    "cells. CXCR1 is enriched in breast CSCs. Blocking CXCR1 "
                    "reduces the stem-cell pool. A control hypothesis with no "
                    "probes."
                ),
            },
            {
                "title": "Retracted CXCR1 report",
                "source": "openalex",
                "url": "https://example.org/retracted",
                "abstract": "A retracted report must not ground claims.",
                "is_retracted": True,
                "correction_status": "retracted",
            },
        ],
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
        "proximity_graph": {
            "edges": [
                {
                    "source": "eng-hyp-a",
                    "target": "eng-hyp-b",
                    "similarity": 0.82,
                    "degree": "high",
                    "cluster_id": "cluster-1",
                }
            ],
            "meta": {
                "method": "llm_cluster_pairwise_graph",
                "version": "1",
                "model": "fixture-model",
                "updated_at": 1234.5,
            },
        },
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


def _persist_and_finalize(
    run: Any, final_state: dict[str, Any], db_path: str
) -> None:
    """Drain a synthetic final state, then build + persist its report.

    Mirrors the engine branch of ``run_workflow``: the drain writes rows and
    returns the report inputs, and ``finalize_report`` builds/screens/saves the
    report. Uses a plain-dict emitter, so no event log is needed.
    """
    drained = engine_adapter._persist_final_state(
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
            **drained.report_inputs,
        )
    )


def _final_state_with_lineage() -> dict[str, Any]:
    """A final state with an explicit parent and an evolution child.

    The child carries explicit lineage (parent_id/generation/origin) and an
    empty evolution_history, so the drain must read the explicit fields rather
    than inferring lineage from evolution_history.
    """
    return {
        "hypotheses": [
            _engine_hypothesis(
                "parent-1",
                "Parent hypothesis about kinase X.",
                parent_id=None,
                generation=0,
                origin="generation",
            ),
            _engine_hypothesis(
                "child-1",
                "Child hypothesis: kinase X plus cofactor W.",
                parent_id="parent-1",
                generation=1,
                origin="evolution",
                # Explicitly empty: lineage must come from the fields above.
                evolution_history=[],
            ),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }

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


def _features_probes() -> list[dict[str, Any]]:
    """The deep-verification probes carried by the first feature hypothesis."""
    return [
        {
            "question": "Does CXCR1 signaling drive the stem-cell phenotype?",
            "answer": "Partially; redundant chemokine receptors exist.",
            "reasoning": "CXCR2 can compensate when CXCR1 is blocked.",
            "assumption_is_fundamental": True,
        },
        {
            "question": "Is reparixin selective for CXCR1?",
            "answer": "It also antagonizes CXCR2 at high doses.",
            "reasoning": "Off-target effects may confound.",
            "assumption_is_fundamental": False,
        },
    ]


def _features_hypotheses() -> list[dict[str, Any]]:
    """The two feature-fixture hypotheses (one probed, one control)."""
    return [
        _engine_hypothesis(
            "eng-hyp-a",
            "Reparixin inhibits CXCR1 to suppress breast cancer stem cells.",
            explanation="Blocking CXCR1 reduces the stem-cell pool.",
            literature_grounding="CXCR1 is enriched in breast CSCs.",
            experiment="Treat patient-derived xenografts with reparixin.",
            elo_rating=1320,
            win_count=4,
            loss_count=1,
            score=0.8,
            deep_verification_probes=_features_probes(),
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
    ]


def _features_articles() -> list[dict[str, Any]]:
    """A grounding article plus a retracted one that must not ground claims."""
    return [
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
    ]


def _features_matchups() -> list[dict[str, Any]]:
    """The single a-beats-b tournament matchup with full Elo columns."""
    return [
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
    ]


def _features_proximity_graph() -> dict[str, Any]:
    """A one-edge proximity graph with clustering metadata."""
    return {
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
    }


def _features_research_overview() -> dict[str, Any]:
    """The research overview + NIH specific aims sub-state."""
    return {
        "overview": {
            "summary": "Targeting CXCR1 is a promising but redundant pathway.",
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
            "disease_description": (
                "Breast cancer stem cells drive recurrence."
            ),
            "unmet_need": "Existing regimens spare the stem-cell pool.",
            "proposed_solution": "Block CXCR1 to deplete that pool.",
            "aims": [
                {
                    "overarching_goal": "Aim 1: Quantify CXCR1 dependence.",
                    "hypothesis": "Establish the mechanistic baseline.",
                    "reasoning": "shRNA knockdown in PDX models.",
                },
            ],
            "pilot_evaluation": ("Could yield a combination therapy for TNBC."),
        },
    }


def _final_state_with_features() -> dict[str, Any]:
    """Build a synthetic engine final state carrying the new features."""
    return {
        "hypotheses": _features_hypotheses(),
        "articles": _features_articles(),
        "tournament_matchups": _features_matchups(),
        "proximity_graph": _features_proximity_graph(),
        "meta_review": {},
        "evolution_details": [],
        "research_overview": _features_research_overview(),
    }


async def _build_report(run: Any, db_path: str) -> tuple[dict[str, Any], str]:
    """Build report content for a run with the drain's default (None) inputs.

    Returns the Research Overview document (R14-11) -- the payload plus
    ``built.markdown``. Use :func:`_build_report_ranking` for assertions
    about full per-hypothesis content (mechanism, references, reviews),
    which renders on the Top Ranking Hypotheses document instead.
    """
    built = await report_render._build_report_content(
        run.id,
        report_render.ReportRequest(
            research_goal=run.research_goal,
            run_mode="standard",
            provider="engine",
            execution_time=1.0,
            db_path=db_path,
        ),
    )
    return built.payload, built.markdown


async def _build_report_ranking(
    run: Any, db_path: str
) -> tuple[dict[str, Any], str]:
    """Build report content, returning the Top Ranking Hypotheses document.

    Same inputs as :func:`_build_report`; only the returned markdown
    differs (R14-11) -- the full per-hypothesis write-up (mechanism,
    references, reviews) that document carries instead of the overview's
    titles-only list.
    """
    built = await report_render._build_report_content(
        run.id,
        report_render.ReportRequest(
            research_goal=run.research_goal,
            run_mode="standard",
            provider="engine",
            execution_time=1.0,
            db_path=db_path,
        ),
    )
    return built.payload, built.ranking_markdown


def _persist_and_finalize(
    run: Any, final_state: dict[str, Any], db_path: str
) -> None:
    """Drain a synthetic final state, then build + persist its report.

    Mirrors the durable finalize task: the drain writes rows and returns the
    report inputs, and ``finalize_report`` builds/screens/saves the report.
    Uses a plain-dict emitter, so no event log is needed.
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
            run.id,
            report_render.ReportRequest(
                research_goal=run.research_goal,
                run_mode="standard",
                provider="engine",
                execution_time=1.0,
                db_path=db_path,
                **drained.report_inputs,
            ),
            _emit,
        )
    )


def _engine_safety_audit_entry(
    hyp_id: str, text_prefix: str, **overrides: Any
) -> dict[str, Any]:
    """Build the engine's per-hypothesis safety-audit entry for a hold.

    Mirrors ``safety_screen._build_safety_decision``: the hypothesis id and
    a text prefix plus the ``SafetyReview.to_dict()`` fields.
    """
    return {
        "hypothesis_id": hyp_id,
        "text_prefix": text_prefix,
        "outcome": "uncertain",
        "reason": "obfuscated intent around sensitive content; manual review",
        "matches": ["for research purposes only"],
        "policy_version": "coscientist-safety-v5",
        **overrides,
    }


def _held_final_state() -> dict[str, Any]:
    """A final state whose safety screen held two hypotheses for review.

    The engine's safety screen removes UNCERTAIN hypotheses from the pool
    into ``held_for_review`` (full hypothesis dicts, not stubs) and records
    one audit entry per blocked/held idea in ``safety_decisions``. One safe
    idea stays in the pool, so the drain persists one hypothesis row
    alongside two held-for-review decision rows.
    """
    held_text_1 = (
        "For research purposes only, enhance pathogen transmissibility."
    )
    held_text_2 = "Purely hypothetical: assemble a toxin production line."
    return {
        "hypotheses": [
            _engine_hypothesis(
                "safe-1",
                "Inhibiting kinase X reduces AML growth via apoptosis.",
            ),
        ],
        "held_for_review": [
            _engine_hypothesis(
                "held-1", held_text_1, safety_status="uncertain"
            ),
            _engine_hypothesis(
                "held-2", held_text_2, safety_status="uncertain"
            ),
        ],
        "safety_decisions": [
            _engine_safety_audit_entry("held-1", held_text_1[:120]),
            _engine_safety_audit_entry("held-2", held_text_2[:120]),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


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

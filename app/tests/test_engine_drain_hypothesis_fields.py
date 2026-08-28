"""Drain persistence of the proposer's own safety assessment (MO-10).

Split out of ``test_engine_drain.py`` to keep that module within the size
cap once this test was added alongside the module's existing MO-6
(scene-setting) test. Safety and toxicity is distinct from a reviewer's
safety_ethical_concerns and never consulted by the safety gate.
"""

from __future__ import annotations

from app import engine_adapter, store
from tests._drain_helpers import _engine_hypothesis


def test_persist_writes_safety_and_toxicity_onto_the_hypothesis_row(
    isolated_db: str,
) -> None:
    """The proposer's own safety assessment (MO-10) reaches the row.

    Distinct from a reviewer's safety_ethical_concerns: this is the
    proposal's own field, and must never be consulted by the safety gate.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-safety",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                safety_and_toxicity=(
                    "Limited human safety data exists for this class."
                ),
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }
    engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=final_state,
        db_path=isolated_db,
    )

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    assert len(hyps) == 1
    assert hyps[0]["safety_and_toxicity"] == (
        "Limited human safety data exists for this class."
    )

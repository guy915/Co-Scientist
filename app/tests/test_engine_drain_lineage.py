"""Drain persistence of multi-parent (combination) lineage.

Split out of ``test_engine_drain.py`` to keep that module within the size
cap. Covers the ``parent_ids`` JSON column: a combination child stores
every parent with the primary leading, and a pruned co-parent degrades
the stored lineage to the surviving primary parent.
"""

from __future__ import annotations

from typing import Any

from app import engine_adapter, store
from tests._drain_helpers import _engine_hypothesis


def _multi_parent_state() -> dict[str, Any]:
    """A final state with a two-parent combination child."""
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
                "parent-2",
                "Parent hypothesis about cofactor W.",
                parent_id=None,
                generation=0,
                origin="generation",
            ),
            _engine_hypothesis(
                "child-1",
                "Combined hypothesis: kinase X with cofactor W.",
                parent_id="parent-1",
                parent_ids=["parent-1", "parent-2"],
                generation=1,
                origin="evolution",
            ),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def test_drain_persists_multi_parent_lineage(isolated_db: str) -> None:
    """A combination child stores every parent, primary leading."""
    run = store.create_run("combine goal", "standard", "engine", {})
    engine_adapter._persist_final_state(
        run_id=run.id, final_state=_multi_parent_state(), db_path=isolated_db
    )

    hyps = {
        h["id"]: h for h in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    child = hyps["child-1"]
    assert child["parent_id"] == "parent-1"
    assert child["parent_ids"] == ["parent-1", "parent-2"]
    # Single-parent rows carry no multi-parent list.
    assert hyps["parent-1"]["parent_ids"] is None
    assert hyps["parent-2"]["parent_ids"] is None


def test_drain_drops_pruned_co_parent_from_lineage(isolated_db: str) -> None:
    """A co-parent pruned before the drain leaves a single-parent child.

    The primary parent survives but the combination partner was archived, so
    the stored lineage degrades to the one remaining parent (parent_id alone)
    rather than persisting a dangling id in the JSON list.
    """
    state = _multi_parent_state()
    state["hypotheses"] = [
        h for h in state["hypotheses"] if h["id"] != "parent-2"
    ]
    run = store.create_run("combine goal", "standard", "engine", {})
    engine_adapter._persist_final_state(
        run_id=run.id, final_state=state, db_path=isolated_db
    )

    hyps = {
        h["id"]: h for h in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    child = hyps["child-1"]
    assert child["parent_id"] == "parent-1"
    assert child["parent_ids"] is None

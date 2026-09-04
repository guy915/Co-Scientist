"""Drain tests for the pre-tournament per-hypothesis safety screen.

Split out of ``test_engine_drain_safety.py`` when that file passed the
module-size budget. This module covers the screen that runs inside the
drain itself -- persisting each hypothesis's ``safety_status`` and, for a
held UNCERTAIN idea, a reviewable ``hold`` decision -- before the report is
ever built. The rank-and-publish split and the persisted-status gate that
decide what a *drained* idea may publish stay in
``test_engine_drain_safety.py``.
"""

from __future__ import annotations

from typing import Any

from app import engine_adapter, store
from tests._drain_helpers import _held_final_state


def _screening_hypothesis(hyp_id: str, text: str) -> dict[str, Any]:
    """A minimal engine hypothesis carrying every field the drain reads."""
    return {
        "id": hyp_id,
        "text": text,
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
    }


def _screening_state() -> dict[str, Any]:
    """A final state with one safe and one unsafe hypothesis to screen."""
    return {
        "hypotheses": [
            _screening_hypothesis(
                "safe-1",
                "Inhibiting kinase X reduces AML growth via apoptosis.",
            ),
            _screening_hypothesis(
                "unsafe-1",
                "Weaponize the pathogen to enhance transmissibility.",
            ),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def test_drain_screens_hypotheses_before_finalize(isolated_db: str) -> None:
    """The drain persists each hypothesis's safety_status and blocks unsafe.

    Milestone 6/M9: the per-hypothesis safety screen runs inside the drain
    (before the report is built), so an unsafe hypothesis is marked and audited
    at persistence time -- not only filtered out later at report synthesis.
    """
    run = store.create_run("safety goal", "standard", "engine", {})
    state = _screening_state()

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


def test_drain_persists_held_hypotheses_as_reviewable_decisions(
    isolated_db: str,
) -> None:
    """Held UNCERTAIN hypotheses survive the drain as adjudicable decisions.

    The engine's safety screen holds UNCERTAIN hypotheses out of the pool in
    ``held_for_review``; the drain must persist each one as a ``hold``
    decision at the hypothesis stage, carrying the screen's rationale and
    enough of the idea to display -- otherwise the hold vanishes at the app
    boundary and no person can ever inspect or adjudicate it.
    """
    run = store.create_run("held hypotheses goal", "standard", "engine", {})

    engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_held_final_state(),
        db_path=isolated_db,
    )

    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    holds = [d for d in decisions if d["decision"] == "hold"]
    assert len(holds) == 2
    for row in holds:
        # The shape the adjudication path requires: a reviewable decision
        # that no resolution has touched yet.
        assert row["stage"] == "hypothesis"
        assert row["requires_review"] is True
        assert row["resolution"] is None
        assert row["policy_version"] == "coscientist-safety-v5"
        assert row["matches"] == ["for research purposes only"]
        # Identity + rationale: the engine's reason and the held idea's text.
        assert "uncertain" in row["reason"]
        assert "obfuscated intent" in row["reason"]
    reasons = " ".join(row["reason"] for row in holds)
    assert "held-1" in reasons and "held-2" in reasons
    assert "enhance pathogen transmissibility" in reasons
    assert "toxin production line" in reasons
    # The held ideas never got hypothesis rows -- the engine kept them out
    # of the pool -- so the decision row is the only record of them.
    assert [h["id"] for h in store.list_hypotheses(run.id)] == ["safe-1"]


def test_drain_records_a_hold_without_an_engine_audit_entry(
    isolated_db: str,
) -> None:
    """A held entry whose audit entry is missing still gets a hold row.

    The engine writes ``held_for_review`` and ``safety_decisions`` in the
    same node, but the drain must not depend on the join succeeding: a held
    hypothesis with no matching audit entry records a hold with a fallback
    rationale rather than being dropped.
    """
    run = store.create_run("orphan hold goal", "standard", "engine", {})
    state = _held_final_state()
    state["safety_decisions"] = []

    engine_adapter._persist_final_state(
        run_id=run.id, final_state=state, db_path=isolated_db
    )

    holds = [
        d
        for d in store.list_safety_decisions(run.id, db_path=isolated_db)
        if d["decision"] == "hold"
    ]
    assert len(holds) == 2
    for row in holds:
        assert row["requires_review"] is True
        assert row["reason"]

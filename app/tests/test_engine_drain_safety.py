"""Engine-drain tests for pre-tournament safety and rank-and-publish gating.

Split out of ``test_engine_drain.py`` by concern. These cover the drain's
per-hypothesis safety screen (writing ``safety_status`` and audit rows before
finalize) and the rank-and-publish split of contradicted versus merely
unverified ideas. The PARITY-cited synthesis-exclusion case stays in
``test_engine_drain.py``.
"""

from __future__ import annotations

from typing import Any

from app import engine_adapter, report_render, store


def test_rank_and_publish_splits_contradicted_from_unverified(
    isolated_db: str,
) -> None:
    """Contradicted ideas are withheld; unsupported ones publish unverified.

    Batch 9 rank-and-publish: ``_exclude_unsafe_hypotheses`` drops a
    contradicted idea but keeps a merely-unsupported one, which
    ``_unverified_hypothesis_ids`` flags for the "Unverified" badge. A run with
    no claim-evidence at all (mock demo runs) flags nothing.
    """
    run = store.create_run("gate split", "standard", "engine", {})
    supported_id = store.add_hypothesis(
        run.id,
        title="Supported",
        statement="Kinase X inhibition drives AML apoptosis.",
        db_path=isolated_db,
    )
    unsupported_id = store.add_hypothesis(
        run.id,
        title="Unsupported",
        statement="A novel latent mechanism without any evidence yet.",
        db_path=isolated_db,
    )
    contradicted_id = store.add_hypothesis(
        run.id,
        title="Contradicted",
        statement="Drug Y single-handedly cures the disease.",
        db_path=isolated_db,
    )
    store.add_claim_evidence(
        run.id,
        supported_id,
        "Kinase X inhibition drives AML apoptosis.",
        "supports",
        ["A supporting source span."],
        [],
        "fixture",
        db_path=isolated_db,
    )
    store.add_claim_evidence(
        run.id,
        contradicted_id,
        "Drug Y single-handedly cures the disease.",
        "contradicts",
        [],
        ["A source span refuting the claim."],
        "fixture",
        db_path=isolated_db,
    )
    # ``unsupported_id`` deliberately has no claim-evidence edge at all.

    contradicted = report_render._contradicted_hypothesis_ids(
        run.id, isolated_db
    )
    unverified = report_render._unverified_hypothesis_ids(run.id, isolated_db)
    assert contradicted == {contradicted_id}
    # Only the supported idea has a ``supports`` edge; the other two lack one.
    assert unverified == {unsupported_id, contradicted_id}

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    kept_ids = {
        h["id"]
        for h in report_render._exclude_unsafe_hypotheses(
            run.id, hyps, isolated_db
        )
    }
    # Contradicted is withheld; supported and unsupported both publish.
    assert kept_ids == {supported_id, unsupported_id}

    # A run with no claim-evidence at all badges nothing (mock demo exemption).
    demo = store.create_run("demo", "standard", "mock", {})
    store.add_hypothesis(
        demo.id, title="Demo", statement="Demo idea.", db_path=isolated_db
    )
    assert (
        report_render._unverified_hypothesis_ids(demo.id, isolated_db) == set()
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

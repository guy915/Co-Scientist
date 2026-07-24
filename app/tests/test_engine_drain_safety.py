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


def _seed_gate_split(run: Any, db_path: str) -> tuple[str, str, str]:
    """Seed supported/unsupported/contradicted hypotheses for the gate split.

    The supported idea gets a ``supports`` edge and the contradicted one a
    ``contradicts`` edge; the unsupported idea deliberately gets no edge at all.
    """
    supported_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Supported",
            statement="Kinase X inhibition drives AML apoptosis.",
        ),
        db_path=db_path,
    )
    unsupported_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Unsupported",
            statement="A novel latent mechanism without any evidence yet.",
        ),
        db_path=db_path,
    )
    contradicted_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Contradicted",
            statement="Drug Y single-handedly cures the disease.",
        ),
        db_path=db_path,
    )
    _add_gate_split_edges(run, supported_id, contradicted_id, db_path)
    return supported_id, unsupported_id, contradicted_id


def _add_gate_split_edges(
    run: Any, supported_id: str, contradicted_id: str, db_path: str
) -> None:
    """Add a supports edge for the supported id, contradicts for the other."""
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=supported_id,
            claim="Kinase X inhibition drives AML apoptosis.",
            label="supports",
            supporting=["A supporting source span."],
            contradicting=[],
            assessor="fixture",
        ),
        db_path=db_path,
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=contradicted_id,
            claim="Drug Y single-handedly cures the disease.",
            label="contradicts",
            supporting=[],
            contradicting=["A source span refuting the claim."],
            assessor="fixture",
        ),
        db_path=db_path,
    )


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
    supported_id, unsupported_id, contradicted_id = _seed_gate_split(
        run, isolated_db
    )

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

    _assert_demo_run_badges_nothing(isolated_db)


def _assert_demo_run_badges_nothing(db_path: str) -> None:
    """A run with no claim-evidence at all badges nothing (demo exemption)."""
    demo = store.create_run("demo", "standard", "mock", {})
    store.add_hypothesis(
        store.NewHypothesis(
            run_id=demo.id, title="Demo", statement="Demo idea."
        ),
        db_path=db_path,
    )
    assert report_render._unverified_hypothesis_ids(demo.id, db_path) == set()


def test_partial_edge_clears_the_unverified_badge(isolated_db: str) -> None:
    """A hypothesis whose best evidence is PARTIAL is not badged unverified.

    A partial (near-miss) verdict means relevant, consistent evidence was
    found, so it clears the badge exactly as a ``supports`` edge does -- the
    fix for the flood of "Unverified" ideas whose claims only ever landed on
    ``insufficient``.
    """
    run = store.create_run("partial badge", "standard", "engine", {})
    partial_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Partially supported",
            statement="Kinase X modulation influences AML growth.",
        ),
        db_path=isolated_db,
    )
    insufficient_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Insufficient",
            statement="An entirely unevidenced conjecture.",
        ),
        db_path=isolated_db,
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=partial_id,
            claim="Kinase X modulation influences AML growth.",
            label="partial",
            supporting=["A near-miss source span."],
            contradicting=[],
            assessor="fixture",
        ),
        db_path=isolated_db,
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=insufficient_id,
            claim="An entirely unevidenced conjecture.",
            label="insufficient",
            supporting=[],
            contradicting=[],
            assessor="fixture",
        ),
        db_path=isolated_db,
    )

    unverified = report_render._unverified_hypothesis_ids(run.id, isolated_db)
    # The partial idea clears the badge; only the insufficient one is flagged.
    assert unverified == {insufficient_id}


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

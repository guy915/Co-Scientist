"""Engine-drain tests for pre-tournament safety and rank-and-publish gating.

Split out of ``test_engine_drain.py`` by concern. These cover the drain's
per-hypothesis safety screen (writing ``safety_status`` and audit rows before
finalize), the rank-and-publish split of contradicted versus merely
unverified ideas, and the persisted-status gate that decides which drained
ideas the report may publish at all. The PARITY-cited synthesis-exclusion
case stays in ``test_engine_drain.py``.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from co_scientist import models as engine_models

from app import engine_adapter, report_render, store
from tests._drain_helpers import _final_state_with_lineage


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


def test_gate_reports_exclusions_once_and_at_info(
    isolated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A withheld idea is news at info; the report losing every idea warns.

    Withholding a contradicted or unsafe idea is the gate doing its job, so
    it belongs in the run narrative rather than in the warnings band -- one
    warning per idea is a row per idea that needs no action. The case that
    does need one is the gate emptying the report.
    """
    run = store.create_run("gate logging", "standard", "engine", {})
    _, _, contradicted_id = _seed_gate_split(run, isolated_db)
    hyps = store.list_hypotheses(run.id, db_path=isolated_db)

    with caplog.at_level(logging.INFO, logger="app.report_content_gates"):
        report_render._exclude_unsafe_hypotheses(run.id, hyps, isolated_db)

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(contradicted_id in r.getMessage() for r in caplog.records)
    assert any(
        "excluded 1 of 3" in r.getMessage().lower() for r in caplog.records
    )


def test_gate_warns_when_it_excludes_everything(
    isolated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing left to synthesize is the outcome worth a warning."""
    run = store.create_run("gate empty", "standard", "engine", {})
    store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Unsafe",
            statement="Weaponize the pathogen to enhance transmissibility.",
        ),
        db_path=isolated_db,
    )
    hyps = store.list_hypotheses(run.id, db_path=isolated_db)

    with caplog.at_level(logging.INFO, logger="app.report_content_gates"):
        kept = report_render._exclude_unsafe_hypotheses(
            run.id, hyps, isolated_db
        )

    assert kept == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "no ideas" in warnings[0].getMessage()


def _drained_status(
    disposition: str | None, isolated_db: str, goal: str
) -> str:
    """Drain a state whose parent carries ``disposition``; return its status."""
    state = _final_state_with_lineage()
    state["hypotheses"][0]["review_disposition"] = disposition
    run = store.create_run(goal, "standard", "engine", {})
    engine_adapter._persist_final_state(
        run_id=run.id, final_state=state, db_path=isolated_db
    )
    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    return str(by_id["parent-1"]["status"])


@pytest.mark.parametrize(
    "disposition", sorted(engine_models.BLOCKING_REVIEW_DISPOSITIONS)
)
def test_every_engine_blocking_disposition_drains_as_rejected(
    isolated_db: str, disposition: str
) -> None:
    """Persisted status tracks the engine's tournament gate, member for member.

    Parametrized over the engine's own set rather than a copy of it: what a
    run may publish and what a run may rank are one rule, and the app used
    to restate both the set and the predicate over it.
    """
    assert _drained_status(disposition, isolated_db, f"{disposition} goal") == (
        "rejected"
    )


@pytest.mark.parametrize("disposition", [None, "needs_revision"])
def test_non_blocking_dispositions_still_publish(
    isolated_db: str, disposition: str | None
) -> None:
    """A weak-but-not-fatal idea competes and publishes; the tournament rules.

    ``duplicate`` is deliberately absent from both this list and the engine's
    blocking set -- it has its own status and its own wording, covered by
    ``test_drain_preserves_proximity_pruned_parent_as_a_duplicate``.
    """
    assert (
        _drained_status(disposition, isolated_db, f"{disposition} goal")
        == "active"
    )


def test_a_new_engine_blocking_disposition_reaches_the_drain(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disposition added to the engine must not stay publishable here.

    The drift the drain used to be exposed to, simulated: a disposition the
    engine starts blocking on makes an idea unrankable there, so the app
    must stop recording it ``active`` and publishing it -- the "report
    contradicts its own tabs" failure. The app no longer keeps its own copy
    of the set or of the predicate over it, so this arrives for free.
    """
    monkeypatch.setattr(
        engine_models,
        "BLOCKING_REVIEW_DISPOSITIONS",
        engine_models.BLOCKING_REVIEW_DISPOSITIONS | {"superseded_by_evidence"},
    )
    status = _drained_status(
        "superseded_by_evidence", isolated_db, "drifted gate goal"
    )
    assert status == "rejected"

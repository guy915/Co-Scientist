"""Engine-drain tests for rank-and-publish gating.

Split out of ``test_engine_drain.py`` by concern. These cover the
rank-and-publish split of contradicted versus merely unverified ideas and
the persisted-status gate that decides which drained ideas the report may
publish at all. The PARITY-cited synthesis-exclusion case stays in
``test_engine_drain.py``; the drain's per-hypothesis safety screen (writing
``safety_status`` and held-review audit rows before finalize) moved to
``test_engine_drain_hypothesis_screening.py`` when this file passed the
module-size budget.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from co_scientist import models as engine_models

from app import report_content_gates, report_render, store
from tests._drain_helpers import (
    _final_state_with_lineage,
    _persist,
    _persist_and_finalize,
)


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

    Batch 9 rank-and-publish: ``exclude_unsafe_hypotheses`` drops a
    contradicted idea but keeps a merely-unsupported one, which
    ``unverified_hypothesis_ids`` flags for the "Unverified" badge. A run with
    no claim-evidence at all (mock demo runs) flags nothing.
    """
    run = store.create_run("gate split", "standard", "engine", {})
    supported_id, unsupported_id, contradicted_id = _seed_gate_split(
        run, isolated_db
    )

    contradicted = report_render._contradicted_hypothesis_ids(
        run.id, isolated_db
    )
    unverified = report_content_gates.unverified_hypothesis_ids(
        run.id, isolated_db
    )
    assert contradicted == {contradicted_id}
    # Only the supported idea has a ``supports`` edge; the other two lack one.
    assert unverified == {unsupported_id, contradicted_id}

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    kept_ids = {
        h["id"]
        for h in report_content_gates.exclude_unsafe_hypotheses(
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
    assert (
        report_content_gates.unverified_hypothesis_ids(demo.id, db_path)
        == set()
    )


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

    unverified = report_content_gates.unverified_hypothesis_ids(
        run.id, isolated_db
    )
    # The partial idea clears the badge; only the insufficient one is flagged.
    assert unverified == {insufficient_id}


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
        report_content_gates.exclude_unsafe_hypotheses(
            run.id, hyps, isolated_db
        )

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(contradicted_id in r.getMessage() for r in caplog.records)
    assert any(
        "excluded 1 of 3" in r.getMessage().lower() for r in caplog.records
    )


def test_gate_warns_when_it_excludes_everything(
    isolated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing left to synthesize is the outcome worth a warning.

    This hypothesis has no persisted review disposition or safety_status
    (a legacy row), so it is excluded through the gate's own re-review
    fallback -- a genuine safety exclusion, and the warning must say so.
    """
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
        kept = report_content_gates.exclude_unsafe_hypotheses(
            run.id, hyps, isolated_db
        )

    assert kept == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "no ideas" in message
    assert "safety review" in message
    assert "peer review" not in message


def test_gate_warning_names_review_rejection_not_safety(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A review-rejected pool warns about peer review, never safety.

    Unlike the legacy-fallback case above, a hypothesis already carrying a
    persisted ``status="rejected"`` (the engine's own blocking review
    disposition) is excluded on that status alone -- the gate never
    re-reviews it, and the warning must not imply it did.
    """
    hyps = [
        {"id": "h1", "status": "rejected", "statement": "Idea one."},
        {"id": "h2", "status": "rejected", "statement": "Idea two."},
    ]

    with caplog.at_level(logging.INFO, logger="app.report_content_gates"):
        kept = report_content_gates.exclude_unsafe_hypotheses(
            "run-review-rejected", hyps, None, claim_edges=[]
        )

    assert kept == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "peer review" in message
    assert "safety review" not in message


def _drained_status(
    disposition: str | None, isolated_db: str, goal: str
) -> str:
    """Drain a state whose parent carries ``disposition``; return its status."""
    state = _final_state_with_lineage()
    state["hypotheses"][0]["review_disposition"] = disposition
    run = store.create_run(goal, "standard", "engine", {})
    _persist(run_id=run.id, final_state=state, db_path=isolated_db)
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


def test_offline_run_with_empty_leaderboard_is_blocked_like_a_real_run(
    isolated_db: str,
) -> None:
    """The scientific-readiness gate applies to offline runs too.

    The offline LLM backend still drives the real graph end to end, so an
    empty leaderboard there means the same "nothing survived review" outcome
    as a real run's -- publishing anyway would understate the failure. Only
    the three curated default demos are exempt, and they bypass this gate
    entirely by writing their report row directly (see ``seed.py``); an
    ad-hoc offline run reaches the same ``finalize_report`` path a real run
    does.

    This is production run 44e848fb reproduced: no safety_status was ever
    set (safety screened 0 blocked) and no claim-evidence edges exist
    (grounding assessed nothing) -- every idea left the report solely
    because the initial review gate rejected it. The blocked reason must
    name that, not the safety review or a contradiction neither pipeline
    ever ran.
    """
    state = _final_state_with_lineage()
    for hypothesis in state["hypotheses"]:
        hypothesis["review_disposition"] = "unsafe"
    run = store.create_run(
        "offline empty leaderboard goal",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(llm_backend="offline", db_path=isolated_db),
    )

    _persist_and_finalize(run, state, isolated_db)

    settled = store.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == store.RunStatus.BLOCKED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is None
    assert settled.error is not None
    assert "peer review" in settled.error
    assert "safety review" not in settled.error
    assert "contradicted" not in settled.error

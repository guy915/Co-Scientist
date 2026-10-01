"""Verification methods survive grounding, API readback and legacy upgrades."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

import pytest

from app import store
from app.claims import (
    AssessorDraft,
    EntailmentLabel,
    EvidencePassage,
    as_passages,
)
from app.claims.grounding import ground_hypotheses
from app.claims.grounding_assess import AssessorSpec
from app.store import db
from tests._client import make_client
from tests._drain_helpers import _build_report
from tests._store_helpers import _add


async def test_grounding_retains_method_across_api_reopen(
    isolated_db: str,
) -> None:
    client = make_client()
    run_id = client.post(
        "/api/runs", json={"research_goal": "Study tissue repair"}
    ).json()["id"]
    claim = "A dietary change improves cardiovascular outcomes in adults."
    _add(run_id, "Diet study", claim, isolated_db)

    def assess(
        claim: str, passages: Sequence[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            EntailmentLabel.SUPPORTS,
            supporting=((passages[0].evidence_id, claim),),
            verification_method="model_primary",
        )

    ground_hypotheses(
        run_id,
        store.list_hypotheses(run_id),
        as_passages([claim]),
        assessment=AssessorSpec(assessor=assess, assessor_id="llm:test"),
    )
    reopened = make_client().get(f"/api/runs/{run_id}/claim-evidence")
    assert reopened.status_code == 200
    edges = reopened.json()["claim_evidence"]
    assert edges and all(
        e["verification_method"] == "model_primary" for e in edges
    )
    assert all(e["assessor"] == "llm:test" for e in edges)
    payload, markdown = await _build_report(store.get_run(run_id), isolated_db)
    assert (
        payload["claim_evidence"][0]["verification_method"] == "model_primary"
    )
    assert "Assessment method: model judgment" in markdown


def test_legacy_edges_keep_unknown_method_after_repeat_migration(
    isolated_db: str,
) -> None:
    run = store.create_run("Legacy evidence", "express", "engine", {})
    hyp_id = _add(
        run.id, "Legacy", "A public research hypothesis.", isolated_db
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=hyp_id,
            claim="A legacy claim.",
            label="insufficient",
            supporting=[],
            contradicting=[],
            assessor="llm:old",
        )
    )
    with sqlite3.connect(isolated_db) as conn:
        columns = {
            r[1] for r in conn.execute("PRAGMA table_info(claim_evidence)")
        }
        if "verification_method" in columns:
            conn.execute(
                "ALTER TABLE claim_evidence DROP COLUMN verification_method"
            )
    for _ in range(2):
        db._initialized.discard(isolated_db)
        with db.connect(isolated_db):
            pass
    edges = store.list_claim_evidence(run.id)
    assert len(edges) == 1
    assert edges[0]["verification_method"] == "legacy_unknown"
    assert edges[0]["assessor"] == "llm:old"


@pytest.mark.parametrize(
    "has_evidence, expected",
    [
        (True, "deterministic_lexical"),
        (False, "no_evidence"),
    ],
)
def test_deterministic_method_describes_actual_evidence_path(
    has_evidence: bool,
    expected: str,
) -> None:
    from app.claims import assess_claim

    claim = "A dietary change improves cardiovascular outcomes in adults."
    result = assess_claim(claim, as_passages([claim]) if has_evidence else [])
    assert result.verification_method == expected


def test_no_candidates_cannot_claim_model_verification() -> None:
    from app.claims import assess_claim

    def assess(
        _claim: str, _passages: Sequence[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            EntailmentLabel.INSUFFICIENT, verification_method="model_primary"
        )

    result = assess_claim(
        "A hypothesis without retrieved evidence.", [], assessor=assess
    )
    assert result.verification_method == "no_evidence"

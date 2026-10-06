from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app
from app.store import db, hypotheses, records, reports
from app.store.hypotheses import HypothesisStateChanges, NewHypothesis
from app.store.records import NewClaimEvidence, NewEvidence
from tests._store_helpers import seed_run


def _run_with_report(isolated_db: str) -> str:
    run = seed_run(
        "Study a causal pathway",
        provider="mock",
        client_id="owner-a",
        db_path=isolated_db,
    )
    reports.save_report(
        run.id,
        {"research_goal": run.research_goal, "leaderboard": []},
        "# Goal Report",
        db_path=isolated_db,
    )
    return run.id


def test_share_link_is_unique_hashed_and_revocable(isolated_db: str) -> None:
    run_id = _run_with_report(isolated_db)
    with TestClient(app) as client:
        denied = client.post(
            f"/api/runs/{run_id}/shares",
            headers={"X-Client-ID": "other"},
        )
        assert denied.status_code == 404

        created = client.post(
            f"/api/runs/{run_id}/shares",
            headers={"X-Client-ID": "owner-a"},
        )
        assert created.status_code == 200
        share = created.json()
        assert len(share["token"]) >= 32

        with db.connect(isolated_db) as conn:
            stored = conn.execute(
                "SELECT token_hash FROM report_shares WHERE id=?",
                (share["id"],),
            ).fetchone()[0]
        assert stored != share["token"]

        public = client.get(f"/api/shared/{share['token']}")
        assert public.status_code == 200
        assert public.json()["report"]["payload"]["research_goal"] == ("Study a causal pathway")

        revoked = client.delete(
            f"/api/runs/{run_id}/shares/{share['id']}",
            headers={"X-Client-ID": "owner-a"},
        )
        assert revoked.status_code == 204
        assert client.get(f"/api/shared/{share['token']}").status_code == 404


def _run_with_blocked_and_released_content(
    isolated_db: str,
) -> tuple[str, str, str]:
    run = seed_run(
        "Map a signaling pathway",
        config={"private_setting": "config-secret-value"},
        client_id="owner-b",
        db_path=isolated_db,
    )
    run_id = run.id

    def add_idea(
        title: str,
        statement: str,
        *,
        status: str | None = None,
        safety_status: str = "allow",
    ) -> str:
        hyp_id = hypotheses.add_hypothesis(
            NewHypothesis(run_id=run_id, title=title, statement=statement),
            db_path=isolated_db,
        )
        hypotheses.update_hypothesis_state(
            hyp_id,
            HypothesisStateChanges(status=status, safety_status=safety_status),
            db_path=isolated_db,
        )
        return hyp_id

    released_id = add_idea(
        "Released feedback idea",
        "Modulating the feedback loop improves throughput.",
    )
    add_idea(
        "Safety blocked idea",
        "A blocked proposal kept out by the safety screen.",
        safety_status="prohibited",
    )
    add_idea(
        "Review rejected idea",
        "A proposal set aside during review.",
        status="rejected",
    )
    add_idea(
        "Deduplicated idea",
        "A proposal folded into a higher-ranked idea.",
        status="duplicate",
    )
    contradicted_id = add_idea(
        "Contradicted idea",
        "A proposal whose claims the evidence contradicts.",
    )

    cited_id = records.add_evidence(
        NewEvidence(
            run_id=run_id,
            title="A public pathway paper",
            source="pubmed",
            abstract="Published abstract text.",
        ),
        db_path=isolated_db,
    )
    records.add_evidence(
        NewEvidence(
            run_id=run_id,
            title="Private lab memo",
            source="attachment",
            abstract="private-document-secret-text",
        ),
        db_path=isolated_db,
    )

    records.add_claim_evidence(
        NewClaimEvidence(
            run_id=run_id,
            hypothesis_id=released_id,
            claim="The feedback loop is causal",
            label="supports",
            supporting=[{"evidence_id": cited_id, "quote": "feedback loop"}],
            contradicting=[],
            assessor="deterministic",
        ),
        db_path=isolated_db,
    )
    records.add_claim_evidence(
        NewClaimEvidence(
            run_id=run_id,
            hypothesis_id=contradicted_id,
            claim="The loop runs backwards",
            label="contradicts",
            supporting=[],
            contradicting=[{"evidence_id": cited_id, "quote": "no such thing"}],
            assessor="deterministic",
        ),
        db_path=isolated_db,
    )

    reports.save_report(
        run_id,
        {"research_goal": run.research_goal},
        "# Goal Report",
        db_path=isolated_db,
    )
    return run_id, released_id, cited_id


def test_shared_payload_is_filtered_to_release_artifact(
    isolated_db: str,
) -> None:
    run_id, released_id, cited_id = _run_with_blocked_and_released_content(isolated_db)
    with TestClient(app) as client:
        created = client.post(
            f"/api/runs/{run_id}/shares",
            headers={"X-Client-ID": "owner-b"},
        )
        assert created.status_code == 200
        public = client.get(f"/api/shared/{created.json()['token']}")
        assert public.status_code == 200
        payload = public.json()

    assert {h["id"] for h in payload["hypotheses"]} == {released_id}
    assert [e["id"] for e in payload["evidence"]] == [cited_id]

    serialized = json.dumps(payload)
    for secret in (
        "Safety blocked idea",
        "A blocked proposal kept out by the safety screen.",
        "Review rejected idea",
        "A proposal set aside during review.",
        "Deduplicated idea",
        "A proposal folded into a higher-ranked idea.",
        "Contradicted idea",
        "A proposal whose claims the evidence contradicts.",
        "Private lab memo",
        "private-document-secret-text",
        "config-secret-value",
    ):
        assert secret not in serialized

    assert payload["run"] == {
        "title": None,
        "research_goal": "Map a signaling pathway",
        "run_mode": "standard",
    }

    shared = payload["hypotheses"][0]
    assert shared["title"] == "Released feedback idea"
    assert shared["statement"] == ("Modulating the feedback loop improves throughput.")
    assert "abstract" not in payload["evidence"][0]
    assert payload["evidence"][0]["title"] == "A public pathway paper"
    assert payload["evidence"][0]["retracted"] is False

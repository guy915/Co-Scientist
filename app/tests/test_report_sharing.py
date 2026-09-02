"""End-to-end tests for revocable public Goal Report capabilities."""

import json

from fastapi.testclient import TestClient

from app import store
from app.main import app


def _run_with_report(isolated_db: str) -> str:
    """Persist a completed run with a saved Goal Report; return its id."""
    run = store.create_run(
        "Study a causal pathway",
        "standard",
        "mock",
        {},
        store.RunCreateOptions(client_id="owner-a", db_path=isolated_db),
    )
    store.save_report(
        run.id,
        {"research_goal": run.research_goal, "leaderboard": []},
        store.ReportMarkdownDocuments("# Goal Report"),
        db_path=isolated_db,
    )
    return run.id


def test_share_link_is_unique_hashed_and_revocable(isolated_db: str) -> None:
    """Owner creation hashes the token; revocation closes public access."""
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

        with store.connect(isolated_db) as conn:
            stored = conn.execute(
                "SELECT token_hash FROM report_shares WHERE id=?",
                (share["id"],),
            ).fetchone()[0]
        assert stored != share["token"]

        public = client.get(f"/api/shared/{share['token']}")
        assert public.status_code == 200
        assert public.json()["report"]["payload"]["research_goal"] == (
            "Study a causal pathway"
        )

        revoked = client.delete(
            f"/api/runs/{run_id}/shares/{share['id']}",
            headers={"X-Client-ID": "owner-a"},
        )
        assert revoked.status_code == 204
        assert client.get(f"/api/shared/{share['token']}").status_code == 404


# R14-11: shares.py forwards the whole report row (store.get_latest_report)
# to a public reader unchanged, so both persisted forms of the split --
# a run with two documents, and an older run with the one legacy combined
# document -- must keep coming through a share exactly as they are stored.


def test_shared_report_carries_both_documents(isolated_db: str) -> None:
    """A two-document report shares both markdown documents, not just one."""
    run = store.create_run(
        "Study a causal pathway",
        "standard",
        "mock",
        {},
        store.RunCreateOptions(client_id="owner-a", db_path=isolated_db),
    )
    store.save_report(
        run.id,
        {"research_goal": run.research_goal, "leaderboard": []},
        store.ReportMarkdownDocuments("# Overview doc", "# Ranking doc"),
        db_path=isolated_db,
    )
    with TestClient(app) as client:
        created = client.post(
            f"/api/runs/{run.id}/shares",
            headers={"X-Client-ID": "owner-a"},
        )
        report = client.get(f"/api/shared/{created.json()['token']}").json()[
            "report"
        ]

    assert report["markdown_text"] == "# Overview doc"
    assert report["markdown_text_ranking"] == "# Ranking doc"


def test_shared_legacy_report_has_no_ranking_document(
    isolated_db: str,
) -> None:
    """An older, single-document report shares with no ranking document.

    Its ``markdown_text`` still holds the one combined document exactly as
    it was persisted -- a share must not claim a second document exists.
    """
    run_id = _run_with_report(isolated_db)
    with TestClient(app) as client:
        created = client.post(
            f"/api/runs/{run_id}/shares",
            headers={"X-Client-ID": "owner-a"},
        )
        report = client.get(f"/api/shared/{created.json()['token']}").json()[
            "report"
        ]

    assert report["markdown_text"] == "# Goal Report"
    assert report["markdown_text_ranking"] is None


def _run_with_blocked_and_released_content(
    isolated_db: str,
) -> tuple[str, str, str]:
    """Persist a run with one released idea and every blocked-idea kind.

    The run also holds one cited literature record and one private
    attachment, so the shared payload has both kinds of evidence to filter.

    Returns:
        A tuple of (run id, released hypothesis id, cited evidence id).
    """
    run = store.create_run(
        "Map a signaling pathway",
        "standard",
        "engine",
        {"private_setting": "config-secret-value"},
        store.RunCreateOptions(client_id="owner-b", db_path=isolated_db),
    )
    run_id = run.id

    released_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Released feedback idea",
            statement="Modulating the feedback loop improves throughput.",
        ),
        db_path=isolated_db,
    )
    store.update_hypothesis_state(
        released_id,
        store.HypothesisStateChanges(safety_status="allow"),
        db_path=isolated_db,
    )

    blocked_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Safety blocked idea",
            statement="A blocked proposal kept out by the safety screen.",
        ),
        db_path=isolated_db,
    )
    store.update_hypothesis_state(
        blocked_id,
        store.HypothesisStateChanges(safety_status="prohibited"),
        db_path=isolated_db,
    )

    rejected_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Review rejected idea",
            statement="A proposal set aside during review.",
        ),
        db_path=isolated_db,
    )
    store.update_hypothesis_state(
        rejected_id,
        store.HypothesisStateChanges(status="rejected", safety_status="allow"),
        db_path=isolated_db,
    )

    duplicate_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Deduplicated idea",
            statement="A proposal folded into a higher-ranked idea.",
        ),
        db_path=isolated_db,
    )
    store.update_hypothesis_state(
        duplicate_id,
        store.HypothesisStateChanges(status="duplicate", safety_status="allow"),
        db_path=isolated_db,
    )

    contradicted_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Contradicted idea",
            statement="A proposal whose claims the evidence contradicts.",
        ),
        db_path=isolated_db,
    )
    store.update_hypothesis_state(
        contradicted_id,
        store.HypothesisStateChanges(safety_status="allow"),
        db_path=isolated_db,
    )

    cited_id = store.add_evidence(
        store.NewEvidence(
            run_id=run_id,
            title="A public pathway paper",
            source="pubmed",
            abstract="Published abstract text.",
        ),
        db_path=isolated_db,
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run_id,
            title="Private lab memo",
            source="attachment",
            abstract="private-document-secret-text",
        ),
        db_path=isolated_db,
    )

    store.add_claim_evidence(
        store.NewClaimEvidence(
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
    store.add_claim_evidence(
        store.NewClaimEvidence(
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

    store.save_report(
        run_id,
        {"research_goal": run.research_goal},
        store.ReportMarkdownDocuments("# Goal Report"),
        db_path=isolated_db,
    )
    return run_id, released_id, cited_id


def test_shared_payload_is_filtered_to_release_artifact(
    isolated_db: str,
) -> None:
    """A share returns the report's filtered view, not the raw run tables.

    Blocked ideas (safety, review, dedup, contradiction), private attachment
    text, and the run configuration must not appear; the released idea and
    the evidence citing it must.
    """
    run_id, released_id, cited_id = _run_with_blocked_and_released_content(
        isolated_db
    )
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

    # The run view keeps exactly the fields the public page renders.
    assert payload["run"] == {
        "title": None,
        "research_goal": "Map a signaling pathway",
        "run_mode": "standard",
    }

    # The release content itself stays intact and text-free of full bodies.
    shared = payload["hypotheses"][0]
    assert shared["title"] == "Released feedback idea"
    assert shared["statement"] == (
        "Modulating the feedback loop improves throughput."
    )
    assert "abstract" not in payload["evidence"][0]
    assert payload["evidence"][0]["title"] == "A public pathway paper"
    # Retraction status travels with `available` into the public payload --
    # at least as relevant to a public reader as reachability is.
    assert payload["evidence"][0]["retracted"] is False

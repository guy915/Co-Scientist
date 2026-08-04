"""Scientist-in-the-loop endpoints (Milestone 7): manual hypotheses + reviews.

Covers POST /api/runs/{id}/hypotheses and /reviews: a scientist hypothesis
passes the same safety path (no bypass), is persisted with authorship
provenance and a screened safety_status, and appears in the run's hypotheses;
a scientist review lands in the shared reviews table attributed to its author.
"""

from __future__ import annotations

from tests._client import make_client as _client


def _new_run(client: object) -> str:
    res = client.post(  # type: ignore[attr-defined]
        "/api/runs", json={"research_goal": "Scientist-in-the-loop goal"}
    )
    return str(res.json()["id"])


def test_scientist_hypothesis_admitted_with_authorship(
    isolated_db: str,
) -> None:
    client = _client()
    run_id = _new_run(client)

    res = client.post(
        f"/api/runs/{run_id}/hypotheses",
        json={
            "statement": "Inhibiting kinase X reduces AML growth by apoptosis.",
            "author": "dr-smith",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["admitted"] is True
    assert body["author"] == "dr-smith"

    # It appears in the run's hypotheses with scientist provenance + a screened
    # safety status (same path as generated hypotheses, not left 'pending').
    hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    manual = next(h for h in hyps if h["id"] == body["id"])
    assert manual["created_by_agent"] == "scientist_manual"
    assert manual["author"] == "dr-smith"
    assert manual["safety_status"] == "allow"
    pending = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    assert pending[-1]["kind"] == "steering"
    assert pending[-1]["meta"]["kind"] == "manual_hypothesis"


def test_scientist_unsafe_hypothesis_is_blocked_not_persisted(
    isolated_db: str,
) -> None:
    client = _client()
    run_id = _new_run(client)

    res = client.post(
        f"/api/runs/{run_id}/hypotheses",
        json={
            "statement": (
                "Weaponize the pathogen to enhance transmissibility in humans."
            ),
            "author": "bad-actor",
        },
    )
    assert res.status_code == 200
    body = res.json()
    # No bypass for human authorship: the unsafe hypothesis is not admitted.
    assert body["admitted"] is False
    assert body["safety"]["outcome"] == "prohibited"

    hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    assert all(h["created_by_agent"] != "scientist_manual" for h in hyps)


def test_scientist_review_lands_in_reviews_table(isolated_db: str) -> None:
    client = _client()
    run_id = _new_run(client)
    hyp = client.post(
        f"/api/runs/{run_id}/hypotheses",
        json={"statement": "A safe, testable hypothesis.", "author": "dr-lee"},
    ).json()

    res = client.post(
        f"/api/runs/{run_id}/reviews",
        json={
            "hypothesis_id": hyp["id"],
            "author": "dr-lee",
            "verdict": "support",
            "critique": "Well grounded; suggest a control arm.",
        },
    )
    assert res.status_code == 200
    assert res.json()["recorded"] is True

    reviews = client.get(f"/api/runs/{run_id}/reviews").json()["reviews"]
    scientist = [r for r in reviews if r["reviewer_agent"] == "scientist"]
    assert len(scientist) == 1
    assert "dr-lee" in scientist[0]["summary"]
    messages = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    assert messages[-1]["meta"]["kind"] == "human_review"
    assert messages[-1]["applied"] is False


def test_scientist_review_rejects_invalid_verdict(isolated_db: str) -> None:
    client = _client()
    run_id = _new_run(client)
    hyp = client.post(
        f"/api/runs/{run_id}/hypotheses",
        json={"statement": "A safe, testable hypothesis.", "author": "dr-lee"},
    ).json()
    res = client.post(
        f"/api/runs/{run_id}/reviews",
        json={
            "hypothesis_id": hyp["id"],
            "author": "dr-lee",
            "verdict": "maybe",
            "critique": "",
        },
    )
    assert res.status_code == 422


def test_scientist_review_rejects_unknown_hypothesis(isolated_db: str) -> None:
    """A review must target a hypothesis that exists (no dangling rows)."""
    client = _client()
    run_id = _new_run(client)
    res = client.post(
        f"/api/runs/{run_id}/reviews",
        json={
            "hypothesis_id": "does-not-exist",
            "author": "dr-lee",
            "verdict": "support",
            "critique": "",
        },
    )
    assert res.status_code == 404


def test_scientist_review_rejects_cross_run_hypothesis(
    isolated_db: str,
) -> None:
    """A review cannot target a hypothesis owned by a different run."""
    client = _client()
    run_a = _new_run(client)
    run_b = _new_run(client)
    hyp_b = client.post(
        f"/api/runs/{run_b}/hypotheses",
        json={"statement": "A safe hypothesis in run B.", "author": "dr-lee"},
    ).json()

    # Post a review to run A referencing run B's hypothesis.
    res = client.post(
        f"/api/runs/{run_a}/reviews",
        json={
            "hypothesis_id": hyp_b["id"],
            "author": "dr-lee",
            "verdict": "support",
            "critique": "",
        },
    )
    assert res.status_code == 404
    # No mismatched review row leaked into run A.
    assert client.get(f"/api/runs/{run_a}/reviews").json()["reviews"] == []


def test_attachment_indexed_and_searchable(isolated_db: str) -> None:
    client = _client()
    run_id = _new_run(client)

    res = client.post(
        f"/api/runs/{run_id}/attachments",
        json={
            "title": "Persister cell review",
            "text": (
                "Drug-tolerant persister cells survive EGFR inhibition via "
                "a reversible transcriptional program and mitochondrial "
                "priming."
            ),
            "consent": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["indexed"] is True

    # The attachment is retrievable from the run's private corpus.
    hits = client.get(
        f"/api/runs/{run_id}/attachments/search",
        params={"q": "persister mitochondrial priming"},
    ).json()["results"]
    assert hits
    assert hits[0]["title"] == "Persister cell review"


def test_attachment_requires_consent(isolated_db: str) -> None:
    client = _client()
    run_id = _new_run(client)
    res = client.post(
        f"/api/runs/{run_id}/attachments",
        json={"title": "Doc", "text": "Some text.", "consent": False},
    )
    assert res.status_code == 422


def test_attachment_rejects_oversized_text(isolated_db: str) -> None:
    client = _client()
    run_id = _new_run(client)
    res = client.post(
        f"/api/runs/{run_id}/attachments",
        json={"title": "Big", "text": "x" * 200_001, "consent": True},
    )
    # The request-model max_length bound rejects it before any storage.
    assert res.status_code == 422


def test_pasted_and_uploaded_attachments_emit_same_audit_event(
    isolated_db: str,
) -> None:
    """A pasted-text attachment must audit identically to an uploaded file.

    Both endpoints persist evidence and steer the run with the same
    contribution kind (see runs_contrib.py); the event log must not treat
    one as invisible while recording the other.
    """
    client = _client()
    run_id = _new_run(client)

    pasted = client.post(
        f"/api/runs/{run_id}/attachments",
        json={
            "title": "Pasted note",
            "text": "Persister cells tolerate EGFR inhibition reversibly.",
            "consent": True,
        },
    ).json()
    uploaded = client.post(
        f"/api/runs/{run_id}/attachments/upload",
        files={
            "file": ("assay.md", b"Kinase X reduced growth.", "text/markdown")
        },
        data={"consent": "true"},
    ).json()

    events = client.get(f"/api/runs/{run_id}/events?stream=false").json()
    attachment_events = [
        e for e in events["events"] if e["type"] == "scientist.attachment"
    ]
    assert [e["payload"]["evidence_id"] for e in attachment_events] == [
        pasted["id"],
        uploaded["id"],
    ]
    assert attachment_events[0]["payload"]["title"] == "Pasted note"
    assert attachment_events[1]["payload"]["title"] == "assay.md"

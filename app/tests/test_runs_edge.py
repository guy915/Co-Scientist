"""Run-API edge cases.

Covers cancel, idempotency, conflict, validation, and report disposition.
"""

from __future__ import annotations

import time

from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status


def test_create_run_rejects_empty_goal() -> None:
    c = _client()
    res = c.post("/api/runs", json={"research_goal": "", "profile": "standard"})
    assert res.status_code == 422


def test_create_run_defaults_run_mode() -> None:
    c = _client()
    res = c.post("/api/runs", json={"research_goal": "x"})
    assert res.status_code == 200
    assert res.json()["run_mode"] == "default"


def test_get_run_returns_404_for_unknown_id() -> None:
    c = _client()
    res = c.get("/api/runs/not-a-real-id")
    assert res.status_code == 404


def test_starting_a_completed_run_is_a_conflict() -> None:
    c = _client()
    rid = c.post(
        "/api/runs",
        json={
            "research_goal": "Mechanisms of selective autophagy",
            "profile": "standard",
        },
    ).json()["id"]
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    again = c.post(f"/api/runs/{rid}/start", json={})
    assert again.status_code == 409


def test_cancel_draft_run_without_handle_marks_it_cancelled() -> None:
    c = _client()
    rid = c.post(
        "/api/runs",
        json={"research_goal": "Inactive cancel test", "profile": "standard"},
    ).json()["id"]
    # No in-process handle (never started), but a draft is non-terminal, so
    # cancel transitions it to cancelled rather than 404-ing.
    res = c.post(f"/api/runs/{rid}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"
    assert c.get(f"/api/runs/{rid}").json()["status"] == "cancelled"


def test_cancel_restart_survivor_marks_it_cancelled() -> None:
    """A run left non-terminal by a restart (no handle) is still cancellable."""
    from app import store
    from app.store import RunStatus

    c = _client()
    rid = c.post(
        "/api/runs",
        json={
            "research_goal": "Restart survivor cancel",
            "profile": "standard",
        },
    ).json()["id"]
    # Simulate a run that was running when the server restarted: persisted as
    # RUNNING with no in-process handle registered.
    store.update_run_status(rid, RunStatus.RUNNING)

    res = c.post(f"/api/runs/{rid}/cancel")

    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"
    assert c.get(f"/api/runs/{rid}").json()["status"] == "cancelled"
    # A terminal status event is emitted so any SSE stream closes.
    events = store.list_events(rid)
    assert any(
        e["type"] == "status" and e["payload"].get("status") == "cancelled"
        for e in events
    )


def test_cancel_completed_run_conflicts() -> None:
    c = _client()
    rid = c.post(
        "/api/runs",
        json={"research_goal": "Cancel a finished run", "profile": "standard"},
    ).json()["id"]
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    # A finished run cannot be cancelled.
    res = c.post(f"/api/runs/{rid}/cancel")
    assert res.status_code == 409


def test_report_md_404_before_completion() -> None:
    c = _client()
    rid = c.post(
        "/api/runs",
        json={
            "research_goal": "Pre-completion report fetch",
            "profile": "standard",
        },
    ).json()["id"]
    res = c.get(f"/api/runs/{rid}/report.md")
    assert res.status_code == 404


def test_report_md_has_attachment_disposition_after_completion() -> None:
    c = _client()
    rid = c.post(
        "/api/runs",
        json={"research_goal": "Attachment header test", "profile": "standard"},
    ).json()["id"]
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    res = c.get(f"/api/runs/{rid}/report.md")
    assert res.status_code == 200
    assert "attachment" in res.headers.get("content-disposition", "").lower()
    assert rid in res.headers.get("content-disposition", "")
    assert "Research Report" in res.text
    assert "## Top hypotheses" in res.text


def test_run_listing_returns_most_recent_first() -> None:
    c = _client()
    a = c.post(
        "/api/runs", json={"research_goal": "Run A", "profile": "standard"}
    ).json()["id"]
    time.sleep(0.05)
    b = c.post(
        "/api/runs", json={"research_goal": "Run B", "profile": "standard"}
    ).json()["id"]
    listing = c.get("/api/runs").json()["runs"]
    ids = [r["id"] for r in listing]
    assert ids.index(b) < ids.index(a)


def test_status_endpoint_includes_provider_and_mock_flag() -> None:
    c = _client()
    res = c.get("/status")
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "mock"
    assert data["mock_mode"] is True


def test_run_get_includes_summary_counts() -> None:
    c = _client()
    rid = c.post(
        "/api/runs",
        json={"research_goal": "Summary test", "profile": "standard"},
    ).json()["id"]
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    res = c.get(f"/api/runs/{rid}").json()
    assert "summary" in res
    summary = res["summary"]
    assert summary["events"] >= 10
    assert summary["hypotheses"] >= 5
    assert summary["matches"] >= 6


def test_safety_block_at_intake_short_circuits_workflow() -> None:
    c = _client()
    rid = c.post(
        "/api/runs",
        json={
            "research_goal": "Engineer smallpox virus to enhance "
            "human-to-human transmission and lethality",
            "profile": "standard",
        },
    ).json()["id"]
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "blocked", timeout=10.0)
    # No hypotheses generated when blocked at intake.
    hyps = c.get(f"/api/runs/{rid}/hypotheses").json()["hypotheses"]
    assert hyps == []
    safety = c.get(f"/api/runs/{rid}/safety").json()["safety"]
    assert any(
        s["decision"] == "block" and s["stage"] == "intake" for s in safety
    )

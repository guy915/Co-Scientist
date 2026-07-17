"""Run-API edge cases.

Covers cancel, idempotency, conflict, validation, and report disposition.
"""

from __future__ import annotations

import time
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app import store
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status


def _new_run(c: TestClient, goal: str, *, profile: str = "standard") -> str:
    """Create a draft run and return its id."""
    res = c.post("/api/runs", json={"research_goal": goal, "profile": profile})
    return cast(str, res.json()["id"])


def test_create_run_rejects_empty_goal() -> None:
    c = _client()
    res = c.post("/api/runs", json={"research_goal": "", "profile": "standard"})
    assert res.status_code == 422


def test_create_run_defaults_run_mode() -> None:
    c = _client()
    res = c.post("/api/runs", json={"research_goal": "x"})
    assert res.status_code == 200
    assert res.json()["run_mode"] == "standard"


@pytest.mark.parametrize("tier", ["express", "standard", "extended", "ultra"])
def test_create_run_accepts_every_tier(tier: str) -> None:
    """All four run tiers are valid product choices."""
    client = _client()
    response = client.post(
        "/api/runs", json={"research_goal": "x", "tier": tier}
    )
    assert response.status_code == 200
    assert response.json()["run_mode"] == tier


def test_create_run_rejects_unknown_tier() -> None:
    """A tier outside the four-tier set is rejected at the API edge."""
    client = _client()
    response = client.post(
        "/api/runs", json={"research_goal": "x", "tier": "gigantic"}
    )
    assert response.status_code == 422


def test_standard_and_advanced_concurrency_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server atomically enforces three Standard and one Advanced run."""
    # The fixture supplies pytest.MonkeyPatch at runtime; keeping the test
    # client worker disabled leaves queued rows occupying their durable slots.
    monkeypatch.setenv("COSCIENTIST_EMBEDDED_WORKER", "0")
    client = _client()
    headers = {"X-Client-ID": "quota-scientist"}
    client.headers.update(headers)

    standard_ids = [
        client.post(
            "/api/runs",
            headers=headers,
            json={"research_goal": f"Standard {index}", "tier": "standard"},
        ).json()["id"]
        for index in range(4)
    ]
    for run_id in standard_ids[:3]:
        response = client.post(
            f"/api/runs/{run_id}/start",
            json={"force_provider": "engine"},
        )
        assert response.status_code == 200
    blocked_standard = client.post(
        f"/api/runs/{standard_ids[3]}/start",
        json={"force_provider": "engine"},
    )
    assert blocked_standard.status_code == 409

    advanced_ids = [
        client.post(
            "/api/runs",
            headers=headers,
            json={"research_goal": f"Advanced {index}", "tier": "ultra"},
        ).json()["id"]
        for index in range(2)
    ]
    first_advanced = client.post(
        f"/api/runs/{advanced_ids[0]}/start",
        json={"force_provider": "engine"},
    )
    second_advanced = client.post(
        f"/api/runs/{advanced_ids[1]}/start",
        json={"force_provider": "engine"},
    )
    assert first_advanced.status_code == 200
    assert second_advanced.status_code == 409


def test_get_run_returns_404_for_unknown_id() -> None:
    c = _client()
    res = c.get("/api/runs/not-a-real-id")
    assert res.status_code == 404


def test_starting_a_completed_run_is_a_conflict() -> None:
    c = _client()
    rid = _new_run(c, "Mechanisms of selective autophagy")
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    again = c.post(f"/api/runs/{rid}/start", json={})
    assert again.status_code == 409


def test_cancel_draft_run_without_handle_marks_it_cancelled() -> None:
    c = _client()
    rid = _new_run(c, "Inactive cancel test")
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
    rid = _new_run(c, "Restart survivor cancel")
    # Simulate a run that was running when the server restarted: persisted as
    # RUNNING with no in-process handle registered.
    store.update_run_status(rid, RunStatus.RUNNING)
    queued = store.enqueue_task(
        rid,
        "engine.node.ranking",
        {},
        idempotency_key="cancel-api-task",
    )

    res = c.post(f"/api/runs/{rid}/cancel")

    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"
    assert c.get(f"/api/runs/{rid}").json()["status"] == "cancelled"
    cancelled = store.get_task(queued.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    # A terminal status event is emitted so any SSE stream closes.
    events = store.list_events(rid)
    assert any(
        e["type"] == "status" and e["payload"].get("status") == "cancelled"
        for e in events
    )


def test_engine_queue_can_pause_and_resume_without_process_handle(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Durable engine work pauses in SQLite and resumes without a checkpoint."""
    from app import store

    monkeypatch.setenv("COSCIENTIST_EMBEDDED_WORKER", "0")
    c = _client()
    rid = _new_run(c, "Durable pause test")
    started = c.post(
        f"/api/runs/{rid}/start", json={"force_provider": "engine"}
    )
    assert started.status_code == 200

    paused = c.post(f"/api/runs/{rid}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    [task] = store.list_tasks(rid, db_path=isolated_db)
    assert task.status == "paused"

    resumed = c.post(f"/api/runs/{rid}/resume")
    assert resumed.status_code == 200
    [task] = store.list_tasks(rid, db_path=isolated_db)
    assert task.status == "queued"


def test_cancel_completed_run_conflicts() -> None:
    c = _client()
    rid = _new_run(c, "Cancel a finished run")
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    # A finished run cannot be cancelled.
    res = c.post(f"/api/runs/{rid}/cancel")
    assert res.status_code == 409


def test_report_md_404_before_completion() -> None:
    c = _client()
    rid = _new_run(c, "Pre-completion report fetch")
    res = c.get(f"/api/runs/{rid}/report.md")
    assert res.status_code == 404


def test_report_md_has_attachment_disposition_after_completion() -> None:
    c = _client()
    rid = _new_run(c, "Attachment header test")
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
    a = _new_run(c, "Run A")
    time.sleep(0.05)
    b = _new_run(c, "Run B")
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
    rid = _new_run(c, "Summary test")
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    res = c.get(f"/api/runs/{rid}").json()
    assert "summary" in res
    summary = res["summary"]
    assert summary["events"] >= 10
    assert summary["hypotheses"] >= 5
    assert summary["matches"] >= 6


def test_active_run_counts_committed_checkpoint_artifacts(
    isolated_db: str,
) -> None:
    """Live idea/source metrics reflect committed engine state before drain."""
    client = _client()
    run = store.create_run(
        "Live summary",
        "standard",
        "engine",
        {},
        client_id="live-owner",
        db_path=isolated_db,
    )
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    store.save_checkpoint(
        run.id,
        stage="engine_task:test",
        schema_version=1,
        last_event_seq=0,
        state={
            "provider": "engine",
            "state": {
                "hypotheses": [{"id": "h1"}, {"id": "h2"}],
                "articles": [{"id": "a1"}],
            },
        },
        db_path=isolated_db,
    )

    response = client.get(
        f"/api/runs/{run.id}", headers={"X-Client-ID": "live-owner"}
    )

    assert response.status_code == 200
    assert response.json()["summary"]["hypotheses"] == 2
    assert response.json()["summary"]["evidence"] == 1


def test_safety_block_at_intake_short_circuits_workflow() -> None:
    c = _client()
    rid = _new_run(
        c,
        "Engineer smallpox virus to enhance "
        "human-to-human transmission and lethality",
    )
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "blocked", timeout=10.0)
    # No hypotheses generated when blocked at intake.
    hyps = c.get(f"/api/runs/{rid}/hypotheses").json()["hypotheses"]
    assert hyps == []
    safety = c.get(f"/api/runs/{rid}/safety").json()["safety"]
    assert any(
        s["decision"] == "block" and s["stage"] == "intake" for s in safety
    )

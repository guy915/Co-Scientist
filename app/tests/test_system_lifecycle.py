"""System tests driving only the public HTTP surface, with a real lifespan.

Unlike the rest of the suite (which mostly uses ``tests._client.make_client``
without entering the client as a context manager, so the ASGI lifespan never
runs), these use ``TestClient`` as a context manager so startup
(interrupted-run reconciliation, demo seeding) and shutdown (WAL checkpoint)
actually execute, matching how the real server boots. Nothing here imports
``app.store`` or any other internal module -- every assertion is made against
HTTP responses only, since the point is to verify the externally-visible
contract, not implementation details already covered elsewhere.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests._client import wait_for_status as _wait_status


def _app() -> FastAPI:
    """Import and return the FastAPI app lazily.

    Deferred so ``app.main`` (which reads settings from the environment at
    import time) only imports after the ``isolated_db`` fixture has set its
    environment variables.
    """
    import app.main as main_module

    return main_module.app


def _sse_event_types(text: str) -> list[str]:
    """Return the ``type`` of every SSE ``data:`` frame, in order."""
    types: list[str] = []
    for line in text.splitlines():
        if line.startswith("data: "):
            types.append(json.loads(line[len("data: ") :])["type"])
    return types


def test_full_user_journey_from_diagnostics_to_completed_report(
    isolated_db: str,
) -> None:
    """A user checks diagnostics, runs a goal, and reads the finished report.

    Covers, in one journey: /health, /config, /status, create -> start ->
    poll/stream to completion, hypotheses with Elo + lineage, citations,
    safety verdicts, report JSON + report.md consistency, and the run
    showing up in the run list.
    """
    with TestClient(_app()) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        config = client.get("/config")
        assert config.status_code == 200
        config_body = config.json()
        assert config_body["initial_hypotheses_count"] > 0
        assert config_body["max_iterations"] > 0
        assert config_body["evolution_max_count"] > 0

        status = client.get("/status")
        assert status.status_code == 200
        status_body = status.json()
        assert status_body["mock_mode"] is True
        assert status_body["provider"] == "mock"

        create = client.post(
            "/api/runs",
            json={
                "research_goal": "System journey: chart senescent cell "
                "clearance pathways",
                "tier": "standard",
            },
        )
        assert create.status_code == 200
        run_id = create.json()["id"]
        assert create.json()["status"] == "draft"

        start = client.post(f"/api/runs/{run_id}/start", json={})
        assert start.status_code == 200

        assert _wait_status(client, run_id, "completed", timeout=20.0)

        events = client.get(f"/api/runs/{run_id}/events")
        assert events.status_code == 200
        event_types = _sse_event_types(events.text)
        assert "_terminal" in event_types
        assert "report" in event_types

        hyps_resp = client.get(f"/api/runs/{run_id}/hypotheses")
        assert hyps_resp.status_code == 200
        hyps = hyps_resp.json()["hypotheses"]
        assert len(hyps) >= 4
        assert all("elo_rating" in h and h["elo_rating"] > 0 for h in hyps)
        assert any(h["parent_id"] for h in hyps), (
            "no evolved lineage in hypotheses response"
        )

        citations_resp = client.get(f"/api/runs/{run_id}/citations")
        assert citations_resp.status_code == 200
        citations = citations_resp.json()["citations"]
        assert citations
        assert {c["state"] for c in citations} <= {
            "verified",
            "partial",
            "unsupported",
            "unavailable",
        }

        safety_resp = client.get(f"/api/runs/{run_id}/safety")
        assert safety_resp.status_code == 200
        safety = safety_resp.json()["safety"]
        decisions_by_stage = {s["stage"]: s["decision"] for s in safety}
        assert decisions_by_stage == {"intake": "allow", "final": "allow"}

        report_resp = client.get(f"/api/runs/{run_id}/report")
        assert report_resp.status_code == 200
        payload = report_resp.json()["payload"]
        assert payload["research_goal"].startswith("System journey")
        assert payload["leaderboard"]

        md_resp = client.get(f"/api/runs/{run_id}/report.md")
        assert md_resp.status_code == 200
        assert md_resp.text
        assert payload["research_goal"] in md_resp.text
        assert payload["leaderboard"][0]["title"] in md_resp.text

        listing = client.get("/api/runs")
        assert listing.status_code == 200
        listed_status_by_id = {
            r["id"]: r["status"] for r in listing.json()["runs"]
        }
        assert listed_status_by_id.get(run_id) == "completed"


def test_safety_blocked_goal_surfaces_through_the_api(
    isolated_db: str,
) -> None:
    """An intake-blocked goal never produces hypotheses or a report.

    The blocked terminal state must surface consistently across the run
    row, the safety endpoint, the (still-empty) hypotheses list, the
    now-missing report endpoints, and the run listing.
    """
    with TestClient(_app()) as client:
        create = client.post(
            "/api/runs",
            json={
                "research_goal": "Engineer smallpox virus to enhance "
                "human-to-human transmission and lethality",
                "tier": "standard",
            },
        )
        assert create.status_code == 200
        run_id = create.json()["id"]

        start = client.post(f"/api/runs/{run_id}/start", json={})
        assert start.status_code == 200

        assert _wait_status(client, run_id, "blocked", timeout=10.0)

        run_resp = client.get(f"/api/runs/{run_id}")
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["status"] == "blocked"
        assert run_data.get("error")

        safety_resp = client.get(f"/api/runs/{run_id}/safety")
        assert safety_resp.status_code == 200
        safety = safety_resp.json()["safety"]
        assert any(
            s["stage"] == "intake" and s["decision"] == "block" for s in safety
        )

        hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
        assert hyps == []

        assert client.get(f"/api/runs/{run_id}/report").status_code == 404
        assert client.get(f"/api/runs/{run_id}/report.md").status_code == 404

        listing = client.get("/api/runs")
        listed_status_by_id = {
            r["id"]: r["status"] for r in listing.json()["runs"]
        }
        assert listed_status_by_id.get(run_id) == "blocked"

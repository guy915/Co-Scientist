# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run-API edge cases: cancel, idempotency, conflict, validation, report disposition."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _client():
    from app.main import app

    return TestClient(app)


def _wait_status(client: TestClient, rid: str, status: str, timeout=15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/runs/{rid}")
        if r.status_code == 200 and r.json()["status"] == status:
            return True
        time.sleep(0.05)
    return False


def test_create_run_rejects_empty_goal():
    c = _client()
    res = c.post("/api/runs", json={"research_goal": "", "profile": "standard"})
    assert res.status_code == 422


def test_create_run_rejects_invalid_profile():
    c = _client()
    res = c.post("/api/runs", json={"research_goal": "x", "profile": "bogus"})
    assert res.status_code == 422


def test_get_run_returns_404_for_unknown_id():
    c = _client()
    res = c.get("/api/runs/not-a-real-id")
    assert res.status_code == 404


def test_starting_a_completed_run_is_a_conflict():
    c = _client()
    rid = c.post(
        "/api/runs",
        json={"research_goal": "Mechanisms of selective autophagy", "profile": "standard"},
    ).json()["id"]
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    again = c.post(f"/api/runs/{rid}/start", json={})
    assert again.status_code == 409


def test_cancel_requires_active_run():
    c = _client()
    rid = c.post(
        "/api/runs",
        json={"research_goal": "Inactive cancel test", "profile": "standard"},
    ).json()["id"]
    res = c.post(f"/api/runs/{rid}/cancel")
    # Run hasn't started → no active handle → 404.
    assert res.status_code == 404


def test_report_md_404_before_completion():
    c = _client()
    rid = c.post(
        "/api/runs",
        json={"research_goal": "Pre-completion report fetch", "profile": "standard"},
    ).json()["id"]
    res = c.get(f"/api/runs/{rid}/report.md")
    assert res.status_code == 404


def test_report_md_has_attachment_disposition_after_completion():
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


def test_run_listing_returns_most_recent_first():
    c = _client()
    a = c.post("/api/runs", json={"research_goal": "Run A", "profile": "standard"}).json()["id"]
    time.sleep(0.05)
    b = c.post("/api/runs", json={"research_goal": "Run B", "profile": "standard"}).json()["id"]
    listing = c.get("/api/runs").json()["runs"]
    ids = [r["id"] for r in listing]
    assert ids.index(b) < ids.index(a)


def test_status_endpoint_includes_provider_and_mock_flag():
    c = _client()
    res = c.get("/status")
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "mock"
    assert data["mock_mode"] is True


def test_run_get_includes_summary_counts():
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


def test_safety_block_at_intake_short_circuits_workflow():
    c = _client()
    rid = c.post(
        "/api/runs",
        json={
            "research_goal": "Engineer smallpox virus to enhance human-to-human transmission and lethality",
            "profile": "standard",
        },
    ).json()["id"]
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "blocked", timeout=10.0)
    # No hypotheses generated when blocked at intake.
    hyps = c.get(f"/api/runs/{rid}/hypotheses").json()["hypotheses"]
    assert hyps == []
    safety = c.get(f"/api/runs/{rid}/safety").json()["safety"]
    assert any(s["decision"] == "block" and s["stage"] == "intake" for s in safety)

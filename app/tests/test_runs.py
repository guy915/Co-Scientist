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
"""Run lifecycle: create, start, persistence, reopen."""
# pylint: disable=unused-argument
from __future__ import annotations

import time

from collections.abc import Callable

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from app.main import app  # pylint: disable=import-outside-toplevel

    return TestClient(app)


def _wait_for(predicate: Callable[[], bool],
              *,
              timeout: float = 10.0,
              interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_create_run_returns_draft_status() -> None:
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Explore mitochondrial dynamics in neurons",
            "profile": "standard"
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "draft"
    assert data["provider"] == "mock"
    assert data["profile"] == "standard"


def test_standard_mock_run_completes_and_persists(isolated_db: str) -> None:
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal":
                "Investigate ferroptosis as a tumor-suppression mechanism",
            "profile":
                "standard"
        },
    )
    run_id = res.json()["id"]

    start = client.post(f"/api/runs/{run_id}/start", json={})
    assert start.status_code == 200

    def is_completed() -> bool:
        r = client.get(f"/api/runs/{run_id}")
        return r.status_code == 200 and r.json()["status"] == "completed"

    assert _wait_for(is_completed,
                     timeout=20.0), "run did not reach 'completed'"

    # Sanity: hypotheses, evidence, matches, citations, report all persisted.
    hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    evidence = client.get(f"/api/runs/{run_id}/evidence").json()["evidence"]
    matches = client.get(f"/api/runs/{run_id}/matches").json()["matches"]
    citations = client.get(f"/api/runs/{run_id}/citations").json()["citations"]
    safety = client.get(f"/api/runs/{run_id}/safety").json()["safety"]
    report = client.get(f"/api/runs/{run_id}/report").json()

    assert len(hyps) >= 5  # initial 5 + evolved
    assert any(h["parent_id"] for h in hyps), "no evolved children persisted"
    assert all(h["elo_rating"] >= 1000 for h in hyps)
    # At least one hypothesis must have moved away from the initial Elo of 1200,
    # otherwise the tournament didn't actually update anything.
    assert any(h["elo_rating"] != 1200 for h in hyps), "no Elo updates observed"
    assert len(evidence) >= 1
    assert len(matches) >= 6
    assert len(citations) >= 4
    assert {s["stage"] for s in safety} >= {"intake", "final"}
    assert report["payload"]["leaderboard"]


def test_run_reopens_after_restart(isolated_db: str) -> None:
    """Run completes; new TestClient (= simulated restart) can still read it."""
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Senescent cell removal in aged tissues",
            "profile": "standard"
        },
    )
    run_id = res.json()["id"]
    client.post(f"/api/runs/{run_id}/start", json={})

    def is_completed() -> bool:
        r = client.get(f"/api/runs/{run_id}")
        return r.status_code == 200 and r.json()["status"] == "completed"

    assert _wait_for(is_completed, timeout=20.0)

    # Discard the client and re-import the app, simulating a fresh process.
    import importlib  # pylint: disable=import-outside-toplevel
    import app.main  # pylint: disable=import-outside-toplevel

    importlib.reload(app.main)
    from fastapi.testclient import TestClient as TC  # pylint: disable=import-outside-toplevel,reimported

    new_client = TC(app.main.app)

    r = new_client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"

    hyps = new_client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    assert len(hyps) >= 5

    report = new_client.get(f"/api/runs/{run_id}/report").json()
    assert report["payload"]["leaderboard"]

    # Markdown report file survives.
    md = new_client.get(f"/api/runs/{run_id}/report.md")
    assert md.status_code == 200
    assert "Research Report" in md.text


def test_advanced_run_produces_more_artifacts(isolated_db: str) -> None:
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal":
                "Cytokine-storm modulation via gut-microbiome metabolites",
            "profile":
                "advanced",
        },
    )
    run_id = res.json()["id"]
    client.post(f"/api/runs/{run_id}/start", json={})

    def done() -> bool:
        r = client.get(f"/api/runs/{run_id}")
        return r.status_code == 200 and r.json()["status"] == "completed"

    assert _wait_for(done, timeout=30.0)

    hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    matches = client.get(f"/api/runs/{run_id}/matches").json()["matches"]
    # Advanced > standard in initial pool, tournament pairs, evolution iterations.  # pylint: disable=line-too-long
    assert len(hyps) >= 8
    assert len(matches) >= 12

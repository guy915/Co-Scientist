"""Run lifecycle: create, start, persistence, reopen."""
# pylint: disable=unused-argument
from __future__ import annotations

import asyncio
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
    assert data["profile"] == "advanced"


def test_list_runs_honors_limit_query(isolated_db: str) -> None:
    client = _client()
    headers = {"X-Client-ID": "limit-test"}
    for i in range(3):
        res = client.post(
            "/api/runs",
            headers=headers,
            json={
                "research_goal": f"Limit test {i}",
                "profile": "advanced"
            },
        )
        assert res.status_code == 200

    listed = client.get("/api/runs?limit=2", headers=headers)

    assert listed.status_code == 200
    assert len(listed.json()["runs"]) == 2


def test_stale_standard_profile_and_tiny_overrides_run_as_advanced(
        isolated_db: str) -> None:
    from app.runs import CreateRunRequest, create_run  # pylint: disable=import-outside-toplevel

    class _Request:
        headers: dict[str, str] = {}

    req = CreateRunRequest(
        research_goal="Map senescence escape mechanisms",
        profile="standard",
        initial_hypotheses_count=1,
        max_iterations=0,
        evolution_max_count=1,
    )

    run = asyncio.run(create_run(req, _Request()))  # type: ignore[arg-type]

    assert run["profile"] == "advanced"
    assert run["config"]["initial_hypotheses_count"] >= 8
    assert run["config"]["max_iterations"] >= 2
    assert run["config"]["evolution_max_count"] >= 8


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
    assert len(hyps) >= 8
    assert len(matches) >= 12

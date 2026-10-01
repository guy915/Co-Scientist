"""Run lifecycle: create, start, persistence, reopen.

Safety-decision adjudication and the awaiting-decision status live in
``test_run_safety_adjudication.py`` (split out when this file grew past the
line-length ceiling).
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from fastapi.testclient import TestClient

from tests._client import DEFAULT_TEST_CLIENT_ID
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status


def _start_and_complete(
    client: TestClient,
    goal: str,
    *,
    tier: str = "express",
    timeout: float = 30.0,
) -> str:
    """Create and start a run, returning its id once it completes."""
    res = client.post("/api/runs", json={"research_goal": goal, "tier": tier})
    run_id: str = res.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    assert _wait_status(client, run_id, "completed", timeout=timeout), (
        "run did not reach 'completed'"
    )
    return run_id


def _run_views(client: TestClient, run_id: str) -> dict[str, Any]:
    """Fetch every persisted run collection the durable path publishes."""

    def _get(name: str) -> Any:
        return client.get(f"/api/runs/{run_id}/{name}").json()

    return {
        "hyps": _get("hypotheses")["hypotheses"],
        "evidence": _get("evidence")["evidence"],
        "matches": _get("matches")["matches"],
        "citations": _get("citations")["citations"],
        "safety": _get("safety")["safety"],
        "claim_evidence": _get("claim-evidence")["claim_evidence"],
        "report": _get("report"),
    }


def test_create_run_returns_draft_status() -> None:
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Explore mitochondrial dynamics in neurons",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "draft"
    assert data["provider"] == "engine"
    assert data["run_mode"] == "standard"
    assert data["profile"] == "standard"
    assert data["config"]["tier"] == "standard"
    assert data["config"]["focus"] == "balance"
    assert data["config"]["setup"]["goal"] == (
        "Explore mitochondrial dynamics in neurons"
    )


def test_owned_proximity_endpoint_returns_persisted_landscape(
    isolated_db: str,
) -> None:
    """The scientist can inspect persisted conceptual-neighbor edges."""
    from app import store

    client = _client()
    headers = {"X-Client-ID": "landscape-owner"}
    run = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Map a conceptual hypothesis landscape"},
    ).json()
    source = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run["id"], title="Source", statement="Source mechanism"
        )
    )
    target = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run["id"], title="Target", statement="Target mechanism"
        )
    )
    store.add_proximity_edge(
        store.NewProximityEdge(
            run_id=run["id"],
            source_hypothesis_id=source,
            target_hypothesis_id=target,
            similarity=0.81,
            cluster_id="cluster-1",
        )
    )

    response = client.get(f"/api/runs/{run['id']}/proximity", headers=headers)

    assert response.status_code == 200
    edges = response.json()["proximity"]
    assert len(edges) == 1
    assert edges[0]["source_hypothesis_id"] == source
    assert edges[0]["target_hypothesis_id"] == target
    assert edges[0]["similarity"] == 0.81
    assert edges[0]["cluster_id"] == "cluster-1"


def test_list_runs_honors_limit_query(isolated_db: str) -> None:
    client = _client()
    headers = {"X-Client-ID": "limit-test"}
    for i in range(3):
        res = client.post(
            "/api/runs",
            headers=headers,
            json={"research_goal": f"Limit test {i}", "run_mode": "default"},
        )
        assert res.status_code == 200

    listed = client.get("/api/runs?limit=2", headers=headers)

    assert listed.status_code == 200
    assert len(listed.json()["runs"]) == 2


def test_legacy_profile_and_tiny_overrides_run_as_default(
    isolated_db: str,
) -> None:
    from fastapi import BackgroundTasks

    from app.runs.crud import create_run
    from app.runs.models import CreateRunRequest

    class _Request:
        headers: ClassVar[dict[str, str]] = {"X-Client-ID": "direct-call-test"}

    req = CreateRunRequest(
        research_goal="Map senescence escape mechanisms",
        initial_hypotheses_count=1,
        max_iterations=0,
        evolution_max_count=1,
    )

    # _Request is a minimal stand-in for fastapi.Request; the handler only
    # touches the attributes the stub provides. No provider key is configured
    # under test, so create_run schedules no title task on this queue.
    run = asyncio.run(
        create_run(req, _Request(), BackgroundTasks())  # type: ignore[arg-type]
    )

    assert run["run_mode"] == "standard"
    assert run["profile"] == "standard"
    assert run["config"]["initial_hypotheses_count"] >= 8
    assert run["config"]["max_iterations"] >= 2
    assert run["config"]["evolution_max_count"] >= 8


def test_create_run_persists_setup_and_exact_tier_defaults(
    isolated_db: str,
) -> None:
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Discover selective autophagy mechanisms",
            "requirements": ["Use primary literature", ""],
            "attributes": ["Mechanistic"],
            "criteria": ["Testability"],
            "focus": "prefer_novelty",
            "tier": "standard",
        },
    )

    assert res.status_code == 200
    config = res.json()["config"]
    assert config["initial_hypotheses_count"] == 8
    assert config["max_iterations"] == 2
    assert config["evolution_max_count"] == 8
    assert config["tournament_pairs"] == 12
    assert config["evidence_count"] == 8
    assert config["setup"] == {
        "goal": "Discover selective autophagy mechanisms",
        "requirements": ["Use primary literature"],
        "attributes": ["Mechanistic"],
        "criteria": ["Testability"],
        "focus": "prefer_novelty",
        "tier": "standard",
    }


def test_create_run_without_spec_gets_baseline_planning(
    isolated_db: str,
) -> None:
    """A goal-only run (no UI-inferred spec) still gets baseline guidance."""
    from app.run_modes import DEFAULT_REQUIREMENTS
    from app.run_modes.attributes import DEFAULT_ATTRIBUTES
    from app.run_modes.criteria import DEFAULT_CRITERIA

    client = _client()
    res = client.post(
        "/api/runs", json={"research_goal": "Map tau propagation in the brain"}
    )

    assert res.status_code == 200
    setup = res.json()["config"]["setup"]
    assert setup["requirements"] == list(DEFAULT_REQUIREMENTS)
    assert setup["attributes"] == list(DEFAULT_ATTRIBUTES)
    assert setup["criteria"] == list(DEFAULT_CRITERIA)


def test_default_run_completes_and_persists(isolated_db: str) -> None:
    """A keyless run drives the engine on the offline backend end-to-end.

    The API start path runs the durable node executor, so the assertions here
    are on the durable path's persisted observables (hypotheses, matches,
    claim grounding, report). Literature review is disabled under test, so a
    keyless run produces no evidence/citations -- that is the offline reality.
    """
    client = _client()
    run_id = _start_and_complete(
        client,
        "Investigate ferroptosis as a tumor-suppression mechanism",
    )
    views = _run_views(client, run_id)
    hyps = views["hyps"]

    assert len(hyps) >= 2  # initial + evolved children
    assert any(h["parent_id"] for h in hyps), "no evolved children persisted"
    assert all(h["elo_rating"] >= 1000 for h in hyps)
    # An Elo moved off the initial 1200, so the tournament updated something.
    assert any(h["elo_rating"] != 1200 for h in hyps), "no Elo updates observed"
    # No literature review under test, so a keyless run grounds no evidence.
    assert views["evidence"] == []
    assert views["citations"] == []
    assert len(views["matches"]) >= 2
    assert {s["stage"] for s in views["safety"]} >= {"intake", "final"}
    # Pre-tournament safety screen ran: benign hypotheses are 'allow'.
    assert all(h["safety_status"] == "allow" for h in hyps)
    # The pre-tournament claim grounding persisted the entailment graph.
    assert len(views["claim_evidence"]) >= 1
    assert all(
        e["label"] in {"supports", "contradicts", "insufficient"}
        for e in views["claim_evidence"]
    )
    # Offline fixtures are illustrative, so the "Unverified" badge stays off.
    assert all(h.get("unverified") is False for h in hyps)
    assert views["report"]["payload"]["leaderboard"]


def test_run_reopens_after_restart(isolated_db: str) -> None:
    """Run completes; new TestClient (= simulated restart) can still read it."""
    client = _client()
    run_id = _start_and_complete(
        client, "Senescent cell removal in aged tissues"
    )

    # Discard the client and re-import the app, simulating a fresh process.
    import importlib

    import app.main

    importlib.reload(app.main)
    new_client = TestClient(
        app.main.app, headers={"X-Client-ID": DEFAULT_TEST_CLIENT_ID}
    )

    r = new_client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"

    hyps = new_client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    assert len(hyps) >= 2

    report = new_client.get(f"/api/runs/{run_id}/report").json()
    assert report["payload"]["leaderboard"]

    # Markdown report file survives.
    md = new_client.get(f"/api/runs/{run_id}/report.md")
    assert md.status_code == 200
    assert "Research Overview" in md.text


def test_legacy_advanced_profile_maps_to_standard_tier(
    isolated_db: str,
) -> None:
    """The retired ``advanced`` profile normalizes to the standard tier.

    ``profile`` is a legacy request field the API no longer honors as a tier
    selector, so a run created with it falls through to the default standard
    tier. The run still completes on the engine; depth assertions track the
    durable path's published pool rather than the mock's fixed counts.
    """
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Cytokine-storm modulation via "
            "gut-microbiome metabolites",
            "profile": "advanced",
        },
    )
    run_id: str = res.json()["id"]
    client.post(f"/api/runs/{run_id}/start", json={})

    assert _wait_status(client, run_id, "completed", timeout=60.0)

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["run_mode"] == "standard"
    assert run["profile"] == "standard"
    hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    matches = client.get(f"/api/runs/{run_id}/matches").json()["matches"]
    assert len(hyps) >= 2
    assert len(matches) >= 2

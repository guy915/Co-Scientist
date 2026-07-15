"""Run lifecycle: create, start, persistence, reopen."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status


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
    assert data["provider"] == "mock"
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
        run["id"], title="Source", statement="Source mechanism"
    )
    target = store.add_hypothesis(
        run["id"], title="Target", statement="Target mechanism"
    )
    store.add_proximity_edge(
        run["id"], source, target, 0.81, cluster_id="cluster-1"
    )

    response = client.get(f"/api/runs/{run['id']}/proximity", headers=headers)

    assert response.status_code == 200
    edges = response.json()["proximity"]
    assert len(edges) == 1
    assert edges[0]["source_hypothesis_id"] == source
    assert edges[0]["target_hypothesis_id"] == target
    assert edges[0]["similarity"] == 0.81
    assert edges[0]["cluster_id"] == "cluster-1"


def test_safety_adjudication_is_identified_and_single_use(
    isolated_db: str,
) -> None:
    """A held decision requires an identified reviewer and resolves once."""
    from app import store

    client = _client()
    headers = {"X-Client-ID": "reviewer-1"}
    created = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Review a sensitive research protocol"},
    ).json()
    store.add_safety_decision(
        created["id"],
        "intake",
        "hold",
        "Context requires review.",
        [],
        category="uncertain",
        policy_version="coscientist-safety-v2",
        requires_review=True,
    )
    decision_id = store.list_safety_decisions(created["id"])[0]["id"]

    anonymous = client.post(
        f"/api/runs/{created['id']}/safety/{decision_id}/adjudicate",
        json={"resolution": "approved"},
    )
    # Ownership middleware hides the existence of another client's run.
    assert anonymous.status_code == 404

    approved = client.post(
        f"/api/runs/{created['id']}/safety/{decision_id}/adjudicate",
        headers=headers,
        json={"resolution": "approved"},
    )
    assert approved.status_code == 200
    assert store.safety_stage_is_approved(
        created["id"], "intake", "coscientist-safety-v2"
    )

    repeated = client.post(
        f"/api/runs/{created['id']}/safety/{decision_id}/adjudicate",
        headers=headers,
        json={"resolution": "rejected"},
    )
    assert repeated.status_code == 409


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

    from app.runs import create_run
    from app.runs_models import CreateRunRequest

    class _Request:
        headers: ClassVar[dict[str, str]] = {}

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
    from app.run_modes import (
        DEFAULT_ATTRIBUTES,
        DEFAULT_CRITERIA,
        DEFAULT_REQUIREMENTS,
    )

    client = _client()
    res = client.post(
        "/api/runs", json={"research_goal": "Map tau propagation in the brain"}
    )

    assert res.status_code == 200
    setup = res.json()["config"]["setup"]
    assert setup["requirements"] == list(DEFAULT_REQUIREMENTS)
    assert setup["attributes"] == list(DEFAULT_ATTRIBUTES)
    assert setup["criteria"] == list(DEFAULT_CRITERIA)


def test_default_mock_run_completes_and_persists(isolated_db: str) -> None:
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Investigate ferroptosis as a "
            "tumor-suppression mechanism",
            "profile": "standard",
        },
    )
    run_id = res.json()["id"]

    start = client.post(f"/api/runs/{run_id}/start", json={})
    assert start.status_code == 200

    assert _wait_status(client, run_id, "completed", timeout=20.0), (
        "run did not reach 'completed'"
    )

    # Sanity: hypotheses, evidence, matches, citations, report all persisted.
    hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    evidence = client.get(f"/api/runs/{run_id}/evidence").json()["evidence"]
    matches = client.get(f"/api/runs/{run_id}/matches").json()["matches"]
    citations = client.get(f"/api/runs/{run_id}/citations").json()["citations"]
    safety = client.get(f"/api/runs/{run_id}/safety").json()["safety"]
    claim_evidence = client.get(f"/api/runs/{run_id}/claim-evidence").json()[
        "claim_evidence"
    ]
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
    # The pre-tournament safety screen ran: every hypothesis carries a real
    # safety_status (benign hypotheses are 'allow', never left 'pending').
    assert all(h["safety_status"] == "allow" for h in hyps)
    # The pre-tournament claim grounding persisted the entailment graph.
    assert len(claim_evidence) >= 1
    assert all(
        e["label"] in {"supports", "contradicts", "insufficient"}
        for e in claim_evidence
    )
    # Mock runs are illustrative fixtures, never assessed science, so the
    # "Unverified" badge is suppressed even though they carry simulated
    # claim-evidence rows that would otherwise flag every idea.
    assert all(h.get("unverified") is False for h in hyps)
    assert report["payload"]["leaderboard"]


def test_run_reopens_after_restart(isolated_db: str) -> None:
    """Run completes; new TestClient (= simulated restart) can still read it."""
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Senescent cell removal in aged tissues",
            "profile": "standard",
        },
    )
    run_id = res.json()["id"]
    client.post(f"/api/runs/{run_id}/start", json={})

    assert _wait_status(client, run_id, "completed", timeout=20.0)

    # Discard the client and re-import the app, simulating a fresh process.
    import importlib

    import app.main

    importlib.reload(app.main)
    from fastapi.testclient import (
        TestClient,
    )

    new_client = TestClient(app.main.app)

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


def test_legacy_advanced_run_uses_default_artifact_depth(
    isolated_db: str,
) -> None:
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Cytokine-storm modulation via "
            "gut-microbiome metabolites",
            "profile": "advanced",
        },
    )
    run_id = res.json()["id"]
    client.post(f"/api/runs/{run_id}/start", json={})

    assert _wait_status(client, run_id, "completed", timeout=30.0)

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["run_mode"] == "standard"
    assert run["profile"] == "standard"
    hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    matches = client.get(f"/api/runs/{run_id}/matches").json()["matches"]
    assert len(hyps) >= 8
    assert len(matches) >= 12

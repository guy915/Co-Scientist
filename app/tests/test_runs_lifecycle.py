from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import pairwise
from threading import Event
from typing import Any, ClassVar, cast

import pytest
from fastapi.testclient import TestClient

from app import engine_tasks, task_worker
from app.config import settings
from app.engine_tasks import node as engine_tasks_node
from app.engine_tasks.support import TaskCommit
from app.runs import events as runs_events
from app.store import checkpoints, runs
from app.store import events as store_events
from app.store import tasks as store
from app.store import tasks_lifecycle as lifecycle
from app.store.checkpoints import NewCheckpoint
from app.store.models import RunRow, RunStatus, ScientificTask
from app.store.runs import RunCreateOptions
from app.store.tasks import NewTask
from tests._client import DEFAULT_TEST_CLIENT_ID, make_client
from tests._client import drain as _drain
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state


def _start_and_complete(
    client: TestClient,
    goal: str,
    *,
    tier: str = "express",
    timeout: float = 30.0,
) -> str:
    res = client.post("/api/runs", json={"research_goal": goal, "tier": tier})
    run_id: str = res.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    assert _wait_status(client, run_id, "completed", timeout=timeout), (
        "run did not reach 'completed'"
    )
    return run_id


def _run_views(client: TestClient, run_id: str) -> dict[str, Any]:

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
    from app.store import hypotheses as store
    from app.store import records
    from app.store.hypotheses import NewHypothesis
    from app.store.records import NewProximityEdge

    client = _client()
    headers = {"X-Client-ID": "landscape-owner"}
    run = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Map a conceptual hypothesis landscape"},
    ).json()
    source = store.add_hypothesis(
        NewHypothesis(
            run_id=run["id"], title="Source", statement="Source mechanism"
        )
    )
    target = store.add_hypothesis(
        NewHypothesis(
            run_id=run["id"], title="Target", statement="Target mechanism"
        )
    )
    records.add_proximity_edge(
        NewProximityEdge(
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


def test_default_run_completes_and_persists(isolated_db: str) -> None:
    client = _client()
    run_id = _start_and_complete(
        client,
        "Investigate ferroptosis as a tumor-suppression mechanism",
    )
    views = _run_views(client, run_id)
    hyps = views["hyps"]

    assert len(hyps) >= 2
    assert any(h["parent_id"] for h in hyps), "no evolved children persisted"
    assert all(h["elo_rating"] >= 1000 for h in hyps)
    assert any(h["elo_rating"] != 1200 for h in hyps), "no Elo updates observed"
    assert views["evidence"] == []
    assert views["citations"] == []
    assert len(views["matches"]) >= 2
    assert {s["stage"] for s in views["safety"]} >= {"intake", "final"}
    assert all(h["safety_status"] == "allow" for h in hyps)
    assert len(views["claim_evidence"]) >= 1
    assert all(
        e["label"] in {"supports", "contradicts", "insufficient"}
        for e in views["claim_evidence"]
    )
    assert all(h.get("unverified") is False for h in hyps)
    assert views["report"]["payload"]["leaderboard"]


def test_run_reopens_after_restart(isolated_db: str) -> None:
    client = _client()
    run_id = _start_and_complete(
        client, "Senescent cell removal in aged tissues"
    )

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

    md = new_client.get(f"/api/runs/{run_id}/report.md")
    assert md.status_code == 200
    assert "Research Overview" in md.text


def test_legacy_advanced_profile_maps_to_standard_tier(
    isolated_db: str,
) -> None:
    # Legacy profile is not a tier selector; only the current tier field chooses
    # run depth.
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


def _new_run(c: TestClient, goal: str, *, tier: str = "express") -> str:
    response = c.post("/api/runs", json={"research_goal": goal, "tier": tier})
    return cast(str, response.json()["id"])


def test_cancel_after_capacity_reservation_prevents_bootstrap_admission(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    start_client = _client()
    cancel_client = _client()
    rid = _new_run(start_client, "Cancel between start admission steps")
    capacity_reserved = Event()
    cancel_entered_transaction = Event()
    continue_start = Event()
    reserve_capacity = runs.reserve_run_capacity_in_transaction
    cancel_tasks = lifecycle.cancel_run_tasks

    def reserve_then_wait(*args: object, **kwargs: object) -> bool:
        reserved = reserve_capacity(*args, **kwargs)  # type: ignore[arg-type]
        capacity_reserved.set()
        if not continue_start.wait(timeout=10):
            raise TimeoutError("test did not release the start barrier")
        return reserved

    def observe_cancel_tasks(*args: object, **kwargs: object) -> int:
        cancel_entered_transaction.set()
        return cancel_tasks(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        runs, "reserve_run_capacity_in_transaction", reserve_then_wait
    )
    monkeypatch.setattr(lifecycle, "cancel_run_tasks", observe_cancel_tasks)
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending_start = executor.submit(
            start_client.post, f"/api/runs/{rid}/start", json={}
        )
        early_cancel = None
        try:
            assert capacity_reserved.wait(timeout=5)
            pending_cancel = executor.submit(
                cancel_client.post, f"/api/runs/{rid}/cancel"
            )
            if cancel_entered_transaction.wait(timeout=0.5):
                early_cancel = pending_cancel.result(timeout=5)
        finally:
            continue_start.set()
        started = pending_start.result(timeout=5)
        cancelled = (
            early_cancel
            if early_cancel is not None
            else pending_cancel.result(timeout=5)
        )

    assert started.status_code == 200
    assert cancelled.status_code == 200
    assert start_client.get(f"/api/runs/{rid}").json()["status"] == "cancelled"
    [task] = store.list_tasks(rid, db_path=isolated_db)
    assert task.status == "cancelled"
    events = store_events.list_events(rid, db_path=isolated_db)
    cancelled_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    queued_event = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "queued"
    )
    assert queued_event["seq"] < cancelled_event["seq"]


def test_cancel_before_capacity_reservation_is_not_a_restart(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    start_client = _client()
    cancel_client = _client()
    rid = _new_run(start_client, "Cancel before the start reservation")
    start_reached_reservation = Event()
    continue_start = Event()
    from app.runs import lifecycle as runs_lifecycle

    admit_workflow = runs_lifecycle._enqueue_workflow_and_maybe_launch_worker

    def wait_before_admission(*args: object, **kwargs: object) -> object:
        start_reached_reservation.set()
        if not continue_start.wait(timeout=10):
            raise TimeoutError("test did not release the start barrier")
        return admit_workflow(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        runs_lifecycle,
        "_enqueue_workflow_and_maybe_launch_worker",
        wait_before_admission,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending_start = executor.submit(
            start_client.post, f"/api/runs/{rid}/start", json={}
        )
        try:
            assert start_reached_reservation.wait(timeout=5)
            cancelled = cancel_client.post(f"/api/runs/{rid}/cancel")
            assert cancelled.status_code == 200
        finally:
            continue_start.set()
        started = pending_start.result(timeout=5)

    assert started.status_code == 409
    assert start_client.get(f"/api/runs/{rid}").json()["status"] == "cancelled"
    assert not any(
        task.status == "queued"
        for task in store.list_tasks(rid, db_path=isolated_db)
    )
    events = store_events.list_events(rid, db_path=isolated_db)
    cancelled_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    assert not any(
        event["type"] == "lifecycle"
        and event["payload"].get("event") == "queued"
        and event["seq"] > cancelled_event["seq"]
        for event in events
    )


def test_normal_start_and_explicit_restart_requeue_cancelled_bootstrap(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Restart a cancelled bootstrap")

    started = client.post(f"/api/runs/{rid}/start", json={})
    assert started.status_code == 200
    [bootstrap] = store.list_tasks(rid, db_path=isolated_db)
    assert bootstrap.status == "queued"
    queued_run = runs.get_run(rid, db_path=isolated_db)
    assert queued_run is not None and queued_run.status == "queued"

    cancelled = client.post(f"/api/runs/{rid}/cancel")
    assert cancelled.status_code == 200
    cancelled_task = store.get_task(bootstrap.id, db_path=isolated_db)
    assert cancelled_task is not None and cancelled_task.status == "cancelled"
    events = store_events.list_events(rid, db_path=isolated_db)
    queued_event = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "queued"
    )
    cancelled_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    assert queued_event["seq"] < cancelled_event["seq"]

    restarted = client.post(f"/api/runs/{rid}/start", json={})

    assert restarted.status_code == 200
    assert restarted.json()["task_id"] == bootstrap.id
    [requeued] = store.list_tasks(rid, db_path=isolated_db)
    assert requeued.id == bootstrap.id
    assert requeued.status == "queued"


def test_cancelled_run_with_checkpoint_resumes_instead_of_restarting(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.store.models import RunStatus
    from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Continue a cancelled checkpoint")
    _seed_checkpoint(rid, _task_state(rid), db_path=isolated_db)
    runs.update_run_status(rid, RunStatus.RUNNING, db_path=isolated_db)
    assert client.post(f"/api/runs/{rid}/cancel").status_code == 200

    restart = client.post(f"/api/runs/{rid}/start", json={})

    assert restart.status_code == 409
    assert "use /resume" in restart.json()["detail"]
    cancelled_run = runs.get_run(rid, db_path=isolated_db)
    assert cancelled_run is not None and cancelled_run.status == "cancelled"
    assert store.list_tasks(rid, db_path=isolated_db) == []

    resumed = client.post(f"/api/runs/{rid}/resume")

    assert resumed.status_code == 200
    assert runs.get_run(rid, db_path=isolated_db).status == "queued"  # type: ignore[union-attr]
    [task] = store.list_tasks(rid, db_path=isolated_db)
    assert task.task_type == "engine.node.orchestrator"
    assert task.status == "queued"


def test_failed_run_with_checkpoint_uses_resume(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.store.models import RunStatus
    from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Resume a failed checkpoint")
    _seed_checkpoint(rid, _task_state(rid), db_path=isolated_db)
    runs.update_run_status(rid, RunStatus.FAILED, db_path=isolated_db)

    restart = client.post(f"/api/runs/{rid}/start", json={})

    assert restart.status_code == 409
    assert "use /resume" in restart.json()["detail"]
    resumed = client.post(f"/api/runs/{rid}/resume")
    assert resumed.status_code == 200
    run = runs.get_run(rid, db_path=isolated_db)
    assert run is not None and run.status == "queued"


def test_blocked_bootstrap_without_checkpoint_requires_new_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.store.models import RunStatus

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Do not revive an intake block")
    assert client.post(f"/api/runs/{rid}/start", json={}).status_code == 200
    task = store.claim_task("blocked-bootstrap", run_id=rid)
    assert task is not None
    assert lifecycle.complete_task(
        task.id,
        "blocked-bootstrap",
        {"status": "withheld"},
        db_path=isolated_db,
    )
    runs.update_run_status(rid, RunStatus.BLOCKED, db_path=isolated_db)

    restart = client.post(f"/api/runs/{rid}/start", json={})

    assert restart.status_code == 409
    assert "create a new run" in restart.json()["detail"]
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None and saved.status == "completed"


def test_blocked_run_with_completed_finalize_requires_new_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.store.models import RunStatus
    from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Do not revive a blocked finalize")
    predecessor = store.enqueue_task(
        NewTask(
            run_id=rid,
            task_type="engine.node.orchestrator",
            inputs={},
            idempotency_key="previous-orchestrator",
        ),
        db_path=isolated_db,
    )
    previous = store.claim_task("previous-worker", run_id=rid)
    assert previous is not None and previous.id == predecessor.id
    assert lifecycle.complete_task(
        previous.id, "previous-worker", {}, db_path=isolated_db
    )
    state = _task_state(rid)
    checkpoint_seq = _seed_checkpoint(
        rid, state, stage=f"engine_task:{previous.id}", db_path=isolated_db
    )
    checkpoint = checkpoints.get_latest_checkpoint(rid, db_path=isolated_db)
    assert checkpoint is not None
    checkpoint_seq = checkpoints.save_checkpoint(
        rid,
        NewCheckpoint(
            stage=f"engine_task:{previous.id}",
            schema_version=checkpoint["schema_version"],
            last_event_seq=checkpoint["last_event_seq"],
            state={
                **checkpoint["state"],
                "resume_successor": "engine.finalize",
            },
        ),
        db_path=isolated_db,
    )
    finalizer = store.enqueue_task(
        NewTask(
            run_id=rid,
            task_type="engine.finalize",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"engine.finalize:after:{previous.id}",
            dependencies=(previous.id,),
        ),
        db_path=isolated_db,
    )
    claimed_finalizer = store.claim_task("finalize-worker", run_id=rid)
    assert claimed_finalizer is not None
    assert claimed_finalizer.id == finalizer.id
    assert lifecycle.complete_task(
        finalizer.id, "finalize-worker", {}, db_path=isolated_db
    )
    runs.update_run_status(rid, RunStatus.BLOCKED, db_path=isolated_db)

    response = client.post(f"/api/runs/{rid}/start", json={})

    assert response.status_code == 409
    assert "create a new run" in response.json()["detail"]
    saved = store.get_task(finalizer.id, db_path=isolated_db)
    assert saved is not None and saved.status == "completed"


def test_start_rolls_back_capacity_when_bootstrap_enqueue_fails(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Rollback an incomplete start")

    def fail_enqueue(*_: object, **__: object) -> object:
        raise HTTPException(status_code=503, detail="injected enqueue failure")

    monkeypatch.setattr(engine_tasks, "enqueue_bootstrap", fail_enqueue)
    response = client.post(f"/api/runs/{rid}/start", json={})

    assert response.status_code == 503
    run = runs.get_run(rid, db_path=isolated_db)
    assert run is not None and run.status == "draft"
    assert store.list_tasks(rid, db_path=isolated_db) == []
    assert not any(
        event["type"] == "lifecycle"
        and event["payload"].get("event") == "queued"
        for event in store_events.list_events(rid, db_path=isolated_db)
    )


def test_cancelled_paused_bootstrap_can_be_explicitly_restarted(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Restart a paused bootstrap")
    assert client.post(f"/api/runs/{rid}/start", json={}).status_code == 200
    [bootstrap] = store.list_tasks(rid, db_path=isolated_db)

    paused = client.post(f"/api/runs/{rid}/pause")
    assert paused.status_code == 200
    parked = store.get_task(bootstrap.id, db_path=isolated_db)
    assert parked is not None and parked.status == "paused"
    assert client.post(f"/api/runs/{rid}/cancel").status_code == 200

    restarted = client.post(f"/api/runs/{rid}/start", json={})

    assert restarted.status_code == 200
    task = store.get_task(bootstrap.id, db_path=isolated_db)
    assert task is not None and task.status == "queued"


class _FakeRequest:
    def __init__(
        self,
        disconnected: bool = False,
        disconnect_after: int | None = None,
    ) -> None:
        self.disconnected = disconnected
        self.disconnect_after = disconnect_after
        self._checks = 0

    async def is_disconnected(self) -> bool:
        self._checks += 1
        if (
            self.disconnect_after is not None
            and self._checks >= self.disconnect_after
        ):
            return True
        return self.disconnected


def test_terminal_frame_formats_sse_payload() -> None:
    frame = runs_events._terminal_frame("completed", 5)
    assert frame.startswith("data: ")
    assert '"type": "_terminal"' in frame
    assert '"status": "completed"' in frame
    assert '"seq": 5' in frame


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"type": "log", "payload": {}}, None),
        ({"type": "status", "payload": {"status": "completed"}}, "completed"),
        ({"type": "status", "payload": {"status": "running"}}, None),
        ({"type": "status", "payload": None}, None),
    ],
    ids=[
        "non_status_type_returns_none",
        "returns_terminal_status",
        "ignores_non_terminal_status",
        "handles_missing_payload",
    ],
)
def test_terminal_status_from_event(
    event: dict[str, object], expected: str | None
) -> None:
    assert runs_events._terminal_status_from_event(event) == expected


def test_terminal_status_from_run_returns_none_for_unknown_run(
    isolated_db: str,
) -> None:
    assert runs_events._terminal_status_from_run("nope") is None


def test_terminal_status_from_run_returns_none_for_active_run(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    assert runs_events._terminal_status_from_run(run.id) is None


def test_terminal_status_from_run_returns_terminal_status(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    runs.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)
    assert runs_events._terminal_status_from_run(run.id) == "completed"


def test_resolve_tick_terminal_prefers_event_terminal_status(
    isolated_db: str,
) -> None:
    assert (
        runs_events._resolve_tick_terminal("completed", "ignored-run", 3)
        == "completed"
    )


def test_resolve_tick_terminal_skips_run_query_on_non_safety_tick(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    runs.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)
    assert runs_events._resolve_tick_terminal(None, run.id, 3) is None


def test_resolve_tick_terminal_safety_net_queries_on_tenth_tick(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    runs.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)
    assert runs_events._resolve_tick_terminal(None, run.id, 9) == "completed"


def test_drain_tick_frames_returns_new_events_as_sse_frames(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    store_events.append_event(run.id, "log", {"i": 0}, db_path=isolated_db)
    seq1 = store_events.append_event(
        run.id, "log", {"i": 1}, db_path=isolated_db
    )

    last_seq, terminal, frames = runs_events._drain_tick_frames(run.id, 0)

    assert last_seq == seq1
    assert terminal is None
    assert len(frames) == 2
    assert all(f.startswith("data: ") for f in frames)


def test_drain_tick_frames_detects_terminal_status_event(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    seq = store_events.append_event(
        run.id, "status", {"status": "failed"}, db_path=isolated_db
    )

    last_seq, terminal, frames = runs_events._drain_tick_frames(run.id, 0)

    assert last_seq == seq
    assert terminal == "failed"
    assert len(frames) == 1


def test_stream_live_tail_returns_immediately_on_disconnect(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    request = _FakeRequest(disconnected=True)

    frames = _drain(
        runs_events._stream_live_tail(
            run.id,
            request,  # type: ignore[arg-type]
            0,
        )
    )
    assert frames == []


def test_stream_live_tail_ends_on_terminal_event(isolated_db: str) -> None:
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    seq = store_events.append_event(
        run.id, "status", {"status": "completed"}, db_path=isolated_db
    )
    request = _FakeRequest()

    frames = _drain(
        runs_events._stream_live_tail(
            run.id,
            request,  # type: ignore[arg-type]
            0,
        )
    )
    assert len(frames) == 2
    assert '"type": "status"' in frames[0]
    assert '"type": "_terminal"' in frames[1]
    assert f'"seq": {seq}' in frames[1]


def test_stream_live_tail_polls_to_a_cancelled_close(isolated_db: str) -> None:
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    store_events.append_event(
        run.id, "status", {"status": "cancelled"}, db_path=isolated_db
    )
    request = _FakeRequest()

    frames = _drain(
        runs_events._stream_live_tail(
            run.id,
            request,  # type: ignore[arg-type]
            0,
        )
    )
    assert any('"type": "_terminal"' in f for f in frames)
    assert any('"status": "cancelled"' in f for f in frames)


def test_event_stream_replays_history_then_terminal_for_finished_run(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    store_events.append_event(run.id, "log", {"i": 0}, db_path=isolated_db)
    runs.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)
    finished_run = runs.get_run(run.id, db_path=isolated_db)
    assert finished_run is not None
    request = _FakeRequest()

    frames = _drain(
        runs_events._event_stream(
            run.id,
            request,  # type: ignore[arg-type]
            0,
            finished_run,
        )
    )
    assert '"type": "log"' in frames[0]
    assert '"type": "_terminal"' in frames[-1]


def test_event_stream_falls_through_to_live_tail_for_active_run(
    isolated_db: str,
) -> None:
    # Append after streaming starts to exercise live-tail delivery rather than
    # replay of pre-existing history.
    run = runs.create_run(
        "g", "default", "mock", {}, RunCreateOptions(db_path=isolated_db)
    )
    request = _FakeRequest()

    async def _append_terminal_soon() -> None:
        await asyncio.sleep(0.05)
        store_events.append_event(
            run.id, "status", {"status": "cancelled"}, db_path=isolated_db
        )

    async def _run() -> list[str]:
        appender = asyncio.create_task(_append_terminal_soon())
        try:
            return [
                frame
                async for frame in runs_events._event_stream(
                    run.id,
                    request,  # type: ignore[arg-type]
                    0,
                    run,
                )
            ]
        finally:
            await appender

    frames = asyncio.run(_run())
    assert any('"type": "_terminal"' in f for f in frames)
    assert any('"status": "cancelled"' in f for f in frames)


def test_events_endpoint_serves_json_snapshot_when_stream_false(
    isolated_db: str,
) -> None:
    from tests._client import DEFAULT_TEST_CLIENT_ID, make_client

    run = runs.create_run(
        "JSON events goal",
        "default",
        "mock",
        {},
        RunCreateOptions(client_id=DEFAULT_TEST_CLIENT_ID, db_path=isolated_db),
    )
    store_events.append_event(run.id, "lifecycle", {"event": "created"})
    store_events.append_event(run.id, "status", {"status": "running"})

    client = make_client()
    res = client.get(f"/api/runs/{run.id}/events?stream=false")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    events = res.json()["events"]
    assert [e["type"] for e in events] == ["lifecycle", "status"]
    assert events[0]["seq"] == 1
    assert events[1]["payload"] == {"status": "running", "activity": "other"}

    after = client.get(f"/api/runs/{run.id}/events?stream=false&after=1")
    assert [e["seq"] for e in after.json()["events"]] == [2]


_OWNER = {"X-Client-ID": "pause-cohort-owner"}


def _owned_running_run(db_path: str) -> tuple[TestClient, str]:
    client = make_client()
    created = client.post(
        "/api/runs",
        headers=_OWNER,
        json={
            "research_goal": "Pause a durable engine cohort",
            "tier": "express",
        },
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    runs.update_run_status(run_id, RunStatus.RUNNING, db_path=db_path)
    return client, run_id


def _leased_supervisor(
    run_id: str, db_path: str
) -> tuple[dict[str, Any], int, ScientificTask]:
    state = _task_state(run_id)
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    writer = store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}supervisor",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="pause-cohort:supervisor",
        ),
        db_path=db_path,
    )
    leased = store.claim_task(
        "pause-cohort-writer", run_id=run_id, db_path=db_path
    )
    assert leased is not None and leased.id == writer.id
    return state, checkpoint_seq, leased


async def _complete_supervisor_after_pause(
    client: TestClient,
    run_id: str,
    writer: tuple[dict[str, Any], int, ScientificTask],
    db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, checkpoint_seq, leased = writer
    monkeypatch.setattr(
        engine_tasks_node,
        "_prepare_node_task",
        lambda *_: (
            state,
            TaskCommit(leased, checkpoint_seq, db_path),
            "supervisor",
        ),
    )

    async def execute_node(
        _name: str, node_state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        return {**node_state, "committed_after_pause": True}, "generate"

    from co_scientist import task_runtime

    monkeypatch.setattr(task_runtime, "execute_task_node", execute_node)
    commit_node_result = engine_tasks_node._commit_node_result

    async def pause_then_commit(
        commit: TaskCommit,
        run: RunRow,
        node_name: str,
        committed: dict[str, Any],
        successor: str | None,
    ) -> dict[str, Any]:
        response = client.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "paused"
        return await commit_node_result(
            commit, run, node_name, committed, successor
        )

    monkeypatch.setattr(
        engine_tasks_node, "_commit_node_result", pause_then_commit
    )
    result = await engine_tasks.execute_node_task(leased, db_path=db_path)
    assert result["status"] == "paused"
    assert lifecycle.complete_task(
        leased.id, "pause-cohort-writer", result, db_path=db_path
    )


@pytest.mark.asyncio
async def test_owned_pause_fences_late_checkpoint_successor_until_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id = _owned_running_run(isolated_db)
    writer = _leased_supervisor(run_id, isolated_db)
    _, checkpoint_seq, leased = writer
    await _complete_supervisor_after_pause(
        client,
        run_id,
        writer,
        isolated_db,
        monkeypatch,
    )

    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["seq"] == checkpoint_seq + 1
    assert checkpoint["stage"] == f"engine_task_paused:{leased.id}"
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}generate"
    assert checkpoint["state"]["resume_successor"] == successor_type

    successor = store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=successor_type,
            inputs={"checkpoint_seq": checkpoint["seq"]},
            idempotency_key=f"{successor_type}:after:{leased.id}",
            dependencies=(leased.id,),
            provenance={"scheduled_by": leased.task_type},
        ),
        db_path=isolated_db,
    )
    queued_successor = store.get_task(successor.id, db_path=isolated_db)
    paused_run = runs.get_run(run_id, db_path=isolated_db)
    assert (
        paused_run is not None and paused_run.status == RunStatus.PAUSED.value
    )
    assert queued_successor is not None and queued_successor.status == "queued"
    assert (
        store.claim_task(
            "claim-late-queued-successor",
            run_id=run_id,
            db_path=isolated_db,
        )
        is None
    )
    claimable, active, _parked_until = lifecycle.cohort_poll(
        run_id, db_path=isolated_db
    )
    assert not claimable and not active

    resumed = client.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    task_ids = [task.id for task in tasks]
    assert len(task_ids) == len(set(task_ids))
    assert len(task_ids) == 2
    assert set(task_ids) == {leased.id, successor.id}
    assert (
        sum(
            task.idempotency_key == f"{successor_type}:after:{leased.id}"
            for task in tasks
        )
        == 1
    )

    claimed = store.claim_task(
        "claim-after-resume", run_id=run_id, db_path=isolated_db
    )
    assert claimed is not None and claimed.id == successor.id
    assert claimed.task_type == successor_type
    assert claimed.inputs["checkpoint_seq"] == checkpoint["seq"]
    assert claimed.dependencies == (leased.id,)
    assert (
        store.claim_task(
            "claim-after-resume-again", run_id=run_id, db_path=isolated_db
        )
        is None
    )

    events = store_events.list_events(run_id, db_path=isolated_db)
    pause = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
    )
    completion = next(
        event
        for event in events
        if event["type"] == "scientific_task"
        and event["payload"].get("task") == "supervisor"
        and event["payload"].get("status") == "completed"
    )
    resuming = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "resuming"
    )
    assert pause["seq"] < completion["seq"] < resuming["seq"]
    assert not any(
        pause["seq"] < event["seq"] < resuming["seq"]
        and event["payload"].get("status") == "running"
        for event in events
    )


_OLD_OWNER = "pre-restart-worker"


@dataclass
class _StartupProbe:
    recovery_finished: Event = field(default_factory=Event)
    worker_started: Event = field(default_factory=Event)
    task_scans: list[list[str]] = field(default_factory=list)
    cohort_run_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _PausedRestart:
    run_id: str
    writer_id: str
    successor_id: str
    paused_seq: int


def _seed_paused_restart(db_path: str) -> _PausedRestart:
    run = runs.create_run(
        "Pause restart acceptance",
        "express",
        "engine",
        {},
        RunCreateOptions(client_id=DEFAULT_TEST_CLIENT_ID, db_path=db_path),
    )
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=db_path)
    writer = store.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause-restart:writer",
        ),
        db_path=db_path,
    )
    claimed = store.claim_task(
        _OLD_OWNER, run_id=run.id, lease_seconds=3600, db_path=db_path
    )
    assert claimed is not None and claimed.id == writer.id
    successor_id, paused_seq = _append_late_successor(run.id, writer, db_path)
    return _PausedRestart(run.id, writer.id, successor_id, paused_seq)


def _append_late_successor(
    run_id: str, writer: ScientificTask, db_path: str
) -> tuple[str, int]:
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    runs.update_run_status(run_id, RunStatus.PAUSED, db_path=db_path)
    paused_seq = store_events.append_event(
        run_id, "status", {"status": "paused"}, db_path=db_path
    )
    checkpoint_seq = checkpoints.save_checkpoint(
        run_id,
        NewCheckpoint(
            stage=f"engine_task_paused:{writer.id}",
            schema_version=1,
            last_event_seq=paused_seq,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=db_path,
    )
    successor = store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=successor_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{successor_type}:after:{writer.id}",
            dependencies=(writer.id,),
            provenance={"scheduled_by": writer.task_type},
        ),
        db_path=db_path,
    )
    return successor.id, paused_seq


def _observe_startup(monkeypatch: pytest.MonkeyPatch) -> _StartupProbe:
    from app import main as main_module

    probe = _StartupProbe()
    original_start = main_module._start_recovery_task
    original_scan = store.list_active_engine_task_run_ids

    async def no_seed() -> None:
        return None

    def start_recovery(
        reconciled: dict[str, list[str]],
    ) -> tuple[asyncio.Task[None], list[asyncio.Task[None]]]:
        recovery, workers = original_start(reconciled)
        recovery.add_done_callback(lambda _: probe.recovery_finished.set())
        return recovery, workers

    def scan_active(db_path: str | None = None) -> list[str]:
        run_ids = original_scan(db_path)
        probe.task_scans.append(run_ids)
        return run_ids

    def record_cohort(run_id: str, _worker_id: str) -> None:
        probe.cohort_run_ids.append(run_id)
        probe.worker_started.set()

    monkeypatch.setattr(main_module, "seed_demo_runs", no_seed)
    monkeypatch.setattr(main_module, "_start_recovery_task", start_recovery)
    monkeypatch.setattr(store, "list_active_engine_task_run_ids", scan_active)
    monkeypatch.setattr(task_worker, "run_run_worker_pool_sync", record_cohort)
    return probe


def _assert_startup_left_run_paused(
    probe: _StartupProbe,
    state: _PausedRestart,
    db_path: str,
) -> None:
    assert probe.recovery_finished.wait(5), "startup recovery did not finish"
    assert probe.task_scans
    assert all(state.run_id not in run_ids for run_ids in probe.task_scans)
    assert probe.cohort_run_ids == []
    run = runs.get_run(state.run_id, db_path=db_path)
    writer = store.get_task(state.writer_id, db_path=db_path)
    successor = store.get_task(state.successor_id, db_path=db_path)
    assert run is not None and run.status == RunStatus.PAUSED.value
    assert writer is not None and writer.status == "leased"
    assert successor is not None and successor.status == "queued"
    assert (
        store.claim_task(
            "before-explicit-resume", run_id=state.run_id, db_path=db_path
        )
        is None
    )


def _assert_resume_reuses_successor(
    client: TestClient,
    probe: _StartupProbe,
    state: _PausedRestart,
    db_path: str,
) -> None:
    before = store.list_tasks(state.run_id, db_path=db_path)
    before_ids = {task.id for task in before}
    assert before_ids == {state.writer_id, state.successor_id}
    response = client.post(f"/api/runs/{state.run_id}/resume")
    assert response.status_code == 200, response.text
    assert probe.worker_started.wait(5), "explicit resume did not launch"
    assert probe.cohort_run_ids == [state.run_id]
    after = store.list_tasks(state.run_id, db_path=db_path)
    assert {task.id for task in after} == before_ids
    successors = [
        task
        for task in after
        if task.task_type == f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    ]
    assert len(successors) == 1 and successors[0].id == state.successor_id
    assert successors[0].dependencies == (state.writer_id,)
    assert lifecycle.complete_task(
        state.writer_id, _OLD_OWNER, {}, db_path=db_path
    )
    claimed = store.claim_task(
        "after-explicit-resume", run_id=state.run_id, db_path=db_path
    )
    assert claimed is not None and claimed.id == state.successor_id
    _assert_ordered_event_replay(client, state.run_id, state.paused_seq)


def _assert_ordered_event_replay(
    client: TestClient, run_id: str, paused_seq: int
) -> None:
    events = client.get(f"/api/runs/{run_id}/events?stream=false").json()[
        "events"
    ]
    seqs = [event["seq"] for event in events]
    assert all(left < right for left, right in pairwise(seqs))
    paused = next(event for event in events if event["seq"] == paused_seq)
    assert paused["type"] == "status"
    assert paused["payload"]["status"] == "paused"
    replay = client.get(
        f"/api/runs/{run_id}/events?stream=false&after={paused_seq}"
    ).json()["events"]
    assert replay == [event for event in events if event["seq"] > paused_seq]
    assert [event["payload"].get("status") for event in replay] == ["resuming"]


def test_restart_keeps_paused_successor_idle_until_explicit_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", True)
    restart = _seed_paused_restart(isolated_db)
    probe = _observe_startup(monkeypatch)
    with make_client() as client:
        _assert_startup_left_run_paused(probe, restart, isolated_db)
        _assert_resume_reuses_successor(client, probe, restart, isolated_db)

"""Start and restart admission races at the durable run boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app import engine_tasks, store
from app.config import settings
from tests._client import make_client as _client


def _new_run(c: TestClient, goal: str, *, tier: str = "express") -> str:
    response = c.post("/api/runs", json={"research_goal": goal, "tier": tier})
    return cast(str, response.json()["id"])


def test_cancel_after_capacity_reservation_prevents_bootstrap_admission(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A start transaction orders admission before a waiting cancellation."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    start_client = _client()
    cancel_client = _client()
    rid = _new_run(start_client, "Cancel between start admission steps")
    capacity_reserved = Event()
    cancel_entered_transaction = Event()
    continue_start = Event()
    reserve_capacity = store.reserve_run_capacity_in_transaction
    cancel_tasks = store.cancel_run_tasks

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
        store, "reserve_run_capacity_in_transaction", reserve_then_wait
    )
    monkeypatch.setattr(store, "cancel_run_tasks", observe_cancel_tasks)
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
            # If cancellation enters its transaction before admission releases
            # the lock, the old split reservation/enqueue design is exposed.
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
    events = store.list_events(rid, db_path=isolated_db)
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
    """A stale start read cannot reinterpret its cancelled run as restart."""
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
    events = store.list_events(rid, db_path=isolated_db)
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
    """A deliberate restart revives the existing bootstrap task row."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Restart a cancelled bootstrap")

    started = client.post(f"/api/runs/{rid}/start", json={})
    assert started.status_code == 200
    [bootstrap] = store.list_tasks(rid, db_path=isolated_db)
    assert bootstrap.status == "queued"
    queued_run = store.get_run(rid, db_path=isolated_db)
    assert queued_run is not None and queued_run.status == "queued"

    cancelled = client.post(f"/api/runs/{rid}/cancel")
    assert cancelled.status_code == 200
    cancelled_task = store.get_task(bootstrap.id, db_path=isolated_db)
    assert cancelled_task is not None and cancelled_task.status == "cancelled"
    events = store.list_events(rid, db_path=isolated_db)
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
    """A cancelled progressed run rejects fresh start and offers resume."""
    from app.store import RunStatus
    from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Continue a cancelled checkpoint")
    _seed_checkpoint(rid, _task_state(rid), db_path=isolated_db)
    store.update_run_status(rid, RunStatus.RUNNING, db_path=isolated_db)
    assert client.post(f"/api/runs/{rid}/cancel").status_code == 200

    restart = client.post(f"/api/runs/{rid}/start", json={})

    assert restart.status_code == 409
    assert "use /resume" in restart.json()["detail"]
    cancelled_run = store.get_run(rid, db_path=isolated_db)
    assert cancelled_run is not None and cancelled_run.status == "cancelled"
    assert store.list_tasks(rid, db_path=isolated_db) == []

    resumed = client.post(f"/api/runs/{rid}/resume")

    assert resumed.status_code == 200
    assert store.get_run(rid, db_path=isolated_db).status == "queued"  # type: ignore[union-attr]
    [task] = store.list_tasks(rid, db_path=isolated_db)
    assert task.task_type == "engine.node.orchestrator"
    assert task.status == "queued"


def test_failed_run_with_checkpoint_uses_resume(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.store import RunStatus
    from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Resume a failed checkpoint")
    _seed_checkpoint(rid, _task_state(rid), db_path=isolated_db)
    store.update_run_status(rid, RunStatus.FAILED, db_path=isolated_db)

    restart = client.post(f"/api/runs/{rid}/start", json={})

    assert restart.status_code == 409
    assert "use /resume" in restart.json()["detail"]
    resumed = client.post(f"/api/runs/{rid}/resume")
    assert resumed.status_code == 200
    run = store.get_run(rid, db_path=isolated_db)
    assert run is not None and run.status == "queued"


def test_blocked_bootstrap_without_checkpoint_requires_new_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A succeeded, checkpoint-free safety block is never revived as queued."""
    from app.store import RunStatus

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Do not revive an intake block")
    assert client.post(f"/api/runs/{rid}/start", json={}).status_code == 200
    task = store.claim_task("blocked-bootstrap", run_id=rid)
    assert task is not None
    assert store.complete_task(
        task.id,
        "blocked-bootstrap",
        {"status": "withheld"},
        db_path=isolated_db,
    )
    store.update_run_status(rid, RunStatus.BLOCKED, db_path=isolated_db)

    restart = client.post(f"/api/runs/{rid}/start", json={})

    assert restart.status_code == 409
    assert "create a new run" in restart.json()["detail"]
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None and saved.status == "completed"


def test_blocked_run_with_completed_finalize_requires_new_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed finalize row must not make blocked /start look resumable."""
    from app.store import RunStatus
    from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Do not revive a blocked finalize")
    predecessor = store.enqueue_task(
        store.NewTask(
            run_id=rid,
            task_type="engine.node.orchestrator",
            inputs={},
            idempotency_key="previous-orchestrator",
        ),
        db_path=isolated_db,
    )
    previous = store.claim_task("previous-worker", run_id=rid)
    assert previous is not None and previous.id == predecessor.id
    assert store.complete_task(
        previous.id, "previous-worker", {}, db_path=isolated_db
    )
    state = _task_state(rid)
    checkpoint_seq = _seed_checkpoint(
        rid, state, stage=f"engine_task:{previous.id}", db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(rid, db_path=isolated_db)
    assert checkpoint is not None
    checkpoint_seq = store.save_checkpoint(
        rid,
        store.NewCheckpoint(
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
        store.NewTask(
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
    assert store.complete_task(
        finalizer.id, "finalize-worker", {}, db_path=isolated_db
    )
    store.update_run_status(rid, RunStatus.BLOCKED, db_path=isolated_db)

    response = client.post(f"/api/runs/{rid}/start", json={})

    assert response.status_code == 409
    assert "create a new run" in response.json()["detail"]
    saved = store.get_task(finalizer.id, db_path=isolated_db)
    assert saved is not None and saved.status == "completed"


def test_start_rolls_back_capacity_when_bootstrap_enqueue_fails(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quota reservation and durable admission share one transaction."""
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Rollback an incomplete start")

    def fail_enqueue(*_: object, **__: object) -> object:
        raise HTTPException(status_code=503, detail="injected enqueue failure")

    monkeypatch.setattr(engine_tasks, "enqueue_bootstrap", fail_enqueue)
    response = client.post(f"/api/runs/{rid}/start", json={})

    assert response.status_code == 503
    run = store.get_run(rid, db_path=isolated_db)
    assert run is not None and run.status == "draft"
    assert store.list_tasks(rid, db_path=isolated_db) == []
    assert not any(
        event["type"] == "lifecycle"
        and event["payload"].get("event") == "queued"
        for event in store.list_events(rid, db_path=isolated_db)
    )


def test_cancelled_paused_bootstrap_can_be_explicitly_restarted(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling a paused pre-bootstrap run makes its task revivable."""
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

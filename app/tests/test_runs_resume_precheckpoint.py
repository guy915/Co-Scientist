"""Resume the bootstrap lease when pause races its first checkpoint."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import settings
from tests._client import make_client


def _started_bootstrap(
    client: TestClient, goal: str, db: str
) -> tuple[str, str]:
    run = client.post(
        "/api/runs", json={"research_goal": goal, "tier": "express"}
    )
    run_id = str(run.json()["id"])
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    [bootstrap] = store.list_tasks(run_id, db_path=db)
    claimed = store.claim_task("bootstrap-owner", run_id=run_id, db_path=db)
    assert claimed is not None and claimed.id == bootstrap.id
    return run_id, bootstrap.id


@pytest.mark.parametrize(
    "lease_state", ["live", "expired_retryable", "expired_spent"]
)
def test_resume_reuses_precheckpoint_bootstrap_lease(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    lease_state: str,
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, task_id = _started_bootstrap(
        client, f"Resume {lease_state} bootstrap", isolated_db
    )
    original = store.get_task(task_id, db_path=isolated_db)
    assert original is not None
    lease_expiry = time.time() + 3600
    if lease_state != "live":
        lease_expiry = time.time() - 3600
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=?, "
            "attempt=CASE WHEN ? THEN max_attempts ELSE attempt END WHERE id=?",
            (lease_expiry, int(lease_state == "expired_spent"), task_id),
        )

    paused = client.post(f"/api/runs/{run_id}/pause")
    assert paused.status_code == 200
    paused_run = store.get_run(run_id, db_path=isolated_db)
    assert paused_run is not None and paused_run.status == "paused"
    assert not store.has_checkpoint(run_id, db_path=isolated_db)

    resumed = client.post(f"/api/runs/{run_id}/resume")

    assert resumed.status_code == 200, resumed.text
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "queued"
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert len(tasks) == 1 and tasks[0].id == task_id
    assert tasks[0].task_type == "engine.bootstrap"
    if lease_state == "live":
        assert tasks[0].status == "leased"
        assert tasks[0].lease_owner == "bootstrap-owner"
        assert (
            store.claim_task(
                "second-worker", run_id=run_id, db_path=isolated_db
            )
            is None
        )
    elif lease_state == "expired_retryable":
        assert tasks[0].status == "leased"
        assert tasks[0].lease_owner == "bootstrap-owner"
    else:
        assert tasks[0].status == "queued"
        assert tasks[0].attempt == 0
        reclaimed = store.claim_task(
            "second-worker", run_id=run_id, db_path=isolated_db
        )
        assert reclaimed is not None and reclaimed.id == task_id
        assert reclaimed.lease_owner == "second-worker"
        assert reclaimed.attempt == (
            1 if lease_state == "expired_spent" else original.attempt + 1
        )
    events = store.list_events(run_id, db_path=isolated_db)
    assert (
        sum(
            event["type"] == "status"
            and event["payload"].get("status") == "resuming"
            for event in events
        )
        == 1
    )


def test_precheckpoint_resume_keeps_owner_and_cancellation_precedence(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    run_id, task_id = _started_bootstrap(
        owner, "Owner-scoped bootstrap resume", isolated_db
    )
    assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200
    foreign = make_client()
    assert (
        foreign.post(
            f"/api/runs/{run_id}/resume",
            headers={"X-Client-ID": "other-client"},
        ).status_code
        == 404
    )
    assert owner.post(f"/api/runs/{run_id}/cancel").status_code == 200

    rejected = owner.post(f"/api/runs/{run_id}/resume")

    assert rejected.status_code == 409
    cancelled_run = store.get_run(run_id, db_path=isolated_db)
    assert cancelled_run is not None and cancelled_run.status == "cancelled"
    task = store.get_task(task_id, db_path=isolated_db)
    assert task is not None and task.status == "cancelled"
    assert not any(
        event["type"] == "status"
        and event["payload"].get("status") == "resuming"
        for event in store.list_events(run_id, db_path=isolated_db)
    )


def test_resume_recovers_spent_bootstrap_abandoned_after_pause(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, task_id = _started_bootstrap(
        client, "Recover paused bootstrap", isolated_db
    )
    task = store.get_task(task_id, db_path=isolated_db)
    assert task is not None
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0, "
            "attempt=max_attempts "
            "WHERE id=?",
            (task_id,),
        )
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run_id,
            stage="intake",
            decision="allow",
            reason="intake audit",
            matches=[],
        ),
        db_path=isolated_db,
    )
    assert client.post(f"/api/runs/{run_id}/pause").status_code == 200
    assert store.abandon_dead_leases(run_id, db_path=isolated_db) == 1
    paused = store.get_run(run_id, db_path=isolated_db)
    assert paused is not None and paused.status == "paused"
    abandoned = store.get_task(task_id, db_path=isolated_db)
    assert abandoned is not None and abandoned.status == "failed"

    resumed = client.post(f"/api/runs/{run_id}/resume")

    assert resumed.status_code == 200, resumed.text
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "queued"
    [reused] = store.list_tasks(run_id, db_path=isolated_db)
    assert reused.id == task_id and reused.task_type == "engine.bootstrap"
    assert reused.status == "queued" and reused.attempt == 0
    assert (
        store.list_safety_decisions(run_id, db_path=isolated_db)[0]["reason"]
        == "intake audit"
    )
    reclaimed = store.claim_task(
        "bootstrap-recovery", run_id=run_id, db_path=isolated_db
    )
    assert reclaimed is not None and reclaimed.id == task_id


def test_failed_precheckpoint_bootstrap_without_pause_is_not_resumable(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, task_id = _started_bootstrap(
        client, "Do not revive an ordinary failure", isolated_db
    )
    assert store.fail_task(
        task_id,
        "bootstrap-owner",
        "permanent failure",
        retryable=False,
        db_path=isolated_db,
    )

    response = client.post(f"/api/runs/{run_id}/resume")

    assert response.status_code == 409
    task = store.get_task(task_id, db_path=isolated_db)
    assert task is not None and task.status == "failed"


def test_cancelled_abandoned_bootstrap_is_not_resumable(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, task_id = _started_bootstrap(
        client, "Do not revive a cancelled paused bootstrap", isolated_db
    )
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0, "
            "attempt=max_attempts WHERE id=?",
            (task_id,),
        )
    assert client.post(f"/api/runs/{run_id}/pause").status_code == 200
    assert store.abandon_dead_leases(run_id, db_path=isolated_db) == 1
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200

    response = client.post(f"/api/runs/{run_id}/resume")

    assert response.status_code == 409
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "cancelled"
    task = store.get_task(task_id, db_path=isolated_db)
    assert task is not None and task.status == "failed"


def test_paused_permanent_bootstrap_failure_is_not_resumable(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, task_id = _started_bootstrap(
        client, "Do not retry a permanent paused bootstrap failure", isolated_db
    )
    assert client.post(f"/api/runs/{run_id}/pause").status_code == 200
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET attempt=max_attempts WHERE id=?",
            (task_id,),
        )
    assert store.fail_task(
        task_id,
        "bootstrap-owner",
        "permanent budget ceiling",
        retryable=False,
        db_path=isolated_db,
    )

    response = client.post(f"/api/runs/{run_id}/resume")

    assert response.status_code == 409
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "paused"
    task = store.get_task(task_id, db_path=isolated_db)
    assert task is not None and task.status == "failed"
    assert task.attempt == task.max_attempts
    assert task.error == "permanent budget ceiling"

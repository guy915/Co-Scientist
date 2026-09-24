"""Ambiguous LLM timeouts distinguish automatic and owner recovery."""

from __future__ import annotations

import json
from typing import Any

import pytest
from co_scientist.exceptions import LLMTimeoutError

from app import credentials, engine_tasks, store, task_worker
from app.config import settings
from app.store import db as store_db
from tests._client import DEFAULT_TEST_CLIENT_ID, make_client

_BYOK_SECRET = "synthetic-timeout-encryption-secret"
_BYOK_KEY = "sk-synthetic-ambiguous-timeout-12345"


@pytest.mark.asyncio
async def test_byok_timeout_waits_for_explicit_owner_restart(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lost BYOK response is persisted without automatic redelivery."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "byok_encryption_key", _BYOK_SECRET)
    accepted: list[int] = []

    async def accepted_then_lost(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        accepted.append(1)
        if len(accepted) == 1:
            raise LLMTimeoutError(
                "provider accepted the request but its response was lost"
            )
        return {"recovered_after_owner_restart": True}

    monkeypatch.setattr(
        engine_tasks, "_dispatch_engine_task", accepted_then_lost
    )

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "ambiguous BYOK timeout"}
        )
        assert created.status_code == 200
        run_id = created.json()["id"]
        credentials.store_run_credential(
            run_id,
            DEFAULT_TEST_CLIENT_ID,
            credentials.ByokCredential(
                provider="deepseek",
                api_key=_BYOK_KEY,
                model="deepseek/deepseek-v4-flash",
            ),
            db_path=isolated_db,
        )
        assert (
            client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
        )
        sibling = store.enqueue_task(
            store.NewTask(
                run_id=run_id,
                task_type="engine.node.generate",
                inputs={"checkpoint_seq": 0},
                idempotency_key="engine.node.generate:0",
            ),
            db_path=isolated_db,
        )
        assert await task_worker.run_once("timeout-worker", db_path=isolated_db)

    # The durable record survives reopening the owner API client.
    with make_client() as reopened:
        body = reopened.get(f"/api/runs/{run_id}").json()
        task_rows = reopened.get(f"/api/runs/{run_id}/tasks").json()["tasks"]
        task_by_id = {row["id"]: row for row in task_rows}
        task_row = next(
            row for row in task_rows if row["task_type"] == "engine.bootstrap"
        )
        assert body["status"] == "failed"
        assert body["failure_kind"] == "llm_timeout_unknown"
        assert task_row["status"] == "failed"
        assert len(task_row["attempts"]) == 1
        assert task_by_id[sibling.id]["status"] == "cancelled"
        assert not await task_worker.run_once(
            "timeout-worker", db_path=isolated_db
        )
        assert accepted == [1]

        # The existing owner action is the explicit acknowledgement to replay.
        assert (
            reopened.post(f"/api/runs/{run_id}/start", json={}).status_code
            == 200
        )
        assert await task_worker.run_once("timeout-worker", db_path=isolated_db)

    assert len(accepted) == 2


@pytest.mark.asyncio
async def test_expired_byok_lease_requires_owner_restart(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker crash cannot silently replay a persisted BYOK task."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "byok_encryption_key", _BYOK_SECRET)
    accepted = ["response lost with old worker"]

    async def _would_accept_again(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        accepted.append("replayed")
        return {"unexpected_replay": True}

    monkeypatch.setattr(
        engine_tasks, "_dispatch_engine_task", _would_accept_again
    )
    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "BYOK lease loss"}
        )
        run_id = created.json()["id"]
        credentials.store_run_credential(
            run_id,
            DEFAULT_TEST_CLIENT_ID,
            credentials.ByokCredential(
                provider="deepseek",
                api_key=_BYOK_KEY,
                model="deepseek/deepseek-v4-flash",
            ),
            db_path=isolated_db,
        )
        store.update_run_status(
            run_id, store.RunStatus.RUNNING, db_path=isolated_db
        )
        store.save_checkpoint(
            run_id,
            store.NewCheckpoint(
                stage="post_generation",
                schema_version=1,
                last_event_seq=1,
                state={
                    "provider": "engine",
                    "resume_successor": "engine.node.generate",
                },
            ),
            db_path=isolated_db,
        )
        target = store.enqueue_task(
            store.NewTask(
                run_id=run_id,
                task_type="engine.node.generate",
                inputs={"checkpoint_seq": 1},
                idempotency_key="engine.node.generate:1",
            ),
            db_path=isolated_db,
        )
        sibling = store.enqueue_task(
            store.NewTask(
                run_id=run_id,
                task_type="engine.node.verify",
                inputs={"checkpoint_seq": 1},
                idempotency_key="engine.node.verify:1",
            ),
            db_path=isolated_db,
        )
        leased = store.claim_task(
            "old-worker",
            run_id=run_id,
            lease_seconds=1,
            db_path=isolated_db,
        )
        assert leased is not None and leased.id == target.id
    # Model a worker that died after provider acceptance but before it wrote
    # any task outcome. Startup reconciliation must fail the run before it
    # can auto-resume the checkpoint or dispatch the queued sibling.
    now = store_db._now()
    monkeypatch.setattr("app.store.db.time.time", lambda: now + 2)

    with make_client() as reopened:
        body = reopened.get(f"/api/runs/{run_id}").json()
        task_rows = reopened.get(f"/api/runs/{run_id}/tasks").json()["tasks"]
        task_by_id = {row["id"]: row for row in task_rows}
        assert body["status"] == "failed"
        assert body["failure_kind"] == "llm_timeout_unknown"
        assert task_by_id[target.id]["status"] == "failed"
        assert task_by_id[sibling.id]["status"] == "cancelled"
        assert accepted == ["response lost with old worker"]

        with store.connect(isolated_db) as conn:
            events = conn.execute(
                "SELECT payload_json FROM run_events "
                "WHERE run_id=? AND type='status'",
                (run_id,),
            ).fetchall()
        failed_events = [
            json.loads(row["payload_json"])
            for row in events
            if json.loads(row["payload_json"]).get("status") == "failed"
        ]
        assert len(failed_events) == 1
        assert failed_events[0]["failure_kind"] == "llm_timeout_unknown"

        # The persisted checkpoint remains available, but replay is an
        # explicit owner action and the existing resume path revives it.
        assert reopened.post(f"/api/runs/{run_id}/resume").status_code == 200
        assert await task_worker.run_once("owner-retry", db_path=isolated_db)

    assert accepted == ["response lost with old worker", "replayed"]


@pytest.mark.asyncio
async def test_expired_lease_fails_closed_after_paid_to_free_route_change(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Current free settings cannot prove an orphaned lease was free."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    paid_route = "openrouter/provider/paid-model"
    free_route = "openrouter/nex-agi/nex-n2.5-pro:free"
    monkeypatch.setattr(settings, "model_name", paid_route)
    monkeypatch.setattr(settings, "supervisor_model_name", paid_route)
    monkeypatch.setattr(settings, "chat_model_name", paid_route)
    monkeypatch.setattr(settings, "semantic_safety_model", paid_route)

    dispatches: list[str] = []

    async def _dispatch_after_owner_resume(
        task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        dispatches.append(task.task_type)
        return {"owner_replay": True}

    monkeypatch.setattr(
        engine_tasks, "_dispatch_engine_task", _dispatch_after_owner_resume
    )

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "route changed after lease"}
        )
        run_id = created.json()["id"]
        store.update_run_status(
            run_id, store.RunStatus.RUNNING, db_path=isolated_db
        )
        store.save_checkpoint(
            run_id,
            store.NewCheckpoint(
                stage="post_generation",
                schema_version=1,
                last_event_seq=1,
                state={
                    "provider": "engine",
                    "resume_successor": "engine.node.generate",
                },
            ),
            db_path=isolated_db,
        )
        target = store.enqueue_task(
            store.NewTask(
                run_id=run_id,
                task_type="engine.node.generate",
                inputs={"checkpoint_seq": 1},
                idempotency_key="engine.node.generate:1",
            ),
            db_path=isolated_db,
        )
        sibling = store.enqueue_task(
            store.NewTask(
                run_id=run_id,
                task_type="engine.node.verify",
                inputs={"checkpoint_seq": 1},
                idempotency_key="engine.node.verify:1",
            ),
            db_path=isolated_db,
        )
        leased = store.claim_task(
            "paid-route-worker",
            run_id=run_id,
            lease_seconds=30,
            db_path=isolated_db,
        )
        assert leased is not None and leased.id == target.id
        with store.connect(isolated_db) as conn:
            conn.execute(
                "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
                (target.id,),
            )

    # The prior worker may have sent a paid request. A rolling deployment
    # changes current settings before startup, but the task has no durable
    # record of its original route or exact-zero admission result.
    monkeypatch.setattr(settings, "model_name", free_route)
    monkeypatch.setattr(
        settings,
        "supervisor_model_name",
        free_route,
    )
    monkeypatch.setattr(settings, "chat_model_name", free_route)
    monkeypatch.setattr(settings, "semantic_safety_model", free_route)

    with make_client() as restarted:
        body = restarted.get(f"/api/runs/{run_id}").json()
        task_rows = restarted.get(f"/api/runs/{run_id}/tasks").json()["tasks"]
        task_by_id = {row["id"]: row for row in task_rows}
        assert body["status"] == "failed"
        assert body["failure_kind"] == "llm_timeout_unknown"
        assert task_by_id[target.id]["status"] == "failed"
        assert task_by_id[sibling.id]["status"] == "cancelled"

        with store.connect(isolated_db) as conn:
            events = conn.execute(
                "SELECT payload_json FROM run_events "
                "WHERE run_id=? AND type='status'",
                (run_id,),
            ).fetchall()
        failed_events = [
            json.loads(row["payload_json"])
            for row in events
            if json.loads(row["payload_json"]).get("status") == "failed"
        ]
        assert len(failed_events) == 1
        assert failed_events[0]["failure_kind"] == "llm_timeout_unknown"
        assert not await task_worker.run_once(
            "unacknowledged-worker", db_path=isolated_db
        )
        assert dispatches == []

        # Owner acknowledgement keeps the existing explicit recovery path.
        assert restarted.post(f"/api/runs/{run_id}/resume").status_code == 200
        assert await task_worker.run_once("owner-resume", db_path=isolated_db)

    assert dispatches == ["engine.node.generate"]


@pytest.mark.asyncio
async def test_expired_nonfree_system_route_requires_owner_recovery(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A no-BYOK run is not assumed free when its model route is paid."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "model_name", "openrouter/provider/model")
    accepted: list[str] = []

    async def _must_not_call(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        accepted.append("provider call")
        return {"unexpected_replay": True}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", _must_not_call)
    run = store.create_run("Paid route lease loss", "standard", "engine", {})
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task(
        "old-paid-worker", run_id=run.id, lease_seconds=1, db_path=isolated_db
    )
    assert leased is not None
    now = store_db._now()
    monkeypatch.setattr("app.store.db.time.time", lambda: now + 2)

    assert not await task_worker.run_once(
        "new-paid-worker", db_path=isolated_db
    )
    failed = store.get_task(task.id, db_path=isolated_db)
    assert failed is not None and failed.status == "failed"
    assert accepted == []


@pytest.mark.asyncio
async def test_exact_zero_cost_timeout_uses_bounded_delayed_retry(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only request-time exact-zero admission may authorize auto-retry."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    accepted: list[int] = []

    async def _timeout_once(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        accepted.append(1)
        if len(accepted) == 1:
            raise LLMTimeoutError(
                "provider outcome may be unknown", zero_cost_admitted=True
            )
        return {"recovered": True}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", _timeout_once)
    run = store.create_run("Exact free timeout", "standard", "engine", {})
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
        ),
        db_path=isolated_db,
    )

    assert await task_worker.run_once(
        "free-timeout-worker", db_path=isolated_db
    )
    queued = store.get_task(task.id, db_path=isolated_db)
    assert queued is not None and queued.status == "queued"
    assert queued.attempt == 1
    assert (
        queued.available_at is not None
        and queued.available_at > store_db._now()
    )
    assert not await task_worker.run_once(
        "free-timeout-worker", db_path=isolated_db
    )
    assert accepted == [1]

    monkeypatch.setattr(
        "app.store.db.time.time", lambda: queued.available_at + 1
    )
    assert await task_worker.run_once(
        "free-timeout-worker", db_path=isolated_db
    )
    completed = store.get_task(task.id, db_path=isolated_db)
    assert completed is not None and completed.status == "completed"
    assert accepted == [1, 1]

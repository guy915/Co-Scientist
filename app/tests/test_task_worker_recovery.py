from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import pytest
from co_scientist.exceptions import LLMTimeoutError

from app import credentials, engine_tasks, store, task_worker
from app.config import settings
from app.store import RunStatus, ScientificTask
from app.store import db as store_db
from tests._client import DEFAULT_TEST_CLIENT_ID, make_client


def _mark_leased(
    task_id: str,
    db: str,
    *,
    owner: str,
    expires_at: float,
    spend_budget: bool,
) -> None:
    extra = ", attempt=max_attempts" if spend_budget else ""
    with store.connect(db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner=?, "
            f"lease_expires_at=?{extra} WHERE id=?",
            (owner, expires_at, task_id),
        )


def _commit_checkpoint_successor(
    db: str, run_id: str, writer: ScientificTask, successor_type: str
) -> None:
    with store.transaction(db) as conn:
        checkpoint_seq = store.save_checkpoint(
            run_id,
            store.NewCheckpoint(
                stage=f"engine_task:{writer.id}",
                schema_version=1,
                last_event_seq=2,
                state={"resume_successor": successor_type},
            ),
            conn=conn,
        )
        store.enqueue_task(
            store.NewTask(
                run_id=run_id,
                task_type=successor_type,
                inputs={"checkpoint_seq": checkpoint_seq},
                idempotency_key=f"{successor_type}:after:{writer.id}",
                dependencies=(writer.id,),
                provenance={"scheduled_by": writer.task_type},
            ),
            conn=conn,
        )
    assert store.complete_task(writer.id, "ranking-worker", {}, db_path=db)


@dataclass
class _CheckpointReadInterleaver:
    original_get: Callable[..., dict[str, Any] | None]
    old_checkpoint: dict[str, Any]
    run_id: str
    db: str
    writer: ScientificTask
    successor_type: str
    pool: ThreadPoolExecutor
    future: Future[None] | None = None
    reads: int = 0

    def __call__(
        self,
        check_run_id: str,
        db_path: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        checkpoint = self.original_get(check_run_id, db_path=db_path, conn=conn)
        if check_run_id != self.run_id:
            return checkpoint
        self.reads += 1
        if self.reads == 1:
            self._start_commit(conn)
        if conn is None and self.reads > 1:
            return self.old_checkpoint
        return checkpoint

    def _start_commit(self, conn: sqlite3.Connection | None) -> None:
        self.future = self.pool.submit(
            _commit_checkpoint_successor,
            self.db,
            self.run_id,
            self.writer,
            self.successor_type,
        )
        if conn is None:
            self.future.result(timeout=5)
        else:
            time.sleep(0.05)

    def wait_for_writer(self) -> None:
        assert self.future is not None
        self.future.result(timeout=5)


def test_resume_reuses_live_checkpoint_writer_lease(
    isolated_db: str,
) -> None:
    run = store.create_run("paused live commit", "standard", "engine", {})
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:ranking-parent",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        task.id,
        isolated_db,
        owner="still-running",
        expires_at=time.time() + 3600,
        spend_budget=False,
    )
    store.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task:{task.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=isolated_db,
    )
    child = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=successor_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{successor_type}:after:{task.id}",
            dependencies=(task.id,),
            provenance={"scheduled_by": "engine.node.generate"},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.id == child.id
    assert resumed.dependencies == (task.id,)
    assert not store.claim_task(
        "early-child", run_id=run.id, db_path=isolated_db
    )
    assert store.complete_task(
        task.id, "still-running", {}, db_path=isolated_db
    )
    claimed_child = store.claim_task(
        "child-worker", run_id=run.id, db_path=isolated_db
    )
    assert claimed_child is not None and claimed_child.id == child.id


def test_resume_paused_stage_reuses_recorded_successor_not_writer(
    isolated_db: str,
) -> None:
    run = store.create_run("paused checkpoint", "standard", "engine", {})
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    writer = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:paused-writer",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        writer.id,
        isolated_db,
        owner="paused-writer",
        expires_at=time.time() + 3600,
        spend_budget=False,
    )
    store.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task_paused:{writer.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.task_type == successor_type
    assert resumed.status == "queued"
    assert resumed.dependencies == (writer.id,)
    assert resumed.id != writer.id
    assert not store.claim_task(
        "early-child", run_id=run.id, db_path=isolated_db
    )
    assert store.complete_task(
        writer.id, "paused-writer", {}, db_path=isolated_db
    )
    claimed = store.claim_task(
        "successor-worker", run_id=run.id, db_path=isolated_db
    )
    assert claimed is not None and claimed.id == resumed.id


def test_resume_explicitly_requeues_retryable_expired_checkpoint_writer(
    isolated_db: str,
) -> None:
    run = store.create_run("paused expired commit", "standard", "engine", {})
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:expired-generate-parent",
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)
    claimed = store.claim_task(
        "expired-worker", run_id=run.id, db_path=isolated_db
    )
    assert claimed is not None and claimed.id == task.id
    task = claimed
    with store.transaction(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=? WHERE id=?",
            (time.time() - 3600, task.id),
        )
    store.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task:{task.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=isolated_db,
    )
    child = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=successor_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{successor_type}:after:{task.id}",
            dependencies=(task.id,),
            provenance={"scheduled_by": "engine.node.generate"},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.id == child.id
    reclaimed = store.claim_task(
        "replacement-worker", run_id=run.id, db_path=isolated_db
    )
    assert reclaimed is not None and reclaimed.id == task.id
    assert reclaimed.attempt == task.attempt + 1
    assert store.complete_task(
        task.id, "replacement-worker", {}, db_path=isolated_db
    )
    claimed_child = store.claim_task(
        "child-worker", run_id=run.id, db_path=isolated_db
    )
    assert claimed_child is not None and claimed_child.id == child.id


def test_resume_revives_spent_expired_checkpoint_writer_before_child(
    isolated_db: str,
) -> None:
    run = store.create_run("paused spent commit", "standard", "engine", {})
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    writer = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:spent-writer",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        writer.id,
        isolated_db,
        owner="dead-writer",
        expires_at=time.time() - 3600,
        spend_budget=True,
    )
    store.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task:{writer.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=isolated_db,
    )
    child = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=successor_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{successor_type}:after:{writer.id}",
            dependencies=(writer.id,),
            provenance={"scheduled_by": "engine.node.generate"},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    revived_writer = store.get_task(writer.id, db_path=isolated_db)
    assert resumed.id == child.id
    assert revived_writer is not None and revived_writer.status == "queued"
    assert revived_writer.attempt == writer.max_attempts
    assert revived_writer.max_attempts == writer.max_attempts + 1
    replayed = store.claim_task(
        "replacement-worker", run_id=run.id, db_path=isolated_db
    )
    assert replayed is not None and replayed.id == writer.id
    assert replayed.attempt == writer.max_attempts + 1
    assert store.complete_task(
        writer.id, "replacement-worker", {}, db_path=isolated_db
    )
    claimed_child = store.claim_task(
        "child-worker", run_id=run.id, db_path=isolated_db
    )
    assert claimed_child is not None and claimed_child.id == child.id


def test_resume_serializes_checkpoint_discovery_with_writer_commit(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = store.create_run("resume commit race", "standard", "engine", {})
    writer = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.ranking",
            inputs={"checkpoint_seq": 0},
            idempotency_key="resume:ranking-writer",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        writer.id,
        isolated_db,
        owner="ranking-worker",
        expires_at=time.time() + 3600,
        spend_budget=False,
    )
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task:{writer.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine"},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)
    original_get_checkpoint = store.get_latest_checkpoint
    old_checkpoint = original_get_checkpoint(run.id, db_path=isolated_db)
    assert old_checkpoint is not None
    successor_type = "engine.node.orchestrator"
    pool = ThreadPoolExecutor(max_workers=1)
    interleaver = _CheckpointReadInterleaver(
        original_get_checkpoint,
        old_checkpoint,
        run.id,
        isolated_db,
        writer,
        successor_type,
        pool,
    )

    monkeypatch.setattr(
        store,
        "get_latest_checkpoint",
        interleaver,
    )
    try:
        resumed = task_worker.enqueue_run_workflow(
            run.id, resume=True, db_path=isolated_db
        )
    finally:
        interleaver.wait_for_writer()
        pool.shutdown()

    assert resumed.id == writer.id
    orchestrators = [
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == successor_type and task.status == "queued"
    ]
    assert len(orchestrators) == 1
    assert orchestrators[0].idempotency_key == (
        f"{successor_type}:after:{writer.id}"
    )


_BYOK_SECRET = "synthetic-timeout-encryption-secret"
_BYOK_KEY = "sk-synthetic-ambiguous-timeout-12345"


@pytest.mark.asyncio
async def test_byok_timeout_waits_for_explicit_owner_restart(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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

        assert reopened.post(f"/api/runs/{run_id}/resume").status_code == 200
        assert await task_worker.run_once("owner-retry", db_path=isolated_db)

    assert accepted == ["response lost with old worker", "replayed"]


@pytest.mark.asyncio
async def test_expired_lease_fails_closed_after_paid_to_free_route_change(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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

        assert restarted.post(f"/api/runs/{run_id}/resume").status_code == 200
        assert await task_worker.run_once("owner-resume", db_path=isolated_db)

    assert dispatches == ["engine.node.generate"]


@pytest.mark.asyncio
async def test_expired_nonfree_system_route_requires_owner_recovery(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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

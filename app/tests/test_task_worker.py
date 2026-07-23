"""Tests for the standalone durable workflow worker."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import engine_adapter, engine_tasks, store, task_worker
from tests._client import make_client


def test_enqueue_workflow_is_idempotent(isolated_db: str) -> None:
    """Repeated start delivery creates one workflow task per checkpoint."""
    run = store.create_run("worker goal", "standard", "engine", {})
    first = task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    duplicate = task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    assert duplicate.id == first.id
    assert duplicate.task_type == "engine.bootstrap"


def test_engine_start_queues_durable_work(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API returns after persisting real-engine work for a worker."""
    monkeypatch.setenv("COSCIENTIST_EMBEDDED_WORKER", "0")
    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "Durable engine goal"}
        )
        run_id = created.json()["id"]
        started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200
    assert started.json()["status"] == "queued"
    [task] = store.list_tasks(run_id, db_path=isolated_db)
    assert task.task_type == "engine.bootstrap"
    assert task.status == "queued"


@pytest.mark.asyncio
async def test_worker_executes_and_commits_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leased workflow commits one terminal result."""
    run = store.create_run("worker goal", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="run.workflow",
            inputs={},
            idempotency_key="legacy-workflow",
        ),
        db_path=isolated_db,
    )

    async def _workflow(*_args: Any, **_kwargs: Any) -> Any:
        store.update_run_status(run.id, store.RunStatus.COMPLETED)
        if False:
            yield None

    monkeypatch.setattr(engine_adapter, "run_workflow", _workflow)
    assert await task_worker.run_once("worker-a", db_path=isolated_db)
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.result == {"run_id": run.id, "status": "completed"}
    assert not await task_worker.run_once("worker-b", db_path=isolated_db)


@pytest.mark.asyncio
async def test_worker_completes_superseded_engine_task(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An obsolete branch completes without retries or failure state."""
    run = store.create_run("superseded goal", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.test.superseded",
            inputs={},
            idempotency_key="superseded",
            max_attempts=3,
        ),
        db_path=isolated_db,
    )

    async def _execute(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise engine_tasks.SupersededTaskError("checkpoint advanced")

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)
    assert await task_worker.run_once("worker-a", db_path=isolated_db)
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.attempt == 1
    assert saved.error is None
    assert saved.result == {
        "superseded": True,
        "reason": "checkpoint advanced",
    }


@pytest.mark.asyncio
async def test_worker_shutdown_cancels_task_payload(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling the worker does not orphan its provider coroutine."""
    run = store.create_run("worker shutdown", "standard", "engine", {})
    store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.test.shutdown",
            inputs={},
            idempotency_key="shutdown",
        ),
        db_path=isolated_db,
    )
    started = asyncio.Event()
    interrupted = asyncio.Event()

    async def _execute(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, bool]:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            interrupted.set()
            raise
        return {"completed": True}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)
    running = asyncio.create_task(
        task_worker.run_once("worker-a", db_path=isolated_db)
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert interrupted.is_set()


def test_sync_worker_pool_runs_on_its_own_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FastAPI can dispatch the sync wrapper through its threadpool."""
    observed: list[tuple[str, str]] = []

    async def _pool(run_id: str, worker_prefix: str) -> None:
        observed.append((run_id, worker_prefix))

    monkeypatch.setattr(task_worker, "run_run_worker_pool", _pool)

    task_worker.run_run_worker_pool_sync("run-1", "embedded")

    assert observed == [("run-1", "embedded")]


@pytest.mark.asyncio
async def test_worker_delivers_opted_in_completion_email(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A notification task is durable and commits its SMTP delivery result."""
    run = store.create_run("notification goal", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="notification.email",
            inputs={
                "run_id": run.id,
                "email": "scientist@example.org",
                "title": "Result",
            },
            idempotency_key="email:1",
            max_attempts=3,
        ),
        db_path=isolated_db,
    )

    async def _deliver(inputs: dict[str, Any]) -> dict[str, str]:
        assert inputs["email"] == "scientist@example.org"
        return {"recipient": str(inputs["email"]), "status": "sent"}

    monkeypatch.setattr(
        task_worker, "deliver_completion_notification", _deliver
    )
    assert await task_worker.run_once("mail-worker", db_path=isolated_db)
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.result == {
        "recipient": "scientist@example.org",
        "status": "sent",
    }

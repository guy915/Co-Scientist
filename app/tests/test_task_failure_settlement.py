"""Run settlement when durable tasks exhaust their retry budget.

A task that fails past its retry budget -- or permanently, the way an
unsupported task type does -- used to leave its run non-terminal forever:
``fail_task`` marked the task failed and nothing transitioned the run, so
no error was recorded, the SSE stream never closed, and ``cosci runs
wait`` hung until a process restart's startup reconciliation picked the
run up. These tests pin the in-process settlement: the run fails
transactionally with its last claimable work, records the error, and the
event log carries the terminal ``status`` event the SSE stream closes on.
"""

from __future__ import annotations

import concurrent.futures
import json
from typing import Any

import pytest

from app import engine_tasks, store, task_worker
from app.config import settings
from tests._client import make_client


def _running_run(db_path: str, goal: str = "settlement goal") -> str:
    """Create a run and move it to the RUNNING status; return its id."""
    run = store.create_run(goal, "standard", "engine", {})
    store.update_run_status(run.id, store.RunStatus.RUNNING, db_path=db_path)
    return run.id


def _enqueue_engine_task(
    run_id: str, key: str, db_path: str, *, max_attempts: int = 3
) -> str:
    """Enqueue one engine task by idempotency key and return its id."""
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.ranking",
            inputs={},
            idempotency_key=key,
            max_attempts=max_attempts,
        ),
        db_path=db_path,
    )
    return task.id


def _failed_status_events(run_id: str, db_path: str) -> list[dict[str, Any]]:
    """Return the run's terminal ``failed`` status events."""
    return [
        event
        for event in store.list_events(run_id, db_path=db_path)
        if event["type"] == "status"
        and (event.get("payload") or {}).get("status") == "failed"
    ]


def _parse_sse(text: str) -> list[dict[str, Any]]:
    """Parse an SSE response body into its ``data:`` event dicts."""
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


# ---------------------------------------------------------------------------
# Store-level settlement semantics
# ---------------------------------------------------------------------------


def test_exhausted_retry_budget_settles_run(isolated_db: str) -> None:
    """Failing past the budget fails the run and keeps the error."""
    run_id = _running_run(isolated_db)
    task_id = _enqueue_engine_task(
        run_id, "doomed", isolated_db, max_attempts=2
    )

    first = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert first is not None and first.id == task_id
    assert store.fail_task(
        first.id, "w1", "provider timeout", db_path=isolated_db
    )
    # Budget left: the task is requeued and the run keeps running.
    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None and saved.status == "queued"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"

    second = store.claim_task("w2", run_id=run_id, db_path=isolated_db)
    assert second is not None and second.attempt == 2
    assert store.fail_task(
        second.id, "w2", "provider timeout again", db_path=isolated_db
    )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None and saved.status == "failed"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert run.error is not None
    assert "provider timeout again" in run.error
    assert run.completed_at is not None

    failed_events = _failed_status_events(run_id, isolated_db)
    assert len(failed_events) == 1
    assert "provider timeout again" in failed_events[0]["payload"]["error"]


def test_permanent_failure_settles_run(isolated_db: str) -> None:
    """A non-retryable failure settles the run on its first attempt."""
    run_id = _running_run(isolated_db)
    task_id = _enqueue_engine_task(
        run_id, "unsupported", isolated_db, max_attempts=3
    )
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id

    assert store.fail_task(
        leased.id,
        "w1",
        "unsupported task type: nope",
        retryable=False,
        db_path=isolated_db,
    )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None and saved.status == "failed"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert run.error is not None
    assert "unsupported task type" in run.error
    assert len(_failed_status_events(run_id, isolated_db)) == 1


def test_claimable_sibling_task_blocks_settlement(isolated_db: str) -> None:
    """A failed task with queued work left must not settle the run."""
    run_id = _running_run(isolated_db)
    doomed = _enqueue_engine_task(run_id, "doomed", isolated_db, max_attempts=1)
    _enqueue_engine_task(run_id, "survivor", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == doomed

    assert store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"
    assert _failed_status_events(run_id, isolated_db) == []


def test_active_sibling_lease_blocks_settlement(isolated_db: str) -> None:
    """A live sibling lease may still fan out work, blocking settlement."""
    run_id = _running_run(isolated_db)
    doomed = _enqueue_engine_task(run_id, "doomed", isolated_db, max_attempts=1)
    sibling = _enqueue_engine_task(
        run_id, "sibling", isolated_db, max_attempts=1
    )
    leased_doomed = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    leased_sibling = store.claim_task("w2", run_id=run_id, db_path=isolated_db)
    assert leased_doomed is not None and leased_doomed.id == doomed
    assert leased_sibling is not None and leased_sibling.id == sibling

    assert store.fail_task(
        leased_doomed.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"
    assert _failed_status_events(run_id, isolated_db) == []


def test_task_failure_does_not_settle_inactive_run(isolated_db: str) -> None:
    """Only queued/running/synthesizing runs settle; a draft stays draft."""
    run = store.create_run("draft goal", "standard", "engine", {})
    task_id = _enqueue_engine_task(run.id, "doomed", isolated_db)
    leased = store.claim_task("w1", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id

    assert store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    saved = store.get_run(run.id, db_path=isolated_db)
    assert saved is not None and saved.status == "draft"
    assert _failed_status_events(run.id, isolated_db) == []


def test_concurrent_final_failures_settle_exactly_once(
    isolated_db: str,
) -> None:
    """Two workers failing the last tasks cannot double-emit settlement."""
    run_id = _running_run(isolated_db)
    task_a = _enqueue_engine_task(run_id, "a", isolated_db, max_attempts=1)
    task_b = _enqueue_engine_task(run_id, "b", isolated_db, max_attempts=1)
    leased_a = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    leased_b = store.claim_task("w2", run_id=run_id, db_path=isolated_db)
    assert leased_a is not None and leased_a.id == task_a
    assert leased_b is not None and leased_b.id == task_b

    def _fail(task_id: str, worker: str) -> bool:
        return store.fail_task(
            task_id, worker, "boom", retryable=False, db_path=isolated_db
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [
            pool.submit(_fail, leased_a.id, "w1"),
            pool.submit(_fail, leased_b.id, "w2"),
        ]
        assert all(future.result() for future in outcomes)

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "failed"
    assert len(_failed_status_events(run_id, isolated_db)) == 1


def test_settled_run_is_not_reprocessed_at_startup(isolated_db: str) -> None:
    """An in-process settlement is final for the startup reconciliation."""
    run_id = _running_run(isolated_db)
    task_id = _enqueue_engine_task(
        run_id, "doomed", isolated_db, max_attempts=1
    )
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id
    assert store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )
    events_before = store.list_events(run_id, db_path=isolated_db)

    reconciled = store.reconcile_interrupted_runs(db_path=isolated_db)

    assert run_id not in reconciled["failed"]
    assert run_id not in reconciled["resumable"]
    assert store.list_events(run_id, db_path=isolated_db) == events_before


# ---------------------------------------------------------------------------
# Worker-level settlement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cohort_settles_run_when_budget_exhausts(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cohort drains an always-failing task, then its run settles failed."""
    run_id = _running_run(isolated_db)
    task_id = _enqueue_engine_task(
        run_id, "doomed", isolated_db, max_attempts=2
    )

    async def _always_fail(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _always_fail)

    await task_worker.run_run_worker_pool(
        run_id,
        "settle-test",
        worker_count=2,
        policy=task_worker.WorkerPolicy(db_path=isolated_db, lease_seconds=5),
    )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.attempt == saved.max_attempts
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert "provider exploded" in (run.error or "")
    assert len(_failed_status_events(run_id, isolated_db)) == 1


@pytest.mark.asyncio
async def test_unsupported_task_type_settles_run(isolated_db: str) -> None:
    """The one permanent failure class settles the run on first failure."""
    run_id = _running_run(isolated_db)
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="unknown.task",
            inputs={},
            idempotency_key="unknown",
        ),
        db_path=isolated_db,
    )

    assert await task_worker.run_once("w1", db_path=isolated_db)

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert "unsupported task type" in (run.error or "")
    assert len(_failed_status_events(run_id, isolated_db)) == 1


# ---------------------------------------------------------------------------
# API and SSE surfaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_run_settles_through_api_and_sse(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The settlement surfaces in the run API and closes the SSE stream."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    async def _always_fail(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _always_fail)

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "doomed goal"}
        )
        run_id = created.json()["id"]
        started = client.post(f"/api/runs/{run_id}/start", json={})
        assert started.status_code == 200

        # The bootstrap task retries three times before its budget is spent.
        for _ in range(3):
            assert await task_worker.run_once("w", db_path=isolated_db)
        assert not await task_worker.run_once("w", db_path=isolated_db)

        body = client.get(f"/api/runs/{run_id}").json()
        assert body["status"] == "failed"
        assert "provider exploded" in body["error"]

        frames = _parse_sse(client.get(f"/api/runs/{run_id}/events").text)

    assert frames[-1]["type"] == "_terminal"
    assert frames[-1]["payload"]["status"] == "failed"
    failed = [
        frame
        for frame in frames
        if frame["type"] == "status"
        and (frame.get("payload") or {}).get("status") == "failed"
    ]
    assert len(failed) == 1
    assert "provider exploded" in failed[0]["payload"]["error"]

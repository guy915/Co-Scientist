from __future__ import annotations

import asyncio
import time
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

import pytest
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from co_scientist.llm import current_run_call_count, scoped_llm_call_budget
from co_scientist.llm.admission.call_budget import record_provider_request
from fastapi import BackgroundTasks

import app.main as main_lifespan
from app import engine_tasks, task_worker
from app.config import Settings, settings
from app.runs import lifecycle as runs_lifecycle
from app.store import checkpoints, runs, tasks
from app.store import db as _store_db
from app.store import db as store_db
from app.store import events as store_events
from app.store import tasks_lifecycle as lifecycle
from app.store.checkpoints import NewCheckpoint
from app.store.models import RunRow, RunStatus, ScientificTask
from app.store.tasks import NewTask
from app.task_worker import outcomes as task_worker_outcomes
from tests._client import make_client
from tests._engine_tasks_helpers import _enqueue, make_cancellable_executor

# All launch sites must share worker-mode semantics for nonliteral boolean
# environment values.


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), ("1", True), ("true", True), ("0", False), ("false", False)],
)
def test_embedded_worker_parses_from_its_env_var(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    # Settings has no env prefix and is case-insensitive; disable .env loading
    # to isolate deployment variables.
    monkeypatch.delenv("COSCIENTIST_EMBEDDED_WORKER", raising=False)
    if value is not None:
        monkeypatch.setenv("COSCIENTIST_EMBEDDED_WORKER", value)

    parsed = Settings(_env_file=None)

    assert parsed.coscientist_embedded_worker is expected


@pytest.mark.parametrize(("embedded", "expected"), [(True, 1), (False, 0)])
def test_start_launches_an_embedded_worker_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, embedded: bool, expected: int
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", embedded)
    monkeypatch.setattr(_store_db, "transaction", lambda: nullcontext(object()))
    monkeypatch.setattr(
        runs, "reserve_run_capacity_in_transaction", lambda *_, **__: True
    )
    monkeypatch.setattr(
        lifecycle, "revive_task_for_retry", lambda *_, **__: None
    )
    monkeypatch.setattr(
        engine_tasks, "enqueue_bootstrap", lambda *_, **__: object()
    )
    monkeypatch.setattr(store_events, "append_event", lambda *a, **k: None)
    background = BackgroundTasks()

    runs_lifecycle._enqueue_workflow_and_maybe_launch_worker(
        RunRow(
            id="run-1",
            research_goal="test",
            profile="express",
            status="draft",
            provider="engine",
            config={},
            client_id="client",
            created_at=0,
            updated_at=0,
            completed_at=None,
            error=None,
        ),
        background,
    )

    assert len(background.tasks) == expected


async def test_recovery_launches_no_embedded_workers_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Start, resume, and recovery must agree on which process owns worker
    # execution.
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(
        tasks, "list_active_engine_task_run_ids", lambda: ["run-1"]
    )
    workers: list[asyncio.Task[Any]] = []

    main_lifespan._launch_embedded_recovery_workers(workers)

    assert workers == []


def test_enqueue_workflow_is_idempotent(isolated_db: str) -> None:
    run = runs.create_run("worker goal", "standard", "engine", {})
    first = task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    duplicate = task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    assert duplicate.id == first.id
    assert duplicate.task_type == "engine.bootstrap"


def test_engine_start_queues_durable_work(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "Durable engine goal"}
        )
        run_id = created.json()["id"]
        started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200
    assert started.json()["status"] == "queued"
    [task] = tasks.list_tasks(run_id, db_path=isolated_db)
    assert task.task_type == "engine.bootstrap"
    assert task.status == "queued"


@pytest.mark.asyncio
async def test_worker_executes_and_commits_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("worker goal", "standard", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.test.commit",
            inputs={},
            idempotency_key="commit-once",
        ),
        db_path=isolated_db,
    )

    async def _execute(
        _task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, str]:
        runs.update_run_status(run.id, RunStatus.COMPLETED)
        return {"run_id": run.id, "status": "completed"}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)
    assert await task_worker.run_once("worker-a", db_path=isolated_db)
    saved = tasks.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.result == {"run_id": run.id, "status": "completed"}
    assert not await task_worker.run_once("worker-b", db_path=isolated_db)


@pytest.mark.asyncio
async def test_worker_completes_superseded_engine_task(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("superseded goal", "standard", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.test.superseded",
            inputs={},
            idempotency_key="superseded",
            max_attempts=3,
        ),
        db_path=isolated_db,
    )

    async def _execute(
        _task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise engine_tasks.SupersededTaskError("checkpoint advanced")

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)
    assert await task_worker.run_once("worker-a", db_path=isolated_db)
    saved = tasks.get_task(task.id, db_path=isolated_db)
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
    run = runs.create_run("worker shutdown", "standard", "engine", {})
    tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.test.shutdown",
            inputs={},
            idempotency_key="shutdown",
        ),
        db_path=isolated_db,
    )
    started = asyncio.Event()
    interrupted = asyncio.Event()
    monkeypatch.setattr(
        engine_tasks,
        "execute_engine_task",
        make_cancellable_executor(started, interrupted),
    )
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
    run = runs.create_run("notification goal", "standard", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
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
    saved = tasks.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.result == {
        "recipient": "scientist@example.org",
        "status": "sent",
    }


# An exhausted lease without a live owner cannot settle itself; recovery must
# make the run terminal.


_TASK_TYPE = f"{engine_tasks.NODE_TASK_PREFIX}ranking"


def _run_with_lease(
    db: str,
    *,
    expires_at: float,
    spend_budget: bool,
    goal: str = "stranded goal",
) -> tuple[str, str]:
    run = runs.create_run(goal, "standard", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=_TASK_TYPE,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{_TASK_TYPE}:1",
        ),
        db_path=db,
    )
    extra = ", attempt=max_attempts" if spend_budget else ""
    with _store_db.connect(db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner=?, "
            f"lease_expires_at=?{extra} WHERE id=?",
            ("dead", expires_at, task.id),
        )
        conn.execute("UPDATE runs SET status='running' WHERE id=?", (run.id,))
    return run.id, task.id


def _task_status(task_id: str, db: str) -> str:
    with _store_db.connect(db) as conn:
        row = conn.execute(
            "SELECT status FROM scientific_tasks WHERE id=?", (task_id,)
        ).fetchone()
    return str(row["status"])


def test_dead_lease_is_failed_and_settles_its_run(isolated_db: str) -> None:
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    abandoned = lifecycle.abandon_dead_leases(run_id, db_path=isolated_db)

    assert abandoned == 1
    assert _task_status(task_id, isolated_db) == "failed"
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"


def test_dead_lease_settlement_emits_a_terminal_status_event(
    isolated_db: str,
) -> None:
    run_id, _ = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    lifecycle.abandon_dead_leases(run_id, db_path=isolated_db)

    events = store_events.list_events(run_id, db_path=isolated_db)
    terminal = [
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "failed"
    ]
    assert terminal, "a settled run must announce it"


def test_a_live_lease_is_never_abandoned(isolated_db: str) -> None:
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() + 3600, spend_budget=True
    )

    assert lifecycle.abandon_dead_leases(run_id, db_path=isolated_db) == 0
    assert _task_status(task_id, isolated_db) == "leased"
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "running"


def test_an_expired_lease_with_retries_left_is_never_abandoned(
    isolated_db: str,
) -> None:
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=False
    )

    assert lifecycle.abandon_dead_leases(run_id, db_path=isolated_db) == 0
    assert _task_status(task_id, isolated_db) == "leased"


def test_cohort_poll_reports_a_dead_lease_as_inactive(
    isolated_db: str,
) -> None:
    run_id, _ = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    claimable, active, _ = lifecycle.cohort_poll(run_id, db_path=isolated_db)

    assert not claimable, "a spent-budget lease is claimable by nobody"
    assert not active, "nor is anyone still working on it"


def test_cohort_poll_still_reports_a_live_lease_as_active(
    isolated_db: str,
) -> None:
    run_id, _ = _run_with_lease(
        isolated_db, expires_at=time.time() + 3600, spend_budget=True
    )

    _, active, _park = lifecycle.cohort_poll(run_id, db_path=isolated_db)

    assert active


async def test_cohort_idle_exit_settles_a_run_left_with_a_dead_lease(
    isolated_db: str,
) -> None:
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    await task_worker.run_run_worker_pool(
        run_id,
        "cohort",
        worker_count=1,
        policy=task_worker.WorkerPolicy(db_path=isolated_db),
    )

    assert _task_status(task_id, isolated_db) == "failed"
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"


def _enqueue_test_tasks(
    run_id: str, count: int, prefix: str, db_path: str
) -> None:
    for index in range(count):
        tasks.enqueue_task(
            NewTask(
                run_id=run_id,
                task_type=f"engine.test.{index}",
                inputs={},
                idempotency_key=f"{prefix}:{index}",
            ),
            db_path=db_path,
        )


def _assert_all_completed(run_id: str, db_path: str) -> None:
    assert {
        task.status for task in tasks.list_tasks(run_id, db_path=db_path)
    } == {"completed"}


def _count_lease_renewals(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    box = {"renewals": 0}

    def _renew(*_args: Any, **_kwargs: Any) -> bool:
        box["renewals"] += 1
        return True

    monkeypatch.setattr(lifecycle, "renew_task_lease", _renew)
    return box


class _ConcurrencyProbe:
    def __init__(self, sleep_seconds: float) -> None:
        self._sleep = sleep_seconds
        self._active = 0
        self.max_active = 0
        self._lock = asyncio.Lock()

    async def execute(
        self, _task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, bool]:
        async with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        await asyncio.sleep(self._sleep)
        async with self._lock:
            self._active -= 1
        return {"completed": True}


@pytest.mark.asyncio
async def test_worker_heartbeats_long_workflow_lease(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("long worker goal", "standard", "engine", {})
    tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.test.long",
            inputs={},
            idempotency_key="long-engine-task",
        ),
        db_path=isolated_db,
    )
    release = asyncio.Event()

    async def _execute(
        _task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, bool]:
        await release.wait()
        runs.update_run_status(run.id, RunStatus.COMPLETED)
        return {"completed": True}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)
    running = asyncio.create_task(
        task_worker.run_once(
            "worker-a", db_path=isolated_db, lease_seconds=0.06
        )
    )
    await asyncio.sleep(0.1)
    assert tasks.claim_task("worker-b", db_path=isolated_db) is None
    release.set()
    assert await running


@pytest.mark.asyncio
async def test_worker_cancels_execution_after_lease_revocation(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("cancel active work", "standard", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.test.cancellable",
            inputs={},
            idempotency_key="cancellable",
        ),
        db_path=isolated_db,
    )
    started = asyncio.Event()
    interrupted = asyncio.Event()
    monkeypatch.setattr(
        engine_tasks,
        "execute_engine_task",
        make_cancellable_executor(started, interrupted),
    )
    running = asyncio.create_task(
        task_worker.run_once(
            "worker-a", db_path=isolated_db, lease_seconds=0.15
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    assert lifecycle.cancel_run_tasks(run.id, db_path=isolated_db) == 1
    assert await asyncio.wait_for(running, timeout=1)
    assert interrupted.is_set()
    saved = tasks.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "cancelled"


@pytest.mark.asyncio
async def test_embedded_worker_pool_executes_fanout_concurrently(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("parallel goal", "standard", "engine", {})
    _enqueue_test_tasks(run.id, 4, "parallel", isolated_db)
    probe = _ConcurrencyProbe(0.03)
    monkeypatch.setattr(engine_tasks, "execute_engine_task", probe.execute)

    await task_worker.run_run_worker_pool(
        run.id,
        "embedded-test",
        worker_count=4,
        policy=task_worker.WorkerPolicy(db_path=isolated_db, lease_seconds=1),
    )

    assert probe.max_active == 4
    _assert_all_completed(run.id, isolated_db)


@pytest.mark.asyncio
async def test_worker_isolates_unknown_task_failure(isolated_db: str) -> None:
    run = runs.create_run("worker goal", "standard", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="unknown.task",
            inputs={},
            idempotency_key="unknown:0",
        ),
        db_path=isolated_db,
    )
    assert await task_worker.run_once("worker-a", db_path=isolated_db)
    saved = tasks.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "failed"
    assert "unsupported task type" in str(saved.error)


@pytest.mark.asyncio
async def test_transient_provider_failure_keeps_its_retry_budget(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Empty provider responses are transient; classifying every ValueError as
    # permanent strands runs.
    run = runs.create_run("Transient failure", "standard", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.ranking",
            inputs={},
            idempotency_key="transient-1",
        ),
        db_path=isolated_db,
    )

    async def empty_response(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise ValueError("LLM returned None or empty content. Model: x")

    monkeypatch.setattr(task_worker, "_execute_task_payload", empty_response)
    assert await task_worker.run_once("w1", run_id=run.id, db_path=isolated_db)

    after = tasks.get_task(task.id, db_path=isolated_db)
    assert after is not None
    assert after.status == "queued", "a transient failure must stay retryable"
    assert after.attempt < after.max_attempts


@pytest.mark.asyncio
async def test_unsupported_task_type_is_still_permanent(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Bad task type", "standard", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.ranking",
            inputs={},
            idempotency_key="unsupported-1",
        ),
        db_path=isolated_db,
    )

    async def unsupported(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise task_worker.UnsupportedTaskError("unsupported task type: nope")

    monkeypatch.setattr(task_worker, "_execute_task_payload", unsupported)
    assert await task_worker.run_once("w1", run_id=run.id, db_path=isolated_db)

    after = tasks.get_task(task.id, db_path=isolated_db)
    assert after is not None
    assert after.status == "failed", "an unknown task type is not retryable"


@pytest.mark.asyncio
async def test_default_worker_cohort_overlaps_more_than_four_leases(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("wide fanout", "standard", "engine", {})
    _enqueue_test_tasks(run.id, 12, "wide", isolated_db)
    probe = _ConcurrencyProbe(0.05)
    monkeypatch.setattr(engine_tasks, "execute_engine_task", probe.execute)

    await task_worker.run_run_worker_pool(
        run.id,
        "embedded-test",
        policy=task_worker.WorkerPolicy(db_path=isolated_db, lease_seconds=5),
    )

    assert probe.max_active > 4
    _assert_all_completed(run.id, isolated_db)


@pytest.mark.asyncio
async def test_heartbeat_writes_on_the_lease_schedule_not_the_poll_schedule(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cancellation polls are memory-only; writing lease renewal every tick
    # starves the single SQLite writer.
    run = runs.create_run("heartbeat cost", "standard", "engine", {})
    task = _enqueue(run.id, "engine.test.heartbeat", "heartbeat:0", isolated_db)
    renewals = _count_lease_renewals(monkeypatch)

    stop = asyncio.Event()
    lease_lost = asyncio.Event()
    beat = asyncio.create_task(
        task_worker._heartbeat_lease(
            task,
            "worker-hb",
            task_worker._HeartbeatSignals(stop=stop, lease_lost=lease_lost),
            db_path=isolated_db,
            lease_seconds=300.0,
        )
    )
    await asyncio.sleep(2.5)
    stop.set()
    await beat

    count = renewals["renewals"]
    assert count == 0, f"{count} lease writes in 2.5s of polling"


def test_idle_claim_does_not_contend_for_the_write_lock(
    isolated_db: str,
) -> None:
    # Idle queue polls must not open write transactions or they starve unrelated
    # API writes.
    import sqlite3
    import time as _time

    assert tasks.claim_task("warmup", db_path=isolated_db) is None

    blocker = sqlite3.connect(isolated_db, timeout=0.5, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        started = _time.monotonic()
        assert tasks.claim_task("idle-worker", db_path=isolated_db) is None
        assert _time.monotonic() - started < 1.0
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()


def test_idle_wait_does_not_decode_every_task(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Polling one boolean must not decode every historical task row.
    run = runs.create_run("idle wait cost", "standard", "engine", {})
    for index in range(30):
        tasks.enqueue_task(
            NewTask(
                run_id=run.id,
                task_type=f"engine.test.{index}",
                inputs={},
                idempotency_key=f"idle:{index}",
            ),
            db_path=isolated_db,
        )
    calls = 0
    real_list = tasks.list_tasks

    def _counting_list(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_list(*args, **kwargs)

    monkeypatch.setattr(tasks, "list_tasks", _counting_list)

    claimable, active, _park = lifecycle.cohort_poll(
        run.id, db_path=isolated_db
    )
    assert claimable is True and active is False
    assert calls == 0


# Call-budget exhaustion is permanent; retrying it cannot create more allowance.


def test_ceiling_exceeded_fails_permanently_and_settles_the_run(
    isolated_db: str,
) -> None:
    run = runs.create_run("LLM budget ceiling", "standard", "engine", {})
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=isolated_db)
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
            # A generous budget distinguishes permanent failure from accidental
            # retry classification.
            max_attempts=5,
        ),
        db_path=isolated_db,
    )
    leased = tasks.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == task.id

    error = LLMCallBudgetExceededError(count=2501, ceiling=2500)
    task_worker_outcomes._handle_task_failure(
        leased, "worker", error, isolated_db
    )

    task_after = tasks.get_task(task.id, db_path=isolated_db)
    assert task_after is not None
    assert task_after.status == "failed", (
        "a ceiling breach must fail outright, not requeue for retry"
    )
    assert task_after.attempt < task_after.max_attempts, (
        "it must not have burned through the retry budget to get there"
    )

    settled = runs.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == RunStatus.FAILED.value
    assert settled.error is not None
    assert "LLM-call ceiling exceeded" in settled.error
    assert "2501" in settled.error and "2500" in settled.error, (
        "the user-visible reason must name the count and the ceiling, "
        "not read as a generic task failure"
    )


def test_ceiling_exceeded_releases_the_runs_counter(
    isolated_db: str,
) -> None:
    run = runs.create_run("LLM budget release", "standard", "engine", {})
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=isolated_db)
    tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
        ),
        db_path=isolated_db,
    )
    leased = tasks.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None

    with scoped_llm_call_budget(run.id, ceiling=1):
        record_provider_request()
    assert current_run_call_count(run.id) == 1

    task_worker_outcomes._handle_task_failure(
        leased,
        "worker",
        LLMCallBudgetExceededError(count=2, ceiling=1),
        isolated_db,
    )

    assert current_run_call_count(run.id) == 0, (
        "a permanently failed run's counter must be dropped, not left to"
        " grow the process-wide tracker until the eviction cap"
    )


# Platform rate caps park without spending attempts or settling the run.


def _advance_clock(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    real_now = store_db._now()
    monkeypatch.setattr("app.store.db.time.time", lambda: real_now + seconds)


def test_rate_limit_park_requeues_without_spending_an_attempt(
    isolated_db: str,
) -> None:
    run = runs.create_run("Rate limit park", "standard", "engine", {})
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=isolated_db)
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
            max_attempts=3,
        ),
        db_path=isolated_db,
    )
    leased = tasks.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == task.id
    assert leased.attempt == 1

    now = store_db._now()
    resume_at = now + 3600
    error = LLMRateLimitParkError(resume_at=resume_at, reason="message_per_day")

    task_worker_outcomes._handle_task_failure(
        leased, "worker", error, isolated_db
    )

    parked = tasks.get_task(task.id, db_path=isolated_db)
    assert parked is not None
    assert parked.status == "queued", "a platform cap must not fail the task"
    assert parked.attempt == 0, "parking must not consume an attempt"
    assert parked.lease_owner is None
    assert parked.available_at is not None
    assert resume_at <= parked.available_at <= resume_at + 15

    reclaim = tasks.claim_task("worker2", run_id=run.id, db_path=isolated_db)
    assert reclaim is None

    still_running = runs.get_run(run.id, db_path=isolated_db)
    assert still_running is not None
    assert still_running.status == RunStatus.RUNNING.value

    assert parked.attempts, "the park must be visible in attempt history"
    last_attempt = parked.attempts[-1]
    assert last_attempt["retryable"] is True
    assert "message_per_day" in last_attempt["error"]


def test_rate_limit_park_becomes_claimable_once_due(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Rate limit park due", "standard", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
        ),
        db_path=isolated_db,
    )
    leased = tasks.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None

    resume_at = store_db._now() + 60
    ok = lifecycle.park_task_for_rate_limit(
        task.id, "worker", "rate limited", resume_at, db_path=isolated_db
    )
    assert ok

    reclaim = tasks.claim_task("worker2", run_id=run.id, db_path=isolated_db)
    assert reclaim is None

    _advance_clock(monkeypatch, 61)

    reclaimed = tasks.claim_task("worker2", run_id=run.id, db_path=isolated_db)
    assert reclaimed is not None and reclaimed.id == task.id


async def test_cohort_keeps_polling_over_a_parked_task_instead_of_exiting(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Future-due parked rows keep the cohort alive even though they are neither
    # claimable nor leased.
    run = runs.create_run("Rate limit park cohort", "standard", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
        ),
        db_path=isolated_db,
    )
    leased = tasks.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    resume_at = store_db._now() + 3600
    ok = lifecycle.park_task_for_rate_limit(
        task.id, "worker", "rate limited", resume_at, db_path=isolated_db
    )
    assert ok

    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.task_worker.asyncio.sleep", _fake_sleep)

    policy = task_worker.WorkerPolicy(db_path=isolated_db)
    keep_going = await task_worker._cohort_worker_step(
        run.id, "worker2", policy
    )

    assert keep_going, "a pending park must keep the cohort alive"
    assert slept, "the idle loop must wait rather than busy-poll"
    assert slept[0] <= task_worker._PARKED_POLL_SECONDS


@dataclass(frozen=True)
class _ResumeShape:
    stage: str = "post_generation"
    last_event_seq: int = 1
    provider: str | None = None


def _save_resume_checkpoint(
    run_id: str,
    successor: str,
    db: str,
    shape: _ResumeShape | None = None,
) -> None:
    shape = shape or _ResumeShape()
    state: dict[str, Any] = {"resume_successor": successor}
    if shape.provider is not None:
        state["provider"] = shape.provider
    checkpoints.save_checkpoint(
        run_id,
        NewCheckpoint(
            stage=shape.stage,
            schema_version=1,
            last_event_seq=shape.last_event_seq,
            state=state,
        ),
        db_path=db,
    )


def _mark_leased(
    task_id: str,
    db: str,
    *,
    owner: str,
    expires_at: float,
    spend_budget: bool,
) -> None:
    extra = ", attempt=max_attempts" if spend_budget else ""
    with _store_db.connect(db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner=?, "
            f"lease_expires_at=?{extra} WHERE id=?",
            (owner, expires_at, task_id),
        )


def test_resume_uses_recorded_successor_not_orchestrator_default(
    isolated_db: str,
) -> None:
    # Bootstrap checkpoints precede supervisor guidance; their successor must be
    # supervisor, with the original idempotency key.
    supervisor_type = f"{engine_tasks.NODE_TASK_PREFIX}supervisor"
    run = runs.create_run("worker goal", "standard", "engine", {})
    enqueued = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=supervisor_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{supervisor_type}:1",
        ),
        db_path=isolated_db,
    )
    _save_resume_checkpoint(
        run.id,
        supervisor_type,
        isolated_db,
        _ResumeShape(
            stage="engine_task:bootstrap",
            last_event_seq=0,
            provider="engine",
        ),
    )

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.task_type == supervisor_type
    assert resumed.id == enqueued.id, "must resolve to the already-queued task"


def test_resume_defaults_to_orchestrator_when_successor_unrecorded(
    isolated_db: str,
) -> None:
    # Legacy and fan-out planning checkpoints already have supervisor guidance,
    # so orchestrator re-entry remains valid.
    run = runs.create_run("worker goal", "standard", "engine", {})
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="engine_task:orchestrator",
            schema_version=1,
            last_event_seq=0,
            state={"provider": "engine"},
        ),
        db_path=isolated_db,
    )

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.task_type == f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"


def test_resume_reuses_post_pause_fanout_rows_for_latest_checkpoint(
    isolated_db: str,
) -> None:
    run = runs.create_run("paused fanout", "standard", "engine", {})
    parent = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:generate-parent",
        ),
        db_path=isolated_db,
    )
    leased = tasks.claim_task(
        "parent-worker", run_id=run.id, db_path=isolated_db
    )
    assert leased is not None and leased.id == parent.id
    assert lifecycle.complete_task(
        parent.id, "parent-worker", {}, db_path=isolated_db
    )
    runs.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage=f"engine_task:{parent.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine"},
        ),
        db_path=isolated_db,
    )

    stale = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}review",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:stale-lookahead",
            provenance={"scheduled_by": "engine.node.old"},
        ),
        db_path=isolated_db,
    )
    fanout = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.fanout.generation.strategy",
            inputs={"checkpoint_seq": 1},
            idempotency_key="generation:debate_only:1:0:1",
            dependencies=(parent.id,),
            provenance={"scheduled_by": parent.task_type},
        ),
        db_path=isolated_db,
    )
    runs.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.id == fanout.id
    assert resumed.id != stale.id
    assert not any(
        task.task_type == f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
        and task.status == "queued"
        for task in tasks.list_tasks(run.id, db_path=isolated_db)
    )


def _wedge_task_at(
    run_id: str, task_type: str, checkpoint_seq: int, status: str, db: str
) -> str:
    task = tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{task_type}:{checkpoint_seq}",
        ),
        db_path=db,
    )
    with _store_db.connect(db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status=?, attempt=max_attempts "
            "WHERE id=?",
            (status, task.id),
        )
    return task.id


def _queued(run_id: str, db: str) -> list[Any]:
    return [
        t for t in tasks.list_tasks(run_id, db_path=db) if t.status == "queued"
    ]


@pytest.mark.parametrize("dead_status", ["failed", "cancelled"])
def test_resume_revives_a_boundary_whose_task_died(
    isolated_db: str, dead_status: str
) -> None:
    # An unchanged checkpoint collides with a terminal boundary key; explicit
    # resume must revive failed work.
    run = runs.create_run("wedged goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="post_generation",
            schema_version=1,
            last_event_seq=1,
            state={"resume_successor": task_type},
        ),
        db_path=isolated_db,
    )
    task_id = _wedge_task_at(run.id, task_type, 1, dead_status, isolated_db)
    assert not _queued(run.id, isolated_db)

    task_worker.enqueue_run_workflow(run.id, resume=True, db_path=isolated_db)

    queued = _queued(run.id, isolated_db)
    assert len(queued) == 1
    assert queued[0].id == task_id
    assert queued[0].task_type == task_type
    assert queued[0].attempt < queued[0].max_attempts


def test_resume_does_not_rerun_completed_work(isolated_db: str) -> None:
    # Reviving succeeded boundaries repeats already committed and paid-for work.
    run = runs.create_run("done goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="post_generation",
            schema_version=1,
            last_event_seq=1,
            state={"resume_successor": task_type},
        ),
        db_path=isolated_db,
    )
    _wedge_task_at(run.id, task_type, 1, "succeeded", isolated_db)

    task_worker.enqueue_run_workflow(run.id, resume=True, db_path=isolated_db)

    assert not _queued(run.id, isolated_db)


def test_resume_revives_a_lease_stranded_by_a_dead_worker(
    isolated_db: str,
) -> None:
    # Expired exhausted leases need explicit recovery; ordinary claim rescue
    # intentionally skips spent retries.
    run = runs.create_run("stranded goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    _save_resume_checkpoint(run.id, task_type, isolated_db)
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=task_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{task_type}:1",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        task.id,
        isolated_db,
        owner="dead",
        expires_at=time.time() - 3600,
        spend_budget=True,
    )
    assert not _queued(run.id, isolated_db)

    task_worker.enqueue_run_workflow(run.id, resume=True, db_path=isolated_db)

    queued = _queued(run.id, isolated_db)
    assert len(queued) == 1
    assert queued[0].id == task.id
    assert queued[0].attempt < queued[0].max_attempts


def test_resume_leaves_a_live_lease_alone(isolated_db: str) -> None:
    # Only expired leases imply abandonment; reviving a live lease executes the
    # boundary concurrently.
    run = runs.create_run("busy goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="post_generation",
            schema_version=1,
            last_event_seq=1,
            state={"resume_successor": task_type},
        ),
        db_path=isolated_db,
    )
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=task_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{task_type}:1",
        ),
        db_path=isolated_db,
    )
    with _store_db.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner='alive', "
            "lease_expires_at=? WHERE id=?",
            (time.time() + 3600, task.id),
        )

    task_worker.enqueue_run_workflow(run.id, resume=True, db_path=isolated_db)

    assert not _queued(run.id, isolated_db)
    with _store_db.connect(isolated_db) as conn:
        row = conn.execute(
            "SELECT status, lease_owner FROM scientific_tasks WHERE id=?",
            (task.id,),
        ).fetchone()
    assert (row["status"], row["lease_owner"]) == ("leased", "alive")

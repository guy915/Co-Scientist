"""Tests for task worker 1."""

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
from app import engine_tasks, store, task_worker
from app.config import Settings, settings
from app.runs import lifecycle as runs_lifecycle
from app.store import RunStatus
from app.store import db as store_db
from app.task_worker import outcomes as task_worker_outcomes
from tests._client import make_client
from tests._engine_tasks_helpers import _enqueue, make_cancellable_executor

# Tests for the ``COSCIENTIST_EMBEDDED_WORKER`` deployment knob.
#
# Whether this process drains the durable task queue itself is one fact, read
# at three launch sites: run start, resume, and startup recovery. Each used to
# call ``os.getenv`` with its own restated ``"1"`` default and compared it
# inconsistently (``== "1"`` twice, ``!= "1"`` once), so any value other than
# exactly ``"1"`` or ``"0"`` meant different things to different sites. It is
# now a ``Settings`` field, which is what these tests pin.


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), ("1", True), ("true", True), ("0", False), ("false", False)],
)
def test_embedded_worker_parses_from_its_env_var(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    """The knob keeps its name and its default-on behavior after the move.

    Settings sets no ``env_prefix`` and is case-insensitive, so the field
    picks ``COSCIENTIST_EMBEDDED_WORKER`` up exactly as the removed
    ``os.getenv`` calls did -- no deployment has to change a variable.
    ``_env_file=None`` keeps a developer's local .env out of the answer.
    """
    monkeypatch.delenv("COSCIENTIST_EMBEDDED_WORKER", raising=False)
    if value is not None:
        monkeypatch.setenv("COSCIENTIST_EMBEDDED_WORKER", value)

    parsed = Settings(_env_file=None)

    assert parsed.coscientist_embedded_worker is expected


@pytest.mark.parametrize(("embedded", "expected"), [(True, 1), (False, 0)])
def test_start_launches_an_embedded_worker_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, embedded: bool, expected: int
) -> None:
    """A worker-service deployment leaves the queued task for its own worker."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", embedded)
    monkeypatch.setattr(store, "transaction", lambda: nullcontext(object()))
    monkeypatch.setattr(
        store, "reserve_run_capacity_in_transaction", lambda *_, **__: True
    )
    monkeypatch.setattr(store, "revive_task_for_retry", lambda *_, **__: None)
    monkeypatch.setattr(
        engine_tasks, "enqueue_bootstrap", lambda *_, **__: object()
    )
    monkeypatch.setattr(store, "append_event", lambda *a, **k: None)
    background = BackgroundTasks()

    runs_lifecycle._enqueue_workflow_and_maybe_launch_worker(
        store.RunRow(
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
    """Startup recovery reads the same setting as the two run-launch sites.

    The recovery site is the one that phrased the check as ``!= "1"``. It
    must agree with the others, or a deployment that meant to hand every
    task to a worker service still leases them in the API process at boot.
    """
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(
        store, "list_active_engine_task_run_ids", lambda: ["run-1"]
    )
    workers: list[asyncio.Task[Any]] = []

    main_lifespan._launch_embedded_recovery_workers(workers)

    assert workers == []


# Tests for the standalone durable workflow worker.


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
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
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
    """A leased engine task commits one terminal result, then work is done."""
    run = store.create_run("worker goal", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.test.commit",
            inputs={},
            idempotency_key="commit-once",
        ),
        db_path=isolated_db,
    )

    async def _execute(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, str]:
        store.update_run_status(run.id, store.RunStatus.COMPLETED)
        return {"run_id": run.id, "status": "completed"}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)
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


# A lease that outlives its worker with no retries left must settle.
#
# ``fail_task`` settles a run whose task dies past its retry budget, but it
# can only run if someone still holds the lease to call it. When the worker
# dies holding a lease whose attempts are already spent, nobody does, and
# ``claim_task``'s expired-lease rescue skips the row by design -- so the
# run was left ``running`` with nothing that could ever advance it. These
# tests pin the automatic recovery; ``test_task_worker_resume.py`` covers
# the operator-initiated one.


_TASK_TYPE = f"{engine_tasks.NODE_TASK_PREFIX}ranking"


def _run_with_lease(
    db: str,
    *,
    expires_at: float,
    spend_budget: bool,
    goal: str = "stranded goal",
) -> tuple[str, str]:
    """Create a run holding one leased task; return its (run, task) ids."""
    run = store.create_run(goal, "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=_TASK_TYPE,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{_TASK_TYPE}:1",
        ),
        db_path=db,
    )
    extra = ", attempt=max_attempts" if spend_budget else ""
    with store.connect(db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner=?, "
            f"lease_expires_at=?{extra} WHERE id=?",
            ("dead", expires_at, task.id),
        )
        conn.execute("UPDATE runs SET status='running' WHERE id=?", (run.id,))
    return run.id, task.id


def _task_status(task_id: str, db: str) -> str:
    """Read one task's queue status."""
    with store.connect(db) as conn:
        row = conn.execute(
            "SELECT status FROM scientific_tasks WHERE id=?", (task_id,)
        ).fetchone()
    return str(row["status"])


def test_dead_lease_is_failed_and_settles_its_run(isolated_db: str) -> None:
    """The whole point: the run reaches a terminal state on its own."""
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    abandoned = store.abandon_dead_leases(run_id, db_path=isolated_db)

    assert abandoned == 1
    assert _task_status(task_id, isolated_db) == "failed"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"


def test_dead_lease_settlement_emits_a_terminal_status_event(
    isolated_db: str,
) -> None:
    """The SSE stream closes on this event, so it has to be written."""
    run_id, _ = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    store.abandon_dead_leases(run_id, db_path=isolated_db)

    events = store.list_events(run_id, db_path=isolated_db)
    terminal = [
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "failed"
    ]
    assert terminal, "a settled run must announce it"


def test_a_live_lease_is_never_abandoned(isolated_db: str) -> None:
    """Its owner may still be working; failing it would discard real work."""
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() + 3600, spend_budget=True
    )

    assert store.abandon_dead_leases(run_id, db_path=isolated_db) == 0
    assert _task_status(task_id, isolated_db) == "leased"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "running"


def test_an_expired_lease_with_retries_left_is_never_abandoned(
    isolated_db: str,
) -> None:
    """That row belongs to claim_task's rescue, which requeues it."""
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=False
    )

    assert store.abandon_dead_leases(run_id, db_path=isolated_db) == 0
    assert _task_status(task_id, isolated_db) == "leased"


def test_cohort_poll_reports_a_dead_lease_as_inactive(
    isolated_db: str,
) -> None:
    """Reported active, the cohort polls forever over unclaimable work."""
    run_id, _ = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    claimable, active, _ = store.cohort_poll(run_id, db_path=isolated_db)

    assert not claimable, "a spent-budget lease is claimable by nobody"
    assert not active, "nor is anyone still working on it"


def test_cohort_poll_still_reports_a_live_lease_as_active(
    isolated_db: str,
) -> None:
    """The sibling may yet fan out more work; the cohort must wait."""
    run_id, _ = _run_with_lease(
        isolated_db, expires_at=time.time() + 3600, spend_budget=True
    )

    _, active, _park = store.cohort_poll(run_id, db_path=isolated_db)

    assert active


async def test_cohort_idle_exit_settles_a_run_left_with_a_dead_lease(
    isolated_db: str,
) -> None:
    """End to end: the cohort exits and the run does not hang."""
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
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"


# Lease, heartbeat, retry, and concurrency tests for the durable worker.
#
# Enqueue/resume/shutdown semantics live in ``test_task_worker.py``.


def _enqueue_test_tasks(
    run_id: str, count: int, prefix: str, db_path: str
) -> None:
    """Enqueue ``count`` independent ``engine.test.<i>`` specialist tasks."""
    for index in range(count):
        store.enqueue_task(
            store.NewTask(
                run_id=run_id,
                task_type=f"engine.test.{index}",
                inputs={},
                idempotency_key=f"{prefix}:{index}",
            ),
            db_path=db_path,
        )


def _assert_all_completed(run_id: str, db_path: str) -> None:
    """Assert every task in the run reached the completed status."""
    assert {
        task.status for task in store.list_tasks(run_id, db_path=db_path)
    } == {"completed"}


def _count_lease_renewals(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Patch ``store.renew_task_lease`` with a counter, return the counter."""
    box = {"renewals": 0}

    def _renew(*_args: Any, **_kwargs: Any) -> bool:
        box["renewals"] += 1
        return True

    monkeypatch.setattr(store, "renew_task_lease", _renew)
    return box


class _ConcurrencyProbe:
    """A fake executor that records the peak number of overlapping leases."""

    def __init__(self, sleep_seconds: float) -> None:
        self._sleep = sleep_seconds
        self._active = 0
        self.max_active = 0
        self._lock = asyncio.Lock()

    async def execute(
        self, _task: store.ScientificTask, *, db_path: str | None = None
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
    """Long execution cannot be reclaimed after its original lease expires."""
    run = store.create_run("long worker goal", "standard", "engine", {})
    store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.test.long",
            inputs={},
            idempotency_key="long-engine-task",
        ),
        db_path=isolated_db,
    )
    release = asyncio.Event()

    async def _execute(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, bool]:
        await release.wait()
        store.update_run_status(run.id, store.RunStatus.COMPLETED)
        return {"completed": True}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)
    running = asyncio.create_task(
        task_worker.run_once(
            "worker-a", db_path=isolated_db, lease_seconds=0.06
        )
    )
    await asyncio.sleep(0.1)
    assert store.claim_task("worker-b", db_path=isolated_db) is None
    release.set()
    assert await running


@pytest.mark.asyncio
async def test_worker_cancels_execution_after_lease_revocation(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run cancellation interrupts an already executing specialist task."""
    run = store.create_run("cancel active work", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
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

    assert store.cancel_run_tasks(run.id, db_path=isolated_db) == 1
    assert await asyncio.wait_for(running, timeout=1)
    assert interrupted.is_set()
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "cancelled"


@pytest.mark.asyncio
async def test_embedded_worker_pool_executes_fanout_concurrently(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default embedded workers overlap independent specialist leases."""
    run = store.create_run("parallel goal", "standard", "engine", {})
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
    """An unsupported task fails without crashing the worker loop."""
    run = store.create_run("worker goal", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="unknown.task",
            inputs={},
            idempotency_key="unknown:0",
        ),
        db_path=isolated_db,
    )
    assert await task_worker.run_once("worker-a", db_path=isolated_db)
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "failed"
    assert "unsupported task type" in str(saved.error)


@pytest.mark.asyncio
async def test_transient_provider_failure_keeps_its_retry_budget(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty provider response must not burn the whole task.

    The engine raises a bare ValueError when a provider returns empty
    content -- a routine, transient DashScope hiccup. The worker classified
    every ValueError as non-retryable, so one empty response marked the task
    'failed' at attempt 1 of 3 with its budget untouched. Nothing requeues a
    failed task, so the run stopped dead until an app restart revived it,
    which is what produced hours of silence between bursts of progress.
    """
    run = store.create_run("Transient failure", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
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

    after = store.get_task(task.id, db_path=isolated_db)
    assert after is not None
    assert after.status == "queued", "a transient failure must stay retryable"
    assert after.attempt < after.max_attempts


@pytest.mark.asyncio
async def test_unsupported_task_type_is_still_permanent(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task no worker can execute must not be retried forever."""
    run = store.create_run("Bad task type", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
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

    after = store.get_task(task.id, db_path=isolated_db)
    assert after is not None
    assert after.status == "failed", "an unknown task type is not retryable"


@pytest.mark.asyncio
async def test_default_worker_cohort_overlaps_more_than_four_leases(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default cohort is sized for the provider, not for caution.

    Measured against the production model, twenty-four concurrent
    completions finish in the same wall clock as four -- latency is flat and
    throughput scales linearly, so a cohort of four left most of a run's
    fan-out sitting in the queue for no reason. Every item here is an
    independent durable task, so widening the cohort changes only how many
    run at once, never what any of them produces.
    """
    run = store.create_run("wide fanout", "standard", "engine", {})
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
    """A long lease must not cost one database write per second.

    The heartbeat wakes every second so cancellation is noticed promptly,
    but that is an in-memory event: only the lease renewal touches the
    database, and a 300-second lease does not need renewing every second.
    Written per poll it becomes a steady write stream per in-flight task,
    and SQLite's single writer has no fair queuing -- with a cohort of them
    the stream starved ordinary API writes until creating a run failed
    outright with "database is locked".
    """
    run = store.create_run("heartbeat cost", "standard", "engine", {})
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

    # A 300s lease is renewed on its own schedule; 2.5 seconds of polling
    # owes the database nothing.
    count = renewals["renewals"]
    assert count == 0, f"{count} lease writes in 2.5s of polling"


def test_idle_claim_does_not_contend_for_the_write_lock(
    isolated_db: str,
) -> None:
    """Finding no work must not require taking the single write lock.

    Every worker in every run's cohort polls for work several times a
    second. Opening a write transaction just to discover the queue is empty
    turns an idle cohort into a write-lock storm -- hundreds of no-op
    BEGIN IMMEDIATEs a second, changing no rows. The database looks idle
    while ordinary API writes exhaust their 30-second busy timeout, which is
    exactly how production started returning 500 from run creation with the
    embedded worker on, and stopped the moment it was turned off.
    """
    import sqlite3
    import time as _time

    # Open the store once so schema init (itself a write) is already done
    # and the lock below is contended only by the claim under test.
    assert store.claim_task("warmup", db_path=isolated_db) is None

    # Someone else holds the write lock; an idle claim must not want it.
    blocker = sqlite3.connect(isolated_db, timeout=0.5, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        started = _time.monotonic()
        assert store.claim_task("idle-worker", db_path=isolated_db) is None
        assert _time.monotonic() - started < 1.0
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()


def test_idle_wait_does_not_decode_every_task(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Waiting on the cohort must not scan the whole task table.

    Every idle worker asks "is anyone still working?" twenty times a second.
    Answering it by listing and decoding every row of the run's task table
    costs more the further a run gets -- a late-stage run has hundreds of
    rows, and the cohort was widened to eight, so it is thousands of row
    decodes a second spent to compute a single boolean.
    """
    run = store.create_run("idle wait cost", "standard", "engine", {})
    for index in range(30):
        store.enqueue_task(
            store.NewTask(
                run_id=run.id,
                task_type=f"engine.test.{index}",
                inputs={},
                idempotency_key=f"idle:{index}",
            ),
            db_path=isolated_db,
        )
    calls = 0
    real_list = store.list_tasks

    def _counting_list(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_list(*args, **kwargs)

    monkeypatch.setattr(store, "list_tasks", _counting_list)

    claimable, active, _park = store.cohort_poll(run.id, db_path=isolated_db)
    assert claimable is True and active is False
    assert calls == 0


# ``LLMCallBudgetExceededError`` is a permanent, plainly-named failure.
#
# Mirrors ``test_engine_tasks_portfolio_cancel.py::
# test_a_permanent_failure_cancels_the_downstream_chain``: a task failing
# this way must not keep its retry budget (it is one of the two permanent
# failures ``_handle_task_failure`` classifies, alongside
# ``UnsupportedTaskError``), and the run's settled failure reason must say
# plainly that the run hit its LLM-call ceiling rather than reading as a
# generic task failure.


def test_ceiling_exceeded_fails_permanently_and_settles_the_run(
    isolated_db: str,
) -> None:
    run = store.create_run("LLM budget ceiling", "standard", "engine", {})
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
            # A generous retry budget: a permanent failure must not
            # consume it one attempt at a time, so if the classification
            # regressed to the retryable branch this would still read
            # "queued" for retry rather than "failed" below.
            max_attempts=5,
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == task.id

    error = LLMCallBudgetExceededError(count=2501, ceiling=2500)
    task_worker_outcomes._handle_task_failure(
        leased, "worker", error, isolated_db
    )

    task_after = store.get_task(task.id, db_path=isolated_db)
    assert task_after is not None
    assert task_after.status == "failed", (
        "a ceiling breach must fail outright, not requeue for retry"
    )
    assert task_after.attempt < task_after.max_attempts, (
        "it must not have burned through the retry budget to get there"
    )

    settled = store.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == store.RunStatus.FAILED.value
    assert settled.error is not None
    assert "LLM-call ceiling exceeded" in settled.error
    assert "2501" in settled.error and "2500" in settled.error, (
        "the user-visible reason must name the count and the ceiling, "
        "not read as a generic task failure"
    )


def test_ceiling_exceeded_releases_the_runs_counter(
    isolated_db: str,
) -> None:
    run = store.create_run("LLM budget release", "standard", "engine", {})
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
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


# A platform rate-limit cap parks a task instead of failing it.
#
# Mirrors ``test_task_worker_outcomes_llm_budget.py``'s shape: this is the
# opposite outcome from that permanent failure -- ``LLMRateLimitParkError``
# must not spend the task's retry budget and must not settle the run, only
# make the row wait until the provider's own cap resets.


def _advance_clock(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """Move the store's clock forward by ``seconds``, ticking every call."""
    real_now = store_db._now()
    monkeypatch.setattr("app.store.db.time.time", lambda: real_now + seconds)


def test_rate_limit_park_requeues_without_spending_an_attempt(
    isolated_db: str,
) -> None:
    run = store.create_run("Rate limit park", "standard", "engine", {})
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
            max_attempts=3,
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == task.id
    assert leased.attempt == 1

    now = store_db._now()
    resume_at = now + 3600
    error = LLMRateLimitParkError(resume_at=resume_at, reason="message_per_day")

    task_worker_outcomes._handle_task_failure(
        leased, "worker", error, isolated_db
    )

    parked = store.get_task(task.id, db_path=isolated_db)
    assert parked is not None
    assert parked.status == "queued", "a platform cap must not fail the task"
    assert parked.attempt == 0, "parking must not consume an attempt"
    assert parked.lease_owner is None
    assert parked.available_at is not None
    # Jittered forward from resume_at, never before it.
    assert resume_at <= parked.available_at <= resume_at + 15

    # Not claimable yet: the clock has not reached available_at.
    reclaim = store.claim_task("worker2", run_id=run.id, db_path=isolated_db)
    assert reclaim is None

    # The run itself must not have settled -- it is waiting, not done.
    still_running = store.get_run(run.id, db_path=isolated_db)
    assert still_running is not None
    assert still_running.status == store.RunStatus.RUNNING.value

    # The park is recorded in the attempt history for the tasks endpoint.
    assert parked.attempts, "the park must be visible in attempt history"
    last_attempt = parked.attempts[-1]
    assert last_attempt["retryable"] is True
    assert "message_per_day" in last_attempt["error"]


def test_rate_limit_park_becomes_claimable_once_due(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = store.create_run("Rate limit park due", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None

    resume_at = store_db._now() + 60
    ok = store.park_task_for_rate_limit(
        task.id, "worker", "rate limited", resume_at, db_path=isolated_db
    )
    assert ok

    reclaim = store.claim_task("worker2", run_id=run.id, db_path=isolated_db)
    assert reclaim is None

    _advance_clock(monkeypatch, 61)

    reclaimed = store.claim_task("worker2", run_id=run.id, db_path=isolated_db)
    assert reclaimed is not None and reclaimed.id == task.id


async def test_cohort_keeps_polling_over_a_parked_task_instead_of_exiting(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The idle loop must not read a park as "no work" and exit.

    A parked row is ``queued`` with a future ``available_at``: not
    claimable, and not a live lease either (the lease was released on
    park). Without the third ``cohort_poll`` answer this reads as no work
    at all, the cohort exits, and nothing is left polling to notice the
    row becomes due -- exactly the strand this feature exists to prevent.
    """
    run = store.create_run("Rate limit park cohort", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="generate:seed",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    resume_at = store_db._now() + 3600
    ok = store.park_task_for_rate_limit(
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
    # Bounded well under the hour-plus wait for resume_at: the park path
    # sleeps a short capped interval and re-checks, never the raw gap.
    assert slept[0] <= task_worker._PARKED_POLL_SECONDS


# Resume and recovery tests for the durable workflow worker.


@dataclass(frozen=True)
class _ResumeShape:
    """The optional shape of a saved resume checkpoint.

    Attributes:
        stage: Stage name written on the checkpoint row.
        last_event_seq: Event high-water mark the checkpoint records.
        provider: Provider tag to write, or ``None`` to omit it.
    """

    stage: str = "post_generation"
    last_event_seq: int = 1
    provider: str | None = None


def _save_resume_checkpoint(
    run_id: str,
    successor: str,
    db: str,
    shape: _ResumeShape | None = None,
) -> None:
    """Save a checkpoint that records ``successor`` as the resume target."""
    shape = shape or _ResumeShape()
    state: dict[str, Any] = {"resume_successor": successor}
    if shape.provider is not None:
        state["provider"] = shape.provider
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
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
    """Force a task into the leased state held by ``owner``."""
    extra = ", attempt=max_attempts" if spend_budget else ""
    with store.connect(db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner=?, "
            f"lease_expires_at=?{extra} WHERE id=?",
            (owner, expires_at, task_id),
        )


def test_resume_uses_recorded_successor_not_orchestrator_default(
    isolated_db: str,
) -> None:
    """A crash-resume re-enters at the checkpoint's recorded successor.

    Regression: a run interrupted right after bootstrap held only the
    bootstrap checkpoint, whose state has no supervisor_guidance. Resume
    defaulted to the orchestrator, which routed straight into generation and
    raised GenerationError('No supervisor_guidance in state'). Bootstrap's
    checkpoint now records resume_successor=engine.supervisor, and resume must
    honour it. The idempotency key matches the successor bootstrap already
    enqueued, so no duplicate task is created.
    """
    supervisor_type = f"{engine_tasks.NODE_TASK_PREFIX}supervisor"
    run = store.create_run("worker goal", "standard", "engine", {})
    # The successor bootstrap enqueues in the same commit as its checkpoint.
    enqueued = store.enqueue_task(
        store.NewTask(
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
    """A checkpoint without a recorded successor keeps the legacy default.

    Older checkpoints (pre-fix) and the fan-out planning checkpoints do not
    record a successor; by then supervisor_guidance is in state, so the
    orchestrator re-entry is valid and must be preserved.
    """
    run = store.create_run("worker goal", "standard", "engine", {})
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
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
    """A queued fan-out wave is already the continuation for its checkpoint."""
    run = store.create_run("paused fanout", "standard", "engine", {})
    parent = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:generate-parent",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task(
        "parent-worker", run_id=run.id, db_path=isolated_db
    )
    assert leased is not None and leased.id == parent.id
    assert store.complete_task(
        parent.id, "parent-worker", {}, db_path=isolated_db
    )
    store.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task:{parent.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine"},
        ),
        db_path=isolated_db,
    )

    # A stale queued lookahead from another checkpoint must not mask the
    # actual fan-out rows attached to the newest checkpoint.
    stale = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}review",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:stale-lookahead",
            provenance={"scheduled_by": "engine.node.old"},
        ),
        db_path=isolated_db,
    )
    fanout = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.fanout.generation.strategy",
            inputs={"checkpoint_seq": 1},
            idempotency_key="generation:debate_only:1:0:1",
            dependencies=(parent.id,),
            provenance={"scheduled_by": parent.task_type},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.id == fanout.id
    assert resumed.id != stale.id
    assert not any(
        task.task_type == f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
        and task.status == "queued"
        for task in store.list_tasks(run.id, db_path=isolated_db)
    )


def _wedge_task_at(
    run_id: str, task_type: str, checkpoint_seq: int, status: str, db: str
) -> str:
    """Leave the boundary's task in a terminal, unclaimable state.

    Reproduces what the disk-full outage did in production: the boundary's
    task burned its retry budget and settled as ``failed``.
    """
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{task_type}:{checkpoint_seq}",
        ),
        db_path=db,
    )
    with store.connect(db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status=?, attempt=max_attempts "
            "WHERE id=?",
            (status, task.id),
        )
    return task.id


def _queued(run_id: str, db: str) -> list[Any]:
    return [
        t for t in store.list_tasks(run_id, db_path=db) if t.status == "queued"
    ]


@pytest.mark.parametrize("dead_status", ["failed", "cancelled"])
def test_resume_revives_a_boundary_whose_task_died(
    isolated_db: str, dead_status: str
) -> None:
    """A resume must give a dead boundary a fresh attempt, not silently no-op.

    Regression: the resume enqueue is idempotent on
    ``{task_type}:{checkpoint_seq}``, and that key cannot change while the run
    makes no progress -- the checkpoint it names is exactly the one it failed
    at. Once that task reached a terminal state, every later resume hit
    ON CONFLICT DO NOTHING and enqueued nothing, so the worker had nothing to
    claim. In production the run announced "resuming from specialist
    checkpoint" on every restart and then sat silent forever: no LLM call, no
    tool call, no task ever leased. Neither escape hatch reached it either --
    resume_run_tasks only requeues 'paused', and claim_task's expired-lease
    rescue skips tasks whose attempts are spent.
    """
    run = store.create_run("wedged goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
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

    # The boundary is runnable again, with a budget to run on.
    queued = _queued(run.id, isolated_db)
    assert len(queued) == 1
    assert queued[0].id == task_id
    assert queued[0].task_type == task_type
    assert queued[0].attempt < queued[0].max_attempts


def test_resume_does_not_rerun_completed_work(isolated_db: str) -> None:
    """A boundary that already succeeded is left alone.

    Reviving it would redo work the run has already paid for and committed.
    """
    run = store.create_run("done goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
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
    """A resume rescues a boundary whose worker died holding it.

    Regression, and the state production actually reached: the run's
    engine.node.ranking task sat 'leased' by a process that no longer existed.
    Every recovery path declined it -- claim_task requeues expired leases only
    "unless their retry budget is spent", resume_run_tasks handles just
    'paused', and the resume enqueue collided with the existing row. The run
    announced "resuming from specialist checkpoint" on every restart for
    hours and never leased a task.
    """
    run = store.create_run("stranded goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    _save_resume_checkpoint(run.id, task_type, isolated_db)
    task = store.enqueue_task(
        store.NewTask(
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
    """A boundary another worker is actively running is not stolen.

    Only an *expired* lease means its owner is gone. Reviving a live one
    would run the same boundary twice concurrently.
    """
    run = store.create_run("busy goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="post_generation",
            schema_version=1,
            last_event_seq=1,
            state={"resume_successor": task_type},
        ),
        db_path=isolated_db,
    )
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=task_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{task_type}:1",
        ),
        db_path=isolated_db,
    )
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner='alive', "
            "lease_expires_at=? WHERE id=?",
            (time.time() + 3600, task.id),
        )

    task_worker.enqueue_run_workflow(run.id, resume=True, db_path=isolated_db)

    assert not _queued(run.id, isolated_db)
    with store.connect(isolated_db) as conn:
        row = conn.execute(
            "SELECT status, lease_owner FROM scientific_tasks WHERE id=?",
            (task.id,),
        ).fetchone()
    assert (row["status"], row["lease_owner"]) == ("leased", "alive")

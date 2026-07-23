"""Lease, heartbeat, retry, and concurrency tests for the durable worker.

Enqueue/resume/shutdown semantics live in ``test_task_worker.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import engine_tasks, store, task_worker


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


def _enqueue_one(run_id: str, task_type: str, key: str, db_path: str) -> Any:
    """Enqueue a single specialist task with the given idempotency key."""
    return store.enqueue_task(
        store.NewTask(
            run_id=run_id, task_type=task_type, inputs={}, idempotency_key=key
        ),
        db_path=db_path,
    )


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
    task = _enqueue_one(
        run.id, "engine.test.heartbeat", "heartbeat:0", isolated_db
    )
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

    claimable, active = store.cohort_poll(run.id, db_path=isolated_db)
    assert claimable is True and active is False
    assert calls == 0

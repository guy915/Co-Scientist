"""Tests for the standalone durable workflow worker."""

from __future__ import annotations

import asyncio
import time
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
        run.id,
        supervisor_type,
        {"checkpoint_seq": 1},
        idempotency_key=f"{supervisor_type}:1",
        db_path=isolated_db,
    )
    store.save_checkpoint(
        run.id,
        stage="engine_task:bootstrap",
        schema_version=1,
        last_event_seq=0,
        state={
            "provider": "engine",
            "resume_successor": supervisor_type,
        },
        db_path=isolated_db,
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
        stage="engine_task:orchestrator",
        schema_version=1,
        last_event_seq=0,
        state={"provider": "engine"},
        db_path=isolated_db,
    )

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.task_type == f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"


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
        run.id,
        "run.workflow",
        {},
        idempotency_key="legacy-workflow",
        db_path=isolated_db,
    )

    async def _workflow(**_kwargs: Any) -> Any:
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
        run.id,
        "engine.test.superseded",
        {},
        idempotency_key="superseded",
        max_attempts=3,
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
async def test_worker_heartbeats_long_workflow_lease(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Long execution cannot be reclaimed after its original lease expires."""
    run = store.create_run("long worker goal", "standard", "engine", {})
    store.enqueue_task(
        run.id,
        "run.workflow",
        {},
        idempotency_key="legacy-long-workflow",
        db_path=isolated_db,
    )
    release = asyncio.Event()

    async def _workflow(**_kwargs: Any) -> Any:
        await release.wait()
        store.update_run_status(run.id, store.RunStatus.COMPLETED)
        if False:
            yield None

    monkeypatch.setattr(engine_adapter, "run_workflow", _workflow)
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
        run.id,
        "engine.test.cancellable",
        {},
        idempotency_key="cancellable",
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
async def test_worker_shutdown_cancels_task_payload(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling the worker does not orphan its provider coroutine."""
    run = store.create_run("worker shutdown", "standard", "engine", {})
    store.enqueue_task(
        run.id,
        "engine.test.shutdown",
        {},
        idempotency_key="shutdown",
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


@pytest.mark.asyncio
async def test_embedded_worker_pool_executes_fanout_concurrently(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default embedded workers overlap independent specialist leases."""
    run = store.create_run("parallel goal", "standard", "engine", {})
    for index in range(4):
        store.enqueue_task(
            run.id,
            f"engine.test.{index}",
            {},
            idempotency_key=f"parallel:{index}",
            db_path=isolated_db,
        )
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def _execute(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, bool]:
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.03)
        async with lock:
            active -= 1
        return {"completed": True}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)

    await task_worker.run_run_worker_pool(
        run.id,
        "embedded-test",
        worker_count=4,
        db_path=isolated_db,
        lease_seconds=1,
    )

    assert max_active == 4
    assert {
        task.status for task in store.list_tasks(run.id, db_path=isolated_db)
    } == {"completed"}


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
async def test_worker_isolates_unknown_task_failure(isolated_db: str) -> None:
    """An unsupported task fails without crashing the worker loop."""
    run = store.create_run("worker goal", "standard", "engine", {})
    task = store.enqueue_task(
        run.id,
        "unknown.task",
        {},
        idempotency_key="unknown:0",
        db_path=isolated_db,
    )
    assert await task_worker.run_once("worker-a", db_path=isolated_db)
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "failed"
    assert "unsupported task type" in str(saved.error)


@pytest.mark.asyncio
async def test_worker_delivers_opted_in_completion_email(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A notification task is durable and commits its SMTP delivery result."""
    run = store.create_run("notification goal", "standard", "engine", {})
    task = store.enqueue_task(
        run.id,
        "notification.email",
        {"run_id": run.id, "email": "scientist@example.org", "title": "Result"},
        idempotency_key="email:1",
        max_attempts=3,
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


def _wedge_task_at(
    run_id: str, task_type: str, checkpoint_seq: int, status: str, db: str
) -> str:
    """Leave the boundary's task in a terminal, unclaimable state.

    Reproduces what the disk-full outage did in production: the boundary's
    task burned its retry budget and settled as ``failed``.
    """
    task = store.enqueue_task(
        run_id,
        task_type,
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key=f"{task_type}:{checkpoint_seq}",
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
        stage="post_generation",
        schema_version=1,
        last_event_seq=1,
        state={"resume_successor": task_type},
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
        stage="post_generation",
        schema_version=1,
        last_event_seq=1,
        state={"resume_successor": task_type},
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
    store.save_checkpoint(
        run.id,
        stage="post_generation",
        schema_version=1,
        last_event_seq=1,
        state={"resume_successor": task_type},
        db_path=isolated_db,
    )
    task = store.enqueue_task(
        run.id,
        task_type,
        {"checkpoint_seq": 1},
        idempotency_key=f"{task_type}:1",
        db_path=isolated_db,
    )
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner='dead', "
            "lease_expires_at=?, attempt=max_attempts WHERE id=?",
            (time.time() - 3600, task.id),
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
        stage="post_generation",
        schema_version=1,
        last_event_seq=1,
        state={"resume_successor": task_type},
        db_path=isolated_db,
    )
    task = store.enqueue_task(
        run.id,
        task_type,
        {"checkpoint_seq": 1},
        idempotency_key=f"{task_type}:1",
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
        run.id,
        "engine.node.ranking",
        {},
        idempotency_key="transient-1",
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
        run.id,
        "engine.node.ranking",
        {},
        idempotency_key="unsupported-1",
        db_path=isolated_db,
    )

    async def unsupported(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise task_worker.UnsupportedTaskError("unsupported task type: nope")

    monkeypatch.setattr(task_worker, "_execute_task_payload", unsupported)
    assert await task_worker.run_once("w1", run_id=run.id, db_path=isolated_db)

    after = store.get_task(task.id, db_path=isolated_db)
    assert after is not None
    assert after.status == "failed", "an unknown task type is not retryable"

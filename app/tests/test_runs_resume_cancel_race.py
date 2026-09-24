"""Cancellation wins when it commits before an admitted resume is queued."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from typing import Any

import pytest

from app import engine_tasks, store, task_worker
from app.config import settings
from app.store import NewCheckpoint, NewTask, RunStatus, ScientificTask
from tests._client import make_client


def _checkpointed_run(db: str, client: Any) -> tuple[str, str]:
    """Create a progressed run whose exact checkpoint successor is durable."""
    response = client.post(
        "/api/runs",
        json={"research_goal": "Resume/cancel ordering", "tier": "express"},
    )
    assert response.status_code == 200, response.text
    run_id = str(response.json()["id"])
    store.update_run_status(run_id, RunStatus.RUNNING, db_path=db)

    writer_type = f"{engine_tasks.NODE_TASK_PREFIX}generate"
    writer = store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=writer_type,
            inputs={"checkpoint_seq": 0},
            idempotency_key="resume-cancel:writer",
        ),
        db_path=db,
    )
    claimed = store.claim_task("checkpoint-writer", run_id=run_id, db_path=db)
    assert claimed is not None and claimed.id == writer.id
    assert store.complete_task(writer.id, "checkpoint-writer", {}, db_path=db)

    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    checkpoint_seq = store.save_checkpoint(
        run_id,
        NewCheckpoint(
            stage=f"engine_task:{writer.id}",
            schema_version=1,
            last_event_seq=0,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=db,
    )
    successor = store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=successor_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{successor_type}:after:{writer.id}",
            dependencies=(writer.id,),
            provenance={"scheduled_by": writer_type},
        ),
        db_path=db,
    )
    return run_id, successor.id


def test_cancel_wins_when_it_commits_before_resume_enqueue(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale resume admission cannot reverse cancellation or revive work."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    run_id, successor_id = _checkpointed_run(isolated_db, owner)
    assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200

    foreign = make_client()
    foreign_headers = {"X-Client-ID": "resume-cancel-foreign"}
    assert (
        foreign.post(
            f"/api/runs/{run_id}/resume", headers=foreign_headers
        ).status_code
        == 404
    )
    assert (
        foreign.post(
            f"/api/runs/{run_id}/cancel", headers=foreign_headers
        ).status_code
        == 404
    )

    from app import runs_lifecycle

    queue_reached = Event()
    release_queue = Event()
    original_queue = runs_lifecycle._queue_resume_workflow

    def hold_resume_before_enqueue(*args: Any, **kwargs: Any) -> ScientificTask:
        queue_reached.set()
        assert release_queue.wait(timeout=5), "resume barrier was not released"
        return original_queue(*args, **kwargs)

    monkeypatch.setattr(
        runs_lifecycle, "_queue_resume_workflow", hold_resume_before_enqueue
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        resume_future = pool.submit(owner.post, f"/api/runs/{run_id}/resume")
        assert queue_reached.wait(timeout=5), (
            "resume did not reach enqueue boundary"
        )
        cancelled = owner.post(f"/api/runs/{run_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        release_queue.set()
        resumed = resume_future.result(timeout=5)

    run = store.get_run(run_id, db_path=isolated_db)
    task = store.get_task(successor_id, db_path=isolated_db)
    events = store.list_events(run_id, db_path=isolated_db)
    assert resumed.status_code == 409, (
        f"resume returned {resumed.status_code}; run status is "
        f"{run.status if run else None}; task is "
        f"{task.status if task else None}; lifecycle events are "
        f"{[(event['type'], event['payload']) for event in events]}"
    )
    assert run is not None and run.status == RunStatus.CANCELLED.value
    assert task is not None and task.status == "cancelled"
    cancelled_seq = next(
        event["seq"]
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    assert not any(
        event["type"] == "status"
        and event["payload"].get("status") == "resuming"
        and event["seq"] > cancelled_seq
        for event in events
    )
    assert (
        store.claim_task("after-cancel", run_id=run_id, db_path=isolated_db)
        is None
    )

    # A new, explicit request admitted after cancellation remains supported.
    later_resume = owner.post(f"/api/runs/{run_id}/resume")
    assert later_resume.status_code == 200, later_resume.text
    later_task = store.get_task(successor_id, db_path=isolated_db)
    assert later_task is not None
    assert later_task.task_type == f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    assert later_task.status == "queued"
    assert later_task.dependencies == (task.dependencies[0],)
    claimed_later = store.claim_task(
        "later-resume-worker", run_id=run_id, db_path=isolated_db
    )
    assert claimed_later is not None and claimed_later.id == successor_id


def test_resume_transaction_commits_before_waiting_cancel(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancellation waiting on resume admission still wins afterward."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    cancel_client = make_client()
    run_id, successor_id = _checkpointed_run(isolated_db, owner)
    assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200

    enqueue_entered = Event()
    release_enqueue = Event()
    observe_cancel = Event()
    cancel_transaction_entered = Event()
    original_enqueue = task_worker.enqueue_run_workflow
    original_transaction = store.transaction

    @contextmanager
    def track_cancel_transaction(
        path: str | None = None,
    ) -> Iterator[sqlite3.Connection]:
        if observe_cancel.is_set():
            cancel_transaction_entered.set()
        with original_transaction(path) as conn:
            yield conn

    def hold_resume_transaction(*args: Any, **kwargs: Any) -> ScientificTask:
        enqueue_entered.set()
        assert release_enqueue.wait(timeout=5), (
            "resume transaction was not released"
        )
        return original_enqueue(*args, **kwargs)

    monkeypatch.setattr(store, "transaction", track_cancel_transaction)
    monkeypatch.setattr(
        task_worker,
        "enqueue_run_workflow",
        hold_resume_transaction,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        resume_future = pool.submit(owner.post, f"/api/runs/{run_id}/resume")
        assert enqueue_entered.wait(timeout=5), (
            "resume did not enter its transaction"
        )
        observe_cancel.set()
        cancel_future = pool.submit(
            cancel_client.post, f"/api/runs/{run_id}/cancel"
        )
        try:
            assert cancel_transaction_entered.wait(timeout=5)
        finally:
            release_enqueue.set()
        resumed = resume_future.result(timeout=5)
        cancelled = cancel_future.result(timeout=5)

    assert resumed.status_code == 200, resumed.text
    assert cancelled.status_code == 200, cancelled.text
    run = store.get_run(run_id, db_path=isolated_db)
    task = store.get_task(successor_id, db_path=isolated_db)
    events = store.list_events(run_id, db_path=isolated_db)
    assert run is not None and run.status == RunStatus.CANCELLED.value
    assert task is not None and task.status == "cancelled"
    resuming_seq = next(
        event["seq"]
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "resuming"
    )
    cancelled_seq = next(
        event["seq"]
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    assert resuming_seq < cancelled_seq
    assert (
        store.claim_task(
            "after-waiting-cancel", run_id=run_id, db_path=isolated_db
        )
        is None
    )


def test_lifecycle_revision_rejects_paused_cancel_resume_pause_aba(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale PAUSED admission cannot pass after a full status ABA cycle."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    later_resumer = make_client()
    run_id, successor_id = _checkpointed_run(isolated_db, owner)
    assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200

    from app import runs_lifecycle

    first_queue_reached = Event()
    release_first_queue = Event()
    original_queue = runs_lifecycle._queue_resume_workflow
    calls = 0

    def hold_first_resume(*args: Any, **kwargs: Any) -> ScientificTask:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_queue_reached.set()
            assert release_first_queue.wait(timeout=5)
        return original_queue(*args, **kwargs)

    monkeypatch.setattr(
        runs_lifecycle, "_queue_resume_workflow", hold_first_resume
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale_resume = pool.submit(owner.post, f"/api/runs/{run_id}/resume")
        assert first_queue_reached.wait(timeout=5)
        assert owner.post(f"/api/runs/{run_id}/cancel").status_code == 200
        later = later_resumer.post(f"/api/runs/{run_id}/resume")
        assert later.status_code == 200, later.text
        assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200
        release_first_queue.set()
        stale = stale_resume.result(timeout=5)

    assert stale.status_code == 409, stale.text
    run = store.get_run(run_id, db_path=isolated_db)
    task = store.get_task(successor_id, db_path=isolated_db)
    events = store.list_events(run_id, db_path=isolated_db)
    assert run is not None and run.status == RunStatus.PAUSED.value
    assert task is not None and task.status == "paused"
    assert not any(
        event["type"] == "status"
        and event["payload"].get("status") == "resuming"
        and event["seq"]
        > max(
            event["seq"]
            for event in events
            if event["type"] == "lifecycle"
            and event["payload"].get("event") == "pause_requested"
        )
        for event in events
    )
    assert (
        store.claim_task("after-aba", run_id=run_id, db_path=isolated_db)
        is None
    )


def test_legacy_cleanup_waits_until_resume_status_guard(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A losing legacy resume leaves checkpoints and audit events intact."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    created = owner.post(
        "/api/runs",
        json={"research_goal": "Legacy resume cancellation", "tier": "express"},
    )
    assert created.status_code == 200
    run_id = str(created.json()["id"])
    store.update_run_status(run_id, RunStatus.RUNNING, db_path=isolated_db)
    task = store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}orchestrator",
            inputs={},
            idempotency_key="legacy-resume:orchestrator",
        ),
        db_path=isolated_db,
    )
    checkpoint_seq = store.save_checkpoint(
        run_id,
        NewCheckpoint(
            stage="legacy-envelope",
            schema_version=1,
            last_event_seq=0,
            state={"legacy": True},
        ),
        db_path=isolated_db,
    )
    store.append_event(
        run_id, "fixture.marker", {"keep": True}, db_path=isolated_db
    )
    assert checkpoint_seq > 0
    assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200

    from app import runs_lifecycle

    queue_reached = Event()
    release_queue = Event()
    original_queue = runs_lifecycle._queue_resume_workflow

    def hold_resume_before_cleanup(*args: Any, **kwargs: Any) -> ScientificTask:
        queue_reached.set()
        assert release_queue.wait(timeout=5)
        return original_queue(*args, **kwargs)

    monkeypatch.setattr(
        runs_lifecycle, "_queue_resume_workflow", hold_resume_before_cleanup
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        resume_future = pool.submit(owner.post, f"/api/runs/{run_id}/resume")
        assert queue_reached.wait(timeout=5)
        assert owner.post(f"/api/runs/{run_id}/cancel").status_code == 200
        release_queue.set()
        resumed = resume_future.result(timeout=5)

    assert resumed.status_code == 409, resumed.text
    run = store.get_run(run_id, db_path=isolated_db)
    task_after = store.get_task(task.id, db_path=isolated_db)
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    events = store.list_events(run_id, db_path=isolated_db)
    assert run is not None and run.status == RunStatus.CANCELLED.value
    assert task_after is not None and task_after.status == "cancelled"
    assert checkpoint is not None and checkpoint["state"] == {"legacy": True}
    assert any(event["type"] == "fixture.marker" for event in events)
    assert (
        store.claim_task(
            "after-legacy-cancel", run_id=run_id, db_path=isolated_db
        )
        is None
    )


def test_startup_resume_skips_cancelled_run_after_admission_race(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Startup's active-status snapshot cannot requeue a later cancellation."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    run_id, successor_id = _checkpointed_run(isolated_db, owner)

    from app import runs_lifecycle

    queue_reached = Event()
    release_queue = Event()
    original_queue = runs_lifecycle._queue_resume_workflow

    def hold_startup_before_enqueue(
        *args: Any, **kwargs: Any
    ) -> ScientificTask:
        queue_reached.set()
        assert release_queue.wait(timeout=5)
        return original_queue(*args, **kwargs)

    monkeypatch.setattr(
        runs_lifecycle, "_queue_resume_workflow", hold_startup_before_enqueue
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        startup = pool.submit(
            asyncio.run, runs_lifecycle.resume_interrupted_runs([run_id])
        )
        assert queue_reached.wait(timeout=5)
        assert owner.post(f"/api/runs/{run_id}/cancel").status_code == 200
        release_queue.set()
        startup.result(timeout=5)

    run = store.get_run(run_id, db_path=isolated_db)
    task = store.get_task(successor_id, db_path=isolated_db)
    events = store.list_events(run_id, db_path=isolated_db)
    assert run is not None and run.status == RunStatus.CANCELLED.value
    assert task is not None and task.status == "cancelled"
    cancelled_seq = next(
        event["seq"]
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    assert not any(
        event["type"] == "status"
        and event["payload"].get("status") == "resuming"
        and event["seq"] > cancelled_seq
        for event in events
    )
    assert (
        store.claim_task(
            "after-startup-cancel", run_id=run_id, db_path=isolated_db
        )
        is None
    )


def test_adjudication_rejection_does_not_overwrite_cancel(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected hold cannot write BLOCKED after cancellation commits."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    created = owner.post(
        "/api/runs",
        json={
            "research_goal": "Safety rejection cancellation",
            "tier": "express",
        },
    )
    assert created.status_code == 200
    run_id = str(created.json()["id"])
    store.update_run_status(run_id, RunStatus.PAUSED, db_path=isolated_db)
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run_id,
            stage="intake",
            decision="hold",
            reason="Needs review",
            matches=[],
            category="uncertain",
            policy_version="coscientist-safety-v2",
            requires_review=True,
        ),
        db_path=isolated_db,
    )
    [decision] = store.list_safety_decisions(run_id, db_path=isolated_db)
    decision_id = int(decision["id"])

    resolved = Event()
    release_adjudication = Event()
    original_resolve = store.resolve_safety_decision

    def resolve_then_wait(*args: Any, **kwargs: Any) -> bool:
        result = original_resolve(*args, **kwargs)
        resolved.set()
        assert release_adjudication.wait(timeout=5)
        return result

    monkeypatch.setattr(store, "resolve_safety_decision", resolve_then_wait)
    with ThreadPoolExecutor(max_workers=1) as pool:
        adjudication = pool.submit(
            owner.post,
            f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
            json={"resolution": "rejected"},
        )
        assert resolved.wait(timeout=5)
        assert owner.post(f"/api/runs/{run_id}/cancel").status_code == 200
        release_adjudication.set()
        response = adjudication.result(timeout=5)

    assert response.status_code == 409, response.text
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == RunStatus.CANCELLED.value
    [decision] = store.list_safety_decisions(run_id, db_path=isolated_db)
    assert decision["resolution"] == "rejected"

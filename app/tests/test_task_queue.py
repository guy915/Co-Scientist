"""Behavior tests for the durable scientific task queue."""

from __future__ import annotations

import time

from app import store


def _run() -> str:
    return store.create_run("queue goal", "standard", "engine", {}).id


def test_enqueue_is_idempotent(isolated_db: str) -> None:
    """Duplicate Supervisor delivery resolves to one durable task."""
    run_id = _run()
    first = store.enqueue_task(
        run_id,
        "generation.observation",
        {"branch": "a"},
        idempotency_key="generation:a:0",
        db_path=isolated_db,
    )
    duplicate = store.enqueue_task(
        run_id,
        "generation.observation",
        {"branch": "changed"},
        idempotency_key="generation:a:0",
        db_path=isolated_db,
    )
    assert duplicate.id == first.id
    assert duplicate.inputs == {"branch": "a"}
    assert len(store.list_tasks(run_id, db_path=isolated_db)) == 1


def test_claim_respects_priority_and_dependencies(isolated_db: str) -> None:
    """Workers lease only ready tasks and prefer Supervisor priority."""
    run_id = _run()
    prerequisite = store.enqueue_task(
        run_id,
        "retrieval.pubmed",
        {},
        idempotency_key="retrieval:0",
        priority=1,
        db_path=isolated_db,
    )
    store.enqueue_task(
        run_id,
        "reflection.full",
        {},
        idempotency_key="review:0",
        priority=100,
        dependencies=[prerequisite.id],
        db_path=isolated_db,
    )
    leased = store.claim_task("worker-a", run_id=run_id, db_path=isolated_db)
    assert leased is not None
    assert leased.id == prerequisite.id
    assert store.complete_task(
        leased.id, "worker-a", {"evidence": 2}, db_path=isolated_db
    )
    review = store.claim_task("worker-b", run_id=run_id, db_path=isolated_db)
    assert review is not None
    assert review.task_type == "reflection.full"


def test_completion_is_exactly_once(isolated_db: str) -> None:
    """A stale or duplicate delivery cannot commit a second result."""
    run_id = _run()
    task = store.enqueue_task(
        run_id,
        "ranking.debate",
        {},
        idempotency_key="match:a:b:0",
        db_path=isolated_db,
    )
    leased = store.claim_task("worker-a", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task.id
    assert store.complete_task(
        task.id, "worker-a", {"winner": "a"}, db_path=isolated_db
    )
    assert not store.complete_task(
        task.id, "worker-a", {"winner": "b"}, db_path=isolated_db
    )
    [saved] = store.list_tasks(run_id, db_path=isolated_db)
    assert saved.result == {"winner": "a"}


def test_expired_lease_is_recovered(isolated_db: str) -> None:
    """A worker crash releases its task through lease expiry."""
    run_id = _run()
    store.enqueue_task(
        run_id,
        "evolution.combine",
        {},
        idempotency_key="evolve:0",
        max_attempts=2,
        db_path=isolated_db,
    )
    first = store.claim_task(
        "dead-worker", lease_seconds=0.001, run_id=run_id, db_path=isolated_db
    )
    assert first is not None
    time.sleep(0.003)
    recovered = store.claim_task(
        "worker-b", run_id=run_id, db_path=isolated_db
    )
    assert recovered is not None
    assert recovered.id == first.id
    assert recovered.attempt == 2


def test_failure_retries_then_stops(isolated_db: str) -> None:
    """Transient failures retry only up to the task's declared limit."""
    run_id = _run()
    store.enqueue_task(
        run_id,
        "verification.deep",
        {},
        idempotency_key="verify:0",
        max_attempts=2,
        db_path=isolated_db,
    )
    first = store.claim_task("worker-a", run_id=run_id, db_path=isolated_db)
    assert first is not None
    assert store.fail_task(
        first.id, "worker-a", "timeout", db_path=isolated_db
    )
    second = store.claim_task("worker-b", run_id=run_id, db_path=isolated_db)
    assert second is not None and second.attempt == 2
    assert store.fail_task(
        second.id, "worker-b", "timeout", db_path=isolated_db
    )
    assert (
        store.claim_task("worker-c", run_id=run_id, db_path=isolated_db)
        is None
    )
    [saved] = store.list_tasks(run_id, db_path=isolated_db)
    assert saved.status == "failed"

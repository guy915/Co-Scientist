"""Shared fixtures for the durable task-queue suites.

Used by ``test_task_queue.py`` and ``test_task_queue_control.py``.
"""

from __future__ import annotations

from typing import Any

from app import store


def _run() -> str:
    return store.create_run("queue goal", "standard", "engine", {}).id


def _enqueue(
    run_id: str, task_type: str, key: str, db: str, **kwargs: Any
) -> Any:
    """Enqueue an empty-input task by type and idempotency key."""
    return store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={},
            idempotency_key=key,
            **kwargs,
        ),
        db_path=db,
    )


def _three_control_tasks(run_id: str, db: str) -> tuple[str, str, str]:
    """Enqueue promote/cancel/retry tasks and fail the retry one.

    Returns the ``(promoted, cancelled, failed)`` task ids.
    """
    promoted = _enqueue(
        run_id, "reflection.full", "control:promote", db, priority=1
    )
    cancelled = _enqueue(
        run_id, "generation.assumptions", "control:cancel", db, priority=2
    )
    failed = _enqueue(
        run_id,
        "verification.deep",
        "control:retry",
        db,
        priority=100,
        max_attempts=1,
    )
    leased = store.claim_task("failed-worker", run_id=run_id, db_path=db)
    assert leased is not None and leased.id == failed.id
    assert store.fail_task(
        failed.id,
        "failed-worker",
        "transient provider error",
        retryable=False,
        db_path=db,
    )
    return promoted.id, cancelled.id, failed.id

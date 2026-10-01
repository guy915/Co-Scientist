"""A platform rate-limit cap parks a task instead of failing it.

Mirrors ``test_task_worker_outcomes_llm_budget.py``'s shape: this is the
opposite outcome from that permanent failure -- ``LLMRateLimitParkError``
must not spend the task's retry budget and must not settle the run, only
make the row wait until the provider's own cap resets.
"""

from __future__ import annotations

import pytest
from co_scientist.exceptions import LLMRateLimitParkError

from app import store, task_worker
from app.store import db as store_db
from app.task_worker import outcomes as task_worker_outcomes


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

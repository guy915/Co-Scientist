"""``LLMCallBudgetExceededError`` is a permanent, plainly-named failure.

Mirrors ``test_engine_tasks_portfolio_cancel.py::
test_a_permanent_failure_cancels_the_downstream_chain``: a task failing
this way must not keep its retry budget (it is one of the two permanent
failures ``_handle_task_failure`` classifies, alongside
``UnsupportedTaskError``), and the run's settled failure reason must say
plainly that the run hit its LLM-call ceiling rather than reading as a
generic task failure.
"""

from __future__ import annotations

from co_scientist.exceptions import LLMCallBudgetExceededError
from co_scientist.llm_call_budget import (
    current_run_call_count,
    record_provider_request,
    scoped_llm_call_budget,
)

from app import store, task_worker_outcomes


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

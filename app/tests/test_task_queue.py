"""Behavior tests for the durable scientific task queue."""

from __future__ import annotations

import subprocess
import sys
import time

from app import store

_CLAIM_SCRIPT = """
import sys
from app import store
task = store.claim_task(sys.argv[3], run_id=sys.argv[2], db_path=sys.argv[1])
print(task.id if task else "NONE")
"""

_COMPLETE_SCRIPT = """
import sys
from app import store
completed = store.complete_task(
    sys.argv[2], sys.argv[3], {"value": sys.argv[4]}, db_path=sys.argv[1]
)
print("TRUE" if completed else "FALSE")
"""


def _parallel_scripts(script: str, arguments: list[list[str]]) -> list[str]:
    """Run isolated Python workers concurrently and return their outputs."""
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", script, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for args in arguments
    ]
    outputs: list[str] = []
    for worker in workers:
        stdout, stderr = worker.communicate(timeout=10)
        assert worker.returncode == 0, stderr
        outputs.append(stdout.strip())
    return outputs


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


def test_multi_process_claim_has_single_lease_winner(
    isolated_db: str,
) -> None:
    """Independent worker processes cannot lease the same queued task."""
    run_id = _run()
    task = store.enqueue_task(
        run_id,
        "ranking.debate",
        {},
        idempotency_key="multi-process-claim",
        db_path=isolated_db,
    )

    claimed_ids = _parallel_scripts(
        _CLAIM_SCRIPT,
        [
            [isolated_db, run_id, "worker-0"],
            [isolated_db, run_id, "worker-1"],
        ],
    )

    assert claimed_ids.count(task.id) == 1
    assert claimed_ids.count("NONE") == 1


def test_multi_process_duplicate_completion_commits_one_effect(
    isolated_db: str,
) -> None:
    """Concurrent duplicate acknowledgements commit exactly one result."""
    run_id = _run()
    task = store.enqueue_task(
        run_id,
        "verification.deep",
        {},
        idempotency_key="multi-process-completion",
        db_path=isolated_db,
    )
    leased = store.claim_task(
        "shared-worker", run_id=run_id, db_path=isolated_db
    )
    assert leased is not None

    outcomes = _parallel_scripts(
        _COMPLETE_SCRIPT,
        [
            [isolated_db, task.id, "shared-worker", "first"],
            [isolated_db, task.id, "shared-worker", "second"],
        ],
    )

    assert sorted(outcomes) == ["FALSE", "TRUE"]
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.result in ({"value": "first"}, {"value": "second"})


def test_crashed_process_lease_is_redelivered_after_restart(
    isolated_db: str,
) -> None:
    """A process exit before acknowledgement is recovered by a new worker."""
    run_id = _run()
    task = store.enqueue_task(
        run_id,
        "evolution.combine",
        {},
        idempotency_key="process-crash-redelivery",
        max_attempts=2,
        db_path=isolated_db,
    )
    crash_script = _CLAIM_SCRIPT.replace(
        "run_id=sys.argv[2], db_path=sys.argv[1]",
        "run_id=sys.argv[2], db_path=sys.argv[1], lease_seconds=0.01",
    )

    [claimed] = _parallel_scripts(
        crash_script, [[isolated_db, run_id, "crashed-worker"]]
    )
    assert claimed == task.id
    time.sleep(0.02)

    recovered = store.claim_task(
        "restart-worker", run_id=run_id, db_path=isolated_db
    )
    assert recovered is not None
    assert recovered.id == task.id
    assert recovered.attempt == 2
    assert store.complete_task(
        task.id,
        "restart-worker",
        {"recovered": True},
        db_path=isolated_db,
    )


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
    recovered = store.claim_task("worker-b", run_id=run_id, db_path=isolated_db)
    assert recovered is not None
    assert recovered.id == first.id
    assert recovered.attempt == 2


def test_owned_lease_can_be_renewed_without_redelivery(
    isolated_db: str,
) -> None:
    """A heartbeat extension prevents another worker from reclaiming work."""
    run_id = _run()
    queued = store.enqueue_task(
        run_id,
        "verification.deep",
        {},
        idempotency_key="renew:0",
        db_path=isolated_db,
    )
    leased = store.claim_task(
        "worker-a", lease_seconds=0.01, run_id=run_id, db_path=isolated_db
    )
    assert leased is not None
    assert store.renew_task_lease(
        queued.id, "worker-a", 1.0, db_path=isolated_db
    )
    time.sleep(0.02)
    assert (
        store.claim_task("worker-b", run_id=run_id, db_path=isolated_db) is None
    )
    assert not store.renew_task_lease(
        queued.id, "worker-b", 1.0, db_path=isolated_db
    )


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
    assert store.fail_task(first.id, "worker-a", "timeout", db_path=isolated_db)
    second = store.claim_task("worker-b", run_id=run_id, db_path=isolated_db)
    assert second is not None and second.attempt == 2
    assert store.fail_task(
        second.id, "worker-b", "timeout", db_path=isolated_db
    )
    assert (
        store.claim_task("worker-c", run_id=run_id, db_path=isolated_db) is None
    )
    [saved] = store.list_tasks(run_id, db_path=isolated_db)
    assert saved.status == "failed"


def test_task_progress_is_monotonic_and_budget_derived(
    isolated_db: str,
) -> None:
    """Progress uses committed task rows and advances only on terminal work."""
    run_id = _run()
    first = store.enqueue_task(
        run_id,
        "retrieval.pubmed",
        {},
        idempotency_key="progress:retrieval",
        db_path=isolated_db,
    )
    store.enqueue_task(
        run_id,
        "generation.initial",
        {},
        idempotency_key="progress:generation",
        db_path=isolated_db,
    )
    initial = store.task_progress(run_id, db_path=isolated_db)
    assert initial == {
        "determinate": True,
        "completed_tasks": 0,
        "total_tasks": 2,
        "fraction": 0.0,
        "active_task": None,
        "queued_tasks": 2,
    }

    leased = store.claim_task("worker", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == first.id
    active = store.task_progress(run_id, db_path=isolated_db)
    assert active["fraction"] == 0.0
    assert active["active_task"] == "retrieval.pubmed"

    assert store.complete_task(
        first.id, "worker", {"count": 4}, db_path=isolated_db
    )
    completed = store.task_progress(run_id, db_path=isolated_db)
    assert completed["fraction"] == 0.5
    assert completed["completed_tasks"] == 1


def test_monolithic_workflow_lease_is_honestly_indeterminate(
    isolated_db: str,
) -> None:
    """A process wrapper is not misrepresented as a scientific task budget."""
    run_id = _run()
    store.enqueue_task(
        run_id,
        "run.workflow",
        {},
        idempotency_key="workflow:0:0",
        db_path=isolated_db,
    )
    assert store.task_progress(run_id, db_path=isolated_db) == {
        "determinate": False,
        "completed_tasks": 0,
        "total_tasks": 0,
        "fraction": None,
        "active_task": None,
        "queued_tasks": 0,
    }


def test_dynamic_engine_plan_stays_indeterminate_as_tasks_expand(
    isolated_db: str,
) -> None:
    """A model-expanded task denominator never produces regressing percent."""
    run_id = _run()
    store.enqueue_task(
        run_id,
        "engine.bootstrap",
        {},
        idempotency_key="engine-bootstrap",
        db_path=isolated_db,
    )
    progress = store.task_progress(run_id, db_path=isolated_db)
    assert progress["determinate"] is False
    assert progress["fraction"] is None
    assert progress["total_tasks"] == 1


def test_cancel_run_tasks_revokes_queued_and_leased_work(
    isolated_db: str,
) -> None:
    """Cancellation prevents both queued and in-flight task acknowledgement."""
    run_id = _run()
    first = store.enqueue_task(
        run_id,
        "engine.node.review",
        {},
        idempotency_key="cancel:first",
        db_path=isolated_db,
    )
    store.enqueue_task(
        run_id,
        "engine.node.ranking",
        {},
        idempotency_key="cancel:second",
        db_path=isolated_db,
    )
    assert store.claim_task("worker", run_id=run_id, db_path=isolated_db)
    assert store.cancel_run_tasks(run_id, db_path=isolated_db) == 2
    assert not store.complete_task(
        first.id, "worker", {"late": True}, db_path=isolated_db
    )
    statuses = {
        task.status for task in store.list_tasks(run_id, db_path=isolated_db)
    }
    assert statuses == {"cancelled"}


def test_pause_and_resume_make_queued_tasks_non_claimable(
    isolated_db: str,
) -> None:
    """Paused work stays durable but leaves the global claimable queue."""
    run_id = _run()
    task = store.enqueue_task(
        run_id,
        "engine.bootstrap",
        {},
        idempotency_key="pause-bootstrap",
        db_path=isolated_db,
    )
    assert store.pause_run_tasks(run_id, db_path=isolated_db) == 1
    assert (
        store.claim_task("worker", run_id=run_id, db_path=isolated_db) is None
    )
    paused = store.get_task(task.id, db_path=isolated_db)
    assert paused is not None
    assert paused.status == "paused"
    assert store.resume_run_tasks(run_id, db_path=isolated_db) == 1
    claimed = store.claim_task("worker", run_id=run_id, db_path=isolated_db)
    assert claimed is not None and claimed.id == task.id


def test_supervisor_can_reprioritize_cancel_and_retry_individual_tasks(
    isolated_db: str,
) -> None:
    """Queue controls mutate only tasks in compatible lifecycle states."""
    run_id = _run()
    promoted = store.enqueue_task(
        run_id,
        "reflection.full",
        {},
        idempotency_key="control:promote",
        priority=1,
        db_path=isolated_db,
    )
    cancelled = store.enqueue_task(
        run_id,
        "generation.assumptions",
        {},
        idempotency_key="control:cancel",
        priority=2,
        db_path=isolated_db,
    )
    failed = store.enqueue_task(
        run_id,
        "verification.deep",
        {},
        idempotency_key="control:retry",
        priority=100,
        max_attempts=1,
        db_path=isolated_db,
    )
    leased = store.claim_task(
        "failed-worker", run_id=run_id, db_path=isolated_db
    )
    assert leased is not None and leased.id == failed.id
    assert store.fail_task(
        failed.id,
        "failed-worker",
        "transient provider error",
        retryable=False,
        db_path=isolated_db,
    )

    assert store.reprioritize_task(
        promoted.id,
        99,
        reason="most valuable evidence gap",
        db_path=isolated_db,
    )
    assert store.cancel_task(
        cancelled.id,
        reason="superseded branch",
        db_path=isolated_db,
    )
    assert store.retry_task(
        failed.id,
        reason="new evidence available",
        db_path=isolated_db,
    )

    by_id = {
        task.id: task for task in store.list_tasks(run_id, db_path=isolated_db)
    }
    assert by_id[promoted.id].priority == 99
    assert by_id[cancelled.id].status == "cancelled"
    assert by_id[failed.id].status == "queued"
    assert by_id[failed.id].max_attempts == 2

"""Run-level control over queued work: cancel, pause/resume, Supervisor.

Split out of ``test_task_queue.py``; the enqueue/claim/complete/lease
behaviors live there, and these cover the operations that act on a whole
run's queue at once.
"""

from __future__ import annotations

import time

import pytest

import app.store.tasks as task_store
from app import store
from app.store import RunStatus
from tests._task_queue_helpers import _enqueue, _run, _three_control_tasks


def test_cancel_run_tasks_revokes_queued_leased_and_paused_work(
    isolated_db: str,
) -> None:
    """Cancellation revokes every task state that is safe to restart."""
    run_id = _run()
    first = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.review",
            inputs={},
            idempotency_key="cancel:first",
        ),
        db_path=isolated_db,
    )
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.ranking",
            inputs={},
            idempotency_key="cancel:second",
        ),
        db_path=isolated_db,
    )
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.review",
            inputs={},
            idempotency_key="cancel:paused",
        ),
        db_path=isolated_db,
    )
    assert store.claim_task("worker", run_id=run_id, db_path=isolated_db)
    assert store.pause_run_tasks(run_id, db_path=isolated_db) == 2
    assert store.cancel_run_tasks(run_id, db_path=isolated_db) == 3
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
        store.NewTask(
            run_id=run_id,
            task_type="engine.bootstrap",
            inputs={},
            idempotency_key="pause-bootstrap",
        ),
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


@pytest.mark.parametrize(
    "task_type",
    [
        "engine.bootstrap",
        "engine.fanout.generation.strategy",
        "engine.ranking.match",
        "engine.fanout.generation.aggregate",
    ],
)
def test_paused_run_ignores_late_queue_rows_and_cohort_work(
    isolated_db: str, task_type: str
) -> None:
    """A leased task may fan out after pause, but its run stays idle."""
    run_id = _run()
    predecessor = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.orchestrator",
            inputs={},
            idempotency_key="pause:predecessor",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task(
        "predecessor-worker", run_id=run_id, db_path=isolated_db
    )
    assert leased is not None and leased.id == predecessor.id
    assert store.complete_task(
        predecessor.id, "predecessor-worker", {}, db_path=isolated_db
    )

    active = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.ranking",
            inputs={},
            idempotency_key="pause:active-lease",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task(
        "active-worker", run_id=run_id, db_path=isolated_db
    )
    assert leased is not None and leased.id == active.id

    with store.transaction(isolated_db) as conn:
        store.pause_run_tasks(run_id, conn=conn)
        store.update_run_status(run_id, RunStatus.PAUSED, conn=conn)

    # This is the successor a still-running predecessor inserts after the
    # pause transaction. The dependency is complete, so only run status can
    # keep a normal claim from taking it.
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={},
            idempotency_key=f"pause:late:{task_type}",
            dependencies=(predecessor.id,),
        ),
        db_path=isolated_db,
    )
    delayed = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.fanout.review.aggregate",
            inputs={},
            idempotency_key="pause:future-due",
        ),
        db_path=isolated_db,
    )
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET available_at=? WHERE id=?",
            (time.time() + 3600, delayed.id),
        )

    assert (
        store.claim_task("new-worker", run_id=run_id, db_path=isolated_db)
        is None
    )
    assert store.cohort_poll(run_id, db_path=isolated_db) == (False, True, None)
    assert store.complete_task(
        active.id, "active-worker", {}, db_path=isolated_db
    )
    assert store.cohort_poll(run_id, db_path=isolated_db) == (
        False,
        False,
        None,
    )


def test_claim_rechecks_pause_after_advisory_probe(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write-side claim fence closes a pause racing the read probe."""
    run_id = _run()
    task = _enqueue(run_id, "engine.node.generate", "pause:racing", isolated_db)
    advisory_probe = task_store._has_claimable_task

    def pause_after_probe(
        probed_run_id: str | None, db_path: str | None
    ) -> bool:
        claimable = advisory_probe(probed_run_id, db_path)
        store.update_run_status(run_id, RunStatus.PAUSED, db_path=isolated_db)
        return claimable

    monkeypatch.setattr(task_store, "_has_claimable_task", pause_after_probe)

    assert (
        store.claim_task("racing-worker", run_id=run_id, db_path=isolated_db)
        is None
    )
    still_queued = store.get_task(task.id, db_path=isolated_db)
    assert still_queued is not None and still_queued.status == "queued"


def test_paused_cohort_does_not_wait_for_expired_retryable_engine_lease(
    isolated_db: str,
) -> None:
    """A lease hidden from claim must not keep a paused cohort polling."""
    run_id = _run()
    task = _enqueue(
        run_id, "engine.node.generate", "pause:expired", isolated_db
    )
    leased = store.claim_task(
        "expired-worker", run_id=run_id, db_path=isolated_db
    )
    assert leased is not None and leased.id == task.id
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=? WHERE id=?",
            (time.time() - 3600, task.id),
        )
    store.update_run_status(run_id, RunStatus.PAUSED, db_path=isolated_db)

    assert store.cohort_poll(run_id, db_path=isolated_db) == (
        False,
        False,
        None,
    )


def test_supervisor_can_reprioritize_cancel_and_retry_individual_tasks(
    isolated_db: str,
) -> None:
    """Queue controls mutate only tasks in compatible lifecycle states."""
    run_id = _run()
    promoted_id, cancelled_id, failed_id = _three_control_tasks(
        run_id, isolated_db
    )

    assert store.reprioritize_task(
        promoted_id,
        99,
        reason="most valuable evidence gap",
        db_path=isolated_db,
    )
    assert store.cancel_task(
        cancelled_id,
        reason="superseded branch",
        db_path=isolated_db,
    )
    assert store.retry_task(
        failed_id,
        reason="new evidence available",
        db_path=isolated_db,
    )

    by_id = {
        task.id: task for task in store.list_tasks(run_id, db_path=isolated_db)
    }
    assert by_id[promoted_id].priority == 99
    assert by_id[cancelled_id].status == "cancelled"
    assert by_id[failed_id].status == "queued"
    assert by_id[failed_id].max_attempts == 2

"""Run-level control over queued work: cancel, pause/resume, Supervisor.

Split out of ``test_task_queue.py``; the enqueue/claim/complete/lease
behaviors live there, and these cover the operations that act on a whole
run's queue at once.
"""

from __future__ import annotations

from app import store
from tests._task_queue_helpers import _run, _three_control_tasks


def test_cancel_run_tasks_revokes_queued_and_leased_work(
    isolated_db: str,
) -> None:
    """Cancellation prevents both queued and in-flight task acknowledgement."""
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

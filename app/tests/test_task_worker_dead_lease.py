"""A lease that outlives its worker with no retries left must settle.

``fail_task`` settles a run whose task dies past its retry budget, but it
can only run if someone still holds the lease to call it. When the worker
dies holding a lease whose attempts are already spent, nobody does, and
``claim_task``'s expired-lease rescue skips the row by design -- so the
run was left ``running`` with nothing that could ever advance it. These
tests pin the automatic recovery; ``test_task_worker_resume.py`` covers
the operator-initiated one.
"""

from __future__ import annotations

import time

from app import engine_tasks, store, task_worker

_TASK_TYPE = f"{engine_tasks.NODE_TASK_PREFIX}ranking"


def _run_with_lease(
    db: str,
    *,
    expires_at: float,
    spend_budget: bool,
    goal: str = "stranded goal",
) -> tuple[str, str]:
    """Create a run holding one leased task; return its (run, task) ids."""
    run = store.create_run(goal, "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=_TASK_TYPE,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{_TASK_TYPE}:1",
        ),
        db_path=db,
    )
    extra = ", attempt=max_attempts" if spend_budget else ""
    with store.connect(db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner=?, "
            f"lease_expires_at=?{extra} WHERE id=?",
            ("dead", expires_at, task.id),
        )
        conn.execute("UPDATE runs SET status='running' WHERE id=?", (run.id,))
    return run.id, task.id


def _task_status(task_id: str, db: str) -> str:
    """Read one task's queue status."""
    with store.connect(db) as conn:
        row = conn.execute(
            "SELECT status FROM scientific_tasks WHERE id=?", (task_id,)
        ).fetchone()
    return str(row["status"])


def test_dead_lease_is_failed_and_settles_its_run(isolated_db: str) -> None:
    """The whole point: the run reaches a terminal state on its own."""
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    abandoned = store.abandon_dead_leases(run_id, db_path=isolated_db)

    assert abandoned == 1
    assert _task_status(task_id, isolated_db) == "failed"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"


def test_dead_lease_settlement_emits_a_terminal_status_event(
    isolated_db: str,
) -> None:
    """The SSE stream closes on this event, so it has to be written."""
    run_id, _ = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    store.abandon_dead_leases(run_id, db_path=isolated_db)

    events = store.list_events(run_id, db_path=isolated_db)
    terminal = [
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "failed"
    ]
    assert terminal, "a settled run must announce it"


def test_a_live_lease_is_never_abandoned(isolated_db: str) -> None:
    """Its owner may still be working; failing it would discard real work."""
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() + 3600, spend_budget=True
    )

    assert store.abandon_dead_leases(run_id, db_path=isolated_db) == 0
    assert _task_status(task_id, isolated_db) == "leased"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "running"


def test_an_expired_lease_with_retries_left_is_never_abandoned(
    isolated_db: str,
) -> None:
    """That row belongs to claim_task's rescue, which requeues it."""
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=False
    )

    assert store.abandon_dead_leases(run_id, db_path=isolated_db) == 0
    assert _task_status(task_id, isolated_db) == "leased"


def test_cohort_poll_reports_a_dead_lease_as_inactive(
    isolated_db: str,
) -> None:
    """Reported active, the cohort polls forever over unclaimable work."""
    run_id, _ = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    claimable, active = store.cohort_poll(run_id, db_path=isolated_db)

    assert not claimable, "a spent-budget lease is claimable by nobody"
    assert not active, "nor is anyone still working on it"


def test_cohort_poll_still_reports_a_live_lease_as_active(
    isolated_db: str,
) -> None:
    """The sibling may yet fan out more work; the cohort must wait."""
    run_id, _ = _run_with_lease(
        isolated_db, expires_at=time.time() + 3600, spend_budget=True
    )

    _, active = store.cohort_poll(run_id, db_path=isolated_db)

    assert active


async def test_cohort_idle_exit_settles_a_run_left_with_a_dead_lease(
    isolated_db: str,
) -> None:
    """End to end: the cohort exits and the run does not hang."""
    run_id, task_id = _run_with_lease(
        isolated_db, expires_at=time.time() - 3600, spend_budget=True
    )

    await task_worker.run_run_worker_pool(
        run_id,
        "cohort",
        worker_count=1,
        policy=task_worker.WorkerPolicy(db_path=isolated_db),
    )

    assert _task_status(task_id, isolated_db) == "failed"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"

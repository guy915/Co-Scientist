"""Tests for restart-safety: interrupted-run reconciliation and WAL checkpoint.

These harness fixes ensure a long research run does not get stuck "running"
forever when the server is restarted mid-run.
"""

from __future__ import annotations

from app import store
from app.store import db as store_db


def _make_run(goal: str, isolated_db: str) -> str:
    run = store.create_run(
        goal, "default", "engine", {}, client_id="c1", db_path=isolated_db
    )
    return run.id


def test_reconcile_fails_interrupted_runs(isolated_db: str) -> None:
    """Queued/running/synthesizing runs become failed; terminal runs left."""
    running = _make_run("running goal", isolated_db)
    store.update_run_status(
        running, store.RunStatus.RUNNING, db_path=isolated_db
    )
    queued = _make_run("queued goal", isolated_db)
    store.update_run_status(queued, store.RunStatus.QUEUED, db_path=isolated_db)
    synth = _make_run("synth goal", isolated_db)
    store.update_run_status(
        synth, store.RunStatus.SYNTHESIZING, db_path=isolated_db
    )
    done = _make_run("done goal", isolated_db)
    store.update_run_status(
        done, store.RunStatus.COMPLETED, db_path=isolated_db
    )

    reconciled = store.reconcile_interrupted_runs(db_path=isolated_db)

    # None of these have a checkpoint, so all fail (none resumable).
    assert set(reconciled["failed"]) == {running, queued, synth}
    assert reconciled["resumable"] == []
    for rid in (running, queued, synth):
        row = store.get_run(rid, db_path=isolated_db)
        assert row is not None
        assert row.status == store.RunStatus.FAILED.value
        assert row.error and "restart" in row.error
    # Terminal runs are untouched.
    done_row = store.get_run(done, db_path=isolated_db)
    assert done_row is not None
    assert done_row.status == store.RunStatus.COMPLETED.value


def test_active_engine_tasks_are_discoverable_before_lease_expiry(
    isolated_db: str,
) -> None:
    """Startup recovery sees a live lease without waiting to reconcile it."""
    run = store.create_run(
        "recover leased science",
        "standard",
        "engine",
        {},
        db_path=isolated_db,
    )
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    store.enqueue_task(
        run.id,
        "engine.node.review",
        {"checkpoint_seq": 1},
        idempotency_key="recover-review",
        db_path=isolated_db,
    )
    assert (
        store.claim_task("dead-worker", lease_seconds=300, db_path=isolated_db)
        is not None
    )

    assert store.list_active_engine_task_run_ids(db_path=isolated_db) == [
        run.id
    ]


def test_reconcile_marks_checkpointed_run_resumable(isolated_db: str) -> None:
    """An interrupted run with a checkpoint is resumable, not failed (M4)."""
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, store.RunStatus.RUNNING, db_path=isolated_db)
    store.save_checkpoint(
        rid,
        stage="post_ranking",
        schema_version=1,
        last_event_seq=7,
        state={"round": 1},
        db_path=isolated_db,
    )

    reconciled = store.reconcile_interrupted_runs(db_path=isolated_db)

    assert reconciled["resumable"] == [rid]
    assert reconciled["failed"] == []
    # A resumable run is NOT marked failed.
    row = store.get_run(rid, db_path=isolated_db)
    assert row is not None
    assert row.status != store.RunStatus.FAILED.value
    # A 'resumable' status event is logged for the stream/UI.
    events = store.list_events(rid, db_path=isolated_db)
    assert any(
        e["type"] == "status" and e["payload"].get("status") == "resumable"
        for e in events
    )


def test_reconcile_appends_status_event(isolated_db: str) -> None:
    """A reconciled run gets a terminal 'failed' status event for the stream."""
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, store.RunStatus.RUNNING, db_path=isolated_db)
    store.reconcile_interrupted_runs(db_path=isolated_db)
    events = store.list_events(rid, db_path=isolated_db)
    assert any(
        e["type"] == "status" and e["payload"].get("status") == "failed"
        for e in events
    )


def test_reconcile_is_idempotent(isolated_db: str) -> None:
    """A second pass finds nothing to reconcile (all runs already terminal)."""
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, store.RunStatus.RUNNING, db_path=isolated_db)
    assert store.reconcile_interrupted_runs(db_path=isolated_db)["failed"] == [
        rid
    ]
    assert not store.reconcile_interrupted_runs(db_path=isolated_db)["failed"]


def test_reconciled_run_is_restartable(isolated_db: str) -> None:
    """A reconciled (failed) run is restartable.

    It is no longer in an un-startable in-progress state -- ``start_run``
    only rejects running/synthesizing/completed.
    """
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, store.RunStatus.RUNNING, db_path=isolated_db)
    store.reconcile_interrupted_runs(db_path=isolated_db)
    row = store.get_run(rid, db_path=isolated_db)
    assert row is not None
    assert row.status not in (
        store.RunStatus.RUNNING.value,
        store.RunStatus.SYNTHESIZING.value,
        store.RunStatus.COMPLETED.value,
    )


def test_checkpoint_wal_runs_cleanly(isolated_db: str) -> None:
    """The WAL checkpoint helper succeeds on an initialized database."""
    _make_run("g", isolated_db)
    # Should not raise.
    store.checkpoint_wal(db_path=isolated_db)


def test_headerless_run_survives_restart(isolated_db: str) -> None:
    """A header-less (empty client_id) run is not purged on restart.

    The pre-client-isolation purge must be one-time (only when the column is
    first added), not run on every startup -- otherwise every API run created
    without an X-Client-ID header would silently vanish on restart.
    """
    run = store.create_run(
        "g", "default", "engine", {}, client_id="", db_path=isolated_db
    )
    # Simulate a server restart re-running migrations on the existing DB.
    with store.connect(isolated_db) as conn:
        store_db._run_migrations(conn)
    rows = store.list_runs(client_id="", db_path=isolated_db)
    assert any(r.id == run.id for r in rows)

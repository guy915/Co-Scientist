"""Per-attempt failure history on the durable task queue.

``fail_task`` used to overwrite one ``error`` column on every retry, so
the previous attempt's failure was destroyed the moment the next one was
recorded -- indistinguishable from a run that failed identically three
times versus one that failed three different ways. ``attempts_json``
keeps a bounded record of every *failed* attempt (a successful one is
already captured by ``result_json``); these tests pin its shape, its
cap, its transactionality, and that a database built under the old
schema (no ``attempts_json`` column at all) still decodes.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import store
from app.store import db as store_db
from app.store import tasks as store_tasks
from tests._client import make_client


def _running_run(db_path: str, goal: str = "attempts goal") -> str:
    run = store.create_run(goal, "standard", "engine", {})
    store.update_run_status(run.id, store.RunStatus.RUNNING, db_path=db_path)
    return run.id


def _enqueue(
    run_id: str, key: str, db_path: str, *, max_attempts: int = 3
) -> str:
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.ranking",
            inputs={},
            idempotency_key=key,
            max_attempts=max_attempts,
        ),
        db_path=db_path,
    )
    return task.id


def test_lease_renewal_does_not_move_recorded_start_time(
    isolated_db: str,
) -> None:
    """A heartbeat renewal mid-attempt must not overwrite its start time.

    ``renew_task_lease`` bumps ``updated_at`` on every heartbeat so a long
    LLM call's lease survives, which is exactly the failure this history
    exists to diagnose -- so the attempt's recorded start must be the
    original claim time, not the moment of its last renewal.
    """
    run_id = _running_run(isolated_db)
    task_id = _enqueue(run_id, "k", isolated_db, max_attempts=3)

    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None
    claim_time = leased.updated_at

    assert store.renew_task_lease(leased.id, "w1", 60.0, db_path=isolated_db)
    assert store.fail_task(leased.id, "w1", "timed out", db_path=isolated_db)

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None
    assert saved.attempts[0]["started_at"] == claim_time


def test_two_failures_record_distinct_attempts_in_order(
    isolated_db: str,
) -> None:
    """Two successive failures both appear, in order, with distinct errors."""
    run_id = _running_run(isolated_db)
    task_id = _enqueue(run_id, "k", isolated_db, max_attempts=3)

    first = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert first is not None
    assert store.fail_task(first.id, "w1", "first failure", db_path=isolated_db)

    second = store.claim_task("w2", run_id=run_id, db_path=isolated_db)
    assert second is not None
    assert store.fail_task(
        second.id, "w2", "second failure", db_path=isolated_db
    )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None
    assert [a["error"] for a in saved.attempts] == [
        "first failure",
        "second failure",
    ]
    assert [a["attempt"] for a in saved.attempts] == [1, 2]


def test_attempts_history_is_capped(isolated_db: str) -> None:
    """The stored history never exceeds the bounded cap."""
    run_id = _running_run(isolated_db)
    over_cap = store_tasks._MAX_STORED_ATTEMPTS + 3
    task_id = _enqueue(run_id, "k", isolated_db, max_attempts=over_cap + 1)

    for i in range(over_cap):
        leased = store.claim_task("w", run_id=run_id, db_path=isolated_db)
        assert leased is not None
        assert store.fail_task(
            leased.id, "w", f"failure {i}", db_path=isolated_db
        )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None
    assert len(saved.attempts) == store_tasks._MAX_STORED_ATTEMPTS
    # The oldest failures are dropped, the most recent kept.
    assert saved.attempts[-1]["error"] == f"failure {over_cap - 1}"
    first_kept = over_cap - store_tasks._MAX_STORED_ATTEMPTS
    assert saved.attempts[0]["error"] == f"failure {first_kept}"


def test_old_schema_task_decodes_with_empty_history(
    isolated_db: str,
) -> None:
    """A task row written under the pre-``attempts_json`` schema decodes."""
    raw = sqlite3.connect(isolated_db)
    try:
        raw.executescript(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                research_goal TEXT NOT NULL,
                profile TEXT NOT NULL,
                status TEXT NOT NULL,
                provider TEXT NOT NULL,
                config_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                error TEXT
            );
            CREATE TABLE scientific_tasks (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0,
                inputs_json TEXT NOT NULL,
                dependencies_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                budget_json TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                lease_owner TEXT,
                lease_expires_at REAL,
                result_json TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL,
                UNIQUE (run_id, idempotency_key)
            );
            """
        )
        raw.execute(
            "INSERT INTO runs (id, research_goal, profile, status, "
            "provider, config_json, created_at, updated_at) VALUES "
            "('legacy-run', 'legacy goal', 'standard', 'running', "
            "'engine', '{}', 1, 1)"
        )
        raw.execute(
            "INSERT INTO scientific_tasks (id, run_id, task_type, status, "
            "inputs_json, dependencies_json, provenance_json, "
            "idempotency_key, budget_json, error, created_at, updated_at) "
            "VALUES ('legacy-task', 'legacy-run', 'engine.node.ranking', "
            "'failed', '{}', '[]', '{}', 'k', '{}', 'an old failure', "
            "1, 1)"
        )
        raw.commit()
    finally:
        raw.close()

    # Any store call establishes the connection and runs migrations.
    saved = store.get_task("legacy-task", db_path=isolated_db)

    assert saved is not None
    assert saved.attempts == ()
    assert saved.error == "an old failure"

    with store_db.connect(isolated_db) as conn:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(scientific_tasks)")
        }
        assert "attempts_json" in cols
        assert "attempt_started_at" in cols


def test_failed_attempt_write_is_transactional_with_settlement(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rolled-back failure leaves no attempt snapshot behind."""
    run_id = _running_run(isolated_db)
    task_id = _enqueue(run_id, "k", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("settlement exploded")

    monkeypatch.setattr(store_tasks, "_settle_run_for_failed_task", _boom)

    with pytest.raises(RuntimeError, match="settlement exploded"):
        store.fail_task(
            leased.id, "w1", "boom", retryable=False, db_path=isolated_db
        )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "leased"
    assert saved.attempts == ()


def test_tasks_endpoint_returns_attempt_history(isolated_db: str) -> None:
    """The diagnostics endpoint surfaces a task's failed-attempt history."""
    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "attempts endpoint goal"}
        )
        run_id = created.json()["id"]
        store.update_run_status(
            run_id, store.RunStatus.RUNNING, db_path=isolated_db
        )
        task_id = _enqueue(run_id, "k", isolated_db, max_attempts=3)
        leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
        assert leased is not None
        assert store.fail_task(
            leased.id, "w1", "endpoint failure", db_path=isolated_db
        )

        body = client.get(f"/api/runs/{run_id}/tasks").json()

    tasks_by_id = {t["id"]: t for t in body["tasks"]}
    assert tasks_by_id[task_id]["attempts"][0]["error"] == ("endpoint failure")
    assert tasks_by_id[task_id]["attempts"][0]["attempt"] == 1

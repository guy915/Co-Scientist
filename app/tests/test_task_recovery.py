"""Tests for task queue 1."""

from __future__ import annotations

import concurrent.futures
import json
import sqlite3
from typing import Any

import pytest
from co_scientist.exceptions import LLMCallBudgetExceededError, LLMTimeoutError

import app.store.tasks_lifecycle as store_tasks_attempts
from app import credentials, diagnostics, engine_tasks, store, task_worker
from app.config import settings
from app.diagnostics import HealthCheck
from app.store import db as store_db
from app.store import tasks as store_tasks
from app.store.models import UNKNOWN_PROVIDER_OUTCOME_ERROR
from app.store.tasks import queue_health_snapshot
from app.store.tasks_lifecycle import QueueHealthSnapshot
from tests._client import DEFAULT_TEST_CLIENT_ID, make_client
from tests._client import make_client as _client
from tests._client import make_operator_client as _operator_client

# Expired engine leases on campaign runs are rescued, not failed.
#
# An engine lease that outlives its worker normally stops the run with
# ``llm_timeout_unknown``: nothing durable says whether the lost request was
# billed. A campaign run is the exception. Its policy is persisted at creation
# and, while it holds, every provider request must pass the exact zero-price
# gate or is refused before transport, so a lost lease cannot have spent
# anything -- unless a caller credential rode along. Production run 34b29088
# (2026-09-27) failed after a restart for want of this distinction.


def _campaign_run_with_expired_lease(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    """Create a running campaign run whose only engine lease has expired."""
    run = store.create_run(
        "Campaign lease loss",
        "express",
        "engine",
        {},
        store.RunCreateOptions(
            client_id=DEFAULT_TEST_CLIENT_ID, execution_policy="campaign"
        ),
    )
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.fanout.verification.item",
            inputs={},
            idempotency_key="verification:seed",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task(
        "restarted-worker", run_id=run.id, lease_seconds=1, db_path=isolated_db
    )
    assert leased is not None
    now = store_db._now()
    monkeypatch.setattr("app.store.db.time.time", lambda: now + 2)
    return run.id, task.id


@pytest.mark.asyncio
async def test_expired_campaign_lease_is_retried(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lease returns to the queue and the run keeps going."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    replayed: list[str] = []

    async def _replay(
        task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        replayed.append(task.task_type)
        return {"replayed": True}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", _replay)
    run_id, task_id = _campaign_run_with_expired_lease(isolated_db, monkeypatch)

    assert await task_worker.run_once("new-worker", db_path=isolated_db)

    assert replayed == ["engine.fanout.verification.item"]
    task = store.get_task(task_id, db_path=isolated_db)
    assert task is not None and task.status == "completed"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status != store.RunStatus.FAILED


@pytest.mark.asyncio
async def test_expired_campaign_lease_with_byok_still_fails_closed(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller credential is outside the zero-price evidence."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(
        settings, "byok_encryption_key", "synthetic-campaign-lease-secret"
    )
    replayed: list[str] = []

    async def _must_not_call(
        task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        replayed.append(task.task_type)
        return {}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", _must_not_call)
    run_id, task_id = _campaign_run_with_expired_lease(isolated_db, monkeypatch)
    credentials.store_run_credential(
        run_id,
        DEFAULT_TEST_CLIENT_ID,
        credentials.ByokCredential(
            provider="deepseek",
            api_key="sk-synthetic-campaign-lease-12345",
            model="deepseek/deepseek-v4-flash",
        ),
        db_path=isolated_db,
    )

    assert not await task_worker.run_once("new-worker", db_path=isolated_db)

    assert replayed == []
    task = store.get_task(task_id, db_path=isolated_db)
    assert task is not None and task.status == "failed"


# ``/health`` reflecting real durable-queue and disk conditions (L6).
#
# Before this, ``/health`` was store reachability plus an import lookup, so
# a wedged run, an exhausted-retry-budget task, or a full disk all reported
# ``healthy``. These tests cover three layers of the fix:
#
# - the store-level read-only probe (``app.store.tasks.queue_health_snapshot``),
# - the diagnostics-level checks that wrap it (``check_queue``, ``check_disk``,
#   ``derive_overall_health``, and their short-TTL cache), and
# - the ``/health`` endpoint itself, reproducing the exact gap the F1
#   settlement fix leaves open: a lease that expires *after* its retry
#   budget is spent is never explicitly failed (nobody still holds it to
#   call ``fail_task``), so it stays ``leased`` forever and
#   ``_settle_run_out_of_work`` never sees the run as out of work.
#
# Throughout, a degraded condition must return HTTP 200 with
# ``status: "degraded"`` -- never 503 -- because a failed healthcheck kills
# the container mid-run (see AGENTS.md's healthcheck-failure-spiral
# incident), and only true store unreachability may take the process down.


def _health_running_run(db_path: str, goal: str = "queue health goal") -> str:
    """Create a run and move it to RUNNING; return its id."""
    run = store.create_run(goal, "standard", "engine", {})
    store.update_run_status(run.id, store.RunStatus.RUNNING, db_path=db_path)
    return run.id


def _health_enqueue(run_id: str, key: str, db_path: str, **kwargs: Any) -> str:
    """Enqueue an empty-input engine task and return its id."""
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.ranking",
            inputs={},
            idempotency_key=key,
            **kwargs,
        ),
        db_path=db_path,
    )
    return task.id


def _expire_lease(task_id: str, db_path: str) -> None:
    """Force a leased task's lease into the past without touching attempts.

    Simulates the worker that held the lease crashing: nobody ever calls
    ``fail_task``, so the row is left exactly as a dead worker would leave
    it -- still ``leased``, attempts spent, lease timestamp in the past.
    """
    with store.connect(db_path) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (task_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Store-level: app.store.tasks.queue_health_snapshot
# ---------------------------------------------------------------------------


def test_snapshot_empty_when_no_active_runs(isolated_db: str) -> None:
    snapshot = queue_health_snapshot(db_path=isolated_db)
    assert snapshot == QueueHealthSnapshot((), 0, 0, 0)


def test_queued_task_is_not_stalled(isolated_db: str) -> None:
    run_id = _health_running_run(isolated_db)
    _health_enqueue(run_id, "queued", isolated_db)

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == ()
    assert snapshot.queued_depth == 1


def test_active_lease_is_not_stalled(isolated_db: str) -> None:
    run_id = _health_running_run(isolated_db)
    task_id = _health_enqueue(run_id, "leased", isolated_db)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == ()


def test_rescuable_expired_lease_is_not_stalled(isolated_db: str) -> None:
    """Retry budget left: the next claim rescues it automatically."""
    run_id = _health_running_run(isolated_db)
    task_id = _health_enqueue(run_id, "rescuable", isolated_db, max_attempts=3)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id
    _expire_lease(task_id, isolated_db)

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == ()
    assert snapshot.rescuable_leases == 1


def test_orphaned_exhausted_lease_leaves_run_stalled(isolated_db: str) -> None:
    """The gap F1 leaves open: an expired, budget-spent lease never fails.

    Reproduces a crashed worker exactly: the task is leased, its attempts
    are spent, and its lease has expired, but nothing ever calls
    ``fail_task`` on it (nobody holds it any more). The run must stay
    ``running`` forever -- ``_settle_run_out_of_work`` still sees a
    ``leased`` row and refuses to settle -- and the health snapshot must
    be the one thing that notices.
    """
    run_id = _health_running_run(isolated_db)
    task_id = _health_enqueue(run_id, "orphaned", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id
    _expire_lease(task_id, isolated_db)

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == (run_id,)
    assert snapshot.rescuable_leases == 0
    # The run genuinely never settles on its own: it is still "running".
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"


def test_completed_run_is_excluded(isolated_db: str) -> None:
    run = store.create_run("done goal", "standard", "engine", {})
    store.update_run_status(
        run.id, store.RunStatus.COMPLETED, db_path=isolated_db
    )

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == ()


def test_failed_task_counted_without_stalling_active_sibling(
    isolated_db: str,
) -> None:
    """A terminally failed task is surfaced but does not itself stall."""
    run_id = _health_running_run(isolated_db)
    doomed = _health_enqueue(run_id, "doomed", isolated_db, max_attempts=1)
    _health_enqueue(run_id, "survivor", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == doomed
    store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.failed_tasks == 1
    assert snapshot.stalled_run_ids == ()  # the survivor is still queued


# ---------------------------------------------------------------------------
# Diagnostics-level: check_queue, check_disk, derive_overall_health, cache
# ---------------------------------------------------------------------------


def test_check_queue_ok_with_no_active_runs(isolated_db: str) -> None:
    result = diagnostics.check_queue(isolated_db)
    assert result.ok is True
    assert result.detail is None


def test_check_queue_flags_stalled_run(isolated_db: str) -> None:
    run_id = _health_running_run(isolated_db)
    task_id = _health_enqueue(run_id, "orphaned", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id
    _expire_lease(task_id, isolated_db)

    result = diagnostics.check_queue(isolated_db)

    assert result.ok is False
    assert result.detail is not None and run_id in result.detail


def test_check_queue_reports_error_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(db_path: str | None = None) -> QueueHealthSnapshot:
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(diagnostics, "queue_health_snapshot", _boom)

    result = diagnostics.check_queue()

    assert result.ok is False
    assert result.detail is not None and "db unreachable" in result.detail


def test_check_disk_ok_when_space_available(tmp_path: object) -> None:
    result = diagnostics.check_disk(
        str(tmp_path) + "/db.sqlite", min_free_bytes=0
    )
    assert result.ok is True


def test_check_disk_flags_low_free_space(tmp_path: object) -> None:
    huge_floor = 10**18  # no real volume has an exabyte free
    result = diagnostics.check_disk(
        str(tmp_path) + "/db.sqlite", min_free_bytes=huge_floor
    )
    assert result.ok is False
    assert result.detail is not None and "floor" in result.detail


def test_derive_overall_health_degrades_never_unhealthy_on_queue_or_disk() -> (
    None
):
    """A stalled run or low disk must never flip the container-killing bit."""
    status = diagnostics.derive_overall_health(
        HealthCheck(ok=True),
        HealthCheck(ok=True),
        HealthCheck(ok=False, detail="stalled"),
        HealthCheck(ok=False, detail="low disk"),
    )
    assert status == diagnostics.DEGRADED


def test_derive_overall_health_unhealthy_when_store_down_regardless() -> None:
    status = diagnostics.derive_overall_health(
        HealthCheck(ok=False, detail="boom"),
        HealthCheck(ok=True),
        HealthCheck(ok=True),
        HealthCheck(ok=True),
    )
    assert status == diagnostics.UNHEALTHY


def test_queue_and_disk_health_cache_reuses_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def _stub_queue(db_path: str | None = None) -> HealthCheck:
        calls.append(1)
        return HealthCheck(ok=True)

    monkeypatch.setattr(diagnostics, "check_queue", _stub_queue)
    monkeypatch.setattr(
        diagnostics, "check_disk", lambda db_path=None: HealthCheck(ok=True)
    )
    monkeypatch.setattr(settings, "health_check_cache_ttl_seconds", 60.0)
    diagnostics.clear_health_check_cache()

    diagnostics.queue_and_disk_health_cached()
    diagnostics.queue_and_disk_health_cached()

    assert len(calls) == 1


def test_queue_and_disk_health_cache_expires_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def _stub_queue(db_path: str | None = None) -> HealthCheck:
        calls.append(1)
        return HealthCheck(ok=True)

    monkeypatch.setattr(diagnostics, "check_queue", _stub_queue)
    monkeypatch.setattr(
        diagnostics, "check_disk", lambda db_path=None: HealthCheck(ok=True)
    )
    monkeypatch.setattr(settings, "health_check_cache_ttl_seconds", 0.0)
    diagnostics.clear_health_check_cache()

    diagnostics.queue_and_disk_health_cached()
    diagnostics.queue_and_disk_health_cached()

    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Endpoint-level: GET /health against real conditions
# ---------------------------------------------------------------------------


def test_health_reports_all_four_checks() -> None:
    data = _client().get("/health").json()
    assert set(data["checks"]) == {"store", "engine", "queue", "disk"}


def test_health_healthy_with_a_busy_but_progressing_run(
    isolated_db: str,
) -> None:
    """A queued task alone must not read as unhealthy -- busy is normal."""
    run_id = _health_running_run(isolated_db)
    _health_enqueue(run_id, "queued", isolated_db)

    res = _client().get("/health")

    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_health_degrades_at_200_when_a_run_is_stalled(
    isolated_db: str,
) -> None:
    """The exact scenario L6 exists for: a wedged run, surfaced at 200."""
    run_id = _health_running_run(isolated_db)
    task_id = _health_enqueue(run_id, "orphaned", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id
    _expire_lease(task_id, isolated_db)

    res = _client().get("/health")

    assert res.status_code == 200  # must never kill the container
    data = res.json()
    assert data["status"] == "degraded"
    assert data["checks"]["queue"]["ok"] is False
    # The run id names internal state, so the detail text is operator-only
    # (finding N14); an anonymous caller still learns that the queue is
    # degraded, which is what the deploy probe and a status page need.
    operator = _operator_client().get("/health").json()
    assert run_id in (operator["checks"]["queue"]["detail"] or "")
    assert data["checks"]["queue"]["detail"] is None


def test_health_degrades_at_200_when_disk_is_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "health_check_min_free_disk_bytes", 10**18)

    res = _client().get("/health")

    assert res.status_code == 200  # low disk degrades, never kills serving
    data = res.json()
    assert data["status"] == "degraded"
    assert data["checks"]["disk"]["ok"] is False


# Per-attempt failure history on the durable task queue.
#
# ``fail_task`` used to overwrite one ``error`` column on every retry, so
# the previous attempt's failure was destroyed the moment the next one was
# recorded -- indistinguishable from a run that failed identically three
# times versus one that failed three different ways. ``attempts_json``
# keeps a bounded record of every *failed* attempt (a successful one is
# already captured by ``result_json``); these tests pin its shape, its
# cap, its transactionality, and that a database built under the old
# schema (no ``attempts_json`` column at all) still decodes.


def _history_running_run(db_path: str, goal: str = "attempts goal") -> str:
    run = store.create_run(goal, "standard", "engine", {})
    store.update_run_status(run.id, store.RunStatus.RUNNING, db_path=db_path)
    return run.id


def _history_enqueue(
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
    run_id = _history_running_run(isolated_db)
    task_id = _history_enqueue(run_id, "k", isolated_db, max_attempts=3)

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
    run_id = _history_running_run(isolated_db)
    task_id = _history_enqueue(run_id, "k", isolated_db, max_attempts=3)

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
    run_id = _history_running_run(isolated_db)
    over_cap = store_tasks_attempts._MAX_STORED_ATTEMPTS + 3
    task_id = _history_enqueue(
        run_id, "k", isolated_db, max_attempts=over_cap + 1
    )

    for i in range(over_cap):
        leased = store.claim_task("w", run_id=run_id, db_path=isolated_db)
        assert leased is not None
        assert store.fail_task(
            leased.id, "w", f"failure {i}", db_path=isolated_db
        )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None
    assert len(saved.attempts) == store_tasks_attempts._MAX_STORED_ATTEMPTS
    # The oldest failures are dropped, the most recent kept.
    assert saved.attempts[-1]["error"] == f"failure {over_cap - 1}"
    first_kept = over_cap - store_tasks_attempts._MAX_STORED_ATTEMPTS
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
    run_id = _history_running_run(isolated_db)
    task_id = _history_enqueue(run_id, "k", isolated_db, max_attempts=1)
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
        task_id = _history_enqueue(run_id, "k", isolated_db, max_attempts=3)
        leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
        assert leased is not None
        assert store.fail_task(
            leased.id, "w1", "endpoint failure", db_path=isolated_db
        )

        body = client.get(f"/api/runs/{run_id}/tasks").json()

    tasks_by_id = {t["id"]: t for t in body["tasks"]}
    assert tasks_by_id[task_id]["attempts"][0]["error"] == ("endpoint failure")
    assert tasks_by_id[task_id]["attempts"][0]["attempt"] == 1


# Typed provider failure kinds on the owned run API.


@pytest.mark.asyncio
async def test_owned_run_api_retains_typed_budget_failure_after_reopen(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminal budget failure keeps its kind and original error on reopen."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    async def _over_budget(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise LLMCallBudgetExceededError(count=251, ceiling=250)

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _over_budget)

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "typed failure goal"}
        )
        run_id = created.json()["id"]
        assert (
            client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
        )
        assert await task_worker.run_once("worker", db_path=isolated_db)

    with make_client() as reopened:
        response = reopened.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["failure_kind"] == "llm_call_budget_exceeded"
    assert "251 provider requests against a budget of 250" in body["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_kind", "expected_message"),
    [
        (
            LLMTimeoutError("provider timed out"),
            "llm_timeout_unknown",
            UNKNOWN_PROVIDER_OUTCOME_ERROR,
        ),
        (
            RuntimeError("LLM-call ceiling exceeded: 251 provider requests"),
            None,
            "LLM-call ceiling exceeded: 251 provider requests",
        ),
    ],
)
async def test_owned_run_api_classifies_only_exact_terminal_failure_types(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_kind: str | None,
    expected_message: str,
) -> None:
    """Only exact known exception types receive provider guidance."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    async def _raise_known_or_near_miss(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise error

    monkeypatch.setattr(
        engine_tasks, "execute_engine_task", _raise_known_or_near_miss
    )

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "typed timeout goal"}
        )
        run_id = created.json()["id"]
        assert (
            client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
        )

        attempts = 1 if isinstance(error, LLMTimeoutError) else 3
        for _ in range(attempts):
            assert await task_worker.run_once("worker", db_path=isolated_db)

    with make_client() as reopened:
        body = reopened.get(f"/api/runs/{run_id}").json()

    assert body["status"] == "failed"
    assert body["failure_kind"] == expected_kind
    assert expected_message in body["error"]


@pytest.mark.asyncio
async def test_run_failure_kind_comes_from_task_that_settles_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typed task failure cannot classify a run while sibling work remains."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    async def _fail_tasks(
        task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        if task.task_type == "engine.bootstrap":
            raise LLMCallBudgetExceededError(count=251, ceiling=250)
        raise RuntimeError("LLM-call ceiling exceeded: near miss")

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _fail_tasks)

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "sibling failure goal"}
        )
        run_id = created.json()["id"]
        assert (
            client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
        )
        store.enqueue_task(
            store.NewTask(
                run_id=run_id,
                task_type="engine.node.generate",
                inputs={},
                idempotency_key="sibling",
                max_attempts=1,
            ),
            db_path=isolated_db,
        )

        assert await task_worker.run_once(
            "worker", run_id=run_id, db_path=isolated_db
        )
        active = client.get(f"/api/runs/{run_id}").json()
        assert active["status"] == "queued"
        assert active["failure_kind"] is None

        assert await task_worker.run_once(
            "worker", run_id=run_id, db_path=isolated_db
        )
        failed = client.get(f"/api/runs/{run_id}").json()

    assert failed["status"] == "failed"
    assert failed["failure_kind"] is None


def test_queued_cancelled_and_blocked_runs_have_no_failure_kind(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider guidance only appears on a failed run."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    client = make_client()
    queued_id = client.post(
        "/api/runs", json={"research_goal": "queued run"}
    ).json()["id"]
    assert (
        client.post(f"/api/runs/{queued_id}/start", json={}).json()["status"]
        == "queued"
    )
    assert client.get(f"/api/runs/{queued_id}").json()["failure_kind"] is None

    assert client.post(f"/api/runs/{queued_id}/cancel").status_code == 200
    cancelled = client.get(f"/api/runs/{queued_id}").json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["failure_kind"] is None

    blocked_id = client.post(
        "/api/runs", json={"research_goal": "blocked run"}
    ).json()["id"]
    store.update_run_status(
        blocked_id, store.RunStatus.BLOCKED, db_path=isolated_db
    )
    blocked = client.get(f"/api/runs/{blocked_id}").json()
    assert blocked["status"] == "blocked"
    assert blocked["failure_kind"] is None


# Durable BYOK task failures keep key material out of stored diagnostics.


_BYOK_SECRET = "synthetic-byok-encryption-secret"
_BYOK_KEY = "sk-synthetic-echo-redaction-67890"
_DIAGNOSTIC = "provider diagnostic preserved"


def _redaction_parse_sse(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_durable_byok_failure_redacts_owned_surfaces_after_reopen(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider echo stays out of durable task diagnostics."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "byok_encryption_key", _BYOK_SECRET)

    async def _echo_key(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise LLMTimeoutError(f"provider echoed {_BYOK_KEY}; {_DIAGNOSTIC}")

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", _echo_key)

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "synthetic failure goal"}
        )
        assert created.status_code == 200
        run_id = created.json()["id"]
        credentials.store_run_credential(
            run_id,
            DEFAULT_TEST_CLIENT_ID,
            credentials.ByokCredential(
                provider="deepseek",
                api_key=_BYOK_KEY,
                model="deepseek/deepseek-v4-flash",
            ),
            db_path=isolated_db,
        )
        assert (
            client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
        )

        # An ambiguous stored-key timeout requires an explicit owner retry.
        assert await task_worker.run_once(
            "synthetic-worker", db_path=isolated_db
        )
        assert not await task_worker.run_once(
            "synthetic-worker", db_path=isolated_db
        )

    # A new API client models reopening the persisted store after the worker
    # process has gone away; the same owner can still read its run and replay.
    with make_client() as reopened:
        run = reopened.get(f"/api/runs/{run_id}")
        tasks = reopened.get(f"/api/runs/{run_id}/tasks")
        events = reopened.get(f"/api/runs/{run_id}/events")
        logs = reopened.get(
            f"/api/runs/{run_id}/logs", params={"verbose": True}
        )

    assert (
        run.status_code
        == tasks.status_code
        == events.status_code
        == logs.status_code
        == 200
    )
    run_body = run.json()
    task_rows = tasks.json()["tasks"]
    replayed_events = _redaction_parse_sse(events.text)
    serialized = json.dumps(
        [run_body, task_rows, replayed_events, logs.json()], sort_keys=True
    )
    assert run_body["status"] == "failed"
    assert run_body["failure_kind"] == "llm_timeout_unknown"
    assert _BYOK_KEY not in serialized
    assert "[REDACTED]" in serialized
    assert _DIAGNOSTIC in serialized
    assert task_rows[-1]["status"] == "failed"
    assert len(task_rows[-1]["attempts"]) == 1
    assert replayed_events[-1]["type"] == "_terminal"
    assert any(
        row.get("exc_text") and _DIAGNOSTIC in row["exc_text"]
        for row in logs.json()["logs"]
    )


@pytest.mark.asyncio
async def test_required_auth_owner_can_reopen_redacted_failure_replay(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Signed owner reads survive reopen; another researcher gets 404."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "byok_encryption_key", _BYOK_SECRET)
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "auth_secret", "synthetic-test-signing-key")
    monkeypatch.setattr(
        settings,
        "researcher_access_codes",
        '{"failure-owner":"owner-invite","failure-other":"other-invite"}',
    )

    async def _echo_key(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise LLMTimeoutError(f"provider echoed {_BYOK_KEY}; {_DIAGNOSTIC}")

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", _echo_key)

    with make_client() as client:
        owner_session = client.post(
            "/api/auth/exchange", json={"access_code": "owner-invite"}
        )
        other_session = client.post(
            "/api/auth/exchange", json={"access_code": "other-invite"}
        )
        assert owner_session.status_code == other_session.status_code == 200
        owner_headers = {
            "Authorization": f"Bearer {owner_session.json()['access_token']}"
        }
        other_headers = {
            "Authorization": f"Bearer {other_session.json()['access_token']}"
        }
        created = client.post(
            "/api/runs",
            headers=owner_headers,
            json={"research_goal": "authenticated synthetic failure"},
        )
        assert created.status_code == 200
        run_id = created.json()["id"]
        credentials.store_run_credential(
            run_id,
            "failure-owner",
            credentials.ByokCredential(
                provider="deepseek",
                api_key=_BYOK_KEY,
                model="deepseek/deepseek-v4-flash",
            ),
            db_path=isolated_db,
        )
        assert (
            client.post(
                f"/api/runs/{run_id}/start", headers=owner_headers, json={}
            ).status_code
            == 200
        )
        assert await task_worker.run_once(
            "synthetic-worker", db_path=isolated_db
        )

    with make_client() as reopened:
        owner_run = reopened.get(f"/api/runs/{run_id}", headers=owner_headers)
        owner_events = reopened.get(
            f"/api/runs/{run_id}/events", headers=owner_headers
        )
        owner_logs = reopened.get(
            f"/api/runs/{run_id}/logs",
            headers=owner_headers,
            params={"verbose": True},
        )
        other_run = reopened.get(f"/api/runs/{run_id}", headers=other_headers)
        other_events = reopened.get(
            f"/api/runs/{run_id}/events", headers=other_headers
        )

    assert owner_run.status_code == owner_events.status_code == 200
    assert owner_logs.status_code == 200
    assert other_run.status_code == other_events.status_code == 404
    replayed = _redaction_parse_sse(owner_events.text)
    failed = [
        event
        for event in replayed
        if event["type"] == "status"
        and event.get("payload", {}).get("status") == "failed"
    ]
    assert len(failed) == 1
    owned_output = json.dumps(
        [owner_run.json(), replayed, owner_logs.json()], sort_keys=True
    )
    assert "[REDACTED]" in owned_output
    assert _BYOK_KEY not in owned_output
    assert _DIAGNOSTIC in owned_output


# Run settlement when durable tasks exhaust their retry budget.
#
# A task that fails past its retry budget -- or permanently, the way an
# unsupported task type does -- used to leave its run non-terminal forever:
# ``fail_task`` marked the task failed and nothing transitioned the run, so
# no error was recorded, the SSE stream never closed, and ``cosci runs
# wait`` hung until a process restart's startup reconciliation picked the
# run up. These tests pin the in-process settlement: the run fails
# transactionally with its last claimable work, records the error, and the
# event log carries the terminal ``status`` event the SSE stream closes on.


def _settlement_running_run(db_path: str, goal: str = "settlement goal") -> str:
    """Create a run and move it to the RUNNING status; return its id."""
    run = store.create_run(goal, "standard", "engine", {})
    store.update_run_status(run.id, store.RunStatus.RUNNING, db_path=db_path)
    return run.id


def _enqueue_engine_task(
    run_id: str, key: str, db_path: str, *, max_attempts: int = 3
) -> str:
    """Enqueue one engine task by idempotency key and return its id."""
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


def _failed_status_events(run_id: str, db_path: str) -> list[dict[str, Any]]:
    """Return the run's terminal ``failed`` status events."""
    return [
        event
        for event in store.list_events(run_id, db_path=db_path)
        if event["type"] == "status"
        and (event.get("payload") or {}).get("status") == "failed"
    ]


def _settlement_parse_sse(text: str) -> list[dict[str, Any]]:
    """Parse an SSE response body into its ``data:`` event dicts."""
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


# ---------------------------------------------------------------------------
# Store-level settlement semantics
# ---------------------------------------------------------------------------


def test_exhausted_retry_budget_settles_run(isolated_db: str) -> None:
    """Failing past the budget fails the run and keeps the error."""
    run_id = _settlement_running_run(isolated_db)
    task_id = _enqueue_engine_task(
        run_id, "doomed", isolated_db, max_attempts=2
    )

    first = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert first is not None and first.id == task_id
    assert store.fail_task(
        first.id, "w1", "provider timeout", db_path=isolated_db
    )
    # Budget left: the task is requeued and the run keeps running.
    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None and saved.status == "queued"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"

    second = store.claim_task("w2", run_id=run_id, db_path=isolated_db)
    assert second is not None and second.attempt == 2
    assert store.fail_task(
        second.id, "w2", "provider timeout again", db_path=isolated_db
    )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None and saved.status == "failed"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert run.error is not None
    assert "provider timeout again" in run.error
    assert run.completed_at is not None

    failed_events = _failed_status_events(run_id, isolated_db)
    assert len(failed_events) == 1
    assert "provider timeout again" in failed_events[0]["payload"]["error"]


def test_permanent_failure_settles_run(isolated_db: str) -> None:
    """A non-retryable failure settles the run on its first attempt."""
    run_id = _settlement_running_run(isolated_db)
    task_id = _enqueue_engine_task(
        run_id, "unsupported", isolated_db, max_attempts=3
    )
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id

    assert store.fail_task(
        leased.id,
        "w1",
        "unsupported task type: nope",
        retryable=False,
        db_path=isolated_db,
    )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None and saved.status == "failed"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert run.error is not None
    assert "unsupported task type" in run.error
    assert len(_failed_status_events(run_id, isolated_db)) == 1


def test_claimable_sibling_task_blocks_settlement(isolated_db: str) -> None:
    """A failed task with queued work left must not settle the run."""
    run_id = _settlement_running_run(isolated_db)
    doomed = _enqueue_engine_task(run_id, "doomed", isolated_db, max_attempts=1)
    _enqueue_engine_task(run_id, "survivor", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == doomed

    assert store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"
    assert _failed_status_events(run_id, isolated_db) == []


def test_active_sibling_lease_blocks_settlement(isolated_db: str) -> None:
    """A live sibling lease may still fan out work, blocking settlement."""
    run_id = _settlement_running_run(isolated_db)
    doomed = _enqueue_engine_task(run_id, "doomed", isolated_db, max_attempts=1)
    sibling = _enqueue_engine_task(
        run_id, "sibling", isolated_db, max_attempts=1
    )
    leased_doomed = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    leased_sibling = store.claim_task("w2", run_id=run_id, db_path=isolated_db)
    assert leased_doomed is not None and leased_doomed.id == doomed
    assert leased_sibling is not None and leased_sibling.id == sibling

    assert store.fail_task(
        leased_doomed.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"
    assert _failed_status_events(run_id, isolated_db) == []


def test_task_failure_does_not_settle_inactive_run(isolated_db: str) -> None:
    """Only queued/running/synthesizing runs settle; a draft stays draft."""
    run = store.create_run("draft goal", "standard", "engine", {})
    task_id = _enqueue_engine_task(run.id, "doomed", isolated_db)
    leased = store.claim_task("w1", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id

    assert store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    saved = store.get_run(run.id, db_path=isolated_db)
    assert saved is not None and saved.status == "draft"
    assert _failed_status_events(run.id, isolated_db) == []


def test_concurrent_final_failures_settle_exactly_once(
    isolated_db: str,
) -> None:
    """Two workers failing the last tasks cannot double-emit settlement."""
    run_id = _settlement_running_run(isolated_db)
    task_a = _enqueue_engine_task(run_id, "a", isolated_db, max_attempts=1)
    task_b = _enqueue_engine_task(run_id, "b", isolated_db, max_attempts=1)
    leased_a = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    leased_b = store.claim_task("w2", run_id=run_id, db_path=isolated_db)
    assert leased_a is not None and leased_a.id == task_a
    assert leased_b is not None and leased_b.id == task_b

    def _fail(task_id: str, worker: str) -> bool:
        return store.fail_task(
            task_id, worker, "boom", retryable=False, db_path=isolated_db
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [
            pool.submit(_fail, leased_a.id, "w1"),
            pool.submit(_fail, leased_b.id, "w2"),
        ]
        assert all(future.result() for future in outcomes)

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "failed"
    assert len(_failed_status_events(run_id, isolated_db)) == 1


def test_settled_run_is_not_reprocessed_at_startup(isolated_db: str) -> None:
    """An in-process settlement is final for the startup reconciliation."""
    run_id = _settlement_running_run(isolated_db)
    task_id = _enqueue_engine_task(
        run_id, "doomed", isolated_db, max_attempts=1
    )
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id
    assert store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )
    events_before = store.list_events(run_id, db_path=isolated_db)

    reconciled = store.reconcile_interrupted_runs(db_path=isolated_db)

    assert run_id not in reconciled["failed"]
    assert run_id not in reconciled["resumable"]
    assert store.list_events(run_id, db_path=isolated_db) == events_before


# ---------------------------------------------------------------------------
# Worker-level settlement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cohort_settles_run_when_budget_exhausts(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cohort drains an always-failing task, then its run settles failed."""
    run_id = _settlement_running_run(isolated_db)
    task_id = _enqueue_engine_task(
        run_id, "doomed", isolated_db, max_attempts=2
    )

    async def _always_fail(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _always_fail)

    await task_worker.run_run_worker_pool(
        run_id,
        "settle-test",
        worker_count=2,
        policy=task_worker.WorkerPolicy(db_path=isolated_db, lease_seconds=5),
    )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.attempt == saved.max_attempts
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert "provider exploded" in (run.error or "")
    assert len(_failed_status_events(run_id, isolated_db)) == 1


@pytest.mark.asyncio
async def test_unsupported_task_type_settles_run(isolated_db: str) -> None:
    """The one permanent failure class settles the run on first failure."""
    run_id = _settlement_running_run(isolated_db)
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="unknown.task",
            inputs={},
            idempotency_key="unknown",
        ),
        db_path=isolated_db,
    )

    assert await task_worker.run_once("w1", db_path=isolated_db)

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert "unsupported task type" in (run.error or "")
    assert len(_failed_status_events(run_id, isolated_db)) == 1


# ---------------------------------------------------------------------------
# API and SSE surfaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_run_settles_through_api_and_sse(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The settlement surfaces in the run API and closes the SSE stream."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    async def _always_fail(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _always_fail)

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "doomed goal"}
        )
        run_id = created.json()["id"]
        started = client.post(f"/api/runs/{run_id}/start", json={})
        assert started.status_code == 200

        # The bootstrap task retries three times before its budget is spent.
        for _ in range(3):
            assert await task_worker.run_once("w", db_path=isolated_db)
        assert not await task_worker.run_once("w", db_path=isolated_db)

        body = client.get(f"/api/runs/{run_id}").json()
        assert body["status"] == "failed"
        assert "provider exploded" in body["error"]

        frames = _settlement_parse_sse(
            client.get(f"/api/runs/{run_id}/events").text
        )

    assert frames[-1]["type"] == "_terminal"
    assert frames[-1]["payload"]["status"] == "failed"
    failed = [
        frame
        for frame in frames
        if frame["type"] == "status"
        and (frame.get("payload") or {}).get("status") == "failed"
    ]
    assert len(failed) == 1
    assert "provider exploded" in failed[0]["payload"]["error"]

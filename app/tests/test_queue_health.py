"""``/health`` reflecting real durable-queue and disk conditions (L6).

Before this, ``/health`` was store reachability plus an import lookup, so
a wedged run, an exhausted-retry-budget task, or a full disk all reported
``healthy``. These tests cover three layers of the fix:

- the store-level read-only probe (``app.store.tasks.queue_health_snapshot``),
- the diagnostics-level checks that wrap it (``check_queue``, ``check_disk``,
  ``derive_overall_health``, and their short-TTL cache), and
- the ``/health`` endpoint itself, reproducing the exact gap the F1
  settlement fix leaves open: a lease that expires *after* its retry
  budget is spent is never explicitly failed (nobody still holds it to
  call ``fail_task``), so it stays ``leased`` forever and
  ``_settle_run_out_of_work`` never sees the run as out of work.

Throughout, a degraded condition must return HTTP 200 with
``status: "degraded"`` -- never 503 -- because a failed healthcheck kills
the container mid-run (see AGENTS.md's healthcheck-failure-spiral
incident), and only true store unreachability may take the process down.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import diagnostics, store
from app.config import settings
from app.diagnostics import HealthCheck
from app.store.tasks import queue_health_snapshot
from app.store.tasks_probes import QueueHealthSnapshot
from tests._client import make_client as _client
from tests._client import make_operator_client as _operator_client


def _running_run(db_path: str, goal: str = "queue health goal") -> str:
    """Create a run and move it to RUNNING; return its id."""
    run = store.create_run(goal, "standard", "engine", {})
    store.update_run_status(run.id, store.RunStatus.RUNNING, db_path=db_path)
    return run.id


def _enqueue(run_id: str, key: str, db_path: str, **kwargs: Any) -> str:
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
    run_id = _running_run(isolated_db)
    _enqueue(run_id, "queued", isolated_db)

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == ()
    assert snapshot.queued_depth == 1


def test_active_lease_is_not_stalled(isolated_db: str) -> None:
    run_id = _running_run(isolated_db)
    task_id = _enqueue(run_id, "leased", isolated_db)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == ()


def test_rescuable_expired_lease_is_not_stalled(isolated_db: str) -> None:
    """Retry budget left: the next claim rescues it automatically."""
    run_id = _running_run(isolated_db)
    task_id = _enqueue(run_id, "rescuable", isolated_db, max_attempts=3)
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
    run_id = _running_run(isolated_db)
    task_id = _enqueue(run_id, "orphaned", isolated_db, max_attempts=1)
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
    run_id = _running_run(isolated_db)
    doomed = _enqueue(run_id, "doomed", isolated_db, max_attempts=1)
    _enqueue(run_id, "survivor", isolated_db, max_attempts=1)
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
    run_id = _running_run(isolated_db)
    task_id = _enqueue(run_id, "orphaned", isolated_db, max_attempts=1)
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
    run_id = _running_run(isolated_db)
    _enqueue(run_id, "queued", isolated_db)

    res = _client().get("/health")

    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_health_degrades_at_200_when_a_run_is_stalled(
    isolated_db: str,
) -> None:
    """The exact scenario L6 exists for: a wedged run, surfaced at 200."""
    run_id = _running_run(isolated_db)
    task_id = _enqueue(run_id, "orphaned", isolated_db, max_attempts=1)
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

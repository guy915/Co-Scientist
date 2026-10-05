from __future__ import annotations

import concurrent.futures
import json
from typing import Any

import pytest
from co_scientist.exceptions import LLMCallBudgetExceededError, LLMTimeoutError

import app.store.tasks_lifecycle as store_tasks_attempts
from app import credentials, diagnostics, engine_tasks, task_worker
from app.config import settings
from app.diagnostics import HealthCheck
from app.store import db, runs
from app.store import db as store_db
from app.store import events as store_events
from app.store import runs_views as views
from app.store import tasks as store
from app.store import tasks as store_tasks
from app.store import tasks_lifecycle as lifecycle
from app.store.models import (
    UNKNOWN_PROVIDER_OUTCOME_ERROR,
    RunStatus,
    ScientificTask,
)
from app.store.runs import RunCreateOptions
from app.store.tasks import queue_health_snapshot
from app.store.tasks_lifecycle import QueueHealthSnapshot
from tests._client import DEFAULT_TEST_CLIENT_ID, make_client
from tests._client import create_run as _create_run
from tests._client import make_client as _client
from tests._client import make_operator_client as _operator_client
from tests._store_helpers import enqueue_task, seed_run

# Campaign requests enforce exact zero price; lost leases are retry-safe only
# without caller credentials.


def _campaign_run_with_expired_lease(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    run = seed_run(
        "Campaign lease loss",
        profile="express",
        options=RunCreateOptions(
            client_id=DEFAULT_TEST_CLIENT_ID, execution_policy="campaign"
        ),
    )
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=isolated_db)
    task = enqueue_task(
        run.id,
        "engine.fanout.verification.item",
        "verification:seed",
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
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    replayed: list[str] = []

    async def _replay(
        task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        replayed.append(task.task_type)
        return {"replayed": True}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", _replay)
    run_id, task_id = _campaign_run_with_expired_lease(isolated_db, monkeypatch)

    assert await task_worker.run_once("new-worker", db_path=isolated_db)

    assert replayed == ["engine.fanout.verification.item"]
    task = store.get_task(task_id, db_path=isolated_db)
    assert task is not None and task.status == "completed"
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status != RunStatus.FAILED


@pytest.mark.asyncio
async def test_expired_campaign_lease_with_byok_still_fails_closed(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(
        settings, "byok_encryption_key", "synthetic-campaign-lease-secret"
    )
    replayed: list[str] = []

    async def _must_not_call(
        task: ScientificTask, *, db_path: str | None = None
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


# Queue/disk degradation returns HTTP 200 so liveness probes cannot kill
# productive runs.


def _health_running_run(db_path: str, goal: str = "queue health goal") -> str:
    run = seed_run(goal)
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=db_path)
    return run.id


def _health_enqueue(run_id: str, key: str, db_path: str, **kwargs: Any) -> str:
    task = enqueue_task(
        run_id, "engine.node.ranking", key, **kwargs, db_path=db_path
    )
    return task.id


def _expire_lease(task_id: str, db_path: str) -> None:
    # Expire the lease without changing attempts to model a worker that died
    # without failing its task.
    with db.connect(db_path) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (task_id,),
        )
        conn.commit()


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
    run_id = _health_running_run(isolated_db)
    task_id = _health_enqueue(run_id, "rescuable", isolated_db, max_attempts=3)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id
    _expire_lease(task_id, isolated_db)

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == ()
    assert snapshot.rescuable_leases == 1


def test_orphaned_exhausted_lease_leaves_run_stalled(isolated_db: str) -> None:
    # A dead exhausted lease has no owner to fail it; health must expose the
    # stranded running state.
    run_id = _health_running_run(isolated_db)
    task_id = _health_enqueue(run_id, "orphaned", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id
    _expire_lease(task_id, isolated_db)

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == (run_id,)
    assert snapshot.rescuable_leases == 0
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"


def test_completed_run_is_excluded(isolated_db: str) -> None:
    run = seed_run("done goal")
    runs.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == ()


def test_failed_task_counted_without_stalling_active_sibling(
    isolated_db: str,
) -> None:
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
    assert snapshot.stalled_run_ids == ()


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
    huge_floor = 10**18
    result = diagnostics.check_disk(
        str(tmp_path) + "/db.sqlite", min_free_bytes=huge_floor
    )
    assert result.ok is False
    assert result.detail is not None and "floor" in result.detail


def test_derive_overall_health_degrades_never_unhealthy_on_queue_or_disk() -> (
    None
):
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


def test_health_reports_all_four_checks() -> None:
    data = _client().get("/health").json()
    assert set(data["checks"]) == {"store", "engine", "queue", "disk"}


def test_health_healthy_with_a_busy_but_progressing_run(
    isolated_db: str,
) -> None:
    run_id = _health_running_run(isolated_db)
    _health_enqueue(run_id, "queued", isolated_db)

    res = _client().get("/health")

    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_health_degrades_at_200_when_a_run_is_stalled(
    isolated_db: str,
) -> None:
    run_id = _health_running_run(isolated_db)
    task_id = _health_enqueue(run_id, "orphaned", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id
    _expire_lease(task_id, isolated_db)

    res = _client().get("/health")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "degraded"
    assert data["checks"]["queue"]["ok"] is False
    operator = _operator_client().get("/health").json()
    assert run_id in (operator["checks"]["queue"]["detail"] or "")
    assert data["checks"]["queue"]["detail"] is None


def test_health_degrades_at_200_when_disk_is_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "health_check_min_free_disk_bytes", 10**18)

    res = _client().get("/health")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "degraded"
    assert data["checks"]["disk"]["ok"] is False


# Each failed attempt needs bounded history; overwriting one error loses
# distinct failure diagnoses.


def _history_running_run(db_path: str, goal: str = "attempts goal") -> str:
    run = seed_run(goal)
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=db_path)
    return run.id


def _history_enqueue(
    run_id: str, key: str, db_path: str, *, max_attempts: int = 3
) -> str:
    task = enqueue_task(
        run_id,
        "engine.node.ranking",
        key,
        max_attempts=max_attempts,
        db_path=db_path,
    )
    return task.id


def test_lease_renewal_does_not_move_recorded_start_time(
    isolated_db: str,
) -> None:
    # Heartbeats update lease timestamps, but attempt history must retain the
    # original claim time.
    run_id = _history_running_run(isolated_db)
    task_id = _history_enqueue(run_id, "k", isolated_db, max_attempts=3)

    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None
    claim_time = leased.updated_at

    assert lifecycle.renew_task_lease(
        leased.id, "w1", 60.0, db_path=isolated_db
    )
    assert store.fail_task(leased.id, "w1", "timed out", db_path=isolated_db)

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None
    assert saved.attempts[0]["started_at"] == claim_time


def test_two_failures_record_distinct_attempts_in_order(
    isolated_db: str,
) -> None:
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
    assert saved.attempts[-1]["error"] == f"failure {over_cap - 1}"
    first_kept = over_cap - store_tasks_attempts._MAX_STORED_ATTEMPTS
    assert saved.attempts[0]["error"] == f"failure {first_kept}"


def test_failed_attempt_write_is_transactional_with_settlement(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    with make_client() as client:
        created = _create_run(client, "attempts endpoint goal")
        run_id = created.json()["id"]
        runs.update_run_status(run_id, RunStatus.RUNNING, db_path=isolated_db)
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


@pytest.mark.asyncio
async def test_owned_run_api_retains_typed_budget_failure_after_reopen(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    async def _over_budget(
        _task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise LLMCallBudgetExceededError(count=251, ceiling=250)

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _over_budget)

    with make_client() as client:
        created = _create_run(client, "typed failure goal")
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
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    async def _raise_known_or_near_miss(
        _task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise error

    monkeypatch.setattr(
        engine_tasks, "execute_engine_task", _raise_known_or_near_miss
    )

    with make_client() as client:
        created = _create_run(client, "typed timeout goal")
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
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    async def _fail_tasks(
        task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        if task.task_type == "engine.bootstrap":
            raise LLMCallBudgetExceededError(count=251, ceiling=250)
        raise RuntimeError("LLM-call ceiling exceeded: near miss")

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _fail_tasks)

    with make_client() as client:
        created = _create_run(client, "sibling failure goal")
        run_id = created.json()["id"]
        assert (
            client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
        )
        enqueue_task(
            run_id,
            "engine.node.generate",
            "sibling",
            max_attempts=1,
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
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    client = make_client()
    queued_id = _create_run(client, "queued run").json()["id"]
    assert (
        client.post(f"/api/runs/{queued_id}/start", json={}).json()["status"]
        == "queued"
    )
    assert client.get(f"/api/runs/{queued_id}").json()["failure_kind"] is None

    assert client.post(f"/api/runs/{queued_id}/cancel").status_code == 200
    cancelled = client.get(f"/api/runs/{queued_id}").json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["failure_kind"] is None

    blocked_id = _create_run(client, "blocked run").json()["id"]
    runs.update_run_status(blocked_id, RunStatus.BLOCKED, db_path=isolated_db)
    blocked = client.get(f"/api/runs/{blocked_id}").json()
    assert blocked["status"] == "blocked"
    assert blocked["failure_kind"] is None


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
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "byok_encryption_key", _BYOK_SECRET)

    async def _echo_key(
        _task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise LLMTimeoutError(f"provider echoed {_BYOK_KEY}; {_DIAGNOSTIC}")

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", _echo_key)

    with make_client() as client:
        created = _create_run(client, "synthetic failure goal")
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

        assert await task_worker.run_once(
            "synthetic-worker", db_path=isolated_db
        )
        assert not await task_worker.run_once(
            "synthetic-worker", db_path=isolated_db
        )

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
        _task: ScientificTask, *, db_path: str | None = None
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
        created = _create_run(
            client, "authenticated synthetic failure", headers=owner_headers
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


# Settle runs transactionally when their last claimable task fails, or SSE never
# closes.


def _settlement_running_run(db_path: str, goal: str = "settlement goal") -> str:
    run = seed_run(goal)
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=db_path)
    return run.id


def _failed_status_events(run_id: str, db_path: str) -> list[dict[str, Any]]:
    return [
        event
        for event in store_events.list_events(run_id, db_path=db_path)
        if event["type"] == "status"
        and (event.get("payload") or {}).get("status") == "failed"
    ]


def test_exhausted_retry_budget_settles_run(isolated_db: str) -> None:
    run_id = _settlement_running_run(isolated_db)
    task_id = _history_enqueue(run_id, "doomed", isolated_db, max_attempts=2)

    first = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert first is not None and first.id == task_id
    assert store.fail_task(
        first.id, "w1", "provider timeout", db_path=isolated_db
    )
    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None and saved.status == "queued"
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"

    second = store.claim_task("w2", run_id=run_id, db_path=isolated_db)
    assert second is not None and second.attempt == 2
    assert store.fail_task(
        second.id, "w2", "provider timeout again", db_path=isolated_db
    )

    saved = store.get_task(task_id, db_path=isolated_db)
    assert saved is not None and saved.status == "failed"
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert run.error is not None
    assert "provider timeout again" in run.error
    assert run.completed_at is not None

    failed_events = _failed_status_events(run_id, isolated_db)
    assert len(failed_events) == 1
    assert "provider timeout again" in failed_events[0]["payload"]["error"]


def test_permanent_failure_settles_run(isolated_db: str) -> None:
    run_id = _settlement_running_run(isolated_db)
    task_id = _history_enqueue(
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
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert run.error is not None
    assert "unsupported task type" in run.error
    assert len(_failed_status_events(run_id, isolated_db)) == 1


def test_claimable_sibling_task_blocks_settlement(isolated_db: str) -> None:
    run_id = _settlement_running_run(isolated_db)
    doomed = _history_enqueue(run_id, "doomed", isolated_db, max_attempts=1)
    _history_enqueue(run_id, "survivor", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == doomed

    assert store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"
    assert _failed_status_events(run_id, isolated_db) == []


def test_active_sibling_lease_blocks_settlement(isolated_db: str) -> None:
    run_id = _settlement_running_run(isolated_db)
    doomed = _history_enqueue(run_id, "doomed", isolated_db, max_attempts=1)
    sibling = _history_enqueue(run_id, "sibling", isolated_db, max_attempts=1)
    leased_doomed = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    leased_sibling = store.claim_task("w2", run_id=run_id, db_path=isolated_db)
    assert leased_doomed is not None and leased_doomed.id == doomed
    assert leased_sibling is not None and leased_sibling.id == sibling

    assert store.fail_task(
        leased_doomed.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"
    assert _failed_status_events(run_id, isolated_db) == []


def test_task_failure_does_not_settle_inactive_run(isolated_db: str) -> None:
    run = seed_run("draft goal")
    task_id = _history_enqueue(run.id, "doomed", isolated_db)
    leased = store.claim_task("w1", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id

    assert store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    saved = runs.get_run(run.id, db_path=isolated_db)
    assert saved is not None and saved.status == "draft"
    assert _failed_status_events(run.id, isolated_db) == []


def test_concurrent_final_failures_settle_exactly_once(
    isolated_db: str,
) -> None:
    run_id = _settlement_running_run(isolated_db)
    task_a = _history_enqueue(run_id, "a", isolated_db, max_attempts=1)
    task_b = _history_enqueue(run_id, "b", isolated_db, max_attempts=1)
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

    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "failed"
    assert len(_failed_status_events(run_id, isolated_db)) == 1


def test_settled_run_is_not_reprocessed_at_startup(isolated_db: str) -> None:
    run_id = _settlement_running_run(isolated_db)
    task_id = _history_enqueue(run_id, "doomed", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == task_id
    assert store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )
    events_before = store_events.list_events(run_id, db_path=isolated_db)

    reconciled = views.reconcile_interrupted_runs(db_path=isolated_db)

    assert run_id not in reconciled["failed"]
    assert run_id not in reconciled["resumable"]
    assert (
        store_events.list_events(run_id, db_path=isolated_db) == events_before
    )


@pytest.mark.asyncio
async def test_cohort_settles_run_when_budget_exhausts(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _settlement_running_run(isolated_db)
    task_id = _history_enqueue(run_id, "doomed", isolated_db, max_attempts=2)

    async def _always_fail(
        _task: ScientificTask, *, db_path: str | None = None
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
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert "provider exploded" in (run.error or "")
    assert len(_failed_status_events(run_id, isolated_db)) == 1


@pytest.mark.asyncio
async def test_unsupported_task_type_settles_run(isolated_db: str) -> None:
    run_id = _settlement_running_run(isolated_db)
    enqueue_task(run_id, "unknown.task", "unknown", db_path=isolated_db)

    assert await task_worker.run_once("w1", db_path=isolated_db)

    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert "unsupported task type" in (run.error or "")
    assert len(_failed_status_events(run_id, isolated_db)) == 1


@pytest.mark.asyncio
async def test_failed_run_settles_through_api_and_sse(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    async def _always_fail(
        _task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _always_fail)

    with make_client() as client:
        created = _create_run(client, "doomed goal")
        run_id = created.json()["id"]
        started = client.post(f"/api/runs/{run_id}/start", json={})
        assert started.status_code == 200

        for _ in range(3):
            assert await task_worker.run_once("w", db_path=isolated_db)
        assert not await task_worker.run_once("w", db_path=isolated_db)

        body = client.get(f"/api/runs/{run_id}").json()
        assert body["status"] == "failed"
        assert "provider exploded" in body["error"]

        frames = _redaction_parse_sse(
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

from __future__ import annotations

import concurrent.futures
import json
from typing import Any

import pytest
from co_scientist.exceptions import LLMCallBudgetExceededError, LLMTimeoutError

import app.store.tasks_lifecycle as store_tasks_attempts
from app import credentials, engine_tasks, task_worker
from app.config import settings
from app.store import db as store_db
from app.store import events as store_events
from app.store import runs
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
from tests._client import DEFAULT_TEST_CLIENT_ID, make_client
from tests._client import create_run as _create_run
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
    assert [a["attempt"] for a in saved.attempts] == list(
        range(first_kept + 1, over_cap + 1)
    )


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
@pytest.mark.parametrize(
    ("error", "attempts", "expected_kind", "expected_message"),
    [
        pytest.param(
            LLMCallBudgetExceededError(count=251, ceiling=250),
            1,
            "llm_call_budget_exceeded",
            "251 provider requests against a budget of 250",
            id="budget",
        ),
        pytest.param(
            LLMTimeoutError("provider timed out"),
            1,
            "llm_timeout_unknown",
            UNKNOWN_PROVIDER_OUTCOME_ERROR,
            id="timeout",
        ),
        pytest.param(
            RuntimeError("LLM-call ceiling exceeded: 251 provider requests"),
            3,
            None,
            "LLM-call ceiling exceeded: 251 provider requests",
            id="near-miss-is-unclassified",
        ),
    ],
)
async def test_owned_run_api_classifies_only_exact_terminal_failure_types(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    attempts: int,
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
        created = _create_run(client, "typed failure goal")
        run_id = created.json()["id"]
        assert (
            client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
        )
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
        sessions = {
            name: client.post(
                "/api/auth/exchange", json={"access_code": f"{name}-invite"}
            ).json()["access_token"]
            for name in ("owner", "other")
        }
        owner = {"Authorization": f"Bearer {sessions['owner']}"}
        other = {"Authorization": f"Bearer {sessions['other']}"}
        created = _create_run(
            client, "authenticated synthetic failure", headers=owner
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
        started = client.post(
            f"/api/runs/{run_id}/start", headers=owner, json={}
        )
        assert started.status_code == 200
        assert await task_worker.run_once(
            "synthetic-worker", db_path=isolated_db
        )
        assert not await task_worker.run_once(
            "synthetic-worker", db_path=isolated_db
        )

    with make_client() as reopened:
        run = reopened.get(f"/api/runs/{run_id}", headers=owner)
        task_rows = reopened.get(f"/api/runs/{run_id}/tasks", headers=owner)
        events = reopened.get(f"/api/runs/{run_id}/events", headers=owner)
        logs = reopened.get(
            f"/api/runs/{run_id}/logs",
            headers=owner,
            params={"verbose": True},
        )
        other_run = reopened.get(f"/api/runs/{run_id}", headers=other)
        other_events = reopened.get(f"/api/runs/{run_id}/events", headers=other)

    assert run.status_code == task_rows.status_code == 200
    assert events.status_code == logs.status_code == 200
    assert other_run.status_code == other_events.status_code == 404
    run_body = run.json()
    rows = task_rows.json()["tasks"]
    replayed = _redaction_parse_sse(events.text)
    owned_output = json.dumps(
        [run_body, rows, replayed, logs.json()], sort_keys=True
    )
    assert run_body["status"] == "failed"
    assert run_body["failure_kind"] == "llm_timeout_unknown"
    assert _BYOK_KEY not in owned_output
    assert "[REDACTED]" in owned_output
    assert _DIAGNOSTIC in owned_output
    assert rows[-1]["status"] == "failed" and len(rows[-1]["attempts"]) == 1
    assert replayed[-1]["type"] == "_terminal"
    failed = [
        event
        for event in replayed
        if event["type"] == "status"
        and event.get("payload", {}).get("status") == "failed"
    ]
    assert len(failed) == 1
    assert any(
        row.get("exc_text") and _DIAGNOSTIC in row["exc_text"]
        for row in logs.json()["logs"]
    )


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


@pytest.mark.parametrize("sibling_leased", [False, True])
def test_a_live_sibling_task_blocks_settlement(
    isolated_db: str, sibling_leased: bool
) -> None:
    run_id = _settlement_running_run(isolated_db)
    doomed = _history_enqueue(run_id, "doomed", isolated_db, max_attempts=1)
    _history_enqueue(run_id, "sibling", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == doomed
    if sibling_leased:
        assert store.claim_task("w2", run_id=run_id, db_path=isolated_db)

    assert store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
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
async def test_unsupported_task_type_fails_permanently_and_settles_run(
    isolated_db: str,
) -> None:
    run_id = _settlement_running_run(isolated_db)
    task = enqueue_task(
        run_id, "unknown.task", "unknown", max_attempts=3, db_path=isolated_db
    )

    assert await task_worker.run_once("w1", db_path=isolated_db)

    failed = store.get_task(task.id, db_path=isolated_db)
    assert failed is not None and failed.status == "failed"
    assert failed.attempt < failed.max_attempts, (
        "an unknown type is not retried"
    )
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.status == "failed"
    assert "unsupported task type" in (run.error or "")
    assert len(_failed_status_events(run_id, isolated_db)) == 1

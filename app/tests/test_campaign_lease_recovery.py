"""Expired engine leases on campaign runs are rescued, not failed.

An engine lease that outlives its worker normally stops the run with
``llm_timeout_unknown``: nothing durable says whether the lost request was
billed. A campaign run is the exception. Its policy is persisted at creation
and, while it holds, every provider request must pass the exact zero-price
gate or is refused before transport, so a lost lease cannot have spent
anything -- unless a caller credential rode along. Production run 34b29088
(2026-09-27) failed after a restart for want of this distinction.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import credentials, engine_tasks, store, task_worker
from app.config import settings
from app.store import db as store_db
from tests._client import DEFAULT_TEST_CLIENT_ID


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

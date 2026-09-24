"""Typed provider failure kinds on the owned run API."""

from __future__ import annotations

from typing import Any

import pytest
from co_scientist.exceptions import LLMCallBudgetExceededError, LLMTimeoutError

from app import engine_tasks, store, task_worker
from app.config import settings
from app.store.tasks_model import UNKNOWN_PROVIDER_OUTCOME_ERROR
from tests._client import make_client


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

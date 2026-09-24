"""The bootstrap commit resolves pause requests under its commit lock."""

from __future__ import annotations

from typing import Any

import pytest

from app import engine_tasks, engine_tasks_support, store
from app.config import settings
from tests._client import make_client
from tests._engine_tasks_helpers import _task_state


class _PauseDuringPrepare:
    def __init__(self, client: Any, run_id: str, state: dict[str, Any]) -> None:
        self.client = client
        self.run_id = run_id
        self.state = state

    async def prepare_task_state(self, *_: Any, **__: Any) -> dict[str, Any]:
        response = self.client.post(f"/api/runs/{self.run_id}/pause")
        assert response.status_code == 200
        return self.state


def _start_bootstrap(db_path: str) -> tuple[Any, str, Any]:
    client = make_client()
    created = client.post(
        "/api/runs", json={"research_goal": "Pause during bootstrap prepare"}
    )
    run_id = str(created.json()["id"])
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    task = store.claim_task("bootstrap-worker", run_id=run_id, db_path=db_path)
    assert task is not None
    return client, run_id, task


def _resume_after_paused_snapshot(
    monkeypatch: pytest.MonkeyPatch, client: Any, run_id: str
) -> list[bool]:
    get_run = store.get_run
    resumed: list[bool] = []

    def interleaved_get(
        requested: str, db_path: str | None = None, conn: Any | None = None
    ) -> Any:
        run = get_run(requested, db_path=db_path, conn=conn)
        if (
            requested == run_id
            and run is not None
            and run.status == "paused"
            and not resumed
        ):
            resumed.append(True)
            response = client.post(f"/api/runs/{run_id}/resume")
            assert response.status_code == 200
        return run

    monkeypatch.setattr(store, "get_run", interleaved_get)
    return resumed


def _enqueue_bootstrap_successor(
    task: Any,
    _state: dict[str, Any],
    _successor: str | None,
    successor_type: str,
    conn: Any,
) -> Any:
    return store.enqueue_task(
        store.NewTask(
            run_id=task.run_id,
            task_type=successor_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{successor_type}:after:{task.id}",
            dependencies=(task.id,),
        ),
        conn=conn,
    )


@pytest.mark.asyncio
async def test_bootstrap_rechecks_pause_after_resume_before_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id, task = _start_bootstrap(isolated_db)
    state = _task_state(run_id)
    generator = _PauseDuringPrepare(client, run_id, state)
    resumed = _resume_after_paused_snapshot(monkeypatch, client, run_id)

    async def no_intake(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(engine_tasks, "_screen_bootstrap_intake", no_intake)
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "sync_engine_llm_backend", lambda *_: None
    )
    monkeypatch.setattr(
        engine_tasks_support,
        "_enqueue_node_portfolio",
        _enqueue_bootstrap_successor,
    )

    result = await engine_tasks.execute_bootstrap(task, db_path=isolated_db)

    assert resumed == [True]
    assert result.get("status") != "paused"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "queued"
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert (
        checkpoint is not None
        and checkpoint["stage"] == f"engine_task:{task.id}"
    )
    assert checkpoint["state"]["resume_successor"] == "engine.node.supervisor"
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert len(tasks) == 2
    assert sum(item.task_type == "engine.bootstrap" for item in tasks) == 1
    assert any(item.task_type == "engine.node.supervisor" for item in tasks)
    assert store.complete_task(
        task.id, "bootstrap-worker", result, db_path=isolated_db
    )
    claim = store.claim_task(
        "supervisor-worker", run_id=run_id, db_path=isolated_db
    )
    assert claim is not None and claim.task_type == "engine.node.supervisor"


@pytest.mark.asyncio
async def test_bootstrap_pause_without_resume_commits_paused_checkpoint(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id, task = _start_bootstrap(isolated_db)
    generator = _PauseDuringPrepare(client, run_id, _task_state(run_id))

    async def no_intake(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(engine_tasks, "_screen_bootstrap_intake", no_intake)
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "sync_engine_llm_backend", lambda *_: None
    )
    monkeypatch.setattr(
        engine_tasks_support,
        "_enqueue_node_portfolio",
        _enqueue_bootstrap_successor,
    )

    result = await engine_tasks.execute_bootstrap(task, db_path=isolated_db)

    assert result["status"] == "paused"
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task_paused:{task.id}"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "paused"
    assert len(store.list_tasks(run_id, db_path=isolated_db)) == 1


def test_resume_keeps_intake_safety_artifacts_for_leased_bootstrap(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id, _task = _start_bootstrap(isolated_db)
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run_id,
            stage="intake",
            decision="allow",
            reason="intake screen completed",
            matches=[],
        ),
        db_path=isolated_db,
    )
    store.append_event(
        run_id,
        "safety",
        {"event": "intake_decision_persisted"},
        db_path=isolated_db,
    )
    assert client.post(f"/api/runs/{run_id}/pause").status_code == 200

    resumed = client.post(f"/api/runs/{run_id}/resume")

    assert resumed.status_code == 200
    decisions = store.list_safety_decisions(run_id, db_path=isolated_db)
    assert [decision["reason"] for decision in decisions] == [
        "intake screen completed"
    ]
    assert any(
        event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
        for event in store.list_events(run_id, db_path=isolated_db)
    )
    assert any(
        event["type"] == "safety"
        and event["payload"].get("event") == "intake_decision_persisted"
        for event in store.list_events(run_id, db_path=isolated_db)
    )

"""Owned API acceptance for pause quiescence across a late task commit."""

from __future__ import annotations

from typing import Any

import pytest

from app import engine_tasks, store
from app.config import settings
from app.engine_tasks_context import TaskCommit
from tests._client import make_client
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

_OWNER = {"X-Client-ID": "pause-cohort-owner"}


def _owned_running_run(db_path: str) -> tuple[Any, str]:
    """Create the RUNNING run through the owner-scoped API."""
    client = make_client()
    created = client.post(
        "/api/runs",
        headers=_OWNER,
        json={
            "research_goal": "Pause a durable engine cohort",
            "tier": "express",
        },
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    store.update_run_status(run_id, store.RunStatus.RUNNING, db_path=db_path)
    return client, run_id


def _leased_supervisor(
    run_id: str, db_path: str
) -> tuple[dict[str, Any], int, store.ScientificTask]:
    """Seed an engine checkpoint and claim its supervisor writer."""
    state = _task_state(run_id)
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    writer = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}supervisor",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="pause-cohort:supervisor",
        ),
        db_path=db_path,
    )
    leased = store.claim_task(
        "pause-cohort-writer", run_id=run_id, db_path=db_path
    )
    assert leased is not None and leased.id == writer.id
    return state, checkpoint_seq, leased


async def _complete_supervisor_after_pause(
    client: Any,
    run_id: str,
    writer: tuple[dict[str, Any], int, store.ScientificTask],
    db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finish deterministic node work across the completed pause boundary."""
    state, checkpoint_seq, leased = writer
    monkeypatch.setattr(
        engine_tasks,
        "_prepare_node_task",
        lambda *_: (
            state,
            TaskCommit(leased, checkpoint_seq, db_path),
            "supervisor",
        ),
    )

    async def execute_node(
        _name: str, node_state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        return {**node_state, "committed_after_pause": True}, "generate"

    from co_scientist import task_runtime

    monkeypatch.setattr(task_runtime, "execute_task_node", execute_node)
    commit_node_result = engine_tasks._commit_node_result

    async def pause_then_commit(
        commit: TaskCommit,
        run: store.RunRow,
        node_name: str,
        committed: dict[str, Any],
        successor: str | None,
    ) -> dict[str, Any]:
        response = client.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "paused"
        return await commit_node_result(
            commit, run, node_name, committed, successor
        )

    monkeypatch.setattr(engine_tasks, "_commit_node_result", pause_then_commit)
    result = await engine_tasks.execute_node_task(leased, db_path=db_path)
    assert result["status"] == "paused"
    assert store.complete_task(
        leased.id, "pause-cohort-writer", result, db_path=db_path
    )


@pytest.mark.asyncio
async def test_owned_pause_fences_late_checkpoint_successor_until_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leased node may finish, but its late successor waits for resume."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id = _owned_running_run(isolated_db)
    writer = _leased_supervisor(run_id, isolated_db)
    _, checkpoint_seq, leased = writer
    await _complete_supervisor_after_pause(
        client,
        run_id,
        writer,
        isolated_db,
        monkeypatch,
    )

    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["seq"] == checkpoint_seq + 1
    assert checkpoint["stage"] == f"engine_task_paused:{leased.id}"
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}generate"
    assert checkpoint["state"]["resume_successor"] == successor_type

    # This late row models the shared queue boundary only; family tests cover
    # actual bootstrap, fan-out, ranking, and finalizer commits after pause.
    successor = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=successor_type,
            inputs={"checkpoint_seq": checkpoint["seq"]},
            idempotency_key=f"{successor_type}:after:{leased.id}",
            dependencies=(leased.id,),
            provenance={"scheduled_by": leased.task_type},
        ),
        db_path=isolated_db,
    )
    queued_successor = store.get_task(successor.id, db_path=isolated_db)
    paused_run = store.get_run(run_id, db_path=isolated_db)
    assert (
        paused_run is not None
        and paused_run.status == store.RunStatus.PAUSED.value
    )
    assert queued_successor is not None and queued_successor.status == "queued"
    assert (
        store.claim_task(
            "claim-late-queued-successor",
            run_id=run_id,
            db_path=isolated_db,
        )
        is None
    )
    claimable, active, _parked_until = store.cohort_poll(
        run_id, db_path=isolated_db
    )
    assert not claimable and not active

    resumed = client.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    task_ids = [task.id for task in tasks]
    assert len(task_ids) == len(set(task_ids))
    assert len(task_ids) == 2
    assert set(task_ids) == {leased.id, successor.id}
    assert (
        sum(
            task.idempotency_key == f"{successor_type}:after:{leased.id}"
            for task in tasks
        )
        == 1
    )

    claimed = store.claim_task(
        "claim-after-resume", run_id=run_id, db_path=isolated_db
    )
    assert claimed is not None and claimed.id == successor.id
    assert claimed.task_type == successor_type
    assert claimed.inputs["checkpoint_seq"] == checkpoint["seq"]
    assert claimed.dependencies == (leased.id,)
    assert (
        store.claim_task(
            "claim-after-resume-again", run_id=run_id, db_path=isolated_db
        )
        is None
    )

    events = store.list_events(run_id, db_path=isolated_db)
    pause = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
    )
    completion = next(
        event
        for event in events
        if event["type"] == "scientific_task"
        and event["payload"].get("task") == "supervisor"
        and event["payload"].get("status") == "completed"
    )
    resuming = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "resuming"
    )
    assert pause["seq"] < completion["seq"] < resuming["seq"]
    assert not any(
        pause["seq"] < event["seq"] < resuming["seq"]
        and event["payload"].get("status") == "running"
        for event in events
    )

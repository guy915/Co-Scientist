"""Cancellation racing with a durable task's checkpoint commit."""

from __future__ import annotations

from contextlib import suppress
from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist.models import Hypothesis

from app import (
    engine_tasks,
    engine_tasks_fanout_generation,
    engine_tasks_support,
    store,
    task_worker,
)
from app.engine_tasks_context import ExactSuccessor, TaskCommit
from app.engine_tasks_fanout_aggregates import _AggregateSpec
from app.engine_tasks_fanout_generation import _GenerationPlan, _StrategyInputs
from tests._client import make_client
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

_OWNER = {"X-Client-ID": "cancel-commit-owner"}


def _owned_running_run(db_path: str) -> tuple[Any, str]:
    client = make_client()
    created = client.post(
        "/api/runs",
        headers=_OWNER,
        json={
            "research_goal": "Study a durable cancellation boundary",
            "tier": "express",
        },
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    store.update_run_status(run_id, store.RunStatus.RUNNING, db_path=db_path)
    return client, run_id


def _leased_task(
    run_id: str, task_type: str, key: str, db_path: str
) -> tuple[Any, int]:
    checkpoint_seq = _seed_checkpoint(
        run_id, _task_state(run_id), db_path=db_path
    )
    queued = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=key,
        ),
        db_path=db_path,
    )
    task = store.claim_task(
        "cancel-race-worker", run_id=run_id, db_path=db_path
    )
    assert task is not None and task.id == queued.id
    return task, checkpoint_seq


@pytest.mark.asyncio
async def test_cancel_completed_after_node_status_check_blocks_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful cancel cannot be followed by this task's checkpoint."""
    client, run_id = _owned_running_run(isolated_db)
    state = _task_state(run_id)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.supervisor", "cancel-race-node", isolated_db
    )

    monkeypatch.setattr(
        engine_tasks,
        "_prepare_node_task",
        lambda *_: (
            state,
            TaskCommit(task, checkpoint_seq, isolated_db),
            "supervisor",
        ),
    )

    async def execute_node(
        _name: str, node_state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        return {**node_state, "committed_after_execution": True}, "generate"

    from co_scientist import task_runtime

    monkeypatch.setattr(task_runtime, "execute_task_node", execute_node)

    commit_node_result = engine_tasks._commit_node_result

    async def cancel_then_commit(
        commit: TaskCommit,
        run: store.RunRow,
        node_name: str,
        committed: dict[str, Any],
        successor: str | None,
    ) -> dict[str, Any]:
        response = client.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelled"
        return await commit_node_result(
            commit, run, node_name, committed, successor
        )

    monkeypatch.setattr(engine_tasks, "_commit_node_result", cancel_then_commit)

    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_node_task(task, db_path=isolated_db)

    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq
    assert [
        row.id for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [task.id]
    cancelled_task = store.get_task(task.id, db_path=isolated_db)
    assert cancelled_task is not None and cancelled_task.status == "cancelled"
    cancelled_run = store.get_run(run_id, db_path=isolated_db)
    assert cancelled_run is not None and cancelled_run.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_before_review_fanout_transaction_blocks_enqueue(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A canceled review task cannot leave item or aggregate work queued."""
    client, run_id = _owned_running_run(isolated_db)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.review", "cancel-review-fanout", isolated_db
    )
    state = {
        **_task_state(run_id),
        "hypotheses": [Hypothesis(text="A reviewable mechanism")],
    }
    monkeypatch.setattr(
        engine_tasks,
        "_prepare_node_task",
        lambda *_: (
            state,
            TaskCommit(task, checkpoint_seq, isolated_db),
            "review",
        ),
    )

    enqueue_fanout = engine_tasks._dispatch_node_fanout

    async def cancel_then_enqueue(
        *args: Any, **kwargs: Any
    ) -> dict[str, Any] | None:
        response = client.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
        assert response.status_code == 200, response.text
        return await enqueue_fanout(*args, **kwargs)

    monkeypatch.setattr(
        engine_tasks, "_dispatch_node_fanout", cancel_then_enqueue
    )

    with suppress(task_worker._LeaseLostError):
        await engine_tasks.execute_node_task(task, db_path=isolated_db)

    task_types = [
        row.task_type for row in store.list_tasks(run_id, db_path=isolated_db)
    ]
    assert task_types == [task.task_type]
    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq


def test_terminal_run_cannot_commit_an_exact_successor(
    isolated_db: str,
) -> None:
    """An otherwise-owned lease cannot publish work for a terminal run."""
    _client, run_id = _owned_running_run(isolated_db)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.ranking.match", "terminal-exact-task", isolated_db
    )
    store.update_run_status(
        run_id, store.RunStatus.COMPLETED, db_path=isolated_db
    )

    with pytest.raises(task_worker._LeaseLostError):
        engine_tasks_support._save_state_and_enqueue_exact(
            TaskCommit(task, checkpoint_seq, isolated_db),
            _task_state(run_id),
            ExactSuccessor(
                task_type="engine.ranking.match",
                inputs={"match_index": 2},
                idempotency_key="match:{checkpoint_seq}",
            ),
        )

    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq
    assert [
        row.id for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [task.id]
    still_leased = store.get_task(task.id, db_path=isolated_db)
    assert still_leased is not None and still_leased.status == "leased"


def test_old_same_owner_attempt_cannot_commit_after_re_lease(
    isolated_db: str,
) -> None:
    """Reclaiming to the same worker ID still revokes its earlier attempt."""
    _client, run_id = _owned_running_run(isolated_db)
    stale_task, checkpoint_seq = _leased_task(
        run_id, "engine.node.supervisor", "same-owner-re-lease", isolated_db
    )
    assert stale_task.attempt == 1
    assert stale_task.lease_owner == "cancel-race-worker"

    with store.transaction(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (stale_task.id,),
        )
    current_task = store.claim_task(
        "cancel-race-worker",
        lease_seconds=60,
        run_id=run_id,
        db_path=isolated_db,
    )
    assert current_task is not None and current_task.id == stale_task.id
    assert current_task.lease_owner == stale_task.lease_owner
    assert current_task.attempt == stale_task.attempt + 1

    with pytest.raises(task_worker._LeaseLostError):
        engine_tasks_support._save_state_and_enqueue(
            TaskCommit(stale_task, checkpoint_seq, isolated_db),
            _task_state(run_id),
            "generate",
        )

    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq
    persisted_task = store.get_task(stale_task.id, db_path=isolated_db)
    assert persisted_task is not None and persisted_task.attempt == 2
    assert [
        row.id for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [stale_task.id]


def test_cancelled_generation_planner_cannot_enqueue_fanout(
    isolated_db: str,
) -> None:
    """Generation's direct plan transaction obeys the same lease guard."""
    client, run_id = _owned_running_run(isolated_db)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.generate", "cancel-generation-plan", isolated_db
    )
    response = client.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
    assert response.status_code == 200, response.text

    plan = _GenerationPlan(
        task_specs=[],
        inputs=_StrategyInputs(
            literature=None,
            reference_index=SimpleNamespace(text="", sources=[]),
        ),
        aggregate_spec=_AggregateSpec(
            task_type=engine_tasks.GENERATION_AGGREGATE_TASK,
            priority=81,
            key_prefix="generation",
        ),
    )
    envelope = {
        "last_event_seq": store.latest_event_seq(run_id, db_path=isolated_db),
        "state": {},
    }

    with pytest.raises(task_worker._LeaseLostError):
        engine_tasks_fanout_generation._commit_generation_fanout(
            task, checkpoint_seq, envelope, plan, isolated_db
        )

    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq
    assert [
        row.id for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [task.id]

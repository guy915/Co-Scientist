"""Cancellation racing with a durable task's checkpoint commit."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist.models import Hypothesis

from app import engine_tasks, store, task_worker
from app.config import settings
from app.engine_tasks import fanout_generation as engine_tasks_fanout_generation
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.context import ExactSuccessor, TaskCommit
from app.engine_tasks.fanout_aggregates import _AggregateSpec
from app.engine_tasks.fanout_generation import _GenerationPlan, _StrategyInputs
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _seed_checkpoint,
    _task_events,
    _task_state,
)

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
async def test_pause_after_node_status_refresh_keeps_successor_unclaimable(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A final-boundary pause checkpoints without making work claimable."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id = _owned_running_run(isolated_db)
    state = _task_state(run_id)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.supervisor", "pause-successor-race", isolated_db
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
        node_state["metrics"].llm_calls = 7
        node_state["metrics"].hypothesis_count = 3
        return {**node_state, "committed_after_execution": True}, "generate"

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

    result = await engine_tasks.execute_node_task(task, db_path=isolated_db)

    saved_tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert not any(row.status == "queued" for row in saved_tasks), result
    assert result["status"] == "paused"
    assert store.complete_task(
        task.id, "cancel-race-worker", result, db_path=isolated_db
    )
    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq + 1
    assert latest["stage"] == f"engine_task_paused:{task.id}"
    assert latest["state"]["resume_successor"] == "engine.node.generate"
    metrics = store.get_run_metrics(run_id, db_path=isolated_db)
    assert metrics is not None
    assert metrics["llm_calls"] == 7
    assert metrics["hypothesis_count"] == 3
    [completion] = _task_events(run_id, "supervisor", db_path=isolated_db)
    assert completion["payload"] == {
        "task": "supervisor",
        "status": "completed",
        "checkpoint_seq": checkpoint_seq + 1,
        "successor": "generate",
        "activity": "planning",
    }
    saved_tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert [row.id for row in saved_tasks] == [task.id]
    assert (
        store.claim_task(
            "pause-race-claim-check", run_id=run_id, db_path=isolated_db
        )
        is None
    )

    resumed = client.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    queued = [
        row
        for row in store.list_tasks(run_id, db_path=isolated_db)
        if row.status == "queued"
    ]
    assert len(queued) == 1
    assert queued[0].task_type == "engine.node.generate"


def test_pause_api_serializes_queued_revocation_with_node_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit cannot slip between pause's queue and run-state writes."""
    client, run_id = _owned_running_run(isolated_db)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.supervisor", "pause-api-transaction", isolated_db
    )
    commit_finished = Event()
    commit_attempted = Event()
    commit_result: list[tuple[int, str | None]] = []
    commit_errors: list[BaseException] = []

    def commit_successor() -> None:
        try:
            commit_result.append(
                engine_tasks_support._save_state_and_enqueue(
                    TaskCommit(task, checkpoint_seq, isolated_db),
                    _task_state(run_id),
                    "generate",
                    pause_if_requested=True,
                )
            )
        except BaseException as exc:
            commit_errors.append(exc)
        finally:
            commit_finished.set()

    original_pause_tasks = store.pause_run_tasks
    original_transaction = store.transaction
    commit_thread: Thread | None = None

    @contextmanager
    def signal_commit_transaction(
        db_path: str | None = None,
    ) -> Iterator[Any]:
        commit_attempted.set()
        with original_transaction(db_path) as conn:
            yield conn

    def pause_tasks_then_race(
        target_run_id: str, *, db_path: str | None = None, conn: Any = None
    ) -> int:
        nonlocal commit_thread
        changed = original_pause_tasks(
            target_run_id, db_path=db_path, conn=conn
        )
        commit_attempted.clear()
        commit_thread = Thread(target=commit_successor)
        commit_thread.start()
        assert commit_attempted.wait(2), "commit did not reach its transaction"
        assert not commit_finished.wait(0.2), "commit escaped pause transaction"
        return changed

    monkeypatch.setattr(store, "pause_run_tasks", pause_tasks_then_race)
    monkeypatch.setattr(store, "transaction", signal_commit_transaction)
    response = client.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paused"
    assert commit_thread is not None
    commit_thread.join(timeout=5)
    assert not commit_thread.is_alive()
    assert not commit_errors
    assert commit_result == [(checkpoint_seq + 1, None)]
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task_paused:{task.id}"
    assert not any(
        row.status == "queued"
        for row in store.list_tasks(run_id, db_path=isolated_db)
    )


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
    """An explicit retry to the same worker ID revokes the old attempt."""
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
    assert (
        store.claim_task(
            "cancel-race-worker",
            lease_seconds=60,
            run_id=run_id,
            db_path=isolated_db,
        )
        is None
    )
    failed = store.get_task(stale_task.id, db_path=isolated_db)
    assert failed is not None and failed.status == "failed"
    assert "may have accepted" in (failed.error or "")
    assert store.retry_task(
        stale_task.id,
        reason="owner authorized replay after ambiguous lease expiry",
        db_path=isolated_db,
    )
    store.update_run_status(run_id, store.RunStatus.QUEUED, db_path=isolated_db)
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
            task_type=engine_tasks_support.GENERATION_AGGREGATE_TASK,
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

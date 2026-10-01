"""Review fan-out mechanics for the durable engine executor.

Independent child leases committing through a single aggregate. The
deep-verification family's own mechanics live in the sibling
``test_engine_tasks_fanout_verification``, mirroring the source split
between ``engine_tasks.fanout_reflection`` and
``engine_tasks.fanout_verification``.
"""

import asyncio
from typing import Any

import pytest
from co_scientist.models import Hypothesis, HypothesisReview

from app import engine_tasks, store, task_worker
from app.config import settings
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_generator,
    _patch_task_node,
    _task_events,
    _task_state,
)


async def _fake_review(**kwargs: Any) -> HypothesisReview:
    return HypothesisReview(
        review_summary=f"reviewed {kwargs['hypothesis_text']}",
        scores={"scientific_soundness": 8, "novelty": 8},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="continue",
        overall_score=8.0,
    )


async def _advance_to_review_parent(
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    generator: _Generator,
    db_path: str,
) -> None:
    """Bootstrap, route supervisor->review, and fan out the review parent."""
    _patch_generator(monkeypatch, generator, restore=True, screen=True)
    engine_tasks.enqueue_bootstrap(run_id, db_path=db_path)
    await task_worker.run_once("bootstrap", run_id=run_id, db_path=db_path)
    supervisor = store.claim_task("supervisor", run_id=run_id, db_path=db_path)
    assert supervisor is not None

    async def supervisor_to_review(
        _name: str, current: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        return current, "review"

    _patch_task_node(monkeypatch, supervisor_to_review)
    result = await engine_tasks.execute_node_task(supervisor, db_path=db_path)
    assert store.complete_task(
        supervisor.id, "supervisor", result, db_path=db_path
    )
    review_parent = store.claim_task("parent", run_id=run_id, db_path=db_path)
    assert review_parent is not None
    parent_result = await engine_tasks.execute_node_task(
        review_parent, db_path=db_path
    )
    assert store.complete_task(
        review_parent.id, "parent", parent_result, db_path=db_path
    )


async def _run_review_children_and_aggregate(run_id: str, db_path: str) -> None:
    """Lease both review children in parallel and commit one aggregate."""
    first = store.claim_task("child-a", run_id=run_id, db_path=db_path)
    second = store.claim_task("child-b", run_id=run_id, db_path=db_path)
    assert first is not None and second is not None
    assert first.task_type == second.task_type == engine_tasks.REVIEW_ITEM_TASK
    first_result, second_result = await asyncio.gather(
        engine_tasks.execute_review_item(first, db_path=db_path),
        engine_tasks.execute_review_item(second, db_path=db_path),
    )
    assert store.complete_task(
        first.id, "child-a", first_result, db_path=db_path
    )
    assert store.complete_task(
        second.id, "child-b", second_result, db_path=db_path
    )
    aggregate = store.claim_task("aggregate", run_id=run_id, db_path=db_path)
    assert aggregate is not None
    aggregate_result = await engine_tasks.execute_review_aggregate(
        aggregate, db_path=db_path
    )
    assert aggregate_result["successful_reviews"] == 2
    assert store.complete_task(
        aggregate.id, "aggregate", aggregate_result, db_path=db_path
    )


@pytest.mark.asyncio
async def test_review_fanout_uses_independent_leases_and_one_aggregate_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parallel review children share one checkpoint and aggregate once."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    state["hypotheses"] = [Hypothesis(text="alpha"), Hypothesis(text="beta")]
    await _advance_to_review_parent(
        run.id, monkeypatch, _Generator(state), isolated_db
    )

    import co_scientist.agents.reflection.review as review_module

    monkeypatch.setattr(review_module, "review_single_hypothesis", _fake_review)
    await _run_review_children_and_aggregate(run.id, isolated_db)

    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["seq"] == 3
    persisted = checkpoint["state"]["state"]["hypotheses"]
    assert [hypothesis["score"] for hypothesis in persisted] == [8.0, 8.0]
    # The review fan-out aggregate -- one of the five node types the fan-out
    # architecture previously left silent on the event stream -- now emits
    # its own scientific_task completion, same as the generic node path.
    review_events = _task_events(run.id, "review", db_path=isolated_db)
    assert len(review_events) == 1
    assert (
        review_events[0]["payload"]["successor"] == "comprehensive_reflection"
    )


@pytest.mark.asyncio
async def test_review_fanout_created_during_pause_waits_for_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leased review planner's item wave is unavailable until resume."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    original_dispatch = engine_tasks._dispatch_node_fanout

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "Paused review fan-out"}
        )
        assert created.status_code == 200, created.text
        run_id = str(created.json()["id"])
        store.update_run_status(
            run_id, store.RunStatus.RUNNING, db_path=isolated_db
        )
        state = _task_state(run_id)
        state["hypotheses"] = [
            Hypothesis(text="alpha"),
            Hypothesis(text="beta"),
        ]

        async def pause_during_dispatch(
            task: Any,
            node_state: dict[str, Any],
            node_name: str,
            checkpoint_seq: int,
            db_path: str | None,
        ) -> dict[str, Any] | None:
            if node_name == "review":
                paused = client.post(f"/api/runs/{run_id}/pause")
                assert paused.status_code == 200, paused.text
                assert paused.json()["status"] == "paused"
            return await original_dispatch(
                task, node_state, node_name, checkpoint_seq, db_path
            )

        monkeypatch.setattr(
            engine_tasks, "_dispatch_node_fanout", pause_during_dispatch
        )
        await _advance_to_review_parent(
            run_id, monkeypatch, _Generator(state), isolated_db
        )

        tasks = store.list_tasks(run_id, db_path=isolated_db)
        review_work = [
            task
            for task in tasks
            if task.task_type
            in {
                engine_tasks.REVIEW_ITEM_TASK,
                engine_tasks.REVIEW_AGGREGATE_TASK,
            }
        ]
        assert len(review_work) == 3
        saved_run = store.get_run(run_id, db_path=isolated_db)
        assert saved_run is not None and saved_run.status == "paused"
        assert (
            store.claim_task(
                "before-resume", run_id=run_id, db_path=isolated_db
            )
            is None
        )

        resumed = client.post(f"/api/runs/{run_id}/resume")
        assert resumed.status_code == 200, resumed.text
        claimed = [
            store.claim_task(
                f"after-resume-{index}", run_id=run_id, db_path=isolated_db
            )
            for index in range(2)
        ]
        assert all(item is not None for item in claimed)
        assert {item.task_type for item in claimed if item is not None} == {
            engine_tasks.REVIEW_ITEM_TASK
        }


@pytest.mark.asyncio
async def test_review_aggregate_is_ready_after_isolated_child_failure(
    isolated_db: str,
) -> None:
    """An allowed failed dependency does not permanently strand aggregation."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    failed = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=engine_tasks.REVIEW_ITEM_TASK,
            inputs={},
            idempotency_key="failed-child",
            max_attempts=1,
        ),
        db_path=isolated_db,
    )
    aggregate = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=engine_tasks.REVIEW_AGGREGATE_TASK,
            inputs={},
            idempotency_key="aggregate",
            dependencies=(failed.id,),
            provenance={"allow_failed_dependencies": True},
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task("child", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == failed.id
    assert store.fail_task(
        leased.id,
        "child",
        "provider failed",
        retryable=False,
        db_path=isolated_db,
    )

    ready = store.claim_task("aggregate", run_id=run.id, db_path=isolated_db)
    assert ready is not None and ready.id == aggregate.id

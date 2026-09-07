"""One orchestrator commit materializes a stacked pass (FIX-3).

Listing 01's ``DecideNextSteps`` queues several tasks from one pass; our
precedence chain returns one. ``scheduling.policy.stack_companions`` lets
a pass carry a cheap companion -- meta-review -- alongside its primary
decision, riding the ``supervisor_queue_actions`` that already travel
inside the orchestrator's own commit transaction.

These tests drive the real commit path and assert the durable shape: two
node rows from one commit, chained serially so the checkpoint chain
cannot fork, the companion's row keyed exactly as a later reactive
enqueue of the same edge would key it, and the primary still named as
the decision's ``next_task`` for everything that reads it.
"""

from __future__ import annotations

import pytest

from app import engine_tasks_support, store
from app.engine_tasks_context import TaskCommit
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

_ORCHESTRATOR = "engine.node.orchestrator"
_META_REVIEW = "engine.node.meta_review"


def _seed_orchestrator(run_id: str, db_path: str) -> store.ScientificTask:
    """Seed and claim an orchestrator task to commit a decision from."""
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=_ORCHESTRATOR,
            inputs={},
            idempotency_key=f"{_ORCHESTRATOR}:seed",
        ),
        db_path=db_path,
    )
    leased = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


def _stacked_state(run_id: str, next_task: str) -> dict[str, object]:
    """Workflow state as a stacked orchestrator decision commits it."""
    return {
        **_task_state(run_id),
        "next_task": next_task,
        "next_task_priority": 90,
        "supervisor_queue_actions": [
            {
                "action": "enqueue",
                "task_type": "meta_review",
                "reason": "periodic system-wide feedback is due",
            }
        ],
    }


@pytest.mark.asyncio
async def test_one_commit_queues_the_companion_and_the_primary(
    isolated_db: str,
) -> None:
    """A stacked pass leaves two node rows, chained in order.

    The companion runs first and the primary is anchored to it, never to
    the orchestrator: two rows under the same predecessor would both be
    claimable at once and fork the single-writer checkpoint chain.
    """
    run = store.create_run("Stacked pass", "standard", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "reflect")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )

    tasks = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    meta_review = tasks[_META_REVIEW]
    review = tasks["engine.node.review"]
    assert meta_review.dependencies == (orchestrator.id,)
    assert review.dependencies == (meta_review.id,)
    assert meta_review.status == "queued"
    assert review.status == "queued"


@pytest.mark.asyncio
async def test_the_companion_row_is_keyed_for_collision(
    isolated_db: str,
) -> None:
    """The stacked row and a reactive one for the same edge are one row.

    ``_enqueue_after``'s ``{task_type}:after:{predecessor id}`` key is a
    pure function of the edge, so applying the queue action and enqueueing
    the successor resolve to the same row rather than racing as two
    claimable duplicates.
    """
    run = store.create_run("Stacked key", "standard", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "proximity")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )

    rows = [
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == _META_REVIEW
    ]
    assert len(rows) == 1
    assert rows[0].idempotency_key == f"{_META_REVIEW}:after:{orchestrator.id}"


@pytest.mark.asyncio
async def test_an_unstacked_commit_queues_only_its_own_successor(
    isolated_db: str,
) -> None:
    """Without a companion the orchestrator commit is exactly as it was."""
    run = store.create_run("Unstacked pass", "standard", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = {
        **_task_state(run.id),
        "next_task": "proximity",
        "next_task_priority": 90,
    }
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "proximity"
    )

    types = {
        task.task_type for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    assert _META_REVIEW not in types
    assert "engine.node.proximity" in types

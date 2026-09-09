"""One orchestrator commit materializes a stacked pass (FIX-3).

Listing 01's ``DecideNextSteps`` queues several tasks from one pass; our
precedence chain returns one. ``scheduling.policy.stack_companions`` lets
a pass carry the listing's two periodic companions -- system feedback,
then the research overview -- alongside its primary decision, riding the
``supervisor_queue_actions`` that already travel inside the
orchestrator's own commit transaction.

These tests drive the real commit path and assert the durable shape:
several node rows from one commit, chained serially so the checkpoint
chain cannot fork and only the head is ever claimable, each row keyed
exactly as the later reactive enqueue of the same edge would key it, and
the primary still named as the decision's ``next_task`` for everything
that reads it.
"""

from __future__ import annotations

import pytest

from app import engine_tasks_support, store
from app.engine_tasks_context import TaskCommit
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

_ORCHESTRATOR = "engine.node.orchestrator"
_META_REVIEW = "engine.node.meta_review"
_OVERVIEW = "engine.node.research_overview"
_FINALIZE = "engine.finalize"


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


def _stacked_state(
    run_id: str, next_task: str, *companions: str
) -> dict[str, object]:
    """Workflow state as a stacked orchestrator decision commits it."""
    return {
        **_task_state(run_id),
        "next_task": next_task,
        "next_task_priority": 90,
        "supervisor_queue_actions": [
            {
                "action": "enqueue",
                "task_type": companion,
                "reason": "a periodic branch is due",
            }
            for companion in (companions or ("meta_review",))
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


@pytest.mark.asyncio
async def test_two_companions_chain_rather_than_fork(
    isolated_db: str,
) -> None:
    """Both periodic branches from one pass leave one claimable head.

    Anchoring the second companion to the orchestrator as well would put
    two rows under the same predecessor, both claimable at once against a
    single-writer checkpoint chain. Each stacked row is anchored to the
    one before it instead, so exactly one task is ever in flight and the
    rate-limit park (``task_worker_outcomes._park_rate_limited_task``)
    applies to it as it would to any single task.
    """
    run = store.create_run("Two companions", "extended", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "reflect", "meta_review", "synthesize")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )

    tasks = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    assert tasks[_META_REVIEW].dependencies == (orchestrator.id,)
    assert tasks[_OVERVIEW].dependencies == (tasks[_META_REVIEW].id,)
    assert tasks["engine.node.review"].dependencies == (tasks[_OVERVIEW].id,)


@pytest.mark.asyncio
async def test_the_companion_edge_collides_with_its_reactive_enqueue(
    isolated_db: str,
) -> None:
    """The stacked row and the row meta-review's own commit makes are one.

    Both derive ``{task_type}:after:{predecessor id}`` from the same
    edge, so committing the companion for real reuses the row the
    orchestrator's pass already planned instead of racing a duplicate.
    """
    run = store.create_run("Companion edge", "extended", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "reflect", "meta_review", "synthesize")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    committed = engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )
    meta_review = next(
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == _META_REVIEW
    )
    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(meta_review, committed[0], isolated_db),
        state,
        "research_overview",
    )

    rows = [
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == _OVERVIEW
    ]
    assert len(rows) == 1
    assert rows[0].idempotency_key == f"{_OVERVIEW}:after:{meta_review.id}"


@pytest.mark.asyncio
async def test_the_terminal_decision_writes_an_overview_then_a_report(
    isolated_db: str,
) -> None:
    """A stop stacks nothing and still ends overview -> report.

    ``engine.finalize`` is enqueued only as the overview node's own
    successor, so this is the edge a stacking change must not disturb.
    """
    run = store.create_run("Terminal pass", "extended", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = {
        **_task_state(run.id),
        "next_task": "terminate",
        "next_task_priority": 90,
        "supervisor_queue_actions": [],
    }
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    committed = engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "research_overview"
    )
    overview = next(
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == _OVERVIEW
    )
    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(overview, committed[0], isolated_db), state, None
    )

    finalize = next(
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == _FINALIZE
    )
    assert overview.dependencies == (orchestrator.id,)
    assert finalize.dependencies == (overview.id,)


@pytest.mark.asyncio
async def test_a_stacked_task_cannot_run_before_its_inputs(
    isolated_db: str,
) -> None:
    """Only the head of a stacked chain is claimable.

    Ordering exists for a reason at every hop -- the overview reads the
    critique the feedback pass writes, and the primary reads both -- so
    the dependency edges, not the enqueue order, are what has to hold.
    """
    run = store.create_run("Stacked claim", "extended", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "reflect", "meta_review", "synthesize")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )
    store.complete_task(orchestrator.id, "worker", {}, db_path=isolated_db)

    claimed = store.claim_task("w2", run_id=run.id, db_path=isolated_db)
    assert claimed is not None and claimed.task_type == _META_REVIEW
    assert store.claim_task("w3", run_id=run.id, db_path=isolated_db) is None

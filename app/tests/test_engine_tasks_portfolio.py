"""Bounded node-task portfolio coverage (finding F4).

Execution used to enqueue exactly one successor node task per commit,
reactively. These tests drive the shared commit path
(``app.engine_tasks_support._save_state_and_enqueue``) directly to prove
a commit now also chains however much of the deterministic tail
``co_scientist.task_runtime.plan_portfolio`` can already resolve, that a
plan superseded by a real outcome (a mid-run safety halt) is cancelled
rather than left claimable, and that a checkpoint shaped exactly as the
pre-portfolio spine produced it still resumes and the run still settles.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import (
    engine_tasks,
    engine_tasks_support,
    store,
    task_worker,
)
from app.engine_tasks_context import TaskCommit
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_generator,
    _patch_task_node,
    _seed_checkpoint,
    _task_state,
)


def _seed_predecessor(
    run_id: str, db_path: str, task_type: str = "engine.node.generate"
) -> store.ScientificTask:
    """Seed and claim a stand-in predecessor task for a portfolio commit."""
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={},
            idempotency_key=f"{task_type}:seed",
        ),
        db_path=db_path,
    )
    leased = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


def _seed_resume_checkpoint(
    run_id: str,
    state: dict[str, Any],
    *,
    stage: str,
    resume_successor: str,
    db_path: str,
) -> int:
    """Seed a checkpoint shaped exactly as ``_save_node_checkpoint`` would.

    ``resume_successor`` lives beside ``provider`` at the checkpoint's own
    top level, alongside (not inside) the serialized workflow-state
    payload -- the shape ``app.task_worker_enqueue._enqueue_resume_task``
    reads.
    """
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    envelope = serialize_workflow_state(state, last_event_seq=0)
    return store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage=stage,
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=0,
            state={
                "provider": "engine",
                "resume_successor": resume_successor,
                **envelope,
            },
        ),
        db_path=db_path,
    )


@pytest.mark.asyncio
async def test_commit_plans_the_resolvable_tail_behind_the_successor(
    isolated_db: str,
) -> None:
    """A commit chains the deterministic hops behind its immediate successor.

    Mirrors what the real generation aggregate's commit does once
    ``mcp_available`` routes it to ``reflection``: the aggregate's own
    commit here is standing in as ``task``, and ``reflection`` is the
    successor it decided on. ``review`` -- ``reflection``'s own fixed,
    non-fanning-adjacent successor -- must already be queued and chained
    behind it, not created only once ``reflection`` itself later runs.
    """
    run = store.create_run("Portfolio lookahead", "standard", "engine", {})
    predecessor = _seed_predecessor(run.id, isolated_db)
    checkpoint_seq = _seed_checkpoint(
        run.id, _task_state(run.id), db_path=isolated_db
    )
    commit = TaskCommit(predecessor, checkpoint_seq, isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        commit, _task_state(run.id), "reflection"
    )

    tasks = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    reflection = tasks["engine.node.reflection"]
    review = tasks["engine.node.review"]
    assert reflection.status == "queued"
    assert review.status == "queued"
    assert reflection.dependencies == (predecessor.id,)
    assert review.dependencies == (reflection.id,)
    assert (
        reflection.idempotency_key
        == f"engine.node.reflection:after:{predecessor.id}"
    )
    assert review.idempotency_key == f"engine.node.review:after:{reflection.id}"
    # review is itself a fanning node (finding F4's stop set): the plan
    # never guesses what comes after it.
    assert "engine.node.comprehensive_reflection" not in tasks


@pytest.mark.asyncio
async def test_resume_from_a_pre_portfolio_checkpoint_settles_the_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkpoint shaped exactly as the old spine produced it still resumes.

    The checkpoint's own shape (``stage``, ``resume_successor``) is
    unchanged by this feature -- only how a *fresh* successor gets keyed
    changed. This seeds the checkpoint plus a successor task exactly as
    the pre-portfolio code would have left them (checkpoint-sequence
    key, no ``dependencies``) and then lets that task die, the way an
    interrupted worker's boundary would at the moment of this deploy.
    Resume does not need to revive that exact old-keyed row -- it is not
    findable under a key this code would ever construct -- but the run
    must still make forward progress and settle.
    """
    run = store.create_run("Pre-portfolio resume", "standard", "engine", {})
    # `next_task_priority` is a required (non-Optional) WorkflowState field,
    # so a round trip through a real checkpoint always restores it -- unset
    # here, it would restore as `None` rather than being absent, which the
    # orchestrator-priority read in `_enqueue_node_portfolio` (unrelated to
    # this feature -- it already read the same way before it) requires a
    # real int for.
    state = {**_task_state(run.id), "next_task_priority": 90}
    generator = _Generator(state)
    _patch_generator(monkeypatch, generator, restore=True, screen=True)

    # A real predecessor task, exactly as `_save_node_checkpoint` leaves
    # one committing today.
    predecessor = _seed_predecessor(
        run.id, isolated_db, task_type="engine.node.supervisor"
    )
    assert store.complete_task(
        predecessor.id, "worker", {}, db_path=isolated_db
    )

    old_successor_type = "engine.node.orchestrator"
    checkpoint_seq = _seed_resume_checkpoint(
        run.id,
        state,
        stage=f"engine_task:{predecessor.id}",
        resume_successor=old_successor_type,
        db_path=isolated_db,
    )
    # The old, checkpoint-sequence-keyed successor row, already dead --
    # exhausted its retry budget, exactly as `test_task_worker_resume.py`
    # reproduces for the pre-existing scheme.
    dead = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=old_successor_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{old_successor_type}:{checkpoint_seq}",
        ),
        db_path=isolated_db,
    )
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='failed', "
            "attempt=max_attempts WHERE id=?",
            (dead.id,),
        )

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )
    assert resumed.task_type == old_successor_type
    assert resumed.id != dead.id, "the dead old-keyed row is not revived"
    assert resumed.dependencies == (predecessor.id,)

    successors = {
        "orchestrator": "research_overview",
        "research_overview": None,
    }

    async def execute(
        name: str, task_state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        return task_state, successors[name]

    async def finalize(task: Any, **_: Any) -> dict[str, Any]:
        store.update_run_status(task.run_id, store.RunStatus.COMPLETED)
        return {"run_id": task.run_id, "status": "completed"}

    _patch_task_node(monkeypatch, execute)
    # `_ENGINE_TASK_DISPATCH` binds `execute_finalize` at import time, so
    # only patching the dict entry itself (not the module attribute)
    # actually redirects dispatch, matching the stand-in used elsewhere in
    # this module.
    monkeypatch.setitem(
        engine_tasks._ENGINE_TASK_DISPATCH,
        engine_tasks.FINALIZE_TASK,
        finalize,
    )
    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    settled = store.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == store.RunStatus.COMPLETED.value

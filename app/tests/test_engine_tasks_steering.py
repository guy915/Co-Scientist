"""Steering consumption: atomic with its commit, and gated to the orchestrator.

Steering was originally acknowledged while the engine opts were built --
minutes of provider work before the node's checkpoint committed -- so a
worker that died mid-node left the message flagged applied and its
guidance nowhere; that crash-atomicity is what the first test below pins.
A second defect (PARITY ``HITL-STEERING-001``), fixed alongside the newer
tests here: acknowledging happened at *whichever* node's commit ran next,
not necessarily the orchestrator -- the one node whose scheduling decision
actually reads ``state["pending_steering"]`` -- so a message posted while,
say, proximity was executing was retired before ever reaching a
scheduling decision. These tests drive the durable node executor with the
real ``_generator_and_opts``/``_build_engine_opts`` (only the generator
itself is a stand-in) so the acknowledgement path under test is the
production one.
"""

from typing import Any

import pytest

from app import engine_tasks, engine_tasks_support, store
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_task_node,
    _seed_checkpoint,
    _task_state,
)

_STEER = "Prioritise kinase inhibitors over metabolic routes"


def _seed_steered_node_task(
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    db_path: str,
    *,
    node: str = "proximity",
) -> store.ScientificTask:
    """Seed a checkpoint, a queued ``node`` task, and one steering message.

    ``proximity`` is the default because it has no durable fan-out, so the
    executor takes the plain execute-then-commit path most of these tests
    are about; a caller passing ``node="orchestrator"`` exercises the one
    node that may actually acknowledge steering.
    """
    state = _task_state(run_id)
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content=_STEER, kind="steering"
        ),
        db_path=db_path,
    )
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}{node}",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"engine.node.{node}:{checkpoint_seq}",
        ),
        db_path=db_path,
    )
    monkeypatch.setattr(
        engine_tasks_support,
        "_build_generator",
        lambda *_, **__: _Generator(state),
    )
    leased = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


def _record_preferences_and_commit(seen: list[str], *, priority: bool) -> Any:
    """Build an execute_task_node fake that logs preferences then commits.

    ``priority`` sets ``next_task_priority`` on the state before
    returning, required whenever the task under test is the orchestrator
    (``_enqueue_node_portfolio`` reads it only for that node, but reads it
    unconditionally when it does).
    """

    async def _run_node(
        _node: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        seen.append(str(state.get("preferences") or ""))
        if priority:
            state["next_task_priority"] = 90
        return state, "meta_review"

    return _run_node


@pytest.mark.asyncio
async def test_steering_survives_a_crash_before_the_checkpoint_commits(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A node that dies mid-flight leaves its steering claimable again."""
    run = store.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(run.id, monkeypatch, isolated_db)

    async def _crash(*_: Any, **__: Any) -> Any:
        raise RuntimeError("worker died mid-node")

    _patch_task_node(monkeypatch, _crash)

    with pytest.raises(RuntimeError, match="worker died mid-node"):
        await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    pending = store.get_pending_steering(run.id, db_path=isolated_db)
    assert [message.content for message in pending] == [_STEER]


@pytest.mark.asyncio
async def test_a_non_orchestrator_commit_never_acknowledges_steering(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed non-orchestrator node reads but does not retire steering.

    Regression for HITL-STEERING-001: this used to be a valid acknowledging
    boundary (any node's commit). Now only the orchestrator's own commit
    may acknowledge -- see
    ``test_committed_orchestrator_acknowledges_its_steering_exactly_once``
    -- because it is the only node whose scheduling decision reads
    ``state["pending_steering"]`` at all; acknowledging anywhere else
    retires the message before that decision ever runs.
    """
    run = store.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(run.id, monkeypatch, isolated_db)
    seen: list[str] = []
    _patch_task_node(
        monkeypatch, _record_preferences_and_commit(seen, priority=False)
    )

    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert _STEER in seen[0]
    pending = store.get_pending_steering(run.id, db_path=isolated_db)
    assert [message.content for message in pending] == [_STEER]


@pytest.mark.asyncio
async def test_committed_orchestrator_acknowledges_its_steering_exactly_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed orchestrator checkpoint retires the steering it read."""
    run = store.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(
        run.id, monkeypatch, isolated_db, node="orchestrator"
    )
    seen: list[str] = []
    _patch_task_node(
        monkeypatch, _record_preferences_and_commit(seen, priority=True)
    )

    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert _STEER in seen[0]
    assert store.get_pending_steering(run.id, db_path=isolated_db) == []


@pytest.mark.asyncio
async def test_steering_reaches_the_orchestrators_retry_after_a_crash(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crashed orchestrator's retry sees the guidance, then retires it."""
    run = store.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(
        run.id, monkeypatch, isolated_db, node="orchestrator"
    )
    seen: list[str] = []

    async def _crash_then_commit(
        _node: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        seen.append(str(state.get("preferences") or ""))
        if len(seen) == 1:
            raise RuntimeError("worker died mid-node")
        state["next_task_priority"] = 90
        return state, "meta_review"

    _patch_task_node(monkeypatch, _crash_then_commit)

    with pytest.raises(RuntimeError):
        await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert [_STEER in text for text in seen] == [True, True]
    assert store.get_pending_steering(run.id, db_path=isolated_db) == []


@pytest.mark.asyncio
async def test_steering_text_survives_to_the_node_it_was_meant_for(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guidance is not lost the cycle the orchestrator acknowledges it.

    Regression: ``preferences`` used to be rebuilt each restore from only
    the still-*pending* steering, so the very next node after the
    orchestrator's ack (the node the high-priority reschedule is for) saw
    an empty fold and silently lost the guidance it was supposed to
    incorporate. Folding every steering message the run has ever queued
    (applied or not) keeps the text monotone across restores -- checked
    here across two separate durable tasks and checkpoints, not just one.
    """
    run = store.create_run("Steering survives", "standard", "engine", {})
    orchestrator = _seed_steered_node_task(
        run.id, monkeypatch, isolated_db, node="orchestrator"
    )

    async def _orchestrator_run(
        name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        assert name == "orchestrator"
        out = dict(state)
        out["next_task"] = "reflection"
        out["next_task_priority"] = 90
        return out, "reflection"

    _patch_task_node(monkeypatch, _orchestrator_run)
    committed = await engine_tasks.execute_node_task(
        orchestrator, db_path=isolated_db
    )
    assert store.complete_task(
        orchestrator.id, "worker", committed, db_path=isolated_db
    )

    reflection = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert reflection is not None
    assert reflection.task_type == "engine.node.reflection"
    seen: list[str] = []
    _patch_task_node(
        monkeypatch, _record_preferences_and_commit(seen, priority=False)
    )

    await engine_tasks.execute_node_task(reflection, db_path=isolated_db)

    assert seen and "kinase" in seen[0].lower()

"""Steering consumption is atomic with the checkpoint that carries it.

Steering was acknowledged while the engine opts were built -- minutes of
provider work before the node's checkpoint committed -- so a worker that
died mid-node left the message flagged applied and its guidance nowhere.
These tests drive the durable node executor with the real
``_generator_and_opts`` (only the generator itself is a stand-in) so the
acknowledgement path under test is the production one.
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
) -> store.ScientificTask:
    """Seed a checkpoint, a queued proximity node task, and one steer.

    ``proximity`` is deliberately the node: it has no durable fan-out, so
    the executor takes the plain execute-then-commit path this test is
    about.
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
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}proximity",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"engine.node.proximity:{checkpoint_seq}",
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
async def test_committed_node_acknowledges_its_steering_exactly_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed checkpoint retires the steering it folded in."""
    run = store.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(run.id, monkeypatch, isolated_db)
    seen: list[str] = []

    async def _run_node(
        _node: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        seen.append(str(state.get("preferences") or ""))
        return state, "meta_review"

    _patch_task_node(monkeypatch, _run_node)

    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert _STEER in seen[0]
    assert store.get_pending_steering(run.id, db_path=isolated_db) == []


@pytest.mark.asyncio
async def test_steering_reaches_the_retry_after_a_crash(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry of a crashed node still sees the guidance, then retires it."""
    run = store.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(run.id, monkeypatch, isolated_db)
    seen: list[str] = []

    async def _crash_then_commit(
        _node: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        seen.append(str(state.get("preferences") or ""))
        if len(seen) == 1:
            raise RuntimeError("worker died mid-node")
        return state, "meta_review"

    _patch_task_node(monkeypatch, _crash_then_commit)

    with pytest.raises(RuntimeError):
        await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert [_STEER in text for text in seen] == [True, True]
    assert store.get_pending_steering(run.id, db_path=isolated_db) == []

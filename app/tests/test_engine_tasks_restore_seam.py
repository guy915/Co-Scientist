"""A restore generator installed through the test helper is the one used.

Every durable handler that rebuilds workflow state does so with a generator
built for restore. The helper in ``_engine_tasks_helpers`` installs a fixture
generator in its place; a patch on a namespace that nothing looks the name up in
is inert, so it would install nothing and the suite would silently run the
real generator. The fixture generator carries a marker registry, and a spy on
the engine-level restore proves that registry is what each handler restored
with.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple

import co_scientist.checkpoint as engine_checkpoint
import pytest

from app import engine_tasks, engine_tasks_outcome_refinement, store
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_generator,
    _seed_checkpoint,
    _task_state,
)

Handler = Callable[..., Awaitable[dict[str, Any]]]
MARKER = object()


class _RestoredError(Exception):
    """Raised by the restore spy so a handler stops right after restoring."""


class _MarkedGenerator(_Generator):
    tool_registry: Any = MARKER


class _Case(NamedTuple):
    task_type: str
    handler: Handler
    extra_inputs: dict[str, Any]


@pytest.fixture
def restore_spy(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Record the tool registry each restore is given, then stop the handler."""
    seen: list[Any] = []

    def spy(serialized: dict[str, Any], *, tool_registry: Any = None) -> Any:
        seen.append(tool_registry)
        raise _RestoredError

    monkeypatch.setattr(engine_checkpoint, "restore_workflow_state", spy)
    return seen


def _leased_task(
    run_id: str, task_type: str, extra_inputs: dict[str, Any], db_path: str
) -> store.ScientificTask:
    seq = _seed_checkpoint(run_id, _task_state(run_id), db_path=db_path)
    queued = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={"checkpoint_seq": seq, **extra_inputs},
            idempotency_key=task_type,
        ),
        db_path=db_path,
    )
    return queued


_RESTORING_HANDLERS = [
    _Case(engine_tasks.FINALIZE_TASK, engine_tasks.execute_finalize, {}),
    _Case(
        engine_tasks.REVIEW_AGGREGATE_TASK,
        engine_tasks.execute_review_aggregate,
        {"item_task_ids": []},
    ),
    _Case(
        engine_tasks.GENERATION_AGGREGATE_TASK,
        engine_tasks.execute_generation_aggregate,
        {"item_task_ids": []},
    ),
    _Case(
        engine_tasks.MATURE_REFLECTION_AGGREGATE_TASK,
        engine_tasks.execute_mature_reflection_aggregate,
        {"item_task_ids": []},
    ),
    _Case(
        engine_tasks.VERIFICATION_AGGREGATE_TASK,
        engine_tasks.execute_verification_aggregate,
        {"item_task_ids": []},
    ),
    _Case(
        engine_tasks.RANKING_MATCH_TASK, engine_tasks.execute_ranking_match, {}
    ),
    _Case(
        engine_tasks.RANKING_FINALIZE_TASK,
        engine_tasks.execute_ranking_finalize,
        {},
    ),
    _Case(engine_tasks.REVIEW_ITEM_TASK, engine_tasks.execute_review_item, {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", _RESTORING_HANDLERS, ids=[c.task_type for c in _RESTORING_HANDLERS]
)
async def test_handler_restores_with_the_installed_generator(
    case: _Case,
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    restore_spy: list[Any],
) -> None:
    """The handler restores with the generator the helper installed."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = _leased_task(run.id, case.task_type, case.extra_inputs, isolated_db)
    _patch_generator(monkeypatch, _MarkedGenerator({}), restore=True)

    with pytest.raises(_RestoredError):
        await case.handler(task, db_path=isolated_db)

    assert restore_spy == [MARKER]


def test_outcome_refinement_restores_with_the_installed_generator(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    restore_spy: list[Any],
) -> None:
    """Outcome refinement restores its checkpoint with the same generator."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = _leased_task(
        run.id, engine_tasks.OUTCOME_REFINEMENT_TASK, {}, isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    _patch_generator(monkeypatch, _MarkedGenerator({}), restore=True)

    with pytest.raises(_RestoredError):
        engine_tasks_outcome_refinement._checkpoint_state(
            task, checkpoint, db_path=isolated_db
        )

    assert restore_spy == [MARKER]

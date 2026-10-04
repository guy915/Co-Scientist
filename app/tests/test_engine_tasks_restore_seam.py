# Patch the actual lookup seam; the marker proves the handler restored the
# fixture registry.

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple

import co_scientist.checkpoint as engine_checkpoint
import pytest

import app.engine_tasks.fanout as engine_tasks_fanout_items
from app import engine_tasks
from app.engine_tasks import fanout_aggregates as engine_tasks_fanout_aggregates
from app.engine_tasks import (
    outcome_refinement as engine_tasks_outcome_refinement,
)
from app.engine_tasks import ranking as engine_tasks_ranking
from app.engine_tasks import support as engine_tasks_support
from app.store import checkpoints, runs, tasks
from app.store.models import ScientificTask
from app.store.tasks import NewTask
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_generator,
    _seed_checkpoint,
    _task_state,
)

Handler = Callable[..., Awaitable[dict[str, Any]]]
MARKER = object()


class _RestoredError(Exception):
    pass


class _MarkedGenerator(_Generator):
    tool_registry: Any = MARKER


class _Case(NamedTuple):
    task_type: str
    handler: Handler
    extra_inputs: dict[str, Any]


@pytest.fixture
def restore_spy(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    seen: list[Any] = []

    def spy(serialized: dict[str, Any], *, tool_registry: Any = None) -> Any:
        seen.append(tool_registry)
        raise _RestoredError

    monkeypatch.setattr(engine_checkpoint, "restore_workflow_state", spy)
    return seen


def _leased_task(
    run_id: str, task_type: str, extra_inputs: dict[str, Any], db_path: str
) -> ScientificTask:
    seq = _seed_checkpoint(run_id, _task_state(run_id), db_path=db_path)
    queued = tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={"checkpoint_seq": seq, **extra_inputs},
            idempotency_key=task_type,
        ),
        db_path=db_path,
    )
    return queued


_RESTORING_HANDLERS = [
    _Case(
        engine_tasks_support.FINALIZE_TASK, engine_tasks.execute_finalize, {}
    ),
    _Case(
        engine_tasks_support.REVIEW_AGGREGATE_TASK,
        engine_tasks_fanout_aggregates.execute_review_aggregate,
        {"item_task_ids": []},
    ),
    _Case(
        engine_tasks_support.GENERATION_AGGREGATE_TASK,
        engine_tasks_fanout_aggregates.execute_generation_aggregate,
        {"item_task_ids": []},
    ),
    _Case(
        engine_tasks_support.MATURE_REFLECTION_AGGREGATE_TASK,
        engine_tasks_fanout_aggregates.execute_mature_reflection_aggregate,
        {"item_task_ids": []},
    ),
    _Case(
        engine_tasks_support.VERIFICATION_AGGREGATE_TASK,
        engine_tasks_fanout_aggregates.execute_verification_aggregate,
        {"item_task_ids": []},
    ),
    _Case(
        engine_tasks_support.RANKING_MATCH_TASK,
        engine_tasks_ranking.execute_ranking_match,
        {},
    ),
    _Case(
        engine_tasks_support.RANKING_FINALIZE_TASK,
        engine_tasks_ranking.execute_ranking_finalize,
        {},
    ),
    _Case(
        engine_tasks_support.REVIEW_ITEM_TASK,
        engine_tasks_fanout_items.execute_review_item,
        {},
    ),
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
    run = runs.create_run("Task-level science", "standard", "engine", {})
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
    run = runs.create_run("Task-level science", "standard", "engine", {})
    task = _leased_task(
        run.id, engine_tasks.OUTCOME_REFINEMENT_TASK, {}, isolated_db
    )
    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    _patch_generator(monkeypatch, _MarkedGenerator({}), restore=True)

    with pytest.raises(_RestoredError):
        engine_tasks_outcome_refinement._checkpoint_state(
            task, checkpoint, db_path=isolated_db
        )

    assert restore_spy == [MARKER]

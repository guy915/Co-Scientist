"""Durable fan-out scheduling for review, verification, and reflection.

Split from ``app.engine_tasks``, which re-exports every name here. The
generation fan-out lives in ``app.engine_tasks_fanout_generation``, the
per-item executors in ``app.engine_tasks_fanout_items``, and the
aggregates that commit fan-out results in
``app.engine_tasks_fanout_aggregates``; all are re-exported below.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any

from app import store
from app.engine_tasks_fanout_aggregates import (
    _AggregateSpec,
    _enqueue_aggregate_task,
)
from app.engine_tasks_fanout_aggregates import (
    execute_generation_aggregate as execute_generation_aggregate,
)
from app.engine_tasks_fanout_aggregates import (
    execute_mature_reflection_aggregate as execute_mature_reflection_aggregate,
)
from app.engine_tasks_fanout_aggregates import (
    execute_review_aggregate as execute_review_aggregate,
)
from app.engine_tasks_fanout_aggregates import (
    execute_verification_aggregate as execute_verification_aggregate,
)
from app.engine_tasks_fanout_generation import (
    _enqueue_generation_fanout as _enqueue_generation_fanout,
)
from app.engine_tasks_fanout_generation import (
    _enqueue_generation_strategy_tasks as _enqueue_generation_strategy_tasks,
)
from app.engine_tasks_fanout_generation import (
    _generation_task_specs as _generation_task_specs,
)
from app.engine_tasks_fanout_generation import (
    _run_generation_strategy as _run_generation_strategy,
)
from app.engine_tasks_fanout_generation import (
    _save_generation_plan_checkpoint as _save_generation_plan_checkpoint,
)
from app.engine_tasks_fanout_generation import (
    execute_generation_strategy as execute_generation_strategy,
)
from app.engine_tasks_fanout_items import (
    _hypothesis_for_item as _hypothesis_for_item,
)
from app.engine_tasks_fanout_items import (
    _run_observation_reflection as _run_observation_reflection,
)
from app.engine_tasks_fanout_items import (
    execute_mature_reflection_item as execute_mature_reflection_item,
)
from app.engine_tasks_fanout_items import (
    execute_review_item as execute_review_item,
)
from app.engine_tasks_fanout_items import (
    execute_verification_item as execute_verification_item,
)
from app.engine_tasks_support import (
    _CHECKPOINT_PROVIDER as _CHECKPOINT_PROVIDER,
)
from app.engine_tasks_support import (
    GENERATION_AGGREGATE_TASK as GENERATION_AGGREGATE_TASK,
)
from app.engine_tasks_support import (
    GENERATION_STRATEGY_TASK as GENERATION_STRATEGY_TASK,
)
from app.engine_tasks_support import (
    MATURE_REFLECTION_AGGREGATE_TASK,
    MATURE_REFLECTION_ITEM_TASK,
    REVIEW_AGGREGATE_TASK,
    REVIEW_ITEM_TASK,
    VERIFICATION_AGGREGATE_TASK,
    VERIFICATION_ITEM_TASK,
)
from app.engine_tasks_support import (
    _restore_item_checkpoint as _restore_item_checkpoint,
)
from app.store import ScientificTask


def _enqueue_review_item_tasks(
    task: ScientificTask,
    unreviewed: Sequence[Any],
    checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> list[ScientificTask]:
    """Enqueue one review-item task per unreviewed hypothesis."""
    return [
        store.enqueue_task(
            store.NewTask(
                run_id=task.run_id,
                task_type=REVIEW_ITEM_TASK,
                inputs={
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis.id,
                    "hypothesis_index": index,
                },
                idempotency_key=f"review:item:{checkpoint_seq}:{hypothesis.id}",
                priority=85,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "specialist": "reflection.initial",
                },
            ),
            conn=conn,
        )
        for index, hypothesis in enumerate(unreviewed)
    ]


_REVIEW_AGGREGATE_SPEC = _AggregateSpec(
    task_type=REVIEW_AGGREGATE_TASK, priority=80, key_prefix="review"
)


def _create_fanout_tasks(
    enqueue_items: Callable[[sqlite3.Connection], list[ScientificTask]],
    task: ScientificTask,
    checkpoint_seq: int,
    spec: _AggregateSpec,
    db_path: str | None,
) -> tuple[list[ScientificTask], ScientificTask]:
    """Enqueue a family's item tasks and its aggregate in one transaction.

    Args:
        enqueue_items: Enqueues the family's per-item tasks on the open
            connection and returns them in order.
        task: The node task scheduling the fan-out.
        checkpoint_seq: Checkpoint sequence the fan-out is planned at.
        spec: The aggregate's per-family task type, priority, and key.
        db_path: Optional override for the SQLite database path.

    Returns:
        A tuple of (item tasks, aggregate task).
    """
    with store.transaction(db_path) as conn:
        items = enqueue_items(conn)
        aggregate = _enqueue_aggregate_task(
            task, items, checkpoint_seq, conn, spec
        )
    return items, aggregate


def _enqueue_review_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Materialize one independently leasable task per unreviewed hypothesis."""
    unreviewed = [
        hypothesis
        for hypothesis in state["hypotheses"]
        if not hypothesis.reviews
    ]
    items, aggregate = _create_fanout_tasks(
        partial(_enqueue_review_item_tasks, task, unreviewed, checkpoint_seq),
        task,
        checkpoint_seq,
        _REVIEW_AGGREGATE_SPEC,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "review",
    }


def _enqueue_verification_item_tasks(
    task: ScientificTask,
    selected: Sequence[Any],
    checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> list[ScientificTask]:
    """Enqueue one deep-verification task per selected hypothesis."""
    return [
        store.enqueue_task(
            store.NewTask(
                run_id=task.run_id,
                task_type=VERIFICATION_ITEM_TASK,
                inputs={
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis.id,
                },
                idempotency_key=f"verification:item:{checkpoint_seq}:{hypothesis.id}",
                priority=88,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "specialist": "reflection.deep_verification",
                },
            ),
            conn=conn,
        )
        for hypothesis in selected
    ]


_VERIFICATION_AGGREGATE_SPEC = _AggregateSpec(
    task_type=VERIFICATION_AGGREGATE_TASK,
    priority=82,
    key_prefix="verification",
)


def _enqueue_verification_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Materialize one leasable deep-verification task per idea."""
    from co_scientist.agents.reflection.deep_verification import (
        _select_hypotheses_to_verify,
    )

    selected = _select_hypotheses_to_verify(
        state["hypotheses"], state["model_name"]
    )
    items, aggregate = _create_fanout_tasks(
        partial(
            _enqueue_verification_item_tasks, task, selected, checkpoint_seq
        ),
        task,
        checkpoint_seq,
        _VERIFICATION_AGGREGATE_SPEC,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "deep_verification",
    }


def _maturity_specs(hypothesis: Any, iteration: int) -> list[tuple[str, str]]:
    """Return full/simulation/recurrent specs by enrichment maturity.

    Delegates to the engine's rule rather than restating it. This was a
    second copy, and a copy of a scheduling rule is a copy that will one
    day disagree: both copies carried the same defect (re-issuing a
    simulation review that had already succeeded, whenever the full
    review had not), and fixing it in one place would have left the
    durable path -- the one production actually runs -- still paying for
    it.
    """
    from co_scientist.agents.reflection.mature_reviews import (
        reviews_needed,
    )

    return [
        (hypothesis.id, review.value)
        for review in reviews_needed(hypothesis, iteration)
    ]


def _mature_reflection_specs(state: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (hypothesis_id, review_mode) specs for reflection by maturity."""
    iteration = int(state.get("current_iteration", 0))
    literature = state.get("articles_with_reasoning")
    specs: list[tuple[str, str]] = []
    for hypothesis in state["hypotheses"]:
        if hypothesis.review_disposition != "viable":
            continue
        if literature and not hypothesis.reflection_notes:
            specs.append((hypothesis.id, "observation"))
        specs += _maturity_specs(hypothesis, iteration)
    return specs


def _enqueue_mature_reflection_item_tasks(
    task: ScientificTask,
    specs: Sequence[tuple[str, str]],
    checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> list[ScientificTask]:
    """Enqueue one durable task per maturity-appropriate reflection spec."""
    return [
        store.enqueue_task(
            store.NewTask(
                run_id=task.run_id,
                task_type=MATURE_REFLECTION_ITEM_TASK,
                inputs={
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis_id,
                    "review_mode": review_mode,
                },
                idempotency_key=f"reflection:{review_mode}:{checkpoint_seq}:{hypothesis_id}",
                priority=86,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "reflection_mode": review_mode,
                },
            ),
            conn=conn,
        )
        for hypothesis_id, review_mode in specs
    ]


_MATURE_REFLECTION_AGGREGATE_SPEC = _AggregateSpec(
    task_type=MATURE_REFLECTION_AGGREGATE_TASK,
    priority=80,
    key_prefix="reflection",
)


def _enqueue_mature_reflection_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Schedule maturity-appropriate Reflection modes as durable tasks."""
    specs = _mature_reflection_specs(state)
    items, aggregate = _create_fanout_tasks(
        partial(
            _enqueue_mature_reflection_item_tasks, task, specs, checkpoint_seq
        ),
        task,
        checkpoint_seq,
        _MATURE_REFLECTION_AGGREGATE_SPEC,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "comprehensive_reflection",
    }

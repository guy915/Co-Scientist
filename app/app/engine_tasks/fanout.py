"""Durable fan-out scheduling for review, verification, and reflection.

Split from ``app.engine_tasks``, which re-exports the names callers use. The
generation fan-out lives in ``app.engine_tasks.fanout_generation``, the
per-item executors in ``app.engine_tasks.fanout_items``, and the
aggregates that commit fan-out results in
``app.engine_tasks.fanout_aggregates``; the names callers use are
re-exported below.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any, NamedTuple

from app import store
from app.engine_tasks.fanout_aggregates import (
    _AggregateSpec,
    _enqueue_aggregate_task,
)
from app.engine_tasks.fanout_aggregates import (
    execute_generation_aggregate as execute_generation_aggregate,
)
from app.engine_tasks.fanout_aggregates import (
    execute_mature_reflection_aggregate as execute_mature_reflection_aggregate,
)
from app.engine_tasks.fanout_aggregates import (
    execute_review_aggregate as execute_review_aggregate,
)
from app.engine_tasks.fanout_aggregates import (
    execute_verification_aggregate as execute_verification_aggregate,
)
from app.engine_tasks.fanout_generation import (
    _enqueue_generation_fanout as _enqueue_generation_fanout,
)
from app.engine_tasks.fanout_generation import (
    execute_generation_strategy as execute_generation_strategy,
)
from app.engine_tasks.fanout_items import (
    execute_mature_reflection_item as execute_mature_reflection_item,
)
from app.engine_tasks.fanout_items import (
    execute_review_item as execute_review_item,
)
from app.engine_tasks.fanout_items import (
    execute_verification_item as execute_verification_item,
)
from app.engine_tasks.support import (
    MATURE_REFLECTION_AGGREGATE_TASK,
    MATURE_REFLECTION_ITEM_TASK,
    REVIEW_AGGREGATE_TASK,
    REVIEW_ITEM_TASK,
    VERIFICATION_AGGREGATE_TASK,
    VERIFICATION_ITEM_TASK,
    assert_task_commit_allowed,
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
        assert_task_commit_allowed(task, conn)
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
    """Materialize one independently leasable task per unreviewed hypothesis.

    **This is the canonical mirror of the published review chaining
    (FIX-9).** ``02-generation.md`` L24-26 and ``01-supervisor.md`` L34-38
    create one ``Reflection / ReviewHypothesis`` task per new hypothesis
    and add each to the global task queue; ``03-reflection.md`` L12 then
    fetches that hypothesis by id. This function is that step: one queue
    row per hypothesis, keyed and leased independently, which is also what
    production runs.

    The LangGraph engine's ``review_node`` reviews the whole batch behind
    one synchronous barrier instead. That divergence is deliberate and
    reference-only: for a pool of five it is a single comparative call
    against five, on a path with no production cost pressure to justify
    the 5x. Neither side is drifting -- the decision is that the durable
    path owns the mirror, so changes to per-hypothesis chaining belong
    here, not there.
    """
    from co_scientist.models import has_peer_review

    unreviewed = [
        hypothesis
        for hypothesis in state["hypotheses"]
        if not has_peer_review(hypothesis)
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
    from co_scientist.agents.reflection import (
        select_hypotheses_to_verify,
    )

    selected = select_hypotheses_to_verify(
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


class _ReflectionSpec(NamedTuple):
    """One reflection item this fan-out will materialize.

    Attributes:
        hypothesis_id: The hypothesis the review runs against.
        review_mode: The ``ReviewType`` value to issue.
        recheck: Whether this is a blocked idea's one recheck for the run
            rather than part of the mature cascade. Carried into the
            item's inputs so the aggregate can record the attempt even
            when the item never completed.
    """

    hypothesis_id: str
    review_mode: str
    recheck: bool = False


def _viable_specs(
    hypothesis: Any, iteration: int, literature: Any
) -> list[_ReflectionSpec]:
    """Return the cascade specs due for one viable hypothesis."""
    specs: list[_ReflectionSpec] = []
    if literature and not hypothesis.reflection_notes:
        specs.append(_ReflectionSpec(hypothesis.id, "observation"))
    return specs + [
        _ReflectionSpec(hypothesis_id, review_mode)
        for hypothesis_id, review_mode in _maturity_specs(hypothesis, iteration)
    ]


def _recheck_specs(state: dict[str, Any]) -> list[_ReflectionSpec]:
    """Return the one recurrent review each blocked idea is still owed.

    The cascade above selects on ``viable``, so nothing in it can ever
    reach an idea the initial review gate blocked -- which leaves the
    derived disposition (FIX-4) with no later verdict to derive from. The
    engine owns both bounds (once per hypothesis for the whole run, and a
    run-wide ceiling), read off the pool so they survive a checkpoint
    round trip and a resume.
    """
    from co_scientist.agents.reflection.review_recheck import (
        RECHECK_REVIEW_TYPE,
        recheck_targets,
    )

    return [
        _ReflectionSpec(hypothesis.id, RECHECK_REVIEW_TYPE.value, True)
        for hypothesis in recheck_targets(state["hypotheses"])
    ]


def _mature_reflection_specs(state: dict[str, Any]) -> list[_ReflectionSpec]:
    """Return the reflection specs due: the cascade, then the rechecks."""
    iteration = int(state.get("current_iteration", 0))
    literature = state.get("articles_with_reasoning")
    specs: list[_ReflectionSpec] = []
    for hypothesis in state["hypotheses"]:
        if hypothesis.review_disposition == "viable":
            specs += _viable_specs(hypothesis, iteration, literature)
    return specs + _recheck_specs(state)


def _enqueue_mature_reflection_item_tasks(
    task: ScientificTask,
    specs: Sequence[_ReflectionSpec],
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
                    "hypothesis_id": spec.hypothesis_id,
                    "review_mode": spec.review_mode,
                    "recheck": spec.recheck,
                },
                idempotency_key=f"reflection:{spec.review_mode}:{checkpoint_seq}:{spec.hypothesis_id}",
                priority=86,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "reflection_mode": spec.review_mode,
                },
            ),
            conn=conn,
        )
        for spec in specs
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

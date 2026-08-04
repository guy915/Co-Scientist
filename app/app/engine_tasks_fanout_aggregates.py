"""Durable fan-out aggregates: commit results, isolate item failures.

Each fan-out family (review, generation, mature reflection, deep
verification) ends in one aggregate task that folds successful item
results into the workflow checkpoint while preserving per-item failures.
Split from ``app.engine_tasks_fanout``, which re-exports these names so
``app.engine_tasks`` remains the stable import and monkeypatch surface.
The mature-reflection and deep-verification aggregates, plus the shared
checkpoint-and-advance helper, live in
``app.engine_tasks_fanout_reflection`` and are re-exported below.

The one shape every family's aggregate *task* shares -- the enqueue --
lives here too, since both fan-out schedulers
(``app.engine_tasks_fanout`` and ``app.engine_tasks_fanout_generation``)
import this module and neither can import the other without a cycle.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app import store
from app.engine_tasks_context import TaskCommit
from app.engine_tasks_fanout_reflection import (
    _AppliedItems as _AppliedItems,
)
from app.engine_tasks_fanout_reflection import (
    _apply_mature_reflection_items as _apply_mature_reflection_items,
)
from app.engine_tasks_fanout_reflection import (
    _apply_verification_items as _apply_verification_items,
)
from app.engine_tasks_fanout_reflection import (
    _checkpoint_and_advance as _checkpoint_and_advance,
)
from app.engine_tasks_fanout_reflection import (
    _commit_mature_reflection_aggregate as _commit_mature_reflection_aggregate,
)
from app.engine_tasks_fanout_reflection import (
    _commit_verification_aggregate as _commit_verification_aggregate,
)
from app.engine_tasks_fanout_reflection import (
    _mature_reflection_update as _mature_reflection_update,
)
from app.engine_tasks_fanout_reflection import (
    _verification_aggregate_update as _verification_aggregate_update,
)
from app.engine_tasks_fanout_reflection import (
    execute_mature_reflection_aggregate as execute_mature_reflection_aggregate,
)
from app.engine_tasks_fanout_reflection import (
    execute_verification_aggregate as execute_verification_aggregate,
)
from app.engine_tasks_support import (
    _emit_node_completion as _emit_node_completion,
)
from app.engine_tasks_support import (
    _generator_for_restore,
    _replay_or_supersede,
    _require_item_task,
)
from app.engine_tasks_support import (
    _save_state_and_enqueue as _save_state_and_enqueue,
)
from app.store import ScientificTask


@dataclass(frozen=True)
class _AggregateSpec:
    """The parts of an aggregate task that differ per fan-out family.

    Attributes:
        task_type: Durable task type the aggregate is enqueued as.
        priority: Queue priority, below the family's own item tasks so a
            wave drains before the aggregate that folds it in.
        key_prefix: Idempotency-key prefix; the key is that prefix plus
            ``:aggregate:<checkpoint_seq>``.
        extra_inputs: Family-specific task inputs, merged after the two
            every aggregate carries.
    """

    task_type: str
    priority: int
    key_prefix: str
    extra_inputs: Mapping[str, Any] = field(default_factory=dict)


def _enqueue_aggregate_task(
    task: ScientificTask,
    items: Sequence[ScientificTask],
    checkpoint_seq: int,
    conn: sqlite3.Connection,
    spec: _AggregateSpec,
) -> ScientificTask:
    """Enqueue a fan-out aggregate depending on every one of its item tasks.

    The dependency tuple and ``allow_failed_dependencies`` are what let a
    single item's failure be isolated rather than stall the run, so every
    family gets them identically.

    Args:
        task: The node task scheduling the fan-out.
        items: The family's per-item tasks, in enqueue order.
        checkpoint_seq: Checkpoint sequence the fan-out was planned at.
        conn: Open connection of the caller's transaction.
        spec: The per-family task type, priority, key prefix, and inputs.

    Returns:
        The enqueued aggregate task.
    """
    return store.enqueue_task(
        store.NewTask(
            run_id=task.run_id,
            task_type=spec.task_type,
            inputs={
                "checkpoint_seq": checkpoint_seq,
                "item_task_ids": [item.id for item in items],
                **spec.extra_inputs,
            },
            idempotency_key=f"{spec.key_prefix}:aggregate:{checkpoint_seq}",
            priority=spec.priority,
            dependencies=tuple(item.id for item in items),
            provenance={
                "scheduled_by": task.task_type,
                "allow_failed_dependencies": True,
            },
        ),
        conn=conn,
    )


def _apply_review_items(
    by_id: dict[str, Any],
    item_task_ids: Sequence[Any],
    db_path: str | None,
) -> tuple[int, int]:
    """Apply each completed review item to its hypothesis; count failures.

    Mirrors the normal Review node's score update so tournament seeding
    observes peer-review quality.
    """
    from co_scientist.agents.reflection.review import _apply_initial_review_gate
    from co_scientist.models import HypothesisReview

    successful = 0
    failed = 0
    for item_id in item_task_ids:
        item = _require_item_task(item_id, db_path, kind="review item")
        if item.status != "completed" or not item.result:
            failed += 1
            hypothesis_id = str(item.inputs.get("hypothesis_id", ""))
            if hypothesis_id in by_id:
                by_id[hypothesis_id].review_disposition = "review_failed"
            continue
        hypothesis = by_id[str(item.result["hypothesis_id"])]
        review = HypothesisReview(**item.result["review"])
        hypothesis.reviews.append(review)
        hypothesis.score = review.overall_score
        _apply_initial_review_gate([hypothesis], [review])
        successful += 1
    return successful, failed


def _review_aggregate_update(
    state: dict[str, Any], successful: int, failed: int
) -> dict[str, Any]:
    """Build the review aggregate's workflow state update payload."""
    from co_scientist.models import (
        MetricDeltas,
        create_metrics_update,
        phase_message,
    )

    return {
        "hypotheses": state["hypotheses"],
        "metrics": create_metrics_update(
            deltas=MetricDeltas(
                reviews=successful, llm_calls=successful + failed
            )
        ),
        "messages": phase_message(
            "review",
            f"Reviewed {successful} hypotheses; {failed} isolated failures",
            strategy="durable_parallel_individual",
        ),
    }


async def _commit_review_aggregate(
    commit: TaskCommit,
    state: dict[str, Any],
    successful: int,
    failed: int,
) -> dict[str, Any]:
    """Checkpoint the committed reviews and advance the run.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        state: Restored workflow state the review items were applied to.
        successful: Reviews applied to their hypothesis.
        failed: Review items isolated as failures.

    Returns:
        The task result: committed checkpoint, successor, and review tally.
    """
    from co_scientist.task_runtime import apply_task_update

    committed = apply_task_update(
        state, _review_aggregate_update(state, successful, failed)
    )
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        commit, committed, "review"
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_reviews": successful,
        "failed_reviews": failed,
    }


async def execute_review_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit successful review results and preserve isolated failures."""
    from co_scientist.checkpoint import restore_workflow_state

    replay, checkpoint, current_seq = _replay_or_supersede(
        task, db_path, label="review aggregate"
    )
    if replay is not None:
        return replay
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    successful, failed = _apply_review_items(
        by_id, task.inputs.get("item_task_ids", []), db_path
    )
    return await _commit_review_aggregate(
        TaskCommit(task, current_seq, db_path), state, successful, failed
    )


@dataclass(frozen=True)
class _GenerationItems:
    """What the generation fan-out's strategy tasks produced.

    Attributes:
        buckets: Hypotheses per generation strategy.
        transcripts: Debate transcripts the strategies recorded.
        failed: Strategy tasks that never completed.
    """

    buckets: dict[str, list[Any]]
    transcripts: list[dict[str, Any]]
    failed: int


def _collect_generation_results(
    item_task_ids: Sequence[Any],
    db_path: str | None,
) -> _GenerationItems:
    """Gather completed generation-strategy results, isolating failures."""
    from co_scientist.models import Hypothesis

    buckets: dict[str, list[Any]] = {
        "tools": [],
        "debate_lit": [],
        "debate_only": [],
        "assumptions": [],
    }
    transcripts: list[dict[str, Any]] = []
    failed = 0
    for item_id in item_task_ids:
        item = _require_item_task(item_id, db_path, kind="generation strategy")
        if item.status != "completed" or not item.result:
            failed += 1
            continue
        strategy = str(item.result["strategy"])
        buckets[strategy].extend(
            Hypothesis.from_dict(payload)
            for payload in item.result.get("hypotheses", [])
        )
        transcripts.extend(item.result.get("transcripts", []))
    return _GenerationItems(buckets, transcripts, failed)


async def _generation_aggregate_update(
    task: ScientificTask,
    state: dict[str, Any],
    items: _GenerationItems,
) -> dict[str, Any]:
    """Finalize the combined generation strategies into a state update."""
    from co_scientist.agents.generation.coordinator import _finalize_generation
    from co_scientist.agents.generation.coordinator_results import (
        GenerationResults,
    )
    from co_scientist.agents.generation.coordinator_strategy import (
        GenerationCounts,
    )
    from co_scientist.models import create_metrics_update

    buckets = items.buckets
    counts = GenerationCounts(**task.inputs["counts"])
    results = GenerationResults(
        tools_hypotheses=buckets["tools"],
        debate_with_lit_hypotheses=buckets["debate_lit"],
        debate_only_hypotheses=buckets["debate_only"],
        assumptions_hypotheses=buckets["assumptions"],
        debate_transcripts=items.transcripts,
    )
    update: dict[str, Any] = await _finalize_generation(state, counts, results)
    update["metrics"] = create_metrics_update(
        hypothesis_count=update["hypothesis_count"]
    )
    if items.failed:
        update["message"] += f"; {items.failed} strategy failure(s) isolated"
    return update


async def _commit_generation_aggregate(
    commit: TaskCommit,
    state: dict[str, Any],
    items: _GenerationItems,
) -> dict[str, Any]:
    """Finalize combined generation results and advance the run.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        state: Restored workflow state the strategies generated against.
        items: Per-strategy hypotheses, transcripts, and failure count.

    Returns:
        The task result: committed checkpoint, successor, and tallies.
    """
    from co_scientist.task_runtime import apply_task_update

    update = await _generation_aggregate_update(commit.task, state, items)
    committed = apply_task_update(state, update)
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        commit, committed, "generate"
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "hypotheses_generated": update["hypothesis_count"],
        "failed_strategies": items.failed,
    }


async def execute_generation_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Combine independent generation strategies into one hypothesis append."""
    from co_scientist.checkpoint import restore_workflow_state

    replay, checkpoint, current_seq = _replay_or_supersede(
        task, db_path, label="generation aggregate"
    )
    if replay is not None:
        return replay
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    items = _collect_generation_results(
        task.inputs.get("item_task_ids", []), db_path
    )
    return await _commit_generation_aggregate(
        TaskCommit(task, current_seq, db_path), state, items
    )

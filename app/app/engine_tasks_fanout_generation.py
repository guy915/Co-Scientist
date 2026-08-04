"""Durable generation fan-out: plan checkpoint and strategy execution.

The generation node's fan-out scheduling (one durable task per enabled
strategy plus the aggregate) and the per-strategy executor. Split from
``app.engine_tasks_fanout``, which re-exports these names so
``app.engine_tasks`` remains the stable import and monkeypatch surface.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app import store
from app.engine_tasks_fanout_aggregates import (
    _AggregateSpec,
    _enqueue_aggregate_task,
)
from app.engine_tasks_support import (
    _CHECKPOINT_PROVIDER,
    GENERATION_AGGREGATE_TASK,
    GENERATION_STRATEGY_TASK,
    _restore_item_checkpoint,
)
from app.store import ScientificTask


@dataclass(frozen=True)
class _StrategyInputs:
    """Read-only generation inputs every strategy task is scheduled with.

    Attributes:
        literature: Retrieved articles with reasoning, for lit-backed debate.
        reference_index: The run's citation reference index.
    """

    literature: Any
    reference_index: Any


@dataclass(frozen=True)
class _GenerationPlan:
    """The fan-out's shape, decided before any durable row is written.

    Attributes:
        task_specs: (strategy, count, index) spec per durable strategy task.
        inputs: Literature and reference index every strategy task reads.
        aggregate_spec: Spec for the aggregate that folds the strategies in.
    """

    task_specs: list[tuple[str, int, int]]
    inputs: _StrategyInputs
    aggregate_spec: _AggregateSpec


def _generation_task_specs(
    strategy_counts: dict[str, int],
) -> list[tuple[str, int, int]]:
    """Return (strategy, count, index) specs for each strategy's durable tasks.

    Debate strategies get one task per hypothesis so debates run
    independently; every other strategy gets a single task producing its
    whole count.

    Splitting the non-debate strategies per hypothesis was tried and
    reverted. It looked like it should help -- uniform items let the worker
    cohort fill instead of waiting on one oversized task -- but a measured
    production express run spent 145s per generate cycle against a 137s
    baseline, so it bought no wall time. It is not cost-neutral either: the
    tools drafting call emits its whole count in one response, so N tasks
    means N drafting calls where there was one, and N concurrent writers
    against the single SQLite writer where there were fewer. Re-measure the
    strategy's internal draft/validate loops before trying this again.
    """
    debate_strategies = {"debate_lit", "debate_only"}
    return [
        (strategy, 1, index)
        for strategy, count in strategy_counts.items()
        if strategy in debate_strategies
        for index in range(count)
    ] + [
        (strategy, count, 0)
        for strategy, count in strategy_counts.items()
        if strategy not in debate_strategies and count > 0
    ]


def _save_generation_plan_checkpoint(
    task: ScientificTask,
    checkpoint_seq: int,
    envelope: dict[str, Any],
    conn: sqlite3.Connection,
) -> int:
    """Commit the generation plan checkpoint inside the caller's transaction."""
    from co_scientist.checkpoint import CHECKPOINT_VERSION

    latest = store.get_latest_checkpoint(task.run_id, conn=conn)
    latest_seq = int(latest["seq"]) if latest else 0
    if latest_seq != checkpoint_seq:
        raise RuntimeError("checkpoint changed during generation planning")
    return store.save_checkpoint(
        task.run_id,
        store.NewCheckpoint(
            stage=f"engine_task:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={"provider": _CHECKPOINT_PROVIDER, **envelope},
        ),
        conn=conn,
    )


def _enqueue_generation_strategy_tasks(
    task: ScientificTask,
    planned_seq: int,
    task_specs: Sequence[tuple[str, int, int]],
    inputs: _StrategyInputs,
    conn: sqlite3.Connection,
) -> list[ScientificTask]:
    """Enqueue one durable task per planned generation strategy.

    Args:
        task: The generation node task scheduling the fan-out.
        planned_seq: Checkpoint sequence the plan committed at.
        task_specs: (strategy, count, index) spec per durable task.
        inputs: Literature and reference index every strategy reads.
        conn: Open connection of the caller's transaction.

    Returns:
        The enqueued per-strategy tasks, in spec order.
    """
    return [
        store.enqueue_task(
            store.NewTask(
                run_id=task.run_id,
                task_type=GENERATION_STRATEGY_TASK,
                inputs={
                    "checkpoint_seq": planned_seq,
                    "strategy": strategy,
                    "count": count,
                    "strategy_index": index,
                    "literature": inputs.literature,
                    "reference_text": inputs.reference_index.text,
                    "reference_sources": inputs.reference_index.sources,
                },
                idempotency_key=f"generation:{strategy}:{planned_seq}:{index}:{count}",
                priority=87,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "generation_strategy": strategy,
                    "strategy_index": index,
                },
            ),
            conn=conn,
        )
        for strategy, count, index in task_specs
    ]


def _generation_aggregate_spec(counts: Any) -> _AggregateSpec:
    """Return the generation family's aggregate spec, carrying its counts."""
    return _AggregateSpec(
        task_type=GENERATION_AGGREGATE_TASK,
        priority=81,
        key_prefix="generation",
        extra_inputs={"counts": dataclasses.asdict(counts)},
    )


async def _plan_generation_fanout(state: dict[str, Any]) -> _GenerationPlan:
    """Prepare the generation inputs and decide the fan-out's shape.

    Runs entirely before the transaction, so the provider work the
    preparation does never happens while the SQLite write lock is held.

    Args:
        state: Workflow state the generation node was entered with.

    Returns:
        The per-strategy task specs, their shared inputs, and the
        aggregate spec carrying the planned counts.
    """
    from co_scientist.agents.generation.coordinator import _prepare_generation

    counts, reference_index, literature = await _prepare_generation(state)
    strategy_counts = {
        "tools": counts.tools_count,
        "debate_lit": counts.debate_with_lit_count,
        "debate_only": counts.debate_only_count,
        "assumptions": counts.assumptions_count,
    }
    return _GenerationPlan(
        task_specs=_generation_task_specs(strategy_counts),
        inputs=_StrategyInputs(literature, reference_index),
        aggregate_spec=_generation_aggregate_spec(counts),
    )


def _commit_generation_fanout(
    task: ScientificTask,
    checkpoint_seq: int,
    envelope: dict[str, Any],
    plan: _GenerationPlan,
    db_path: str | None,
) -> tuple[int, list[ScientificTask], ScientificTask]:
    """Write the plan checkpoint and every fan-out row in one transaction.

    Args:
        task: The generation node task scheduling the fan-out.
        checkpoint_seq: Checkpoint sequence the plan was built against.
        envelope: Serialized workflow state to checkpoint.
        plan: The fan-out shape from ``_plan_generation_fanout``.
        db_path: Optional override for the SQLite database path.

    Returns:
        The committed checkpoint sequence, the per-strategy tasks in spec
        order, and the aggregate task.
    """
    with store.transaction(db_path) as conn:
        planned_seq = _save_generation_plan_checkpoint(
            task, checkpoint_seq, envelope, conn
        )
        items = _enqueue_generation_strategy_tasks(
            task,
            planned_seq,
            plan.task_specs,
            plan.inputs,
            conn,
        )
        aggregate = _enqueue_aggregate_task(
            task,
            items,
            planned_seq,
            conn,
            plan.aggregate_spec,
        )
    return planned_seq, items, aggregate


async def _enqueue_generation_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Commit generation planning and enqueue each enabled strategy."""
    from co_scientist.checkpoint import serialize_workflow_state

    plan = await _plan_generation_fanout(state)
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    planned_seq, items, aggregate = _commit_generation_fanout(
        task, checkpoint_seq, envelope, plan, db_path
    )
    return {
        "checkpoint_seq": planned_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "generate",
    }


async def _run_generation_strategy(
    state: dict[str, Any],
    strategy: str,
    count: int,
    reference_index: Any,
    literature_raw: Any,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Execute one generation strategy and return its hypotheses/transcripts."""
    from co_scientist.agents.generation.assumptions import (
        generate_with_assumptions,
    )
    from co_scientist.agents.generation.citations import ReferenceIndex
    from co_scientist.agents.generation.debate import generate_with_debate
    from co_scientist.agents.generation.literature_tools import (
        generate_with_tools,
    )

    if strategy == "tools":
        return await generate_with_tools(state, count, reference_index), []
    if strategy in {"debate_lit", "debate_only"}:
        literature = literature_raw if strategy == "debate_lit" else None
        debate_reference = (
            reference_index
            if strategy == "debate_lit"
            else ReferenceIndex(text="", sources={})
        )
        hypotheses, transcripts = await generate_with_debate(
            state=state,
            count=count,
            articles_with_reasoning=literature,
            reference_index=debate_reference,
        )
        return hypotheses, transcripts
    if strategy == "assumptions":
        return await generate_with_assumptions(state, count), []
    raise ValueError(f"unsupported generation strategy: {strategy}")


async def execute_generation_strategy(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute one generation strategy against a read-only plan checkpoint."""
    from co_scientist.agents.generation.citations import ReferenceIndex

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="generation strategy"
    )
    strategy = str(task.inputs["strategy"])
    count = int(task.inputs["count"])
    reference_index = ReferenceIndex(
        text=str(task.inputs.get("reference_text") or ""),
        sources=dict(task.inputs.get("reference_sources") or {}),
    )
    hypotheses, transcripts = await _run_generation_strategy(
        state, strategy, count, reference_index, task.inputs.get("literature")
    )
    return {
        "strategy": strategy,
        "hypotheses": [hypothesis.to_dict() for hypothesis in hypotheses],
        "transcripts": transcripts,
        "checkpoint_seq": expected_seq,
    }

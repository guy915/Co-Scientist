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
    _assert_task_commit_allowed,
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
        task_specs: (strategy, count, index, total) spec per durable
            strategy task. Debate strategies get one task per hypothesis,
            so index is the debate's position and total the family's whole
            batch size (the diversity-angle denominator, finding E14);
            other strategies run as one task where index is 0 and total
            equals count.
        inputs: Literature and reference index every strategy task reads.
        aggregate_spec: Spec for the aggregate that folds the strategies in.
    """

    task_specs: list[tuple[str, int, int, int]]
    inputs: _StrategyInputs
    aggregate_spec: _AggregateSpec


def _generation_task_specs(
    strategy_counts: dict[str, int],
) -> list[tuple[str, int, int, int]]:
    """Return (strategy, count, index, total) specs per durable task.

    Debate strategies get one task per hypothesis so debates run
    independently; every other strategy gets a single task producing its
    whole count. ``total`` carries the strategy's whole batch size to
    every task: the engine assigns each debate a diversity angle from its
    index modulo the batch, and a per-debate task that only knew its own
    count of 1 could never diverge from its siblings (finding E14).

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
        (strategy, 1, index, count)
        for strategy, count in strategy_counts.items()
        if strategy in debate_strategies
        for index in range(count)
    ] + [
        (strategy, count, 0, count)
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
    task_specs: Sequence[tuple[str, int, int, int]],
    inputs: _StrategyInputs,
    conn: sqlite3.Connection,
) -> list[ScientificTask]:
    """Enqueue one durable task per planned generation strategy.

    Args:
        task: The generation node task scheduling the fan-out.
        planned_seq: Checkpoint sequence the plan committed at.
        task_specs: (strategy, count, index, total) spec per durable task.
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
                    # The strategy's whole batch size, so a per-debate
                    # task can angle its debate against the full sibling
                    # set (finding E14). Tasks enqueued before this input
                    # existed simply run without a diversity angle.
                    "debate_total": total,
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
        for strategy, count, index, total in task_specs
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
        _assert_task_commit_allowed(task, conn)
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


@dataclass(frozen=True)
class _StrategyRunInputs:
    """Per-task inputs one generation strategy executes against.

    Attributes:
        reference_index: The run's citation reference index.
        literature: Retrieved literature synthesis, debate_lit only.
        debate_index: This task's position in the strategy's parallel
            debate batch (finding E14); None predates the wiring.
        debate_total: The debate batch's whole size; see debate_index.
    """

    reference_index: Any
    literature: Any
    debate_index: int | None = None
    debate_total: int | None = None


async def _run_debate_strategy(
    state: dict[str, Any],
    strategy: str,
    count: int,
    inputs: _StrategyRunInputs,
) -> tuple[list[Any], list[dict[str, Any]], int]:
    """Run one debate strategy task and return its hypotheses/transcripts.

    The task carries its position and batch size within the strategy's
    parallel debates (finding E14), which the engine turns into a
    distinct diversity angle per task.
    """
    from co_scientist.agents.generation.citations import ReferenceIndex
    from co_scientist.agents.generation.debate import (
        DebateBatchPosition,
        generate_with_debate,
    )

    literature = inputs.literature if strategy == "debate_lit" else None
    debate_reference = (
        inputs.reference_index
        if strategy == "debate_lit"
        else ReferenceIndex(text="", sources={})
    )
    batch_position = None
    if inputs.debate_index is not None and inputs.debate_total is not None:
        batch_position = DebateBatchPosition(
            inputs.debate_index, inputs.debate_total
        )
    # The app's mypy config skips following co_scientist imports, so the
    # engine's declared return type arrives here as Any; restate it on the
    # binding rather than passing an unchecked value on (mirrors
    # _checkpoint_and_advance's next_task_type cast in the sibling module).
    result: tuple[
        list[Any], list[dict[str, Any]], int
    ] = await generate_with_debate(
        state=state,
        count=count,
        articles_with_reasoning=literature,
        reference_index=debate_reference,
        batch_position=batch_position,
    )
    return result


async def _run_generation_strategy(
    state: dict[str, Any],
    strategy: str,
    count: int,
    inputs: _StrategyRunInputs,
) -> tuple[list[Any], list[dict[str, Any]], int]:
    """Execute one generation strategy and return its hypotheses/transcripts.

    Every branch returns ``(hypotheses, transcripts, llm_calls)``:
    ``llm_calls`` is the real LLM completions the strategy spent (finding
    L3), and every leaf strategy function already reports it -- only the
    non-debate branches have no transcripts, so they pair their
    ``(hypotheses, llm_calls)`` return with an empty transcript list here.
    """
    from co_scientist.agents.generation.assumptions import (
        generate_with_assumptions,
    )
    from co_scientist.agents.generation.literature_tools import (
        generate_with_tools,
    )

    if strategy == "tools":
        hypotheses, llm_calls = await generate_with_tools(
            state, count, inputs.reference_index
        )
        return hypotheses, [], llm_calls
    if strategy in {"debate_lit", "debate_only"}:
        return await _run_debate_strategy(state, strategy, count, inputs)
    if strategy == "assumptions":
        hypotheses, llm_calls = await generate_with_assumptions(state, count)
        return hypotheses, [], llm_calls
    raise ValueError(f"unsupported generation strategy: {strategy}")


async def execute_generation_strategy(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute one generation strategy against a read-only plan checkpoint.

    A debate task is one debate of the strategy's parallel batch; the
    batch total defaults to the pre-E14 shape (a lone debate with no
    siblings to diverge from) when the input predates the wiring.

    ``skills_used`` is which third-party data sources this strategy's
    science-skill commands reached, so the report can attribute them;
    see ``co_scientist.skills.usage``. Empty without skills installed.
    """
    from co_scientist.agents.generation.citations import ReferenceIndex
    from co_scientist.llm_telemetry import scoped_telemetry
    from co_scientist.skills import scoped_skill_usage

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="generation strategy"
    )
    strategy = str(task.inputs["strategy"])
    count = int(task.inputs["count"])
    inputs = _StrategyRunInputs(
        reference_index=ReferenceIndex(
            text=str(task.inputs.get("reference_text") or ""),
            sources=dict(task.inputs.get("reference_sources") or {}),
        ),
        literature=task.inputs.get("literature"),
        debate_index=int(task.inputs.get("strategy_index") or 0),
        debate_total=int(task.inputs.get("debate_total") or count),
    )
    with (
        scoped_telemetry("generate") as telemetry,
        scoped_skill_usage() as skills,
    ):
        hypotheses, transcripts, llm_calls = await _run_generation_strategy(
            state, strategy, count, inputs
        )
    return {
        "strategy": strategy,
        "hypotheses": [hypothesis.to_dict() for hypothesis in hypotheses],
        "transcripts": transcripts,
        "llm_calls": llm_calls,
        "model_usage": telemetry.snapshot(),
        "skills_used": skills.snapshot(),
        "checkpoint_seq": expected_seq,
    }

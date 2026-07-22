"""Durable fan-out scheduling and item execution.

Split from ``app.engine_tasks``, which re-exports every name here; the
aggregates that commit fan-out results live in
``app.engine_tasks_fanout_aggregates`` and are re-exported below.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from app import store
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
from app.engine_tasks_support import (
    _CHECKPOINT_PROVIDER,
    GENERATION_AGGREGATE_TASK,
    GENERATION_STRATEGY_TASK,
    MATURE_REFLECTION_AGGREGATE_TASK,
    MATURE_REFLECTION_ITEM_TASK,
    REVIEW_AGGREGATE_TASK,
    REVIEW_ITEM_TASK,
    VERIFICATION_AGGREGATE_TASK,
    VERIFICATION_ITEM_TASK,
    _restore_item_checkpoint,
)
from app.store import ScientificTask


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
    with store.transaction(db_path) as conn:
        items = [
            store.enqueue_task(
                task.run_id,
                REVIEW_ITEM_TASK,
                {
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis.id,
                    "hypothesis_index": index,
                },
                idempotency_key=(
                    f"review:item:{checkpoint_seq}:{hypothesis.id}"
                ),
                priority=85,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "specialist": "reflection.initial",
                },
                conn=conn,
            )
            for index, hypothesis in enumerate(unreviewed)
        ]
        aggregate = store.enqueue_task(
            task.run_id,
            REVIEW_AGGREGATE_TASK,
            {
                "checkpoint_seq": checkpoint_seq,
                "item_task_ids": [item.id for item in items],
            },
            idempotency_key=f"review:aggregate:{checkpoint_seq}",
            priority=80,
            dependencies=tuple(item.id for item in items),
            provenance={
                "scheduled_by": task.task_type,
                "allow_failed_dependencies": True,
            },
            conn=conn,
        )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "review",
    }


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

    selected = _select_hypotheses_to_verify(state["hypotheses"])
    with store.transaction(db_path) as conn:
        items = [
            store.enqueue_task(
                task.run_id,
                VERIFICATION_ITEM_TASK,
                {
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis.id,
                },
                idempotency_key=(
                    f"verification:item:{checkpoint_seq}:{hypothesis.id}"
                ),
                priority=88,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "specialist": "reflection.deep_verification",
                },
                conn=conn,
            )
            for hypothesis in selected
        ]
        aggregate = store.enqueue_task(
            task.run_id,
            VERIFICATION_AGGREGATE_TASK,
            {
                "checkpoint_seq": checkpoint_seq,
                "item_task_ids": [item.id for item in items],
            },
            idempotency_key=f"verification:aggregate:{checkpoint_seq}",
            priority=82,
            dependencies=tuple(item.id for item in items),
            provenance={
                "scheduled_by": task.task_type,
                "allow_failed_dependencies": True,
            },
            conn=conn,
        )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "deep_verification",
    }


async def _enqueue_generation_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Commit generation planning and enqueue each enabled strategy."""
    from co_scientist.agents.generation.coordinator import _prepare_generation
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    counts, reference_index, literature = await _prepare_generation(state)
    strategy_counts = {
        "tools": counts.tools_count,
        "debate_lit": counts.debate_with_lit_count,
        "debate_only": counts.debate_only_count,
        "assumptions": counts.assumptions_count,
    }
    task_specs = [
        (strategy, 1, index)
        for strategy, count in strategy_counts.items()
        if strategy in {"debate_lit", "debate_only"}
        for index in range(count)
    ] + [
        (strategy, count, 0)
        for strategy, count in strategy_counts.items()
        if strategy not in {"debate_lit", "debate_only"} and count > 0
    ]
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    with store.transaction(db_path) as conn:
        latest = store.get_latest_checkpoint(task.run_id, conn=conn)
        latest_seq = int(latest["seq"]) if latest else 0
        if latest_seq != checkpoint_seq:
            raise RuntimeError("checkpoint changed during generation planning")
        planned_seq = store.save_checkpoint(
            task.run_id,
            stage=f"engine_task:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={"provider": _CHECKPOINT_PROVIDER, **envelope},
            conn=conn,
        )
        items = [
            store.enqueue_task(
                task.run_id,
                GENERATION_STRATEGY_TASK,
                {
                    "checkpoint_seq": planned_seq,
                    "strategy": strategy,
                    "count": count,
                    "strategy_index": index,
                    "literature": literature,
                    "reference_text": reference_index.text,
                    "reference_sources": reference_index.sources,
                },
                idempotency_key=(
                    f"generation:{strategy}:{planned_seq}:{index}:{count}"
                ),
                priority=87,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "generation_strategy": strategy,
                    "strategy_index": index,
                },
                conn=conn,
            )
            for strategy, count, index in task_specs
        ]
        aggregate = store.enqueue_task(
            task.run_id,
            GENERATION_AGGREGATE_TASK,
            {
                "checkpoint_seq": planned_seq,
                "item_task_ids": [item.id for item in items],
                "counts": dataclasses.asdict(counts),
            },
            idempotency_key=f"generation:aggregate:{planned_seq}",
            priority=81,
            dependencies=tuple(item.id for item in items),
            provenance={
                "scheduled_by": task.task_type,
                "allow_failed_dependencies": True,
            },
            conn=conn,
        )
    return {
        "checkpoint_seq": planned_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "generate",
    }


def _enqueue_mature_reflection_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Schedule maturity-appropriate Reflection modes as durable tasks."""
    iteration = int(state.get("current_iteration", 0))
    literature = state.get("articles_with_reasoning")
    specs: list[tuple[str, str]] = []
    for hypothesis in state["hypotheses"]:
        if hypothesis.review_disposition != "viable":
            continue
        if literature and not hypothesis.reflection_notes:
            specs.append((hypothesis.id, "observation"))
        if "full" not in hypothesis.enrichments:
            specs.extend(
                ((hypothesis.id, "full"), (hypothesis.id, "simulation"))
            )
        elif iteration > int(
            hypothesis.enrichments.get("recurrent_review_iteration", -1)
        ):
            specs.append((hypothesis.id, "recurrent"))
    with store.transaction(db_path) as conn:
        items = [
            store.enqueue_task(
                task.run_id,
                MATURE_REFLECTION_ITEM_TASK,
                {
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis_id,
                    "review_mode": review_mode,
                },
                idempotency_key=(
                    f"reflection:{review_mode}:{checkpoint_seq}:{hypothesis_id}"
                ),
                priority=86,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "reflection_mode": review_mode,
                },
                conn=conn,
            )
            for hypothesis_id, review_mode in specs
        ]
        aggregate = store.enqueue_task(
            task.run_id,
            MATURE_REFLECTION_AGGREGATE_TASK,
            {
                "checkpoint_seq": checkpoint_seq,
                "item_task_ids": [item.id for item in items],
            },
            idempotency_key=f"reflection:aggregate:{checkpoint_seq}",
            priority=80,
            dependencies=tuple(item.id for item in items),
            provenance={
                "scheduled_by": task.task_type,
                "allow_failed_dependencies": True,
            },
            conn=conn,
        )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "comprehensive_reflection",
    }


def _hypothesis_for_item(
    task: ScientificTask, state: dict[str, Any]
) -> tuple[str, Any]:
    """Resolve the item task's target hypothesis from restored state."""
    hypothesis_id = str(task.inputs["hypothesis_id"])
    hypothesis = next(
        (item for item in state["hypotheses"] if item.id == hypothesis_id),
        None,
    )
    if hypothesis is None:
        raise ValueError(
            f"hypothesis {hypothesis_id} is absent from checkpoint"
        )
    return hypothesis_id, hypothesis


async def execute_review_item(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Review one hypothesis without mutating the shared workflow checkpoint."""
    from co_scientist.agents.reflection.review import review_single_hypothesis

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="review item"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    review = await review_single_hypothesis(
        hypothesis_text=hypothesis.text,
        research_goal=state["research_goal"],
        model_name=state["model_name"],
        supervisor_guidance=state.get("supervisor_guidance"),
        meta_review=state.get("meta_review"),
        run_id=state.get("run_id"),
        hypothesis_index=int(task.inputs["hypothesis_index"]),
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )
    return {
        "hypothesis_id": hypothesis_id,
        "review": dataclasses.asdict(review),
        "checkpoint_seq": expected_seq,
    }


async def execute_verification_item(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Deep-verify one hypothesis without mutating the workflow checkpoint."""
    from co_scientist.agents.reflection.deep_verification import (
        _verification_evidence_context,
        _verify_one,
    )

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="verification item"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    result = await _verify_one(
        hypothesis,
        state["research_goal"],
        state["model_name"],
        asyncio.Semaphore(1),
        state.get("tool_registry"),
        _verification_evidence_context(state),
        state,
    )
    if result is None:
        raise RuntimeError(f"deep verification failed for {hypothesis_id}")
    return {
        "hypothesis_id": hypothesis_id,
        "verification": result,
        "checkpoint_seq": expected_seq,
    }


async def execute_generation_strategy(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute one generation strategy against a read-only plan checkpoint."""
    from co_scientist.agents.generation.assumptions import (
        generate_with_assumptions,
    )
    from co_scientist.agents.generation.citations import ReferenceIndex
    from co_scientist.agents.generation.debate import generate_with_debate
    from co_scientist.agents.generation.literature_tools import (
        generate_with_tools,
    )

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="generation strategy"
    )
    strategy = str(task.inputs["strategy"])
    count = int(task.inputs["count"])
    reference_index = ReferenceIndex(
        text=str(task.inputs.get("reference_text") or ""),
        sources=dict(task.inputs.get("reference_sources") or {}),
    )
    transcripts: list[dict[str, Any]] = []
    if strategy == "tools":
        hypotheses = await generate_with_tools(state, count, reference_index)
    elif strategy in {"debate_lit", "debate_only"}:
        literature = (
            task.inputs.get("literature") if strategy == "debate_lit" else None
        )
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
    elif strategy == "assumptions":
        hypotheses = await generate_with_assumptions(state, count)
    else:
        raise ValueError(f"unsupported generation strategy: {strategy}")
    return {
        "strategy": strategy,
        "hypotheses": [hypothesis.to_dict() for hypothesis in hypotheses],
        "transcripts": transcripts,
        "checkpoint_seq": expected_seq,
    }


async def execute_mature_reflection_item(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute one disclosed mature Reflection mode for one hypothesis."""
    from co_scientist.agents.reflection.comprehensive_reflection import (
        _run_review,
    )
    from co_scientist.agents.reflection.reflection import (
        analyze_single_hypothesis,
    )
    from co_scientist.agents.reflection.review_types import ReviewType

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="mature reflection"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    mode = ReviewType(str(task.inputs["review_mode"]))
    if mode is ReviewType.OBSERVATION:
        literature = state.get("articles_with_reasoning")
        if not literature:
            raise RuntimeError("observation review has no literature context")
        result = await analyze_single_hypothesis(
            hypothesis=hypothesis,
            articles_with_reasoning=literature,
            model_name=state["model_name"],
            hypothesis_index=1,
            total_count=1,
            run_id=state.get("run_id"),
            tool_registry=state.get("tool_registry"),
            meta_review=state.get("meta_review"),
        )
    else:
        _, result = await _run_review(state, hypothesis, mode)
    if result is None:
        raise RuntimeError(f"{mode.value} review failed for {hypothesis_id}")
    return {
        "hypothesis_id": hypothesis_id,
        "review_mode": mode.value,
        "review": result,
        "checkpoint_seq": expected_seq,
    }

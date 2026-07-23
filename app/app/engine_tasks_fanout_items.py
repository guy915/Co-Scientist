"""Durable fan-out item executors for review, verification, reflection.

Each executor runs one hypothesis-scoped unit of work against a
read-only checkpoint, returning its result for the family's aggregate
to commit. Split from ``app.engine_tasks_fanout``, which re-exports
these names so ``app.engine_tasks`` remains the stable import and
monkeypatch surface.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from app.engine_tasks_support import _restore_item_checkpoint
from app.store import ScientificTask


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
    from co_scientist.agents.reflection.review import (
        ReviewContext,
        review_single_hypothesis,
    )

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="review item"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    context = ReviewContext(
        research_goal=state["research_goal"],
        model_name=state["model_name"],
        run_id=state.get("run_id"),
        supervisor_guidance=state.get("supervisor_guidance"),
        meta_review=state.get("meta_review"),
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )
    review = await review_single_hypothesis(
        hypothesis_text=hypothesis.text,
        context=context,
        hypothesis_index=int(task.inputs["hypothesis_index"]),
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
        _VerificationContext,
        _verify_one,
    )

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="verification item"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    context = _VerificationContext(
        research_goal=state["research_goal"],
        model_name=state["model_name"],
        tool_registry=state.get("tool_registry"),
        state=state,
    )
    result = await _verify_one(
        hypothesis,
        context,
        asyncio.Semaphore(1),
        _verification_evidence_context(state),
    )
    if result is None:
        raise RuntimeError(f"deep verification failed for {hypothesis_id}")
    return {
        "hypothesis_id": hypothesis_id,
        "verification": result,
        "checkpoint_seq": expected_seq,
    }


async def _run_observation_reflection(
    state: dict[str, Any], hypothesis: Any
) -> Any:
    """Run the observation-mode reflection against retrieved literature."""
    from co_scientist.agents.reflection.reflection import (
        _ReflectionContext,
        analyze_single_hypothesis,
    )

    literature = state.get("articles_with_reasoning")
    if not literature:
        raise RuntimeError("observation review has no literature context")
    context = _ReflectionContext(
        articles_with_reasoning=literature,
        model_name=state["model_name"],
        run_id=state.get("run_id"),
        tool_registry=state.get("tool_registry"),
        meta_review=state.get("meta_review"),
    )
    return await analyze_single_hypothesis(
        hypothesis=hypothesis,
        hypothesis_index=1,
        total_count=1,
        context=context,
    )


async def execute_mature_reflection_item(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute one disclosed mature Reflection mode for one hypothesis."""
    from co_scientist.agents.reflection.comprehensive_reflection import (
        _run_review,
    )
    from co_scientist.agents.reflection.review_types import ReviewType

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="mature reflection"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    mode = ReviewType(str(task.inputs["review_mode"]))
    if mode is ReviewType.OBSERVATION:
        result = await _run_observation_reflection(state, hypothesis)
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

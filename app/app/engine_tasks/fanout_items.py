"""Durable fan-out item executors for review, verification, reflection.

Each executor runs one hypothesis-scoped unit of work against a
read-only checkpoint, returning its result for the family's aggregate
to commit. Split from ``app.engine_tasks.fanout``, which re-exports
the names callers use so ``app.engine_tasks`` remains their import and
monkeypatch surface.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from app.engine_tasks.support import _restore_item_checkpoint
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
    from co_scientist.llm import scoped_telemetry

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="review item"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    context = ReviewContext.from_state(state)
    with scoped_telemetry("review") as telemetry:
        review = await review_single_hypothesis(
            hypothesis_text=hypothesis.text,
            context=context,
            hypothesis_index=int(task.inputs["hypothesis_index"]),
        )
    return {
        "hypothesis_id": hypothesis_id,
        "review": dataclasses.asdict(review),
        "model_usage": telemetry.snapshot(),
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
    from co_scientist.llm import scoped_telemetry

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
    with scoped_telemetry("deep_verification") as telemetry:
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
        "model_usage": telemetry.snapshot(),
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
    from co_scientist.llm import scoped_telemetry

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="mature reflection"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    mode = ReviewType(str(task.inputs["review_mode"]))
    with scoped_telemetry("comprehensive_reflection") as telemetry:
        ledger: dict[str, Any] | None = None
        if mode is ReviewType.OBSERVATION:
            result = await _run_observation_reflection(state, hypothesis)
        else:
            _, result, ledger = await _run_review(state, hypothesis, mode)
    if result is None:
        raise RuntimeError(f"{mode.value} review failed for {hypothesis_id}")
    return {
        "hypothesis_id": hypothesis_id,
        "review_mode": mode.value,
        "review": result,
        # Beside the review rather than inside it: the aggregate hands
        # this to the run's state, while the review goes to the
        # hypothesis. A ledger stamped on the review would ride into
        # every later checkpoint through enrichments.
        "research_ledger": ledger,
        "model_usage": telemetry.snapshot(),
        "checkpoint_seq": expected_seq,
    }

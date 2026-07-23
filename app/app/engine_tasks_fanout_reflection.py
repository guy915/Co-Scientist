"""Reflection-family fan-out aggregates for the durable engine path.

The aggregate tasks that commit mature-reflection and deep-verification
fan-out results, plus the checkpoint-and-advance commit helper every
fan-out aggregate shares. Split from
``app.engine_tasks_fanout_aggregates``, which imports the shared helper
and re-exports these names so ``app.engine_tasks`` remains the stable
import and monkeypatch surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.engine_tasks_context import TaskCommit
from app.engine_tasks_support import (
    NodeCompletion,
    _emit_node_completion,
    _generator_for_restore,
    _replay_or_supersede,
    _require_item_task,
    _save_state_and_enqueue,
)
from app.store import ScientificTask


@dataclass(frozen=True)
class _AppliedItems:
    """Tally of one fan-out family's applied per-item results.

    Attributes:
        successful: Items whose result was applied to its hypothesis.
        failed: Items that never completed, isolated from the aggregate.
        llm_calls: Provider calls the items are billed for.
        results: The raw per-item review payloads, in item order.
    """

    successful: int
    failed: int
    llm_calls: int
    results: list[dict[str, Any]] = field(default_factory=list)


async def _checkpoint_and_advance(
    commit: TaskCommit,
    committed: dict[str, Any],
    node_name: str,
    successor: str,
) -> tuple[int, str | None]:
    """Checkpoint an aggregate's committed state and emit its completion.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        committed: Workflow state the aggregate folded its items into.
        node_name: Engine node this aggregate completes.
        successor: Node to schedule next.

    Returns:
        A tuple of (committed checkpoint sequence, successor task id).
    """
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        commit.task,
        committed,
        successor,
        expected_checkpoint_seq=commit.current_seq,
        db_path=commit.db_path,
    )
    await _emit_node_completion(
        commit.task.run_id,
        NodeCompletion(node_name, successor, checkpoint_seq),
        committed,
        commit.db_path,
    )
    return checkpoint_seq, successor_id


def _apply_mature_reflection_items(
    by_id: dict[str, Any],
    item_task_ids: Sequence[Any],
    current_iteration: int,
    db_path: str | None,
) -> _AppliedItems:
    """Apply each completed mature-reflection item to its hypothesis.

    Args:
        by_id: The run's hypotheses, keyed by id.
        item_task_ids: Ids of the family's per-item tasks.
        current_iteration: Iteration stamped on a recurrent review.
        db_path: Optional override for the SQLite database path.

    Returns:
        The applied/failed tally and the raw per-item reviews.
    """
    from co_scientist.agents.reflection.review_types import ReviewType

    successful = 0
    failed = 0
    reflection_results: list[dict[str, Any]] = []
    for item_id in item_task_ids:
        item = _require_item_task(item_id, db_path, kind="reflection task")
        if item.status != "completed" or not item.result:
            failed += 1
            continue
        hypothesis = by_id[str(item.result["hypothesis_id"])]
        mode = ReviewType(str(item.result["review_mode"]))
        review = item.result["review"]
        reflection_results.append(review)
        if mode is ReviewType.OBSERVATION:
            classification = review.get("classification", "neutral")
            reasoning = review.get("reasoning", "")
            hypothesis.reflection_notes = (
                f"{reasoning}\n\nClassification: {classification}"
            )
        hypothesis.enrichments[mode.value] = review
        if mode is ReviewType.RECURRENT:
            hypothesis.enrichments["recurrent_review_iteration"] = (
                current_iteration
            )
        successful += 1
    return _AppliedItems(
        successful=successful,
        failed=failed,
        llm_calls=successful + failed,
        results=reflection_results,
    )


def _mature_reflection_update(
    state: dict[str, Any],
    items: _AppliedItems,
) -> dict[str, Any]:
    """Merge retrieved articles and build the reflection state update."""
    from co_scientist.agents.reflection.deep_verification import (
        merge_retrieved_articles,
    )
    from co_scientist.models import (
        MetricDeltas,
        create_metrics_update,
        phase_message,
    )

    state["articles"] = merge_retrieved_articles(
        state.get("articles"), items.results
    )
    return {
        "hypotheses": state["hypotheses"],
        "articles": state["articles"],
        "metrics": create_metrics_update(
            deltas=MetricDeltas(llm_calls=items.llm_calls)
        ),
        "messages": phase_message(
            "reflection",
            f"Completed {items.successful} mature reviews; "
            f"{items.failed} isolated failures",
        ),
    }


async def _commit_mature_reflection_aggregate(
    commit: TaskCommit,
    state: dict[str, Any],
    items: _AppliedItems,
) -> dict[str, Any]:
    """Checkpoint the committed reflection results and hand off to safety.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        state: Restored workflow state the items were applied to.
        items: The applied/failed tally and the raw per-item reviews.

    Returns:
        The task result: committed checkpoint, successor, and review tally.
    """
    from co_scientist.task_runtime import apply_task_update

    update = _mature_reflection_update(state, items)
    committed = apply_task_update(state, update)
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        commit, committed, "comprehensive_reflection", "safety_screen"
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_reviews": items.successful,
        "failed_reviews": items.failed,
    }


async def execute_mature_reflection_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit mature Reflection results while isolating individual failures."""
    from co_scientist.checkpoint import restore_workflow_state

    replay, checkpoint, current_seq = _replay_or_supersede(
        task, db_path, label="reflection aggregate"
    )
    if replay is not None:
        return replay
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    items = _apply_mature_reflection_items(
        by_id,
        task.inputs.get("item_task_ids", []),
        int(state.get("current_iteration", 0)),
        db_path,
    )
    return await _commit_mature_reflection_aggregate(
        TaskCommit(task, current_seq, db_path), state, items
    )


def _apply_verification_items(
    by_id: dict[str, Any],
    item_task_ids: Sequence[Any],
    db_path: str | None,
) -> _AppliedItems:
    """Apply each completed verification item to its hypothesis.

    Args:
        by_id: The run's hypotheses, keyed by id.
        item_task_ids: Ids of the family's per-item tasks.
        db_path: Optional override for the SQLite database path.

    Returns:
        The applied/failed tally, the calls each item reported, and the
        raw per-item verifications.
    """
    successful = 0
    failed = 0
    llm_calls = 0
    verification_results: list[dict[str, Any]] = []
    for item_id in item_task_ids:
        item = _require_item_task(item_id, db_path, kind="verification item")
        if item.status != "completed" or not item.result:
            failed += 1
            continue
        hypothesis = by_id[str(item.result["hypothesis_id"])]
        verification = item.result["verification"]
        verification_results.append(verification)
        hypothesis.deep_verification_probes = verification.get("probes", [])
        hypothesis.deep_verification_verdict = verification.get("verdict")
        hypothesis.enrichments["deep_verification"] = verification
        llm_calls += int(verification.get("verification_llm_calls", 1))
        successful += 1
    return _AppliedItems(
        successful=successful,
        failed=failed,
        llm_calls=llm_calls,
        results=verification_results,
    )


def _verification_aggregate_update(
    state: dict[str, Any],
    items: _AppliedItems,
) -> dict[str, Any]:
    """Merge retrieved articles and build the verification state update."""
    from co_scientist.agents.reflection.deep_verification import (
        merge_retrieved_articles,
    )
    from co_scientist.models import (
        MetricDeltas,
        create_metrics_update,
        phase_message,
    )

    state["articles"] = merge_retrieved_articles(
        state.get("articles"), items.results
    )
    return {
        "hypotheses": state["hypotheses"],
        "articles": state["articles"],
        "metrics": create_metrics_update(
            deltas=MetricDeltas(llm_calls=items.llm_calls)
        ),
        "messages": phase_message(
            "deep_verification",
            f"Deep-verified {items.successful} hypotheses; "
            f"{items.failed} isolated failures",
        ),
    }


async def _commit_verification_aggregate(
    commit: TaskCommit,
    state: dict[str, Any],
    items: _AppliedItems,
) -> dict[str, Any]:
    """Checkpoint the committed verifications and continue the tournament.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        state: Restored workflow state the items were applied to.
        items: The applied/failed tally and the raw per-item verifications.

    Returns:
        The task result: committed checkpoint, successor, and item tally.
    """
    from co_scientist.task_runtime import apply_task_update

    update = _verification_aggregate_update(state, items)
    committed = apply_task_update(state, update)
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        commit, committed, "deep_verification", "ranking"
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_verifications": items.successful,
        "failed_verifications": items.failed,
    }


async def execute_verification_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit independent verification results and continue the tournament."""
    from co_scientist.checkpoint import restore_workflow_state

    replay, checkpoint, current_seq = _replay_or_supersede(
        task, db_path, label="verification aggregate"
    )
    if replay is not None:
        return replay
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    items = _apply_verification_items(
        by_id, task.inputs.get("item_task_ids", []), db_path
    )
    return await _commit_verification_aggregate(
        TaskCommit(task, current_seq, db_path), state, items
    )

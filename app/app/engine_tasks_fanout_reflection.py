"""Mature-reflection fan-out aggregate for the durable engine path.

The aggregate task that commits mature-reflection fan-out results, plus
the ``_AppliedItems`` tally and the checkpoint-and-advance commit helper
every fan-out aggregate shares. Split from
``app.engine_tasks_fanout_aggregates``, which imports the shared helper
and re-exports the names callers use so ``app.engine_tasks`` remains their
import and monkeypatch surface.

The deep-verification aggregate is the sibling
``app.engine_tasks_fanout_verification``, which imports both shared names
from here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.engine_tasks_context import TaskCommit
from app.engine_tasks_support import (
    NodeCompletion,
    _emit_node_completion,
    _require_item_task,
    _save_state_and_enqueue,
    leased_state,
)
from app.engine_tasks_telemetry import merge_usage_snapshots
from app.store import ScientificTask


@dataclass(frozen=True)
class _AppliedItems:
    """Tally of one fan-out family's applied per-item results.

    Attributes:
        successful: Items whose result was applied to its hypothesis.
        failed: Items that never completed, isolated from the aggregate.
        llm_calls: Provider calls the items are billed for.
        results: The raw per-item review payloads, in item order.
        model_usage: Per-(phase, model) telemetry folded from every
            completed item's captured usage.
        research_ledgers: What research the items' evidence came from,
            one per researching item. Carried through the aggregate
            because the state is where a run's ledgers accumulate, and
            an item's own result is discarded once it is applied.
    """

    successful: int
    failed: int
    llm_calls: int
    results: list[dict[str, Any]] = field(default_factory=list)
    model_usage: dict[str, dict[str, Any]] = field(default_factory=dict)
    research_ledgers: list[dict[str, Any]] = field(default_factory=list)


async def _checkpoint_and_advance(
    commit: TaskCommit,
    committed: dict[str, Any],
    node_name: str,
) -> tuple[int, str | None]:
    """Checkpoint an aggregate's committed state and emit its completion.

    The successor is resolved from the engine's own route table, never
    named as a literal here. ``next_task_type`` is what the in-process
    graph routes on, and ``engine/tests/test_task_runtime.py`` pins that
    table against the graph's topology -- but the durable path is the only
    path production runs, so a successor spelled out here would keep the
    old target after a graph re-route while that test still passed. Read
    the route from the committed state, so the state-dependent branches
    (MCP availability after ``generate``) resolve the same way too.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        committed: Workflow state the aggregate folded its items into.
        node_name: Engine node this aggregate completes.

    Returns:
        A tuple of (committed checkpoint sequence, successor task id).
    """
    from co_scientist.task_runtime import next_task_type

    # The app's mypy config skips following ``co_scientist`` imports, so the
    # engine's declared return type arrives here as ``Any``. Restate it on
    # the binding rather than passing an unchecked value on.
    successor: str | None = next_task_type(node_name, committed)
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        commit, committed, successor
    )
    await _emit_node_completion(
        commit.task.run_id,
        NodeCompletion(node_name, successor, checkpoint_seq),
        committed,
        commit.db_path,
    )
    return checkpoint_seq, successor_id


def _apply_one_reflection_item(
    hypothesis: Any,
    mode: Any,
    review: dict[str, Any],
    current_iteration: int,
) -> None:
    """Apply one completed mature-reflection item to its hypothesis."""
    from co_scientist.agents.reflection.mature_reviews import (
        store_mature_review_result,
    )
    from co_scientist.agents.reflection.observation_feedback import (
        apply_observation_result,
    )
    from co_scientist.agents.reflection.review_types import ReviewType

    if mode is ReviewType.OBSERVATION:
        # The shared engine seam, so confirmed strengths reach the
        # hypothesis notes on the durable path exactly as they do in the
        # in-process node (audit K8).
        apply_observation_result(hypothesis, review)
        return
    # The shared engine write path, so a fatal full/simulation/recurrent
    # finding changes the disposition here exactly as it does in the
    # in-process node (audit E1).
    store_mature_review_result(hypothesis, mode, review, current_iteration)


def _mark_recheck_item(by_id: dict[str, Any], item: Any) -> None:
    """Record a blocked idea's one recheck, whatever the item did.

    Read from the item's own inputs and applied before its status is
    consulted: the attempt is spent when it is issued, so a failed item
    must mark its hypothesis too. Marking only on success would let the
    wave re-fire every cycle for exactly the ideas the reviewer keeps
    failing on, which is the unbounded shape this recheck exists to
    avoid.
    """
    from co_scientist.agents.reflection.review_recheck import (
        mark_recheck_issued,
    )

    if not item.inputs.get("recheck"):
        return
    hypothesis = by_id.get(str(item.inputs.get("hypothesis_id") or ""))
    if hypothesis is not None:
        mark_recheck_issued(hypothesis)


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
    usage_snapshots: list[dict[str, Any]] = []
    ledgers: list[dict[str, Any]] = []
    for item_id in item_task_ids:
        item = _require_item_task(item_id, db_path, kind="reflection task")
        _mark_recheck_item(by_id, item)
        if item.status != "completed" or not item.result:
            failed += 1
            continue
        hypothesis = by_id[str(item.result["hypothesis_id"])]
        mode = ReviewType(str(item.result["review_mode"]))
        review = item.result["review"]
        reflection_results.append(review)
        _apply_one_reflection_item(hypothesis, mode, review, current_iteration)
        usage_snapshots.append(item.result.get("model_usage") or {})
        ledger = item.result.get("research_ledger")
        if isinstance(ledger, dict) and ledger and ledger not in ledgers:
            ledgers.append(ledger)
        successful += 1
    return _AppliedItems(
        successful=successful,
        failed=failed,
        llm_calls=successful + failed,
        results=reflection_results,
        model_usage=merge_usage_snapshots(usage_snapshots),
        research_ledgers=ledgers,
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
        # Accumulated by the state's own reducer, so a reviewed
        # hypothesis's searches join the literature review's rather than
        # replacing them (``state_reducers``).
        "research_ledgers": items.research_ledgers,
        "metrics": create_metrics_update(
            deltas=MetricDeltas(llm_calls=items.llm_calls),
            model_usage=items.model_usage,
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
    """Checkpoint the committed reflection results and advance the run.

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
        commit, committed, "comprehensive_reflection"
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
    replay, state, current_seq = leased_state(
        task, db_path, label="reflection aggregate"
    )
    if replay is not None:
        return replay
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

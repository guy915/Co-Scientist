"""Deep-verification fan-out aggregate for the durable engine path.

The aggregate task that commits per-hypothesis deep-verification results
into the run's checkpoint and advances it into the tournament. Split from
``app.engine_tasks_fanout_reflection``, whose ``_AppliedItems`` tally and
``_checkpoint_and_advance`` helper it shares;
``app.engine_tasks_fanout_aggregates`` re-exports these names so
``app.engine_tasks`` remains the stable import and monkeypatch surface.

Two marks are written here rather than by the items themselves, because
this is the only boundary that sees the whole family: the once-ever
verification marker for every item, and the explicit ``unverified``
verdict for every item that produced no usable one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.engine_tasks_context import TaskCommit
from app.engine_tasks_fanout_reflection import (
    _AppliedItems,
    _checkpoint_and_advance,
)
from app.engine_tasks_support import (
    _generator_for_restore,
    _replay_or_supersede,
    _require_item_task,
)
from app.engine_tasks_telemetry import merge_usage_snapshots
from app.store import ScientificTask


def _mark_failed_item_unverified(by_id: dict[str, Any], item: Any) -> None:
    """Stamp the explicit unverified state for a failed verification item.

    Fails closed (audit E9): an item that never completed, or completed
    without a usable verdict, must not leave its hypothesis merely
    untouched -- that read as an implicit pass. The fingerprint stays
    stale, so the next deep-verification pass re-attempts.
    """
    from co_scientist.agents.reflection.deep_verification import (
        mark_hypothesis_unverified,
    )

    hypothesis = by_id.get(str(item.inputs.get("hypothesis_id") or ""))
    if hypothesis is not None:
        mark_hypothesis_unverified(hypothesis)


def _mark_verification_item(by_id: dict[str, Any], item: Any) -> None:
    """Record a hypothesis's one deep verification, whatever the item did.

    Same shape and same reason as ``_mark_recheck_item``: the attempt is
    spent when it is issued, so a failed item marks its hypothesis too.
    Marking only on success re-offers the whole failing population every
    cycle -- the pool x cycles cost this node is bounded against.
    """
    from co_scientist.agents.reflection.deep_verification import (
        mark_verification_issued,
    )

    hypothesis = by_id.get(str(item.inputs.get("hypothesis_id") or ""))
    if hypothesis is not None:
        mark_verification_issued(hypothesis)


def _completed_verification(item: Any) -> dict[str, Any] | None:
    """The item's verification payload, or None when it never completed."""
    if item.status != "completed" or not item.result:
        return None
    verification = item.result.get("verification")
    return verification if isinstance(verification, dict) else None


def _record_verification(
    hypothesis: Any, verification: dict[str, Any], model_name: str
) -> None:
    """Record one completed verification on its hypothesis.

    The fingerprint is what lets the next cycle skip a leader whose inputs
    have not moved, so it is written here rather than by the caller.

    Args:
        hypothesis: The hypothesis the verification item ran against.
        verification: The item's verification payload.
        model_name: Verifier model the item ran on.
    """
    from co_scientist.agents.reflection.deep_verification import (
        verification_fingerprint,
    )

    hypothesis.deep_verification_probes = verification.get("probes", [])
    hypothesis.deep_verification_verdict = verification.get("verdict")
    hypothesis.deep_verification_fingerprint = verification_fingerprint(
        hypothesis, model_name
    )
    hypothesis.enrichments["deep_verification"] = verification


def _apply_verification_items(
    by_id: dict[str, Any],
    item_task_ids: Sequence[Any],
    db_path: str | None,
    model_name: str,
) -> _AppliedItems:
    """Apply each completed verification item to its hypothesis.

    Records the once-ever marker for every item and the verification
    fingerprint for every item that answered. This is the production path
    -- the in-process node is only reached by the library -- so omitting
    either here would re-verify the whole pool on every cycle for the
    life of the run.

    Fails closed (audit E9): an item that never completed, or whose result
    carries no usable verdict, records an explicit ``unverified`` verdict
    on its hypothesis rather than leaving it implicitly passed.

    Args:
        by_id: The run's hypotheses, keyed by id.
        item_task_ids: Ids of the family's per-item tasks.
        db_path: Optional override for the SQLite database path.
        model_name: Verifier model the items ran on.

    Returns:
        The applied/failed tally, the calls each item reported, and the
        raw per-item verifications.
    """
    from co_scientist.agents.reflection.deep_verification import (
        _VALID_VERDICTS,
    )

    successful = failed = llm_calls = 0
    verification_results: list[dict[str, Any]] = []
    usage_snapshots: list[dict[str, Any]] = []
    for item_id in item_task_ids:
        item = _require_item_task(item_id, db_path, kind="verification item")
        _mark_verification_item(by_id, item)
        verification = _completed_verification(item)
        if verification is not None:
            verification_results.append(verification)
        if verification is None or (
            verification.get("verdict") not in _VALID_VERDICTS
        ):
            failed += 1
            _mark_failed_item_unverified(by_id, item)
            continue
        hypothesis = by_id[str((item.result or {})["hypothesis_id"])]
        _record_verification(hypothesis, verification, model_name)
        llm_calls += int(verification.get("verification_llm_calls", 1))
        usage_snapshots.append((item.result or {}).get("model_usage") or {})
        successful += 1
    return _AppliedItems(
        successful=successful,
        failed=failed,
        llm_calls=llm_calls,
        results=verification_results,
        model_usage=merge_usage_snapshots(usage_snapshots),
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
            deltas=MetricDeltas(llm_calls=items.llm_calls),
            model_usage=items.model_usage,
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
    """Checkpoint the committed verifications and advance the run.

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
        commit, committed, "deep_verification"
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
        by_id,
        task.inputs.get("item_task_ids", []),
        db_path,
        state["model_name"],
    )
    return await _commit_verification_aggregate(
        TaskCommit(task, current_seq, db_path), state, items
    )

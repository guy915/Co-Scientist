"""Commit fan-out results at one leased checkpoint boundary.

Aggregates isolate failed items, fold their telemetry, and advance through the
engine's own route table. Recheck and verification markers are spent even when
an item fails, preventing repeated waves against the same failing population.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app import store
from app.engine_tasks.context import TaskCommit
from app.engine_tasks.emit import NodeCompletion, _emit_node_completion
from app.engine_tasks.metrics import merge_usage_snapshots
from app.engine_tasks.support import (
    _require_item_task,
    _save_state_and_enqueue,
    leased_state,
)
from app.store import ScientificTask


@dataclass(frozen=True)
class _AppliedItems:
    """Tally of one fan-out family's applied per-item results."""

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
    """Checkpoint an aggregate's committed state and emit its completion."""
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
    from co_scientist.agents.reflection.reflection import (
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
    """Record a blocked idea's one recheck, whatever the item did."""
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
    """Apply each completed mature-reflection item to its hypothesis."""
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
        # replacing them (``state.reducers``).
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
    from co_scientist.task_runtime import apply_task_update

    committed = apply_task_update(
        state, _mature_reflection_update(state, items)
    )
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        TaskCommit(task, current_seq, db_path),
        committed,
        "comprehensive_reflection",
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_reviews": items.successful,
        "failed_reviews": items.failed,
    }


def _mark_failed_item_unverified(by_id: dict[str, Any], item: Any) -> None:
    """Stamp the explicit unverified state for a failed verification item."""
    from co_scientist.agents.reflection.deep_verification import (
        mark_hypothesis_unverified,
    )

    hypothesis = by_id.get(str(item.inputs.get("hypothesis_id") or ""))
    if hypothesis is not None:
        mark_hypothesis_unverified(hypothesis)


def _mark_verification_item(by_id: dict[str, Any], item: Any) -> None:
    """Record a hypothesis's one deep verification, whatever the item did."""
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
    """Record one completed verification on its hypothesis."""
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
    """Apply each completed verification item to its hypothesis."""
    from co_scientist.agents.reflection import has_valid_verification

    successful = failed = llm_calls = 0
    verification_results: list[dict[str, Any]] = []
    usage_snapshots: list[dict[str, Any]] = []
    for item_id in item_task_ids:
        item = _require_item_task(item_id, db_path, kind="verification item")
        _mark_verification_item(by_id, item)
        verification = _completed_verification(item)
        if verification is not None:
            verification_results.append(verification)
        if not has_valid_verification(verification):
            failed += 1
            _mark_failed_item_unverified(by_id, item)
            continue
        assert verification is not None
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


async def execute_verification_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit independent verification results and continue the tournament."""
    replay, state, current_seq = leased_state(
        task, db_path, label="verification aggregate"
    )
    if replay is not None:
        return replay
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    items = _apply_verification_items(
        by_id,
        task.inputs.get("item_task_ids", []),
        db_path,
        state["model_name"],
    )
    from co_scientist.task_runtime import apply_task_update

    committed = apply_task_update(
        state, _verification_aggregate_update(state, items)
    )
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        TaskCommit(task, current_seq, db_path), committed, "deep_verification"
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_verifications": items.successful,
        "failed_verifications": items.failed,
    }


@dataclass(frozen=True)
class _AggregateSpec:
    """The parts of an aggregate task that differ per fan-out family."""

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
    """Enqueue a fan-out aggregate depending on every one of its item tasks."""
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
    criteria: list[str] | None = None,
) -> tuple[int, int, dict[str, dict[str, Any]]]:
    """Apply each completed review item to its hypothesis; count failures."""
    from co_scientist.agents.reflection import apply_initial_review_gate
    from co_scientist.agents.reflection.review_gate import (
        refresh_review_dispositions,
    )
    from co_scientist.models import HypothesisReview

    successful = 0
    failed = 0
    usage_snapshots: list[dict[str, Any]] = []
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
        apply_initial_review_gate([hypothesis], [review], criteria)
        usage_snapshots.append(item.result.get("model_usage") or {})
        successful += 1
    refresh_review_dispositions(by_id.values(), criteria)
    return successful, failed, merge_usage_snapshots(usage_snapshots)


def _review_aggregate_update(
    state: dict[str, Any],
    successful: int,
    failed: int,
    model_usage: dict[str, dict[str, Any]],
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
            ),
            model_usage=model_usage,
        ),
        "messages": phase_message(
            "review",
            f"Reviewed {successful} hypotheses; {failed} isolated failures",
            strategy="durable_parallel_individual",
        ),
    }


async def execute_review_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit successful review results and preserve isolated failures."""
    replay, state, current_seq = leased_state(
        task, db_path, label="review aggregate"
    )
    if replay is not None:
        return replay
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    successful, failed, model_usage = _apply_review_items(
        by_id,
        task.inputs.get("item_task_ids", []),
        db_path,
        criteria=state.get("criteria"),
    )
    from co_scientist.task_runtime import apply_task_update

    committed = apply_task_update(
        state, _review_aggregate_update(state, successful, failed, model_usage)
    )
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        TaskCommit(task, current_seq, db_path), committed, "review"
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_reviews": successful,
        "failed_reviews": failed,
    }


@dataclass(frozen=True)
class _GenerationItems:
    """What the generation fan-out's strategy tasks produced."""

    buckets: dict[str, list[Any]]
    transcripts: list[dict[str, Any]]
    failed: int
    llm_calls: int = 0
    model_usage: dict[str, dict[str, Any]] = field(default_factory=dict)
    skills_used: dict[str, int] = field(default_factory=dict)


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
    llm_calls = 0
    usage_snapshots: list[dict[str, Any]] = []
    skills_used: dict[str, int] = {}
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
        llm_calls += int(item.result.get("llm_calls", 0))
        usage_snapshots.append(item.result.get("model_usage") or {})
        for name, uses in (item.result.get("skills_used") or {}).items():
            skills_used[name] = skills_used.get(name, 0) + int(uses)
    return _GenerationItems(
        buckets,
        transcripts,
        failed,
        llm_calls,
        merge_usage_snapshots(usage_snapshots),
        skills_used,
    )


async def _generation_aggregate_update(
    task: ScientificTask,
    state: dict[str, Any],
    items: _GenerationItems,
) -> dict[str, Any]:
    """Finalize the combined generation strategies into a state update."""
    from co_scientist.agents.generation import (
        GenerationCounts,
        GenerationResults,
        finalize_generation,
    )
    from co_scientist.models import MetricDeltas, create_metrics_update

    buckets = items.buckets
    update: dict[str, Any] = await finalize_generation(
        state,
        GenerationCounts(**task.inputs["counts"]),
        GenerationResults(
            tools_hypotheses=buckets["tools"],
            debate_with_lit_hypotheses=buckets["debate_lit"],
            debate_only_hypotheses=buckets["debate_only"],
            assumptions_hypotheses=buckets["assumptions"],
            debate_transcripts=items.transcripts,
            llm_call_count=items.llm_calls,
        ),
    )
    update["metrics"] = create_metrics_update(
        hypothesis_count=update["hypothesis_count"],
        deltas=MetricDeltas(
            llm_calls=update.get("llm_call_count", 0),
            skills_used=items.skills_used,
        ),
        model_usage=items.model_usage,
    )
    if items.failed:
        update["message"] += f"; {items.failed} strategy failure(s) isolated"
    return update


async def execute_generation_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Combine independent generation strategies into one hypothesis append."""
    replay, state, current_seq = leased_state(
        task, db_path, label="generation aggregate"
    )
    if replay is not None:
        return replay
    items = _collect_generation_results(
        task.inputs.get("item_task_ids", []), db_path
    )
    from co_scientist.task_runtime import apply_task_update

    update = await _generation_aggregate_update(task, state, items)
    committed = apply_task_update(state, update)
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        TaskCommit(task, current_seq, db_path), committed, "generate"
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "hypotheses_generated": update["hypothesis_count"],
        "failed_strategies": items.failed,
    }

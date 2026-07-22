"""Durable fan-out aggregates: commit results, isolate item failures.

Each fan-out family (review, generation, mature reflection, deep
verification) ends in one aggregate task that folds successful item
results into the workflow checkpoint while preserving per-item failures.
Split from ``app.engine_tasks_fanout``, which re-exports these names so
``app.engine_tasks`` remains the stable import and monkeypatch surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.engine_tasks_support import (
    _emit_node_completion,
    _generator_for_restore,
    _replay_or_supersede,
    _require_item_task,
    _save_state_and_enqueue,
)
from app.store import ScientificTask


async def _checkpoint_and_advance(
    task: ScientificTask,
    committed: dict[str, Any],
    node_name: str,
    successor: str,
    current_seq: int,
    db_path: str | None,
) -> tuple[int, str | None]:
    """Checkpoint an aggregate's committed state and emit its completion."""
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        successor,
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id, node_name, successor, committed, checkpoint_seq, db_path
    )
    return checkpoint_seq, successor_id


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
    from co_scientist.models import create_metrics_update, phase_message

    return {
        "hypotheses": state["hypotheses"],
        "metrics": create_metrics_update(
            reviews_count_delta=successful,
            llm_calls_delta=successful + failed,
        ),
        "messages": phase_message(
            "review",
            f"Reviewed {successful} hypotheses; {failed} isolated failures",
            strategy="durable_parallel_individual",
        ),
    }


async def _commit_review_aggregate(
    task: ScientificTask,
    state: dict[str, Any],
    successful: int,
    failed: int,
    current_seq: int,
    db_path: str | None,
) -> dict[str, Any]:
    """Checkpoint the committed reviews and hand off to reflection."""
    from co_scientist.task_runtime import apply_task_update

    committed = apply_task_update(
        state, _review_aggregate_update(state, successful, failed)
    )
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        task,
        committed,
        "review",
        "comprehensive_reflection",
        current_seq,
        db_path,
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
        task, state, successful, failed, current_seq, db_path
    )


def _collect_generation_results(
    item_task_ids: Sequence[Any],
    db_path: str | None,
) -> tuple[dict[str, list[Any]], list[dict[str, Any]], int]:
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
    return buckets, transcripts, failed


async def _generation_aggregate_update(
    task: ScientificTask,
    state: dict[str, Any],
    buckets: dict[str, list[Any]],
    transcripts: list[dict[str, Any]],
    failed: int,
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

    counts = GenerationCounts(**task.inputs["counts"])
    results = GenerationResults(
        tools_hypotheses=buckets["tools"],
        debate_with_lit_hypotheses=buckets["debate_lit"],
        debate_only_hypotheses=buckets["debate_only"],
        assumptions_hypotheses=buckets["assumptions"],
        debate_transcripts=transcripts,
    )
    update: dict[str, Any] = await _finalize_generation(state, counts, results)
    update["metrics"] = create_metrics_update(
        hypothesis_count=update["hypothesis_count"]
    )
    if failed:
        update["message"] += f"; {failed} strategy failure(s) isolated"
    return update


async def _commit_generation_aggregate(
    task: ScientificTask,
    state: dict[str, Any],
    buckets: dict[str, list[Any]],
    transcripts: list[dict[str, Any]],
    failed: int,
    current_seq: int,
    db_path: str | None,
) -> dict[str, Any]:
    """Finalize combined generation results and hand off to the next node."""
    from co_scientist.task_runtime import apply_task_update

    update = await _generation_aggregate_update(
        task, state, buckets, transcripts, failed
    )
    committed = apply_task_update(state, update)
    successor = "reflection" if state.get("mcp_available") else "review"
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        task, committed, "generate", successor, current_seq, db_path
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "hypotheses_generated": update["hypothesis_count"],
        "failed_strategies": failed,
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
    buckets, transcripts, failed = _collect_generation_results(
        task.inputs.get("item_task_ids", []), db_path
    )
    return await _commit_generation_aggregate(
        task, state, buckets, transcripts, failed, current_seq, db_path
    )


def _apply_mature_reflection_items(
    by_id: dict[str, Any],
    item_task_ids: Sequence[Any],
    current_iteration: int,
    db_path: str | None,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Apply each completed mature-reflection item to its hypothesis."""
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
    return successful, failed, reflection_results


def _mature_reflection_update(
    state: dict[str, Any],
    successful: int,
    failed: int,
    reflection_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge retrieved articles and build the reflection state update."""
    from co_scientist.agents.reflection.deep_verification import (
        merge_retrieved_articles,
    )
    from co_scientist.models import create_metrics_update, phase_message

    state["articles"] = merge_retrieved_articles(
        state.get("articles"), reflection_results
    )
    return {
        "hypotheses": state["hypotheses"],
        "articles": state["articles"],
        "metrics": create_metrics_update(llm_calls_delta=successful + failed),
        "messages": phase_message(
            "reflection",
            f"Completed {successful} mature reviews; "
            f"{failed} isolated failures",
        ),
    }


async def _commit_mature_reflection_aggregate(
    task: ScientificTask,
    state: dict[str, Any],
    successful: int,
    failed: int,
    reflection_results: list[dict[str, Any]],
    current_seq: int,
    db_path: str | None,
) -> dict[str, Any]:
    """Checkpoint the committed reflection results and hand off to safety."""
    from co_scientist.task_runtime import apply_task_update

    update = _mature_reflection_update(
        state, successful, failed, reflection_results
    )
    committed = apply_task_update(state, update)
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        task,
        committed,
        "comprehensive_reflection",
        "safety_screen",
        current_seq,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_reviews": successful,
        "failed_reviews": failed,
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
    successful, failed, reflection_results = _apply_mature_reflection_items(
        by_id,
        task.inputs.get("item_task_ids", []),
        int(state.get("current_iteration", 0)),
        db_path,
    )
    return await _commit_mature_reflection_aggregate(
        task,
        state,
        successful,
        failed,
        reflection_results,
        current_seq,
        db_path,
    )


def _apply_verification_items(
    by_id: dict[str, Any],
    item_task_ids: Sequence[Any],
    db_path: str | None,
) -> tuple[int, int, int, list[dict[str, Any]]]:
    """Apply each completed verification item to its hypothesis."""
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
    return successful, failed, llm_calls, verification_results


def _verification_aggregate_update(
    state: dict[str, Any],
    successful: int,
    failed: int,
    llm_calls: int,
    verification_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge retrieved articles and build the verification state update."""
    from co_scientist.agents.reflection.deep_verification import (
        merge_retrieved_articles,
    )
    from co_scientist.models import create_metrics_update, phase_message

    state["articles"] = merge_retrieved_articles(
        state.get("articles"), verification_results
    )
    return {
        "hypotheses": state["hypotheses"],
        "articles": state["articles"],
        "metrics": create_metrics_update(llm_calls_delta=llm_calls),
        "messages": phase_message(
            "deep_verification",
            f"Deep-verified {successful} hypotheses; "
            f"{failed} isolated failures",
        ),
    }


async def _commit_verification_aggregate(
    task: ScientificTask,
    state: dict[str, Any],
    successful: int,
    failed: int,
    llm_calls: int,
    verification_results: list[dict[str, Any]],
    current_seq: int,
    db_path: str | None,
) -> dict[str, Any]:
    """Checkpoint the committed verifications and continue the tournament."""
    from co_scientist.task_runtime import apply_task_update

    update = _verification_aggregate_update(
        state, successful, failed, llm_calls, verification_results
    )
    committed = apply_task_update(state, update)
    checkpoint_seq, successor_id = await _checkpoint_and_advance(
        task, committed, "deep_verification", "ranking", current_seq, db_path
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_verifications": successful,
        "failed_verifications": failed,
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
    successful, failed, llm_calls, verification_results = (
        _apply_verification_items(
            by_id, task.inputs.get("item_task_ids", []), db_path
        )
    )
    return await _commit_verification_aggregate(
        task,
        state,
        successful,
        failed,
        llm_calls,
        verification_results,
        current_seq,
        db_path,
    )

"""Durable fan-out aggregates: commit results, isolate item failures.

Each fan-out family (review, generation, mature reflection, deep
verification) ends in one aggregate task that folds successful item
results into the workflow checkpoint while preserving per-item failures.
Split from ``app.engine_tasks_fanout``, which re-exports these names so
``app.engine_tasks`` remains the stable import and monkeypatch surface.
"""

from __future__ import annotations

from typing import Any

from app.engine_tasks_support import (
    SupersededTaskError,
    _emit_node_completion,
    _generator_for_restore,
    _latest_task_checkpoint,
    _require_item_task,
    _save_state_and_enqueue,
)
from app.store import ScientificTask


async def execute_review_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit successful review results and preserve isolated failures."""
    from co_scientist.agents.reflection.review import _apply_initial_review_gate
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.models import (
        HypothesisReview,
        create_metrics_update,
        phase_message,
    )
    from co_scientist.task_runtime import apply_task_update

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return {"checkpoint_seq": current_seq, "replayed": True}
    if current_seq != expected_seq:
        raise SupersededTaskError("review aggregate checkpoint was superseded")
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    successful = 0
    failed = 0
    for item_id in task.inputs.get("item_task_ids", []):
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
        # The durable aggregate mirrors the normal Review node's score update
        # so tournament seeding observes peer-review quality.
        hypothesis.score = review.overall_score
        _apply_initial_review_gate([hypothesis], [review])
        successful += 1
    committed = apply_task_update(
        state,
        {
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
        },
    )
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        "comprehensive_reflection",
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id,
        "review",
        "comprehensive_reflection",
        committed,
        checkpoint_seq,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_reviews": successful,
        "failed_reviews": failed,
    }


async def execute_generation_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Combine independent generation strategies into one hypothesis append."""
    from co_scientist.agents.generation.coordinator import _finalize_generation
    from co_scientist.agents.generation.coordinator_results import (
        GenerationResults,
    )
    from co_scientist.agents.generation.coordinator_strategy import (
        GenerationCounts,
    )
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.models import Hypothesis, create_metrics_update
    from co_scientist.task_runtime import apply_task_update

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return {"checkpoint_seq": current_seq, "replayed": True}
    if current_seq != expected_seq:
        raise SupersededTaskError(
            "generation aggregate checkpoint was superseded"
        )
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    buckets: dict[str, list[Hypothesis]] = {
        "tools": [],
        "debate_lit": [],
        "debate_only": [],
        "assumptions": [],
    }
    transcripts: list[dict[str, Any]] = []
    failed = 0
    for item_id in task.inputs.get("item_task_ids", []):
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
    counts = GenerationCounts(**task.inputs["counts"])
    results = GenerationResults(
        tools_hypotheses=buckets["tools"],
        debate_with_lit_hypotheses=buckets["debate_lit"],
        debate_only_hypotheses=buckets["debate_only"],
        assumptions_hypotheses=buckets["assumptions"],
        debate_transcripts=transcripts,
    )
    update = await _finalize_generation(state, counts, results)
    update["metrics"] = create_metrics_update(
        hypothesis_count=update["hypothesis_count"]
    )
    if failed:
        update["message"] += f"; {failed} strategy failure(s) isolated"
    committed = apply_task_update(state, update)
    successor = "reflection" if state.get("mcp_available") else "review"
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        successor,
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id, "generate", successor, committed, checkpoint_seq, db_path
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "hypotheses_generated": update["hypothesis_count"],
        "failed_strategies": failed,
    }


async def execute_mature_reflection_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit mature Reflection results while isolating individual failures."""
    from co_scientist.agents.reflection.deep_verification import (
        merge_retrieved_articles,
    )
    from co_scientist.agents.reflection.review_types import ReviewType
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.models import create_metrics_update, phase_message
    from co_scientist.task_runtime import apply_task_update

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return {"checkpoint_seq": current_seq, "replayed": True}
    if current_seq != expected_seq:
        raise SupersededTaskError(
            "reflection aggregate checkpoint was superseded"
        )
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    successful = 0
    failed = 0
    reflection_results: list[dict[str, Any]] = []
    for item_id in task.inputs.get("item_task_ids", []):
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
            hypothesis.enrichments["recurrent_review_iteration"] = int(
                state.get("current_iteration", 0)
            )
        successful += 1
    state["articles"] = merge_retrieved_articles(
        state.get("articles"), reflection_results
    )
    committed = apply_task_update(
        state,
        {
            "hypotheses": state["hypotheses"],
            "articles": state["articles"],
            "metrics": create_metrics_update(
                llm_calls_delta=successful + failed
            ),
            "messages": phase_message(
                "reflection",
                f"Completed {successful} mature reviews; "
                f"{failed} isolated failures",
            ),
        },
    )
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        "safety_screen",
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id,
        "comprehensive_reflection",
        "safety_screen",
        committed,
        checkpoint_seq,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_reviews": successful,
        "failed_reviews": failed,
    }


async def execute_verification_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit independent verification results and continue the tournament."""
    from co_scientist.agents.reflection.deep_verification import (
        merge_retrieved_articles,
    )
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.models import create_metrics_update, phase_message
    from co_scientist.task_runtime import apply_task_update

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return {"checkpoint_seq": current_seq, "replayed": True}
    if current_seq != expected_seq:
        raise SupersededTaskError(
            "verification aggregate checkpoint was superseded"
        )
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    successful = 0
    failed = 0
    llm_calls = 0
    verification_results: list[dict[str, Any]] = []
    for item_id in task.inputs.get("item_task_ids", []):
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
    state["articles"] = merge_retrieved_articles(
        state.get("articles"), verification_results
    )
    committed = apply_task_update(
        state,
        {
            "hypotheses": state["hypotheses"],
            "articles": state["articles"],
            "metrics": create_metrics_update(llm_calls_delta=llm_calls),
            "messages": phase_message(
                "deep_verification",
                f"Deep-verified {successful} hypotheses; "
                f"{failed} isolated failures",
            ),
        },
    )
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        "ranking",
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id,
        "deep_verification",
        "ranking",
        committed,
        checkpoint_seq,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_verifications": successful,
        "failed_verifications": failed,
    }

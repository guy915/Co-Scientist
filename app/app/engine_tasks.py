"""Durable node-level execution for the real scientific engine.

This module owns the run-level executors (bootstrap, node dispatch,
finalize) and the ``execute_engine_task`` dispatcher. The rest of the
durable vocabulary lives in sibling modules -- ``engine_tasks_support``
(task types, checkpoint plumbing, emitters), ``engine_tasks_inputs``
(bootstrap/continuation enqueueing, scientist-input merge),
``engine_tasks_gate`` (pre-ranking evidence gate), ``engine_tasks_fanout``
(review/verification/generation/reflection fan-out), and
``engine_tasks_ranking`` (tournament chain) -- and every moved name is
re-exported here so ``app.engine_tasks`` remains the stable import and
monkeypatch surface.
"""

from __future__ import annotations

import time
from typing import Any

from app import store
from app.engine_adapter.drain import _persist_final_state
from app.engine_adapter.provider import sync_engine_llm_backend
from app.engine_tasks_fanout import (
    _enqueue_generation_fanout as _enqueue_generation_fanout,
)
from app.engine_tasks_fanout import (
    _enqueue_mature_reflection_fanout as _enqueue_mature_reflection_fanout,
)
from app.engine_tasks_fanout import (
    _enqueue_review_fanout as _enqueue_review_fanout,
)
from app.engine_tasks_fanout import (
    _enqueue_verification_fanout as _enqueue_verification_fanout,
)
from app.engine_tasks_fanout import (
    execute_generation_aggregate as execute_generation_aggregate,
)
from app.engine_tasks_fanout import (
    execute_generation_strategy as execute_generation_strategy,
)
from app.engine_tasks_fanout import (
    execute_mature_reflection_aggregate as execute_mature_reflection_aggregate,
)
from app.engine_tasks_fanout import (
    execute_mature_reflection_item as execute_mature_reflection_item,
)
from app.engine_tasks_fanout import (
    execute_review_aggregate as execute_review_aggregate,
)
from app.engine_tasks_fanout import (
    execute_review_item as execute_review_item,
)
from app.engine_tasks_fanout import (
    execute_verification_aggregate as execute_verification_aggregate,
)
from app.engine_tasks_fanout import (
    execute_verification_item as execute_verification_item,
)
from app.engine_tasks_gate import (
    _apply_pre_ranking_evidence_gate as _apply_pre_ranking_evidence_gate,
)
from app.engine_tasks_gate import (
    _assess_gate_claims as _assess_gate_claims,
)
from app.engine_tasks_gate import (
    _GatePlan as _GatePlan,
)
from app.engine_tasks_inputs import (
    _merge_scientist_inputs as _merge_scientist_inputs,
)
from app.engine_tasks_inputs import (
    enqueue_bootstrap as enqueue_bootstrap,
)
from app.engine_tasks_inputs import (
    enqueue_scientist_continuation as enqueue_scientist_continuation,
)
from app.engine_tasks_ranking import (
    RANKING_WAVE_SIZE as RANKING_WAVE_SIZE,
)
from app.engine_tasks_ranking import (
    _ranking_eligible as _ranking_eligible,
)
from app.engine_tasks_ranking import (
    _ranking_wave as _ranking_wave,
)
from app.engine_tasks_ranking import (
    _schedule_ranking_chain as _schedule_ranking_chain,
)
from app.engine_tasks_ranking import (
    execute_ranking_finalize as execute_ranking_finalize,
)
from app.engine_tasks_ranking import (
    execute_ranking_match as execute_ranking_match,
)
from app.engine_tasks_support import (
    _CHECKPOINT_PROVIDER as _CHECKPOINT_PROVIDER,
)
from app.engine_tasks_support import (
    BOOTSTRAP_TASK as BOOTSTRAP_TASK,
)
from app.engine_tasks_support import (
    FINALIZE_TASK as FINALIZE_TASK,
)
from app.engine_tasks_support import (
    GENERATION_AGGREGATE_TASK as GENERATION_AGGREGATE_TASK,
)
from app.engine_tasks_support import (
    GENERATION_STRATEGY_TASK as GENERATION_STRATEGY_TASK,
)
from app.engine_tasks_support import (
    MATURE_REFLECTION_AGGREGATE_TASK as MATURE_REFLECTION_AGGREGATE_TASK,
)
from app.engine_tasks_support import (
    MATURE_REFLECTION_ITEM_TASK as MATURE_REFLECTION_ITEM_TASK,
)
from app.engine_tasks_support import (
    NODE_TASK_PREFIX as NODE_TASK_PREFIX,
)
from app.engine_tasks_support import (
    RANKING_FINALIZE_TASK as RANKING_FINALIZE_TASK,
)
from app.engine_tasks_support import (
    RANKING_MATCH_TASK as RANKING_MATCH_TASK,
)
from app.engine_tasks_support import (
    RANKING_PROGRESS_EVERY as RANKING_PROGRESS_EVERY,
)
from app.engine_tasks_support import (
    REVIEW_AGGREGATE_TASK as REVIEW_AGGREGATE_TASK,
)
from app.engine_tasks_support import (
    REVIEW_ITEM_TASK as REVIEW_ITEM_TASK,
)
from app.engine_tasks_support import (
    VERIFICATION_AGGREGATE_TASK as VERIFICATION_AGGREGATE_TASK,
)
from app.engine_tasks_support import (
    VERIFICATION_ITEM_TASK as VERIFICATION_ITEM_TASK,
)
from app.engine_tasks_support import (
    SupersededTaskError as SupersededTaskError,
)
from app.engine_tasks_support import (
    _apply_supervisor_queue_actions as _apply_supervisor_queue_actions,
)
from app.engine_tasks_support import (
    _durable_queue_snapshot as _durable_queue_snapshot,
)
from app.engine_tasks_support import (
    _emit_node_completion as _emit_node_completion,
)
from app.engine_tasks_support import (
    _emit_node_milestone as _emit_node_milestone,
)
from app.engine_tasks_support import (
    _generator_and_opts as _generator_and_opts,
)
from app.engine_tasks_support import (
    _generator_for_restore as _generator_for_restore,
)
from app.engine_tasks_support import (
    _latest_task_checkpoint as _latest_task_checkpoint,
)
from app.engine_tasks_support import (
    _plain_final_state as _plain_final_state,
)
from app.engine_tasks_support import (
    _require_item_task as _require_item_task,
)
from app.engine_tasks_support import (
    _require_run as _require_run,
)
from app.engine_tasks_support import (
    _restore_item_checkpoint as _restore_item_checkpoint,
)
from app.engine_tasks_support import (
    _save_paused_state as _save_paused_state,
)
from app.engine_tasks_support import (
    _save_state_and_enqueue as _save_state_and_enqueue,
)
from app.engine_tasks_support import (
    _save_state_and_enqueue_exact as _save_state_and_enqueue_exact,
)
from app.engine_tasks_support import (
    _successor_task_type as _successor_task_type,
)
from app.report_render import finalize_report, make_emitter
from app.run_modes import normalize_run_tier, resolved_run_config
from app.safety import (
    apply_safety_gate,
    screen_intake,
    screen_with_escalation,
)
from app.store import RunStatus, ScientificTask


async def execute_bootstrap(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Safety-gate a run, prepare state, and enqueue the Supervisor task."""
    run = _require_run(task, db_path)
    emit = make_emitter(run.id, db_path=db_path)
    # Via screen_with_escalation, not screen_contextual directly: the
    # escalation wrapper carries the two guards this durable path must honor
    # as much as the streaming one does -- an offline-backed run never pays
    # for a real contextual model call, and a stage a human already approved
    # is not re-screened (which would otherwise let a fresh contextual verdict
    # re-hold an approved run on every resume).
    decision = await screen_with_escalation(
        run.id,
        "intake",
        run.research_goal,
        screen_intake(run.research_goal),
        provider=run.provider,
        db_path=db_path,
    )
    async for _ in apply_safety_gate(run.id, decision, emit, db_path=db_path):
        pass
    if decision.decision in {"block", "hold"}:
        return {"run_id": run.id, "status": "withheld", "terminal": True}

    store.update_run_status(run.id, RunStatus.RUNNING, db_path=db_path)
    # Sync the run row before the generator is built (_generator_and_opts
    # reads it back via run_used_offline), so a config-pinned llm_backend
    # takes effect on the durable boundary exactly as it does on the
    # streaming one.
    sync_engine_llm_backend(run.id, resolved_run_config(run.config), db_path)
    generator, opts = _generator_and_opts(task, db_path)
    state = await generator.prepare_task_state(
        run.research_goal,
        opts=opts,
        run_id=run.id,
    )
    refreshed = store.get_run(run.id, db_path=db_path)
    if refreshed is None or refreshed.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled during bootstrap")
    if refreshed.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(
            task,
            state,
            f"{NODE_TASK_PREFIX}supervisor",
            expected_checkpoint_seq=0,
            db_path=db_path,
        )
        return {"checkpoint_seq": checkpoint_seq, "status": "paused"}
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        state,
        "supervisor",
        expected_checkpoint_seq=0,
        db_path=db_path,
    )
    await emit(
        "scientific_task",
        {
            "task": "bootstrap",
            "status": "completed",
            "checkpoint_seq": checkpoint_seq,
        },
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
    }


async def execute_node_task(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute and commit exactly one engine specialist node."""
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.task_runtime import execute_task_node

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    run = store.get_run(task.run_id, db_path=db_path)
    if run is None or run.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled before specialist execution")
    expected_seq = int(task.inputs.get("checkpoint_seq", -1))
    # Redelivery after the checkpoint commit but before task completion is an
    # acknowledgement replay, never a second scientific effect.
    if current_seq > expected_seq:
        if checkpoint["stage"] == f"engine_task:{task.id}":
            return {"checkpoint_seq": current_seq, "replayed": True}
        raise SupersededTaskError("specialist task checkpoint was superseded")
    if current_seq != expected_seq:
        raise RuntimeError("specialist task checkpoint does not match input")

    generator, opts = _generator_and_opts(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    # Re-deliver durable scientist steering/private sources at every safe task
    # boundary. _build_engine_opts marks the message queue consumed only after
    # materializing these values, so a worker restart cannot silently lose it.
    if opts.get("pending_steering"):
        state["pending_steering"] = True
    if opts.get("preferences"):
        state["preferences"] = opts["preferences"]
    if opts.get("context_enrichment_sources"):
        state["context_enrichment_sources"] = opts["context_enrichment_sources"]
    _merge_scientist_inputs(state, task.run_id, db_path)
    node_name = task.task_type.removeprefix(NODE_TASK_PREFIX)
    if node_name == "orchestrator":
        state["durable_task_queue"] = _durable_queue_snapshot(
            task.run_id, db_path
        )
    if run.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(
            task,
            state,
            task.task_type,
            expected_checkpoint_seq=current_seq,
            db_path=db_path,
        )
        return {
            "checkpoint_seq": checkpoint_seq,
            "node": node_name,
            "status": "paused",
        }
    if node_name == "review":
        return _enqueue_review_fanout(task, state, current_seq, db_path=db_path)
    if node_name == "generate":
        return await _enqueue_generation_fanout(
            task, state, current_seq, db_path=db_path
        )
    if node_name == "comprehensive_reflection":
        return _enqueue_mature_reflection_fanout(
            task, state, current_seq, db_path=db_path
        )
    if node_name == "deep_verification":
        return _enqueue_verification_fanout(
            task, state, current_seq, db_path=db_path
        )
    if node_name == "ranking":
        await _apply_pre_ranking_evidence_gate(state)
        scheduled = await _schedule_ranking_chain(
            task, state, current_seq, db_path=db_path
        )
        if scheduled is not None:
            return scheduled
    committed, successor = await execute_task_node(node_name, state)
    run = store.get_run(task.run_id, db_path=db_path)
    if run is None or run.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled during specialist execution")
    successor_type = _successor_task_type(successor)
    if run.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(
            task,
            committed,
            successor_type,
            expected_checkpoint_seq=current_seq,
            db_path=db_path,
        )
        return {
            "checkpoint_seq": checkpoint_seq,
            "node": node_name,
            "status": "paused",
        }
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
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "node": node_name,
    }


async def execute_finalize(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Drain the final checkpoint and publish through the shared report gate."""
    from co_scientist.checkpoint import restore_workflow_state

    run = _require_run(task, db_path)
    if run.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled before finalization")
    if (
        run.status == RunStatus.COMPLETED.value
        and store.get_latest_report(run.id, db_path=db_path) is not None
    ):
        return {"run_id": run.id, "status": "completed", "replayed": True}
    checkpoint, _ = _latest_task_checkpoint(task, db_path)
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    refreshed = store.get_run(run.id, db_path=db_path)
    if refreshed is not None and refreshed.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(
            task,
            state,
            FINALIZE_TASK,
            expected_checkpoint_seq=int(checkpoint["seq"]),
            db_path=db_path,
        )
        return {"checkpoint_seq": checkpoint_seq, "status": "paused"}
    final_state = _plain_final_state(state)
    # Final drain is deterministic and replayable. Clear only its prior rows
    # so a crash after persistence but before task acknowledgement cannot
    # duplicate hypotheses, evidence, matches, or verification edges.
    store.clear_publication_artifacts(run.id, db_path=db_path)
    drained = _persist_final_state(
        run_id=run.id, final_state=final_state, db_path=db_path
    )
    metrics = final_state.get("metrics") or {}
    execution_time = max(0.0, time.time() - float(state.get("start_time", 0)))
    store.save_run_metrics(run.id, metrics, db_path=db_path)
    store.update_run_status(run.id, RunStatus.SYNTHESIZING, db_path=db_path)
    emit = make_emitter(run.id, db_path=db_path)
    # The same post-drain stage events the streaming engine path emits, so
    # both engine execution modes carry identical per-stage fidelity.
    await emit("safety.hypothesis", drained.safety_counts)
    await emit("citation.grounding", drained.grounding_counts)
    await emit(
        "citation_audit", dict(drained.report_inputs["citation_summary"])
    )
    async for _ in finalize_report(
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode=normalize_run_tier(run.profile),
        provider="engine",
        emit=emit,
        execution_time=execution_time,
        db_path=db_path,
        **drained.report_inputs,
    ):
        pass
    final = store.get_run(run.id, db_path=db_path)
    return {"run_id": run.id, "status": final.status if final else "missing"}


async def execute_engine_task(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Dispatch one leased engine task without executing unrelated nodes."""
    if task.task_type == BOOTSTRAP_TASK:
        return await execute_bootstrap(task, db_path=db_path)
    if task.task_type == REVIEW_ITEM_TASK:
        return await execute_review_item(task, db_path=db_path)
    if task.task_type == REVIEW_AGGREGATE_TASK:
        return await execute_review_aggregate(task, db_path=db_path)
    if task.task_type == VERIFICATION_ITEM_TASK:
        return await execute_verification_item(task, db_path=db_path)
    if task.task_type == VERIFICATION_AGGREGATE_TASK:
        return await execute_verification_aggregate(task, db_path=db_path)
    if task.task_type == RANKING_MATCH_TASK:
        return await execute_ranking_match(task, db_path=db_path)
    if task.task_type == RANKING_FINALIZE_TASK:
        return await execute_ranking_finalize(task, db_path=db_path)
    if task.task_type == GENERATION_STRATEGY_TASK:
        return await execute_generation_strategy(task, db_path=db_path)
    if task.task_type == GENERATION_AGGREGATE_TASK:
        return await execute_generation_aggregate(task, db_path=db_path)
    if task.task_type == MATURE_REFLECTION_ITEM_TASK:
        return await execute_mature_reflection_item(task, db_path=db_path)
    if task.task_type == MATURE_REFLECTION_AGGREGATE_TASK:
        return await execute_mature_reflection_aggregate(task, db_path=db_path)
    if task.task_type.startswith(NODE_TASK_PREFIX):
        return await execute_node_task(task, db_path=db_path)
    if task.task_type == FINALIZE_TASK:
        return await execute_finalize(task, db_path=db_path)
    raise ValueError(f"unsupported engine task: {task.task_type}")

"""Durable node-level execution for the real scientific engine.

This module owns the run-level executors (bootstrap, node dispatch,
finalize) and the ``execute_engine_task`` dispatcher. The rest of the
durable vocabulary lives in sibling modules -- ``engine_tasks_support``
(task types, checkpoint plumbing, emitters), ``engine_tasks_inputs``
(bootstrap/continuation enqueueing, scientist-input merge),
``engine_tasks_gate`` (pre-ranking evidence gate), ``engine_tasks_fanout``
(review/verification/generation/reflection fan-out),
``engine_tasks_ranking`` (tournament chain), and ``engine_tasks_node``
(node/finalize commit helpers) -- and every moved name is re-exported
here so ``app.engine_tasks`` remains the stable import and monkeypatch
surface.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app import store
from app.engine_adapter.drain import (
    _persist_final_state as _persist_final_state,
)
from app.engine_adapter.provider import sync_engine_llm_backend
from app.engine_tasks_context import (
    ExactSuccessor as ExactSuccessor,
)
from app.engine_tasks_context import (
    TaskCommit as TaskCommit,
)
from app.engine_tasks_context import (
    _task_commit as _task_commit,
)
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
    _bootstrap_start_status as _bootstrap_start_status,
)
from app.engine_tasks_inputs import (
    _merge_scientist_inputs as _merge_scientist_inputs,
)
from app.engine_tasks_inputs import (
    _screen_bootstrap_intake as _screen_bootstrap_intake_impl,
)
from app.engine_tasks_inputs import (
    enqueue_bootstrap as enqueue_bootstrap,
)
from app.engine_tasks_inputs import (
    enqueue_scientist_continuation as enqueue_scientist_continuation,
)
from app.engine_tasks_node import (
    _SYNC_FANOUT_HANDLERS as _SYNC_FANOUT_HANDLERS,
)
from app.engine_tasks_node import (
    ADMISSION_NODE as ADMISSION_NODE,
)
from app.engine_tasks_node import (
    _check_node_task_checkpoint as _check_node_task_checkpoint,
)
from app.engine_tasks_node import (
    _commit_node_result as _commit_node_result,
)
from app.engine_tasks_node import (
    _dispatch_node_fanout as _dispatch_node_fanout,
)
from app.engine_tasks_node import (
    _drain_and_persist_final_state as _drain_and_persist_final_state,
)
from app.engine_tasks_node import (
    _emit_finalize_stage_events as _emit_finalize_stage_events,
)
from app.engine_tasks_node import (
    _finalize_replay_or_none as _finalize_replay_or_none,
)
from app.engine_tasks_node import (
    _halt_finalize_if_blocked as _halt_finalize_if_blocked,
)
from app.engine_tasks_node import (
    _pause_finalize_if_requested as _pause_finalize_if_requested,
)
from app.engine_tasks_node import (
    _pause_node_task_if_requested as _pause_node_task_if_requested,
)
from app.engine_tasks_node import (
    _require_active_run as _require_active_run,
)
from app.engine_tasks_node import (
    _restore_finalize_checkpoint as _restore_finalize_checkpoint,
)
from app.engine_tasks_node import (
    _restore_node_task_state as _restore_node_task_state,
)
from app.engine_tasks_node import (
    _settle_finalize_outcome as _settle_finalize_outcome,
)
from app.engine_tasks_node import (
    execute_finalize as execute_finalize,
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
from app.engine_tasks_restore import (
    _prepare_node_task as _prepare_node_task,
)
from app.engine_tasks_support import (
    _CHECKPOINT_PROVIDER as _CHECKPOINT_PROVIDER,
)
from app.engine_tasks_support import (
    BOOTSTRAP_TASK as BOOTSTRAP_TASK,
)
from app.engine_tasks_support import (
    ENGINE_TASK_PREFIX as ENGINE_TASK_PREFIX,
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
    NodeCompletion as NodeCompletion,
)
from app.engine_tasks_support import (
    SafetyHoldError as SafetyHoldError,
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
from app.execution_policy import scoped_execution_policy
from app.report_render import make_emitter
from app.run_modes import resolved_run_config
from app.safety import apply_safety_gate, screen_intake, screen_with_escalation
from app.store import RunStatus, ScientificTask


async def _screen_bootstrap_intake(
    run: store.RunRow,
    emit: Any,
    db_path: str | None,
    task: ScientificTask | None = None,
) -> dict[str, Any] | None:
    return await _screen_bootstrap_intake_impl(
        run,
        emit,
        db_path,
        task=task,
        screening=(screen_with_escalation, screen_intake, apply_safety_gate),
    )


async def _prepare_bootstrap_state(
    task: ScientificTask, run: store.RunRow, db_path: str | None
) -> tuple[dict[str, Any], TaskCommit]:
    """Build initial state and commit target, aborting if cancelled.

    Pause-versus-successor is decided by the caller's commit transaction.
    Bootstrap never consumes steering (``consume_steering=False``): any
    steering queued before the run even started is folded into the initial
    preferences text same as always, but stays pending until the run's first
    orchestrator cycle -- the one place ``pending_steering`` is actually read
    for scheduling -- rather than being acknowledged here where nothing acts
    on it.
    """
    generator, opts = _generator_and_opts(task, db_path)
    state = await generator.prepare_task_state(
        run.research_goal,
        opts=opts,
        run_id=run.id,
    )
    commit = _task_commit(task, 0, db_path, opts, consume_steering=False)
    refreshed = store.get_run(run.id, db_path=db_path)
    if refreshed is None or refreshed.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled during bootstrap")
    # A PAUSED snapshot is advisory only. /resume can change it to QUEUED
    # before the commit transaction, which must choose pause vs successor.
    return state, commit


async def execute_bootstrap(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Safety-gate a run, prepare state, and enqueue its first task."""
    run = _require_run(task, db_path)
    emit = make_emitter(run.id, db_path=db_path)
    withheld = await _screen_bootstrap_intake(run, emit, db_path, task=task)
    if withheld is not None:
        return withheld
    run = _require_run(task, db_path)  # the gate may have redacted the goal
    bootstrap_status = _bootstrap_start_status(task, run, db_path)
    if bootstrap_status in {status.value for status in store.TERMINAL_STATUSES}:
        return {"run_id": run.id, "status": bootstrap_status, "terminal": True}
    # Sync the run row before the generator is built (_generator_and_opts
    # reads it back via run_used_offline), so a config-pinned llm_backend
    # takes effect on this boundary.
    sync_engine_llm_backend(run.id, resolved_run_config(run.config), db_path)
    state, commit = await _prepare_bootstrap_state(task, run, db_path)
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        commit, state, "supervisor", pause_if_requested=True
    )
    if successor_id is None:
        return {"checkpoint_seq": checkpoint_seq, "status": "paused"}
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
    from co_scientist.task_runtime import execute_task_node

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    run = _require_active_run(task, db_path, stage="before specialist run")
    replay = _check_node_task_checkpoint(task, checkpoint, current_seq)
    if replay is not None:
        return replay

    state, commit, node_name = _prepare_node_task(
        task, checkpoint, current_seq, db_path
    )
    paused = _pause_node_task_if_requested(commit, run, node_name, state)
    if paused is not None:
        return paused
    fanout = await _dispatch_node_fanout(
        task, state, node_name, current_seq, db_path=db_path
    )
    if fanout is not None:
        return fanout

    committed, successor = await execute_task_node(node_name, state)
    run = _require_active_run(task, db_path, stage="during specialist run")
    return await _commit_node_result(
        commit, run, node_name, committed, successor
    )


# Non-node task types, by exact match (node/unrecognized: see below).
_ENGINE_TASK_DISPATCH: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    BOOTSTRAP_TASK: execute_bootstrap,
    REVIEW_ITEM_TASK: execute_review_item,
    REVIEW_AGGREGATE_TASK: execute_review_aggregate,
    VERIFICATION_ITEM_TASK: execute_verification_item,
    VERIFICATION_AGGREGATE_TASK: execute_verification_aggregate,
    RANKING_MATCH_TASK: execute_ranking_match,
    RANKING_FINALIZE_TASK: execute_ranking_finalize,
    GENERATION_STRATEGY_TASK: execute_generation_strategy,
    GENERATION_AGGREGATE_TASK: execute_generation_aggregate,
    MATURE_REFLECTION_ITEM_TASK: execute_mature_reflection_item,
    MATURE_REFLECTION_AGGREGATE_TASK: execute_mature_reflection_aggregate,
    FINALIZE_TASK: execute_finalize,
}


async def _dispatch_engine_task(
    task: ScientificTask, *, db_path: str | None
) -> dict[str, Any]:
    """Route one engine task to its handler by task type."""
    handler = _ENGINE_TASK_DISPATCH.get(task.task_type)
    if handler is not None:
        return await handler(task, db_path=db_path)
    if task.task_type.startswith(NODE_TASK_PREFIX):
        return await execute_node_task(task, db_path=db_path)
    raise ValueError(f"unsupported engine task: {task.task_type}")


def _llm_call_ceiling_for_run(run_id: str, db_path: str | None) -> int | None:
    """The run's configured ``max_llm_calls``, or None if unresolvable.

    Read fresh per task rather than cached here: ``scoped_llm_call_budget``
    itself only honors the *first* value it sees for a run id, so a later
    task's read is cheap insurance (an indexed primary-key lookup, the
    same cost as the credential lookup beside it) rather than a source of
    drift. A run row that has vanished or carries no resolvable tier
    scopes to no ceiling -- counted, never enforced -- rather than
    failing the task over a missing backstop.
    """
    run = store.get_run(run_id, db_path=db_path)
    if run is None:
        return None
    ceiling = resolved_run_config(run.config).get("max_llm_calls")
    return int(ceiling) if isinstance(ceiling, int) else None


async def execute_engine_task(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Dispatch one leased engine task without executing unrelated nodes.

    A bring-your-own-key run's credential is scoped around the whole task
    -- into the app context (the app's own LLM calls) and the engine
    context (every agent completion) -- so it overrides the deployment
    credential for this task only, without touching any shared state.

    The run's LLM-call ceiling is scoped the same way, into the engine's
    ``llm_call_budget`` context: every completion this task makes,
    however many retries or tool-loop turns deep, is counted against the
    run without any of that machinery needing to know the run id.
    """
    from co_scientist.llm_call_budget import scoped_llm_call_budget
    from co_scientist.llm_credentials import scoped_api_key

    from app.credentials import get_run_credential, scoped_byok

    run = store.get_run(task.run_id, db_path=db_path)
    if run is None:
        raise LookupError(f"run not found for task dispatch: {task.run_id}")
    credential = get_run_credential(task.run_id, db_path=db_path)
    ceiling = _llm_call_ceiling_for_run(task.run_id, db_path)
    with (
        scoped_byok(credential),
        scoped_api_key(credential.api_key if credential else None),
        scoped_llm_call_budget(task.run_id, ceiling),
        scoped_execution_policy(run.execution_policy),
    ):
        return await _dispatch_engine_task(task, db_path=db_path)

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
    _merge_scientist_inputs as _merge_scientist_inputs,
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
from app.report_render import make_emitter
from app.run_modes import resolved_run_config
from app.safety import (
    ScreenSubject,
    apply_safety_gate,
    screen_intake,
    screen_with_escalation,
)
from app.store import RunStatus, ScientificTask


async def _screen_bootstrap_intake(
    run: store.RunRow,
    emit: Any,
    db_path: str | None,
) -> dict[str, Any] | None:
    """Screen a run's research goal at the durable bootstrap boundary.

    Via screen_with_escalation, not screen_contextual directly: the
    escalation wrapper carries the two guards this boundary must honor --
    an offline-backed run never pays for a real contextual model call, and
    a stage a human already approved is not re-screened (which would
    otherwise let a fresh contextual verdict re-hold an approved run on
    every resume).

    Returns a withheld result if the goal was blocked, else ``None`` to
    let the caller proceed.

    Raises:
        SafetyHoldError: If the goal was held for human adjudication. A
            block is terminal, so the task is genuinely done; a hold is a
            wait, and must leave this bootstrap claimable again for when a
            reviewer approves it.
    """
    decision = await screen_with_escalation(
        run.id,
        ScreenSubject(
            "intake", run.research_goal, screen_intake(run.research_goal)
        ),
        provider=run.provider,
        db_path=db_path,
    )
    async for _ in apply_safety_gate(run.id, decision, emit, db_path=db_path):
        pass
    if decision.decision == "hold":
        raise SafetyHoldError(f"intake held for review: {decision.reason}")
    if decision.decision == "block":
        return {"run_id": run.id, "status": "withheld", "terminal": True}
    return None


async def _prepare_bootstrap_state(
    task: ScientificTask, run: store.RunRow, db_path: str | None
) -> tuple[dict[str, Any], TaskCommit, dict[str, Any] | None]:
    """Build initial workflow state, honoring a cancel/pause during prep.

    Returns the prepared state, the commit target carrying whatever
    steering this state folded in, and -- if the run was paused meanwhile
    -- the checkpointed-pause result the caller must return instead of
    continuing.
    """
    generator, opts = _generator_and_opts(task, db_path)
    state = await generator.prepare_task_state(
        run.research_goal,
        opts=opts,
        run_id=run.id,
    )
    commit = _task_commit(task, 0, db_path, opts)
    refreshed = store.get_run(run.id, db_path=db_path)
    if refreshed is None or refreshed.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled during bootstrap")
    if refreshed.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(
            commit, state, f"{NODE_TASK_PREFIX}supervisor"
        )
        paused = {"checkpoint_seq": checkpoint_seq, "status": "paused"}
        return state, commit, paused
    return state, commit, None


async def execute_bootstrap(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Safety-gate a run, prepare state, and enqueue its first task."""
    run = _require_run(task, db_path)
    emit = make_emitter(run.id, db_path=db_path)
    withheld = await _screen_bootstrap_intake(run, emit, db_path)
    if withheld is not None:
        return withheld
    run = _require_run(task, db_path)  # the gate may have redacted the goal

    store.update_run_status(run.id, RunStatus.RUNNING, db_path=db_path)
    # Sync the run row before the generator is built (_generator_and_opts
    # reads it back via run_used_offline), so a config-pinned llm_backend
    # takes effect on this boundary.
    sync_engine_llm_backend(run.id, resolved_run_config(run.config), db_path)
    state, commit, paused = await _prepare_bootstrap_state(task, run, db_path)
    if paused is not None:
        return paused
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        commit, state, "supervisor"
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
    from co_scientist.task_runtime import execute_task_node

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    run = _require_active_run(task, db_path, stage="before specialist run")
    replay = _check_node_task_checkpoint(task, checkpoint, current_seq)
    if replay is not None:
        return replay

    generator, opts = _generator_and_opts(task, db_path)
    state = _restore_node_task_state(task, checkpoint, generator, opts, db_path)
    node_name = task.task_type.removeprefix(NODE_TASK_PREFIX)
    if node_name == "orchestrator":
        state["durable_task_queue"] = _durable_queue_snapshot(
            task.run_id, db_path
        )
    commit = _task_commit(task, current_seq, db_path, opts)
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


async def execute_engine_task(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Dispatch one leased engine task without executing unrelated nodes.

    A bring-your-own-key run's credential is scoped around the whole task
    -- into the app context (the app's own LLM calls) and the engine
    context (every agent completion) -- so it overrides the deployment
    credential for this task only, without touching any shared state.
    """
    from co_scientist.llm_credentials import scoped_api_key

    from app.credentials import get_run_credential, scoped_byok

    credential = get_run_credential(task.run_id, db_path=db_path)
    with (
        scoped_byok(credential),
        scoped_api_key(credential.api_key if credential else None),
    ):
        return await _dispatch_engine_task(task, db_path=db_path)

"""Commit and restore helpers for the durable node/finalize executors.

The checkpoint-guard, state-restore, pause, fan-out dispatch, and
final-drain helpers that ``execute_node_task`` and ``execute_finalize``
in ``app.engine_tasks`` compose. Split from ``app.engine_tasks``, which
re-exports every name here so it remains the stable import and
monkeypatch surface.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app import store
from app.engine_adapter.drain import _persist_final_state
from app.engine_tasks_context import TaskCommit
from app.engine_tasks_fanout import (
    _enqueue_generation_fanout,
    _enqueue_mature_reflection_fanout,
    _enqueue_review_fanout,
    _enqueue_verification_fanout,
)
from app.engine_tasks_gate import _apply_pre_ranking_evidence_gate
from app.engine_tasks_inputs import _merge_scientist_inputs
from app.engine_tasks_ranking import _schedule_ranking_chain
from app.engine_tasks_support import (
    FINALIZE_TASK,
    NodeCompletion,
    SupersededTaskError,
    _emit_node_completion,
    _plain_final_state,
    _save_paused_state,
    _save_state_and_enqueue,
    _successor_task_type,
)
from app.store import RunStatus, ScientificTask


def _check_node_task_checkpoint(
    task: ScientificTask, checkpoint: dict[str, Any], current_seq: int
) -> dict[str, Any] | None:
    """Return a replay result if this task already advanced the checkpoint.

    Raises when a different task advanced it, or when the leased checkpoint
    does not match what this task was scheduled against.
    """
    expected_seq = int(task.inputs.get("checkpoint_seq", -1))
    # Redelivery after the checkpoint commit but before task completion is an
    # acknowledgement replay, never a second scientific effect.
    if current_seq > expected_seq:
        if checkpoint["stage"] == f"engine_task:{task.id}":
            return {"checkpoint_seq": current_seq, "replayed": True}
        raise SupersededTaskError("specialist task checkpoint was superseded")
    if current_seq != expected_seq:
        raise RuntimeError("specialist task checkpoint does not match input")
    return None


def _restore_node_task_state(
    task: ScientificTask,
    checkpoint: dict[str, Any],
    generator: Any,
    opts: dict[str, Any],
    db_path: str | None,
) -> dict[str, Any]:
    """Restore workflow state and re-apply durable per-boundary overlays.

    Re-delivers durable scientist steering/private sources at every safe
    task boundary: ``_build_engine_opts`` marks the message queue consumed
    only after materializing these values, so a worker restart cannot
    silently lose it.
    """
    from co_scientist.checkpoint import restore_workflow_state

    state: dict[str, Any] = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    if opts.get("pending_steering"):
        state["pending_steering"] = True
    if opts.get("preferences"):
        state["preferences"] = opts["preferences"]
    if opts.get("context_enrichment_sources"):
        state["context_enrichment_sources"] = opts["context_enrichment_sources"]
    _merge_scientist_inputs(state, task.run_id, db_path)
    return state


def _pause_node_task_if_requested(
    commit: TaskCommit,
    run: store.RunRow,
    node_name: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """Checkpoint and pause a node task the operator paused mid-flight.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        run: The task's run row, read for a mid-flight pause.
        node_name: Engine node the paused task was about to run.
        state: Workflow state to checkpoint at the pause point.

    Returns:
        The pause result to return, or ``None`` if the run is not paused.
    """
    if run.status != RunStatus.PAUSED.value:
        return None
    checkpoint_seq = _save_paused_state(
        commit.task,
        state,
        commit.task.task_type,
        expected_checkpoint_seq=commit.current_seq,
        db_path=commit.db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "node": node_name,
        "status": "paused",
    }


# Node types with a synchronous fan-out enqueue helper (see below).
_SYNC_FANOUT_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "review": _enqueue_review_fanout,
    "comprehensive_reflection": _enqueue_mature_reflection_fanout,
    "deep_verification": _enqueue_verification_fanout,
}


async def _dispatch_node_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    node_name: str,
    current_seq: int,
    db_path: str | None,
) -> dict[str, Any] | None:
    """Fan a specialist node out into durable per-item tasks, if it fans out.

    Returns the fan-out scheduling result for node types that do, else
    ``None`` so the caller executes the node inline as usual (also the
    outcome for ``ranking`` when too few hypotheses remain to schedule a
    tournament -- it still runs the gate, but falls through to inline
    execution rather than fanning out).
    """
    if node_name == "generate":
        return await _enqueue_generation_fanout(
            task, state, current_seq, db_path=db_path
        )
    if node_name == "ranking":
        await _apply_pre_ranking_evidence_gate(state)
        return await _schedule_ranking_chain(
            task, state, current_seq, db_path=db_path
        )
    handler = _SYNC_FANOUT_HANDLERS.get(node_name)
    if handler is None:
        return None
    return handler(task, state, current_seq, db_path=db_path)


async def _commit_node_result(
    commit: TaskCommit,
    run: store.RunRow,
    node_name: str,
    committed: dict[str, Any],
    successor: str | None,
) -> dict[str, Any]:
    """Commit a specialist node's result, honoring a pause requested mid-run.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        run: The task's run row, re-read after the node ran.
        node_name: Engine node whose result is being committed.
        committed: Workflow state the node produced.
        successor: Node to schedule next, or ``None`` to finalize.

    Returns:
        The task result: the committed checkpoint plus successor or pause.
    """
    task, db_path = commit.task, commit.db_path
    successor_type = _successor_task_type(successor)
    if run.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(
            task,
            committed,
            successor_type,
            expected_checkpoint_seq=commit.current_seq,
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
        expected_checkpoint_seq=commit.current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id,
        NodeCompletion(node_name, successor, checkpoint_seq),
        committed,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "node": node_name,
    }


def _require_active_run(
    task: ScientificTask, db_path: str | None, *, stage: str
) -> store.RunRow:
    """Return the task's run, or raise if deleted/cancelled (shared guard)."""
    run = store.get_run(task.run_id, db_path=db_path)
    if run is None or run.status == RunStatus.CANCELLED.value:
        raise RuntimeError(f"run cancelled {stage}")
    return run


def _pause_finalize_if_requested(
    task: ScientificTask,
    run: store.RunRow,
    checkpoint: dict[str, Any],
    state: dict[str, Any],
    db_path: str | None,
) -> dict[str, Any] | None:
    """Checkpoint and pause finalization if the operator paused mid-flight."""
    refreshed = store.get_run(run.id, db_path=db_path)
    if refreshed is None or refreshed.status != RunStatus.PAUSED.value:
        return None
    checkpoint_seq = _save_paused_state(
        task,
        state,
        FINALIZE_TASK,
        expected_checkpoint_seq=int(checkpoint["seq"]),
        db_path=db_path,
    )
    return {"checkpoint_seq": checkpoint_seq, "status": "paused"}


def _drain_and_persist_final_state(
    run: store.RunRow,
    state: dict[str, Any],
    db_path: str | None,
) -> tuple[Any, float]:
    """Persist the drained final state and mark the run synthesizing.

    Final drain is deterministic and replayable. Clears only this run's
    prior publication rows so a crash after persistence but before task
    acknowledgement cannot duplicate hypotheses, evidence, matches, or
    verification edges.
    """
    final_state = _plain_final_state(state)
    store.clear_publication_artifacts(run.id, db_path=db_path)
    drained = _persist_final_state(
        run_id=run.id, final_state=final_state, db_path=db_path
    )
    metrics = final_state.get("metrics") or {}
    execution_time = max(0.0, time.time() - float(state.get("start_time", 0)))
    store.save_run_metrics(run.id, metrics, db_path=db_path)
    store.update_run_status(run.id, RunStatus.SYNTHESIZING, db_path=db_path)
    return drained, execution_time


async def _emit_finalize_stage_events(emit: Any, drained: Any) -> None:
    """Emit the same post-drain stage events the streaming path emits.

    Keeps both engine execution modes carrying identical per-stage fidelity.
    """
    await emit("safety.hypothesis", drained.safety_counts)
    await emit("citation.grounding", drained.grounding_counts)
    await emit(
        "citation_audit", dict(drained.report_inputs["citation_summary"])
    )

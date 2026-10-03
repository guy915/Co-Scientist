"""Execute one specialist node, restoring and committing its durable state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app import store
from app.engine_tasks import runtime as engine_tasks_runtime
from app.engine_tasks.fanout import (
    _enqueue_generation_fanout,
    _enqueue_mature_reflection_fanout,
    _enqueue_review_fanout,
    _enqueue_verification_fanout,
)
from app.engine_tasks.gate import _apply_pre_ranking_evidence_gate
from app.engine_tasks.inputs import _merge_scientist_inputs
from app.engine_tasks.portfolio import _durable_queue_snapshot
from app.engine_tasks.ranking import _schedule_ranking_chain
from app.engine_tasks.support import (
    NODE_TASK_PREFIX,
    NodeCompletion,
    SupersededTaskError,
    TaskCommit,
    _emit_node_completion,
    _latest_task_checkpoint,
    _pause_node_task_if_requested,
    _save_paused_state,
    _save_state_and_enqueue,
    _successor_task_type,
    _task_commit,
)
from app.store import RunStatus, ScientificTask

ADMISSION_NODE = "orchestrator"
_SYNC_FANOUT_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "review": _enqueue_review_fanout,
    "comprehensive_reflection": _enqueue_mature_reflection_fanout,
    "deep_verification": _enqueue_verification_fanout,
}


def _check_node_task_checkpoint(
    task: ScientificTask, checkpoint: dict[str, Any], current_seq: int
) -> dict[str, Any] | None:
    """Return replay when committed; reject work behind another checkpoint.

    Portfolio rows validate against their named predecessor because a
    lookahead row cannot know its checkpoint sequence at enqueue time.
    """
    if checkpoint["stage"] == f"engine_task:{task.id}":
        return {"checkpoint_seq": current_seq, "replayed": True}
    if task.dependencies:
        _check_portfolio_predecessor(task, checkpoint)
        return None
    expected_seq = int(task.inputs.get("checkpoint_seq", -1))
    if current_seq > expected_seq:
        raise SupersededTaskError("specialist task checkpoint was superseded")
    if current_seq != expected_seq:
        raise RuntimeError("specialist task checkpoint does not match input")
    return None


def _check_portfolio_predecessor(
    task: ScientificTask, checkpoint: dict[str, Any]
) -> None:
    """Confirm the predecessor committed this task as its successor."""
    predecessor_id = task.dependencies[0]
    resume_successor = checkpoint.get("state", {}).get("resume_successor")
    stage = checkpoint["stage"]
    predecessor_stages = {
        f"engine_task:{predecessor_id}",
        f"engine_task_paused:{predecessor_id}",
    }
    if stage in predecessor_stages and resume_successor == task.task_type:
        return
    raise SupersededTaskError("portfolio task checkpoint was superseded")


def _restore_node_task_state(
    task: ScientificTask,
    checkpoint: dict[str, Any],
    generator: Any,
    opts: dict[str, Any],
    db_path: str | None,
) -> dict[str, Any]:
    """Restore workflow state and re-apply durable per-boundary overlays.

    Re-delivers durable scientist steering/private sources at every safe
    task boundary. ``build_engine_opts`` only *reads* the message queue;
    the ids it read ride the commit target and are retired inside the
    transaction that commits this state's successor checkpoint, so a worker
    lost mid-node leaves the steer claimable rather than acknowledged.

    ``pending_steering`` is set on ``state`` only at the orchestrator: it
    is the sole node whose scheduling stats read that flag
    (``orchestrator_stats._build_scheduler_stats``), so setting it on
    every other node's restored state would do nothing but pretend a
    later commit consumed something it never acted on -- the actual
    consumption gate lives beside this one, in ``_task_commit``.

    ``durable_retries_remain`` is the other overlay, and it is what lets a
    node whose synthesis is optional tell a recoverable failure from a
    final one (``co_scientist.agents.node_degradation``): a provider error
    with a retry behind it propagates so the worker re-runs the node,
    while the same error on the last attempt degrades the node rather than
    failing the task -- which, at the terminal node, settles the run and
    loses the report. The formula mirrors
    ``app.task_worker.outcomes._is_terminal_failure``, which mirrors
    ``app.store.tasks_lifecycle._persist_failed_attempt``'s own
    retry-left test; it assumes the failure is retryable, which holds
    because the two failures the worker refuses to retry
    (``TASK_CONTROL_FLOW_ERRORS``) never reach the degrade decision.
    """
    from app.engine_adapter import restore_workflow_state

    state: dict[str, Any] = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    at_admission_node = (
        task.task_type.removeprefix(NODE_TASK_PREFIX) == ADMISSION_NODE
    )
    if opts.get("pending_steering") and at_admission_node:
        state["pending_steering"] = True
    if opts.get("preferences"):
        state["preferences"] = opts["preferences"]
    if opts.get("context_enrichment_sources"):
        state["context_enrichment_sources"] = opts["context_enrichment_sources"]
    state["durable_retries_remain"] = task.attempt < task.max_attempts
    _merge_scientist_inputs(
        state,
        task.run_id,
        db_path,
        admit_hypotheses=at_admission_node,
    )
    return state


def _prepare_node_task(
    task: ScientificTask,
    checkpoint: dict[str, Any],
    current_seq: int,
    db_path: str | None,
) -> tuple[dict[str, Any], TaskCommit, str]:
    """Restore this node's state and build its commit target.

    Only the orchestrator's own commit may acknowledge steering: it is
    the run's one scheduling decision point (see ``_task_commit``).
    """
    generator, opts = engine_tasks_runtime.active().generator_and_opts(
        task, db_path
    )
    state = _restore_node_task_state(task, checkpoint, generator, opts, db_path)
    node_name = task.task_type.removeprefix(NODE_TASK_PREFIX)
    if node_name == "orchestrator":
        state["durable_task_queue"] = _durable_queue_snapshot(
            task.run_id, db_path
        )
    commit = _task_commit(
        task,
        current_seq,
        db_path,
        opts,
        consume_steering=(node_name == ADMISSION_NODE),
    )
    return state, commit, node_name


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
    if node_name == "ranking" and successor == "orchestrator":
        from app.engine_tasks.ranking import _consume_outcome_refinement_gate

        if _consume_outcome_refinement_gate(
            task.run_id, committed, db_path=db_path
        ):
            successor = None
    successor_type = _successor_task_type(successor)
    if run.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(commit, committed, successor_type)
        successor_id = None
    else:
        checkpoint_seq, successor_id = _save_state_and_enqueue(
            commit, committed, successor, pause_if_requested=True
        )
    await _emit_node_completion(
        task.run_id,
        NodeCompletion(node_name, successor, checkpoint_seq),
        committed,
        db_path,
    )
    if successor_id is None:
        return {
            "checkpoint_seq": checkpoint_seq,
            "node": node_name,
            "status": "paused",
        }
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

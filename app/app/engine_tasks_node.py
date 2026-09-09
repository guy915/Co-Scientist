"""The durable finalize executor and the node/finalize commit helpers.

The checkpoint-guard, state-restore, pause, fan-out dispatch, and
final-drain helpers that ``execute_node_task`` in ``app.engine_tasks``
composes, plus ``execute_finalize`` itself, which is here because every
helper it composes already is. Split from ``app.engine_tasks``, which
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
from app.engine_tasks_inputs import (
    reopen_for_pending_scientist_input as reopen_for_pending_scientist_input,
)
from app.engine_tasks_ranking import _schedule_ranking_chain
from app.engine_tasks_restore import (
    ADMISSION_NODE as ADMISSION_NODE,
)
from app.engine_tasks_restore import (
    _restore_node_task_state as _restore_node_task_state,
)
from app.engine_tasks_support import (
    FINALIZE_TASK,
    NodeCompletion,
    SafetyHoldError,
    SupersededTaskError,
    _emit_node_completion,
    _generator_for_restore,
    _latest_task_checkpoint,
    _metrics_snapshot,
    _plain_final_state,
    _require_run,
    _save_paused_state,
    _save_state_and_enqueue,
    _successor_task_type,
)
from app.report_render import ReportRequest, finalize_report, make_emitter
from app.run_modes import normalize_run_tier
from app.safety import SafetyDecision, apply_safety_gate
from app.store import RunStatus, ScientificTask


def _check_node_task_checkpoint(
    task: ScientificTask, checkpoint: dict[str, Any], current_seq: int
) -> dict[str, Any] | None:
    """Return a replay result if this task already advanced the checkpoint.

    Raises when a different task advanced it, or when the leased checkpoint
    does not match what this task was scheduled against.

    A task enqueued with a ``dependencies`` entry (every portfolio row --
    finding F4 -- both the immediate successor and any lookahead hop
    chained behind it) validates against its named predecessor instead of
    a pre-recorded checkpoint sequence: that sequence cannot be known for
    a lookahead row planned before its predecessor has run. A task with no
    dependencies (bootstrap, resume, scientist-directed continuation) is
    unaffected and keeps the original sequence check.
    """
    # Redelivery after the checkpoint commit but before task completion is an
    # acknowledgement replay, never a second scientific effect -- true
    # regardless of which validation branch below applies.
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
    """Confirm a portfolio row's named predecessor produced this checkpoint.

    Verifies not just that the predecessor committed, but that its own
    recorded successor names this exact task -- a plan can still turn out
    wrong (most often a mid-run safety halt, finding J6, that routes the
    predecessor to finalize instead of the node this row was planned as).
    Checking only the predecessor's identity would let that stale row run
    anyway, since the predecessor genuinely did commit; the recorded
    successor is what ``app.engine_tasks_portfolio`` also compares to
    decide whether a queued row is a reuse target or a stale plan to
    cancel, so a row that slips past that cancellation still cannot run
    here -- it settles as superseded instead, the durable worker's benign
    idempotent outcome for an obsolete branch.

    A checkpoint saved mid-pause (``engine_task_paused:{id}``, from
    ``_save_paused_state``) names its predecessor the same way a normal
    commit does; a portfolio row anchored to it by a resumed run's
    ``_enqueue_resume_task`` (``app.task_worker_enqueue``) validates
    identically either way.

    Raises:
        SupersededTaskError: If the predecessor's real successor was not
            this task.
    """
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
    checkpoint_seq = _save_paused_state(commit, state, commit.task.task_type)
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
        checkpoint_seq = _save_paused_state(commit, committed, successor_type)
        return {
            "checkpoint_seq": checkpoint_seq,
            "node": node_name,
            "status": "paused",
        }
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        commit, committed, successor
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
    # Finalization reads no steering, so this commit acknowledges none.
    checkpoint_seq = _save_paused_state(
        TaskCommit(task, int(checkpoint["seq"]), db_path),
        state,
        FINALIZE_TASK,
    )
    return {"checkpoint_seq": checkpoint_seq, "status": "paused"}


def _settle_finalize_outcome(
    run_id: str, db_path: str | None
) -> dict[str, Any]:
    """Report how finalization ended, parking the task if it was withheld.

    The final gate holds by pausing the run and publishing nothing, so a
    paused run with no report means finalization is waiting on a person
    rather than finished. Letting this task succeed there is what left an
    approved final hold with nothing to claim; raising parks it instead,
    ready for ``resume_run_tasks`` to release. An operator pause landing
    during finalization reaches the same state and wants the same thing.

    Raises:
        SafetyHoldError: If the run was withheld rather than published.
    """
    run = store.get_run(run_id, db_path=db_path)
    status = run.status if run else "missing"
    if (
        status == RunStatus.PAUSED.value
        and store.get_latest_report(run_id, db_path=db_path) is None
    ):
        raise SafetyHoldError("report finalization held for review")
    return {"run_id": run_id, "status": status}


def _monitor_halt_decision(state: dict[str, Any]) -> SafetyDecision:
    """Rebuild the monitor's verdict as an app-side safety decision.

    The engine records the halt in the workflow state's audit trail; this
    carries that record -- its rationale and the policy text it matched --
    onto the run's own safety decisions, so a blocked run explains itself
    through the same surface as an intake or final-gate block. A halt
    whose record did not survive the checkpoint still blocks, on the
    generic reason: the flag is the decision, the record only its detail.
    """
    from co_scientist.agents.safety.safety_monitor import MONITOR_STAGE

    records = [
        item
        for item in (state.get("safety_decisions") or [])
        if isinstance(item, dict) and item.get("stage") == MONITOR_STAGE
    ]
    record: dict[str, Any] = records[-1] if records else {}
    return SafetyDecision(
        stage=MONITOR_STAGE,
        decision="block",
        reason=str(
            record.get("reason")
            or "The research direction reached prohibited content mid-run."
        ),
        matches=[str(match) for match in (record.get("matches") or [])],
        category=str(record.get("outcome") or "prohibited"),
        assessor="engine:safety_monitor",
    )


async def _halt_finalize_if_blocked(
    run: store.RunRow, state: dict[str, Any], db_path: str | None
) -> dict[str, Any] | None:
    """Block a run the engine's safety monitor halted, instead of publishing.

    The monitor halts mid-run (finding J6), and the durable runtime routes
    straight here rather than scheduling more science. Nothing is drained
    and no report is built: the run stopped because its direction was
    unpublishable, so producing the document anyway only to withhold it at
    the final gate would spend the synthesis and leave the reason implicit.

    Returns:
        The finalize result for a halted run, or ``None`` to publish as
        usual.
    """
    if not state.get("safety_blocked"):
        return None
    decision = _monitor_halt_decision(state)
    emit = make_emitter(run.id, db_path=db_path)
    async for _ in apply_safety_gate(run.id, decision, emit, db_path=db_path):
        pass
    return {"run_id": run.id, "status": RunStatus.BLOCKED.value}


async def _drain_and_persist_final_state(
    run: store.RunRow,
    state: dict[str, Any],
    db_path: str | None,
) -> tuple[Any, float]:
    """Persist the drained final state and mark the run synthesizing.

    Final drain is deterministic and replayable. Clears only this run's
    prior publication rows so a crash after persistence but before task
    acknowledgement cannot duplicate hypotheses, evidence, matches, or
    verification edges. Awaited: its provider waves run off the caller's
    event loop (see ``drain._persist_final_state``).
    """
    final_state = _plain_final_state(state)
    store.clear_publication_artifacts(run.id, db_path=db_path)
    drained = await _persist_final_state(
        run_id=run.id, final_state=final_state, db_path=db_path
    )
    # _metrics_snapshot also folds in the Supervisor's performance_assessment
    # (finding F5); reused here (not just at each node commit, finding L14)
    # so the run's final metrics row does not silently drop it on finalize.
    metrics = _metrics_snapshot(final_state)
    execution_time = max(0.0, time.time() - float(state.get("start_time", 0)))
    store.save_run_metrics(run.id, metrics, db_path=db_path)
    store.update_run_status(run.id, RunStatus.SYNTHESIZING, db_path=db_path)
    return drained, execution_time


async def _emit_finalize_stage_events(emit: Any, drained: Any) -> None:
    """Emit the post-drain safety, grounding, and citation-audit stages."""
    await emit("safety.hypothesis", drained.safety_counts)
    await emit("citation.grounding", drained.grounding_counts)
    await emit(
        "citation_audit", dict(drained.report_inputs["citation_summary"])
    )


def _restore_finalize_checkpoint(
    task: ScientificTask, db_path: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Restore the workflow state the run's last committed checkpoint holds."""
    from co_scientist.checkpoint import restore_workflow_state

    checkpoint, _ = _latest_task_checkpoint(task, db_path)
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    return checkpoint, state


def _finalize_replay_or_none(
    run: store.RunRow, *, db_path: str | None
) -> dict[str, Any] | None:
    """Return the replayed outcome when finalization already published.

    Args:
        run: The run whose finalization is being attempted.
        db_path: Optional database override.

    Returns:
        The replayed completion result, or ``None`` to finalize now.

    Raises:
        RuntimeError: If the run was cancelled before finalization.
    """
    if run.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled before finalization")
    already_published = (
        run.status == RunStatus.COMPLETED.value
        and store.get_latest_report(run.id, db_path=db_path) is not None
    )
    if already_published:
        return {"run_id": run.id, "status": "completed", "replayed": True}
    return None


async def execute_finalize(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Drain the final checkpoint and publish through the shared report gate."""
    run = _require_run(task, db_path)
    replayed = _finalize_replay_or_none(run, db_path=db_path)
    if replayed is not None:
        return replayed
    checkpoint, state = _restore_finalize_checkpoint(task, db_path)
    paused = _pause_finalize_if_requested(task, run, checkpoint, state, db_path)
    if paused is not None:
        return paused
    halted = await _halt_finalize_if_blocked(run, state, db_path)
    if halted is not None:
        return halted
    drained, execution_time = await _drain_and_persist_final_state(
        run, state, db_path
    )
    emit = make_emitter(run.id, db_path=db_path)
    await _emit_finalize_stage_events(emit, drained)
    setup = run.config.get("setup") if isinstance(run.config, dict) else None
    async for _ in finalize_report(
        run.id,
        ReportRequest(
            research_goal=run.research_goal,
            run_mode=normalize_run_tier(run.profile),
            provider="engine",
            execution_time=execution_time,
            setup=setup if isinstance(setup, dict) else None,
            prepared_at=time.time(),
            db_path=db_path,
            **drained.report_inputs,
        ),
        emit,
    ):
        pass
    # A contribution posted after the last orchestrator boundary (the
    # report was still draining/publishing) has no continuation task
    # waiting for it -- reopen right here instead of stranding it on
    # whatever scientist input happens to arrive next. No-ops when the
    # run did not land completed (blocked/held/paused above) or nothing
    # is pending.
    reopen_for_pending_scientist_input(run.id, db_path=db_path)
    return _settle_and_release(run.id, db_path)


def _settle_and_release(run_id: str, db_path: str | None) -> dict[str, Any]:
    """Settle the finalized run and drop its LLM-call counter.

    The run is done, so the counter is released here rather than left to
    the tracking cap's eviction -- that exists for runs which never reach
    a terminal state through this path at all (cancelled, or failed with
    their retry budget spent elsewhere).
    """
    from co_scientist.llm_call_budget import release_run_call_budget

    outcome = _settle_finalize_outcome(run_id, db_path)
    release_run_call_budget(run_id)
    return outcome

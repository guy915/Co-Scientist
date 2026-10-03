"""Drain and publish a completed run through its durable and safety gates."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from app import store
from app.engine_adapter.drain import persist_final_state
from app.engine_tasks import runtime as engine_tasks_runtime
from app.engine_tasks.inputs import reopen_for_pending_scientist_input
from app.engine_tasks.support import (
    FINALIZE_TASK,
    SafetyHoldError,
    TaskCommit,
    _latest_task_checkpoint,
    _metrics_snapshot,
    _plain_final_state,
    _require_run,
    _save_paused_checkpoint,
    _save_paused_state_if_requested,
    assert_task_commit_allowed,
    restore_checkpoint_state,
)
from app.report import ReportRequest, finalize_report
from app.run_events import make_emitter
from app.run_modes import normalize_run_tier
from app.safety import SafetyDecision, apply_safety_gate
from app.store import RunStatus, ScientificTask


def _finalize_replay_or_none(
    run: store.RunRow, *, db_path: str | None
) -> dict[str, Any] | None:
    """Return the replayed outcome when finalization already published."""
    if run.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled before finalization")
    already_published = (
        run.status == RunStatus.COMPLETED.value
        and store.get_latest_report(run.id, db_path=db_path) is not None
    )
    if already_published:
        return {"run_id": run.id, "status": "completed", "replayed": True}
    return None


def _settle_finalize_outcome(
    run_id: str, db_path: str | None
) -> dict[str, Any]:
    """Report outcome; park unpublished work for explicit resume."""
    run = store.get_run(run_id, db_path=db_path)
    status = run.status if run else "missing"
    if (
        status == RunStatus.PAUSED.value
        and store.get_latest_report(run_id, db_path=db_path) is None
    ):
        raise SafetyHoldError("report finalization held for review")
    return {"run_id": run_id, "status": status}


def _pause_finalize_if_requested(
    commit: TaskCommit, state: dict[str, Any]
) -> dict[str, Any] | None:
    """Checkpoint a pause that arrived before finalize starts its drain."""
    run = store.get_run(commit.task.run_id, db_path=commit.db_path)
    if run is None or run.status != RunStatus.PAUSED.value:
        return None
    checkpoint_seq = _save_paused_state_if_requested(
        commit, state, FINALIZE_TASK
    )
    if checkpoint_seq is None:
        return None
    return {"checkpoint_seq": checkpoint_seq, "status": "paused"}


def _commit_finalize_drain(
    commit: TaskCommit,
    state: dict[str, Any],
    drained: Any,
    metrics: dict[str, Any],
) -> dict[str, Any] | None:
    """Preserve pause or enter synthesis after final drain atomically."""
    from co_scientist.checkpoint import serialize_workflow_state

    task, db_path = commit.task, commit.db_path
    envelope = serialize_workflow_state(state, last_event_seq=0)
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        status = conn.execute(
            "SELECT status FROM runs WHERE id=?", (task.run_id,)
        ).fetchone()["status"]
        if status == RunStatus.PAUSED.value:
            store.clear_publication_artifacts(task.run_id, conn=conn)
            envelope["last_event_seq"] = store.latest_event_seq(
                task.run_id, conn=conn
            )
            checkpoint_seq = _save_paused_checkpoint(
                commit,
                state,
                FINALIZE_TASK,
                envelope,
                conn,
            )
            store.save_run_metrics(task.run_id, metrics, conn=conn)
            return {"checkpoint_seq": checkpoint_seq, "status": "paused"}
        store.save_run_metrics(task.run_id, metrics, conn=conn)
        store.update_run_status(task.run_id, RunStatus.SYNTHESIZING, conn=conn)
        for event_type, payload in _finalize_stage_events(drained):
            store.append_event(task.run_id, event_type, payload, conn=conn)
    return None


def _finalize_stage_events(
    drained: Any,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield the ordered, persisted progress events for a completed drain."""
    yield "safety.hypothesis", drained.safety_counts
    yield "citation.grounding", drained.grounding_counts
    yield "citation_audit", dict(drained.report_inputs["citation_summary"])


def _monitor_halt_decision(state: dict[str, Any]) -> SafetyDecision:
    """Rebuild the monitor's verdict as an app-side safety decision.

    The engine records the halt in the workflow state's audit trail; this
    carries that record -- its rationale and the policy text it matched --
    onto the run's own safety decisions, so a blocked run explains itself
    through the same surface as an intake or final-gate block. A halt
    whose record did not survive the checkpoint still blocks, on the
    generic reason: the flag is the decision, the record only its detail.
    """
    from co_scientist.agents.safety import MONITOR_STAGE

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
    run: store.RunRow,
    state: dict[str, Any],
    task: ScientificTask,
    db_path: str | None,
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
    async for _ in apply_safety_gate(
        run.id, decision, emit, db_path=db_path, task=task
    ):
        pass
    return {"run_id": run.id, "status": RunStatus.BLOCKED.value}


async def _drain_and_persist_final_state(
    run: store.RunRow,
    state: dict[str, Any],
    db_path: str | None,
) -> tuple[Any, float, dict[str, Any]]:
    """Persist replayable final artifacts outside a database lock."""
    final_state = _plain_final_state(state)
    store.clear_publication_artifacts(run.id, db_path=db_path)
    drained = await persist_final_state(
        run_id=run.id, final_state=final_state, db_path=db_path
    )
    metrics = _metrics_snapshot(final_state)
    execution_time = max(0.0, time.time() - float(state.get("start_time", 0)))
    return drained, execution_time, metrics


def _restore_finalize_checkpoint(
    task: ScientificTask, db_path: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Restore the workflow state the run's last committed checkpoint holds."""
    checkpoint, _ = _latest_task_checkpoint(task, db_path)
    return checkpoint, restore_checkpoint_state(task, checkpoint, db_path)


async def _publish_finalize_report(
    run: store.RunRow,
    task: ScientificTask,
    drained: Any,
    execution_time: float,
    emit: Any,
    db_path: str | None,
) -> None:
    """Publish through the report gate after the drain commit."""
    setup = run.config.get("setup") if isinstance(run.config, dict) else None
    async for _ in finalize_report(
        run.id,
        ReportRequest(
            research_goal=run.research_goal,
            goal_restatement=run.goal_restatement,
            run_mode=normalize_run_tier(run.profile),
            provider="engine",
            execution_time=execution_time,
            setup=setup if isinstance(setup, dict) else None,
            prepared_at=time.time(),
            db_path=db_path,
            **drained.report_inputs,
        ),
        emit,
        task=task,
    ):
        pass


async def execute_finalize(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Drain the final checkpoint and publish through the shared report gate."""
    run = _require_run(task, db_path)
    replayed = _finalize_replay_or_none(run, db_path=db_path)
    if replayed is not None:
        return replayed
    checkpoint, state = _restore_finalize_checkpoint(task, db_path)
    commit = TaskCommit(task, int(checkpoint["seq"]), db_path)
    paused = _pause_finalize_if_requested(commit, state)
    if paused is not None:
        return paused
    halted = await _halt_finalize_if_blocked(run, state, task, db_path)
    if halted is not None:
        return halted
    drain = engine_tasks_runtime.active().drain_final_state
    drained, execution_time, metrics = await drain(run, state, db_path)
    paused = _commit_finalize_drain(commit, state, drained, metrics)
    if paused is not None:
        return paused
    emit = make_emitter(run.id, db_path=db_path)
    await _publish_finalize_report(
        run, task, drained, execution_time, emit, db_path
    )
    # Contributions posted during report publication have no continuation
    # task. Reopen here; the helper no-ops unless completed with pending input.
    reopen_for_pending_scientist_input(run.id, db_path=db_path)
    return _settle_and_release(run.id, db_path)


def _settle_and_release(run_id: str, db_path: str | None) -> dict[str, Any]:
    """Settle and free call-budget tracking, including nonterminal exits."""
    from co_scientist.llm import release_run_call_budget

    outcome = _settle_finalize_outcome(run_id, db_path)
    release_run_call_budget(run_id)
    return outcome

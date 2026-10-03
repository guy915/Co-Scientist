"""Durable execution for one owner-authorized outcome refinement."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, cast

from co_scientist.agents import evolution
from co_scientist.checkpoint import serialize_workflow_state
from co_scientist.llm import scoped_telemetry
from co_scientist.models import Hypothesis, MetricDeltas
from co_scientist.models.metrics import (
    ExecutionMetrics,
    create_metrics_update,
    merge_metrics,
)
from co_scientist.state import WorkflowState

from app import store
from app.engine_adapter import is_engine_checkpoint
from app.engine_tasks.metrics import _metrics_snapshot
from app.engine_tasks.portfolio import _enqueue_after
from app.engine_tasks.support import (
    NODE_TASK_PREFIX,
    SupersededTaskError,
    _save_exact_checkpoint,
    _save_node_checkpoint,
    assert_task_commit_allowed,
    restore_checkpoint_state,
)
from app.outcome_refinement.lineage import (
    _checkpointed_child,
    _child_row,
    _result_checkpoint_state,
)
from app.safety import screen_intake
from app.store import RunStatus, ScientificTask

_TERMINAL_ACTION_STATUSES = {"completed", "no_child", "safety_rejected"}
_REVIEW_TASK = f"{NODE_TASK_PREFIX}review"
_RESULT_KEY = "outcome_refinement_result"


@dataclass(frozen=True)
class _TargetedEvolution:
    """Inputs for the provider boundary of one targeted action."""

    task: ScientificTask
    action: dict[str, Any]
    parent: Hypothesis
    context_block: str
    siblings: list[Hypothesis]
    state: dict[str, Any]
    db_path: str | None


def _result(
    action: dict[str, Any], *, replayed: bool = False
) -> dict[str, Any]:
    return {
        "action_id": action["action_id"],
        "outcome_id": action["outcome_id"],
        "hypothesis_id": action["hypothesis_id"],
        "status": action["status"],
        "child_hypothesis_id": action.get("child_hypothesis_id"),
        "replayed": replayed,
    }


def _validate_intent(
    task: ScientificTask,
    action: dict[str, Any],
    state: dict[str, Any],
    *,
    db_path: str | None,
) -> tuple[Hypothesis, dict[str, Any]]:
    _validate_intent_identity(task, action)
    snapshot = _validate_intent_snapshot(action)
    parent = _validate_intent_target(action, state, db_path)
    return parent, snapshot


def _validate_intent_identity(
    task: ScientificTask, action: dict[str, Any]
) -> None:
    if (
        task.idempotency_key != action["task_idempotency_key"]
        or task.inputs.get("action_id") != action["action_id"]
        or task.provenance.get("action_id") != action["action_id"]
        or task.provenance.get("outcome_id") != action["outcome_id"]
        or task.provenance.get("hypothesis_id") != action["hypothesis_id"]
    ):
        raise ValueError(
            "outcome refinement task identity does not match intent"
        )


def _validate_intent_snapshot(action: dict[str, Any]) -> dict[str, Any]:
    snapshot = cast(dict[str, Any], json.loads(action["context_snapshot"]))
    if (
        snapshot.get("action_id") != action["action_id"]
        or snapshot.get("task_idempotency_key")
        != action["task_idempotency_key"]
        or snapshot.get("run_id") != action["run_id"]
        or snapshot.get("requested_by") != action["owner_id"]
        or snapshot.get("parent", {}).get("hypothesis_id")
        != action["hypothesis_id"]
        or snapshot.get("outcome", {}).get("outcome_id") != action["outcome_id"]
        or snapshot.get("outcome", {}).get("run_id") != action["run_id"]
        or snapshot.get("outcome", {}).get("hypothesis_id")
        != action["hypothesis_id"]
        or len(action["context_snapshot"]) > 6_000
    ):
        raise ValueError("stored outcome refinement snapshot is invalid")
    return snapshot


def _validate_intent_target(
    action: dict[str, Any],
    state: dict[str, Any],
    db_path: str | None,
) -> Hypothesis:
    parent = next(
        (
            hypothesis
            for hypothesis in state.get("hypotheses", [])
            if hypothesis.id == action["hypothesis_id"]
        ),
        None,
    )
    parent_row = store.get_hypothesis(action["hypothesis_id"], db_path=db_path)
    outcome = store.get_hypothesis_outcome(
        action["run_id"], action["outcome_id"], db_path=db_path
    )
    if (
        parent is None
        or parent_row is None
        or parent_row["run_id"] != action["run_id"]
        or not parent.is_rankable()
        or parent.is_undermined()
        or outcome is None
        or outcome["run_id"] != action["run_id"]
        or outcome["hypothesis_id"] != action["hypothesis_id"]
        or outcome["author"] != action["owner_id"]
    ):
        raise ValueError("outcome refinement target is no longer eligible")
    return parent


def _checkpoint_state(
    task: ScientificTask,
    checkpoint: dict[str, Any],
    *,
    db_path: str | None,
) -> tuple[dict[str, Any], int]:
    if not is_engine_checkpoint(checkpoint):
        raise ValueError("outcome refinement requires an engine checkpoint")
    state = restore_checkpoint_state(task, checkpoint, db_path)
    return state, int(checkpoint["seq"])


def _checkpoint_result(
    task: ScientificTask,
    state: dict[str, Any],
    expected_seq: int,
    marker: dict[str, Any],
    *,
    db_path: str | None,
) -> int:
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    envelope["state"][_RESULT_KEY] = marker
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        if marker["kind"] == "child":
            seq = _save_node_checkpoint(
                task, envelope, _REVIEW_TASK, expected_seq, conn
            )
        else:
            seq = _save_exact_checkpoint(task, envelope, expected_seq, conn)
        store.save_run_metrics(task.run_id, _metrics_snapshot(state), conn=conn)
    return seq


def _commit_result(
    task: ScientificTask,
    action: dict[str, Any],
    state: dict[str, Any],
    marker: dict[str, Any],
    *,
    db_path: str | None,
) -> dict[str, Any]:
    child = _checkpointed_child(action, state, marker)
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        current = store.get_outcome_refinement_action(
            action["run_id"], action["action_id"], conn=conn
        )
        if current is None:
            raise LookupError("outcome refinement intent disappeared")
        if current["status"] in _TERMINAL_ACTION_STATUSES:
            return _result(current, replayed=True)
        if child is not None:
            return _commit_child(task, action, current, child, conn)
        return _commit_terminal_action(task, action, marker, conn)


def _commit_child(
    task: ScientificTask,
    action: dict[str, Any],
    current: dict[str, Any],
    child: Hypothesis,
    conn: Any,
) -> dict[str, Any]:
    """Persist child lineage and enqueue its standard review atomically."""
    if current.get("child_hypothesis_id") not in {None, child.id}:
        raise store.OutcomeRefinementConflictError
    store.add_hypothesis(_child_row(task.run_id, child), conn=conn)
    updated = store.update_outcome_refinement_action(
        action["action_id"],
        status="completed",
        child_hypothesis_id=child.id,
        conn=conn,
    )
    assert updated is not None
    store.append_event(
        task.run_id,
        "scientist.outcome_refinement_completed",
        {
            "action_id": action["action_id"],
            "outcome_id": action["outcome_id"],
            "hypothesis_id": action["hypothesis_id"],
            "child_hypothesis_id": child.id,
        },
        conn=conn,
    )
    _enqueue_after(task, _REVIEW_TASK, 90, conn)
    return _result(updated)


def _commit_terminal_action(
    task: ScientificTask,
    action: dict[str, Any],
    marker: dict[str, Any],
    conn: Any,
) -> dict[str, Any]:
    """Settle an action that returned no child or failed its safety screen."""
    status = (
        "safety_rejected" if marker["kind"] == "safety_rejected" else "no_child"
    )
    updated = store.update_outcome_refinement_action(
        action["action_id"], status=status, conn=conn
    )
    assert updated is not None
    store.update_run_status(task.run_id, RunStatus.COMPLETED, conn=conn)
    store.append_event(
        task.run_id,
        "scientist.outcome_refinement_completed",
        {
            "action_id": action["action_id"],
            "outcome_id": action["outcome_id"],
            "hypothesis_id": action["hypothesis_id"],
            "status": status,
        },
        conn=conn,
    )
    return _result(updated)


def _load_action_and_checkpoint(
    task: ScientificTask, db_path: str | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Load the immutable intent and current checkpoint for this task."""
    action_id = str(task.inputs.get("action_id") or "")
    action = store.get_outcome_refinement_action(
        task.run_id, action_id, db_path=db_path
    )
    if action is None:
        raise LookupError("outcome refinement intent not found")
    if action["status"] in _TERMINAL_ACTION_STATUSES:
        return action, None
    if action["run_id"] != task.run_id:
        raise ValueError("outcome refinement task crossed run boundary")
    return action, _active_checkpoint(task, db_path)


def _active_checkpoint(
    task: ScientificTask, db_path: str | None
) -> dict[str, Any]:
    """Require a live run and its latest engine checkpoint."""
    run = store.get_run(task.run_id, db_path=db_path)
    if run is None or run.status not in {
        RunStatus.QUEUED.value,
        RunStatus.RUNNING.value,
        RunStatus.SYNTHESIZING.value,
    }:
        raise ValueError("outcome refinement run is not active")
    checkpoint = store.get_latest_checkpoint(task.run_id, db_path=db_path)
    if checkpoint is None:
        raise ValueError("outcome refinement checkpoint is missing")
    return checkpoint


def _replay_checkpointed_result(
    task: ScientificTask,
    action: dict[str, Any],
    checkpoint: dict[str, Any],
    db_path: str | None,
) -> dict[str, Any] | None:
    """Commit an already checkpointed child without repeating provider work."""
    checkpoint_state = checkpoint["state"].get("state")
    marker = (
        checkpoint_state.get(_RESULT_KEY)
        if isinstance(checkpoint_state, dict)
        else None
    )
    if checkpoint["stage"] != f"engine_task:{task.id}":
        return None
    if (
        not isinstance(marker, dict)
        or marker.get("action_id") != action["action_id"]
    ):
        raise SupersededTaskError("outcome refinement checkpoint is unrelated")
    state, _checkpoint_seq = _checkpoint_state(
        task, checkpoint, db_path=db_path
    )
    return _commit_result(task, action, state, marker, db_path=db_path)


def _require_expected_checkpoint(
    task: ScientificTask, checkpoint: dict[str, Any]
) -> None:
    """Reject intent replay after any unrelated state advance."""
    expected_seq = int(task.inputs.get("checkpoint_seq", -1))
    if int(checkpoint["seq"]) != expected_seq:
        raise SupersededTaskError(
            "outcome refinement checkpoint was superseded"
        )


def _commit_safety_rejection(
    task: ScientificTask,
    action: dict[str, Any],
    state: dict[str, Any],
    current_seq: int,
    db_path: str | None,
) -> dict[str, Any]:
    """Checkpoint and atomically settle an outcome that fails safety screen."""
    marker = {
        "kind": "safety_rejected",
        "action_id": action["action_id"],
        "outcome_id": action["outcome_id"],
        "hypothesis_id": action["hypothesis_id"],
    }
    _checkpoint_result(task, state, current_seq, marker, db_path=db_path)
    latest = store.get_latest_checkpoint(task.run_id, db_path=db_path)
    assert latest is not None
    restored, _seq = _checkpoint_state(task, latest, db_path=db_path)
    return _commit_result(task, action, restored, marker, db_path=db_path)


async def _evolve_targeted_parent(
    request: _TargetedEvolution,
) -> Hypothesis | None:
    """Call only the selected parent's evolution operator and mark retryable."""
    with store.transaction(request.db_path) as conn:
        assert_task_commit_allowed(request.task, conn)
        store.update_outcome_refinement_action(
            request.action["action_id"], status="executing", conn=conn
        )
    context = evolution.prepare_outcome_refinement_context(
        cast(WorkflowState, request.state), request.parent
    )
    try:
        with capture_refinement_usage(request.state):
            return (
                await evolution.evolve_single_hypothesis_from_outcome(
                    request.parent,
                    context,
                    request.context_block,
                    request.siblings,
                )
            )[0]
    except Exception:
        mark_retryable_with_usage(
            request.task, request.action, request.state, request.db_path
        )
        raise


def _targeted_evolution_request(
    request: _TargetedEvolution,
) -> _TargetedEvolution:
    siblings = [
        hypothesis
        for hypothesis in request.state.get("hypotheses", [])
        if hypothesis.id != request.parent.id
    ]
    return replace(request, siblings=siblings)


def _checkpoint_and_commit_refinement(
    request: _TargetedEvolution,
    child: Hypothesis | None,
    current_seq: int,
) -> dict[str, Any]:
    task, action, state, parent = (
        request.task,
        request.action,
        request.state,
        request.parent,
    )
    db_path = request.db_path
    successor_state, result_marker = _result_checkpoint_state(
        action, state, parent, child
    )
    _checkpoint_result(
        task, successor_state, current_seq, result_marker, db_path=db_path
    )
    latest = store.get_latest_checkpoint(task.run_id, db_path=db_path)
    assert latest is not None
    restored, _checkpoint_seq = _checkpoint_state(task, latest, db_path=db_path)
    return _commit_result(
        task, action, restored, result_marker, db_path=db_path
    )


async def _execute_loaded_refinement(
    task: ScientificTask,
    action: dict[str, Any],
    checkpoint: dict[str, Any],
    db_path: str | None,
) -> dict[str, Any]:
    _require_expected_checkpoint(task, checkpoint)
    state, current_seq = _checkpoint_state(task, checkpoint, db_path=db_path)
    restore_retry_usage(state, task.run_id, db_path)
    parent, _snapshot = _validate_intent(task, action, state, db_path=db_path)
    context_block = action["context_snapshot"]
    if screen_intake(context_block).decision != "allow":
        return _commit_safety_rejection(
            task, action, state, current_seq, db_path
        )
    request = _targeted_evolution_request(
        _TargetedEvolution(
            task=task,
            action=action,
            parent=parent,
            context_block=context_block,
            siblings=[],
            state=state,
            db_path=db_path,
        )
    )
    child = await _evolve_targeted_parent(request)
    try:
        return _checkpoint_and_commit_refinement(request, child, current_seq)
    except Exception:
        mark_retryable_with_usage(task, action, state, db_path)
        raise


async def execute_outcome_refinement(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Resume or execute exactly one outcome-to-parent evolution action."""
    action, checkpoint = _load_action_and_checkpoint(task, db_path)
    if checkpoint is None:
        return _result(action, replayed=True)
    replay = _replay_checkpointed_result(task, action, checkpoint, db_path)
    if replay is not None:
        return replay
    return await _execute_loaded_refinement(task, action, checkpoint, db_path)


@contextmanager
def capture_refinement_usage(state: dict[str, Any]) -> Iterator[None]:
    """Fold Robin calls into the existing metrics reducer."""
    with scoped_telemetry("outcome_refinement") as telemetry:
        try:
            yield
        finally:
            usage = telemetry.snapshot()
            if usage:
                current = state.get("metrics")
                if not isinstance(current, ExecutionMetrics):
                    current = ExecutionMetrics.from_dict(current or {})
                calls = sum(entry.get("calls", 0) for entry in usage.values())
                delta = create_metrics_update(
                    deltas=MetricDeltas(llm_calls=calls), model_usage=usage
                )
                state["metrics"] = merge_metrics(current, delta)


def restore_retry_usage(
    state: dict[str, Any], run_id: str, db_path: str | None
) -> None:
    """Use metrics persisted by earlier attempts beyond the last checkpoint."""
    persisted = store.get_run_metrics(run_id, db_path=db_path)
    if persisted is not None:
        state["metrics"] = ExecutionMetrics.from_dict(persisted)


def mark_retryable_with_usage(
    task: ScientificTask,
    action: dict[str, Any],
    state: dict[str, Any],
    db_path: str | None,
) -> None:
    """Keep a failed attempt's usage alongside its retryable action state."""
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        store.update_outcome_refinement_action(
            action["action_id"], status="retryable", conn=conn
        )
        store.save_run_metrics(task.run_id, _metrics_snapshot(state), conn=conn)

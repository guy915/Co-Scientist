"""Admission for an owner-authorized, one-outcome refinement intent.

The intent is a durable outbox record that recovery can materialize as
one claimable scientific task.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from co_scientist.checkpoint import (
    CheckpointSchemaError,
    restore_workflow_state,
)

from app import store
from app.engine_adapter.checkpoints import is_engine_checkpoint
from app.engine_tasks_support import OUTCOME_REFINEMENT_TASK
from app.store import DEMO_CLIENT_ID, NewOutcomeRefinementAction

MAX_OUTCOME_CONTEXT_CODEPOINTS = 6_000
MAX_OUTCOME_SOURCE_LINKS = 3
_PENDING_RECOVERY_LIMIT = 25
logger = logging.getLogger(__name__)


class OutcomeRefinementNotFoundError(ValueError):
    """The run, outcome, or linked parent is not visible to this owner."""


class OutcomeRefinementIneligibleError(ValueError):
    """The run or linked parent is outside the action's supported state."""


class OutcomeRefinementContextTooLargeError(ValueError):
    """The complete outcome context exceeds a frozen contract limit."""


class OutcomeRefinementRequestError(ValueError):
    """The caller supplied an invalid or conflicting idempotency key."""


@dataclass(frozen=True)
class OutcomeRefinementRequest:
    """One authenticated request to admit or replay an outcome action."""

    run_id: str
    hypothesis_id: str
    outcome_id: str
    owner_id: str
    request_idempotency_key: str


@dataclass(frozen=True)
class RefinementContext:
    """Values frozen into the executor's complete, bounded input snapshot."""

    action_id: str
    task_idempotency_key: str
    run_id: str
    owner_id: str
    checkpoint_seq: int
    parent: Any
    outcome: dict[str, Any]


@dataclass(frozen=True)
class RefinementTarget:
    """The exact outcome and checkpointed parent admitted by the request."""

    outcome: dict[str, Any]
    parent: Any
    checkpoint_seq: int


@dataclass(frozen=True)
class CheckpointedParent:
    """An eligible parent restored from the latest engine checkpoint."""

    parent: Any
    checkpoint_seq: int


def _validate_request_key(key: str) -> str:
    value = key.strip()
    if not value or len(value) > 200 or value != key or not value.isprintable():
        raise OutcomeRefinementRequestError
    return value


def _action_payload(
    action: dict[str, Any], *, replayed: bool
) -> dict[str, Any]:
    """Expose stable IDs and status without returning observation text."""
    return {
        "action_id": action["action_id"],
        "run_id": action["run_id"],
        "outcome_id": action["outcome_id"],
        "hypothesis_id": action["hypothesis_id"],
        "task_idempotency_key": action["task_idempotency_key"],
        "checkpoint_seq": action["checkpoint_seq"],
        "context_codepoints": action["context_codepoints"],
        "status": action["status"],
        "child_hypothesis_id": action.get("child_hypothesis_id"),
        "created_at": action["created_at"],
        "replayed": replayed,
    }


def get_owner_outcome_refinement_action(
    run_id: str,
    hypothesis_id: str,
    outcome_id: str,
    owner_id: str,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Read an existing owner's action without recovering or enqueueing it."""
    action = store.get_outcome_refinement_action_for_outcome(
        run_id, outcome_id, db_path=db_path
    )
    if (
        action is None
        or action["hypothesis_id"] != hypothesis_id
        or action["owner_id"] != owner_id
    ):
        raise OutcomeRefinementNotFoundError
    return _action_payload(action, replayed=True)


def _context_snapshot(context: RefinementContext) -> str:
    evidence_ids, evidence = _context_evidence(context)
    snapshot = {
        "context_version": 1,
        "action_id": context.action_id,
        "task_idempotency_key": context.task_idempotency_key,
        "run_id": context.run_id,
        "requested_by": context.owner_id,
        "checkpoint_seq": context.checkpoint_seq,
        "parent": {
            "hypothesis_id": context.parent.id,
            "title": context.parent.title or "",
            "statement": context.parent.text,
        },
        "outcome": _outcome_snapshot(context.outcome, evidence_ids, evidence),
    }
    serialized = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if len(serialized) > MAX_OUTCOME_CONTEXT_CODEPOINTS:
        raise OutcomeRefinementContextTooLargeError
    return serialized


def _context_evidence(
    context: RefinementContext,
) -> tuple[list[str], list[dict[str, Any]]]:
    evidence_ids = context.outcome["referenced_evidence_ids"]
    evidence = context.outcome["referenced_evidence"]
    if (
        len(evidence_ids) > MAX_OUTCOME_SOURCE_LINKS
        or len(evidence) > MAX_OUTCOME_SOURCE_LINKS
    ):
        raise OutcomeRefinementContextTooLargeError
    if [item.get("id") for item in evidence] != evidence_ids:
        raise OutcomeRefinementNotFoundError
    return evidence_ids, evidence


def _outcome_snapshot(
    outcome: dict[str, Any],
    evidence_ids: list[str],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "outcome_id": outcome["id"],
        "run_id": outcome["run_id"],
        "hypothesis_id": outcome["hypothesis_id"],
        "hypothesis_snapshot": outcome["hypothesis_snapshot"],
        "method_protocol": outcome["method_protocol"],
        "conditions": outcome["conditions"],
        "measured_observation": outcome["measured_observation"],
        "units": outcome["units"],
        "controls": outcome["controls"],
        "interpretation": outcome["interpretation"],
        "referenced_evidence_ids": evidence_ids,
        "referenced_evidence": evidence,
        "author": outcome["author"],
        "recorded_at": outcome["recorded_at"],
    }


def _owned_run(conn: Any, request: OutcomeRefinementRequest) -> Any:
    run = store.get_run(request.run_id, conn=conn)
    if run is None or run.client_id != request.owner_id:
        raise OutcomeRefinementNotFoundError
    return run


def _matching_outcome(
    conn: Any, request: OutcomeRefinementRequest
) -> dict[str, Any]:
    outcome = store.get_hypothesis_outcome(
        request.run_id, request.outcome_id, conn=conn
    )
    if (
        outcome is None
        or outcome["hypothesis_id"] != request.hypothesis_id
        or outcome["author"] != request.owner_id
    ):
        raise OutcomeRefinementNotFoundError
    return outcome


def _eligible_parent(
    conn: Any, request: OutcomeRefinementRequest
) -> CheckpointedParent:
    parent_row = store.get_hypothesis(request.hypothesis_id, conn=conn)
    checkpoint = store.get_latest_checkpoint(request.run_id, conn=conn)
    if (
        parent_row is None
        or parent_row["run_id"] != request.run_id
        or checkpoint is None
        or not is_engine_checkpoint(checkpoint)
    ):
        raise OutcomeRefinementIneligibleError
    try:
        state = restore_workflow_state(checkpoint["state"])
    except (CheckpointSchemaError, TypeError, ValueError, KeyError):
        raise OutcomeRefinementIneligibleError from None
    parent = next(
        (
            candidate
            for candidate in state.get("hypotheses", [])
            if candidate.id == request.hypothesis_id
        ),
        None,
    )
    if parent is None or not parent.is_rankable() or parent.is_undermined():
        raise OutcomeRefinementIneligibleError
    return CheckpointedParent(
        parent=parent, checkpoint_seq=int(checkpoint["seq"])
    )


def _validate_new_action_run(run: Any) -> None:
    if (
        run.client_id == DEMO_CLIENT_ID
        or run.provider != "engine"
        or run.status != store.RunStatus.COMPLETED.value
    ):
        raise OutcomeRefinementIneligibleError


def _replay_for_key(
    existing: dict[str, Any] | None, request: OutcomeRefinementRequest
) -> dict[str, Any] | None:
    if existing is None:
        return None
    if (
        existing["outcome_id"] != request.outcome_id
        or existing["hypothesis_id"] != request.hypothesis_id
        or existing["owner_id"] != request.owner_id
    ):
        raise store.OutcomeRefinementConflictError
    return _action_payload(existing, replayed=True)


def _replay_existing_action(
    request: OutcomeRefinementRequest, request_key: str, conn: Any
) -> dict[str, Any] | None:
    action = store.get_outcome_refinement_action_by_key(
        request.run_id, request_key, conn=conn
    )
    replay = _replay_for_key(action, request)
    if action is None or replay is None:
        return replay
    _materialize_action(action, conn)
    current = store.get_outcome_refinement_action(
        request.run_id, action["action_id"], conn=conn
    )
    return _action_payload(current or action, replayed=True)


def _new_intent(
    request: OutcomeRefinementRequest,
    target: RefinementTarget,
    request_key: str,
    conn: Any,
) -> dict[str, Any]:
    _require_unclaimed_outcome(request, conn)
    action, replayed = store.create_outcome_refinement_action(
        _new_action_record(request, target, request_key),
        conn=conn,
    )
    _materialize_action(action, conn)
    action = (
        store.get_outcome_refinement_action(
            request.run_id, action["action_id"], conn=conn
        )
        or action
    )
    return _action_payload(action, replayed=replayed)


def _require_unclaimed_outcome(
    request: OutcomeRefinementRequest, conn: Any
) -> None:
    if (
        store.get_outcome_refinement_action_for_outcome(
            request.run_id, request.outcome_id, conn=conn
        )
        is not None
    ):
        raise store.OutcomeRefinementConflictError


def _new_action_record(
    request: OutcomeRefinementRequest,
    target: RefinementTarget,
    request_key: str,
) -> NewOutcomeRefinementAction:
    action_id = str(uuid.uuid4())
    task_idempotency_key = f"outcome-refinement:{action_id}"
    context_snapshot = _context_snapshot(
        RefinementContext(
            action_id=action_id,
            task_idempotency_key=task_idempotency_key,
            run_id=request.run_id,
            owner_id=request.owner_id,
            checkpoint_seq=target.checkpoint_seq,
            parent=target.parent,
            outcome=target.outcome,
        )
    )
    return NewOutcomeRefinementAction(
        action_id=action_id,
        run_id=request.run_id,
        outcome_id=request.outcome_id,
        hypothesis_id=request.hypothesis_id,
        owner_id=request.owner_id,
        request_idempotency_key=request_key,
        task_idempotency_key=task_idempotency_key,
        checkpoint_seq=target.checkpoint_seq,
        context_snapshot=context_snapshot,
    )


def _materialize_action(
    action: dict[str, Any], conn: Any, *, retry_failed: bool = True
) -> None:
    """Atomically attach the saved intent to the durable engine queue."""
    if action["status"] in {"completed", "no_child", "safety_rejected"}:
        return
    run = store.get_run(action["run_id"], conn=conn)
    if run is None or run.status in {
        store.RunStatus.CANCELLED.value,
        store.RunStatus.BLOCKED.value,
    }:
        return
    if not _ensure_action_task(action, conn, retry_failed=retry_failed):
        return
    if run.status in {
        store.RunStatus.COMPLETED.value,
        store.RunStatus.FAILED.value,
    }:
        store.update_run_status(
            action["run_id"], store.RunStatus.QUEUED, conn=conn
        )
        store.append_event(
            action["run_id"],
            "lifecycle",
            {
                "event": "outcome_refinement_queued",
                "action_id": action["action_id"],
                "outcome_id": action["outcome_id"],
                "hypothesis_id": action["hypothesis_id"],
            },
            conn=conn,
        )
    store.update_outcome_refinement_action(
        action["action_id"], status="queued", conn=conn
    )


def _ensure_action_task(
    action: dict[str, Any], conn: Any, *, retry_failed: bool
) -> bool:
    """Create the stable task row or explicitly revive its failed attempt."""
    existing = conn.execute(
        "SELECT id, status FROM scientific_tasks "
        "WHERE run_id=? AND idempotency_key=?",
        (action["run_id"], action["task_idempotency_key"]),
    ).fetchone()
    if existing is None:
        store.enqueue_task(
            store.NewTask(
                run_id=action["run_id"],
                task_type=OUTCOME_REFINEMENT_TASK,
                inputs={
                    "action_id": action["action_id"],
                    "checkpoint_seq": action["checkpoint_seq"],
                },
                idempotency_key=action["task_idempotency_key"],
                provenance={
                    "action_id": action["action_id"],
                    "outcome_id": action["outcome_id"],
                    "hypothesis_id": action["hypothesis_id"],
                },
                max_attempts=3,
            ),
            conn=conn,
        )
        return True
    if existing["status"] in {"failed", "cancelled"}:
        return retry_failed and store.revive_task_for_retry(
            action["run_id"], action["task_idempotency_key"], conn=conn
        )
    return True


def materialize_pending_outcome_refinements(
    *, db_path: str | None = None
) -> int:
    """Recover a bounded set of pre-executor intents without retrying work."""
    pending = store.list_pending_outcome_refinement_actions(
        db_path=db_path, limit=_PENDING_RECOVERY_LIMIT
    )
    materialized = 0
    for snapshot in pending:
        try:
            with store.transaction(db_path) as conn:
                action = store.get_outcome_refinement_action(
                    snapshot["run_id"], snapshot["action_id"], conn=conn
                )
                if action is None or action["status"] != "pending_executor":
                    continue
                _materialize_action(action, conn, retry_failed=False)
                current = store.get_outcome_refinement_action(
                    snapshot["run_id"], snapshot["action_id"], conn=conn
                )
                materialized += int(
                    current is not None and current["status"] == "queued"
                )
        except Exception:
            logger.warning(
                "Could not recover outcome-refinement intent %s",
                snapshot["action_id"],
                exc_info=True,
            )
    return materialized


def request_outcome_refinement_action(
    request: OutcomeRefinementRequest,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Atomically admit or replay one owner's refinement intent."""
    request_key = _validate_request_key(request.request_idempotency_key)
    with store.transaction(db_path) as conn:
        run = _owned_run(conn, request)
        outcome = _matching_outcome(conn, request)
        replay = _replay_existing_action(request, request_key, conn)
        if replay is not None:
            return replay
        _validate_new_action_run(run)
        target = _eligible_parent(conn, request)
        return _new_intent(
            request,
            RefinementTarget(
                outcome=outcome,
                parent=target.parent,
                checkpoint_seq=target.checkpoint_seq,
            ),
            request_key,
            conn,
        )

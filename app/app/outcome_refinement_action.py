"""Admission for an owner-authorized, one-outcome refinement intent.

The intent is a durable outbox record, deliberately separate from the
claimable scientific-task queue until the targeted executor lands in 01c.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from co_scientist.checkpoint import (
    CheckpointSchemaError,
    restore_workflow_state,
)

from app import store
from app.engine_adapter.checkpoints import is_engine_checkpoint
from app.store import DEMO_CLIENT_ID, NewOutcomeRefinementAction

MAX_OUTCOME_CONTEXT_CODEPOINTS = 6_000
MAX_OUTCOME_SOURCE_LINKS = 3


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
        "created_at": action["created_at"],
        "replayed": replayed,
    }


def _context_snapshot(context: RefinementContext) -> str:
    evidence_ids = context.outcome["referenced_evidence_ids"]
    evidence = context.outcome["referenced_evidence"]
    if len(evidence_ids) > MAX_OUTCOME_SOURCE_LINKS or len(evidence) > (
        MAX_OUTCOME_SOURCE_LINKS
    ):
        raise OutcomeRefinementContextTooLargeError
    if [item.get("id") for item in evidence] != evidence_ids:
        raise OutcomeRefinementNotFoundError

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
        "outcome": {
            "outcome_id": context.outcome["id"],
            "run_id": context.outcome["run_id"],
            "hypothesis_id": context.outcome["hypothesis_id"],
            "hypothesis_snapshot": context.outcome["hypothesis_snapshot"],
            "method_protocol": context.outcome["method_protocol"],
            "conditions": context.outcome["conditions"],
            "measured_observation": context.outcome["measured_observation"],
            "units": context.outcome["units"],
            "controls": context.outcome["controls"],
            "interpretation": context.outcome["interpretation"],
            "referenced_evidence_ids": evidence_ids,
            "referenced_evidence": evidence,
            "author": context.outcome["author"],
            "recorded_at": context.outcome["recorded_at"],
        },
    }
    serialized = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(serialized) > MAX_OUTCOME_CONTEXT_CODEPOINTS:
        raise OutcomeRefinementContextTooLargeError
    return serialized


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


def _new_intent(
    request: OutcomeRefinementRequest,
    target: RefinementTarget,
    request_key: str,
    conn: Any,
) -> dict[str, Any]:
    existing_for_outcome = store.get_outcome_refinement_action_for_outcome(
        request.run_id, request.outcome_id, conn=conn
    )
    if existing_for_outcome is not None:
        raise store.OutcomeRefinementConflictError

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
    action, replayed = store.create_outcome_refinement_action(
        NewOutcomeRefinementAction(
            action_id=action_id,
            run_id=request.run_id,
            outcome_id=request.outcome_id,
            hypothesis_id=request.hypothesis_id,
            owner_id=request.owner_id,
            request_idempotency_key=request_key,
            task_idempotency_key=task_idempotency_key,
            checkpoint_seq=target.checkpoint_seq,
            context_snapshot=context_snapshot,
        ),
        conn=conn,
    )
    return _action_payload(action, replayed=replayed)


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
        replay = _replay_for_key(
            store.get_outcome_refinement_action_by_key(
                request.run_id, request_key, conn=conn
            ),
            request,
        )
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

"""Recording a safety decision and gating the run on it.

Split from ``app.safety`` so the policy layer (what a decision is) and the
effect layer (what the run does about it) stay independently readable while
the module stays under the repository's file-length ceiling. Every name here
is re-exported from ``app.safety``, which remains the import surface.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app import store
from app.safety_redaction import redact_matched_spans
from app.safety_types import SafetyDecision
from app.store import RunStatus
from app.store.tasks_model import ScientificTask

logger = logging.getLogger(__name__)

__all__ = ["apply_safety_gate"]


def _apply_intake_redaction(
    run_id: str, result: SafetyDecision, *, db_path: str | None
) -> None:
    """Scrub a redacted goal from the run row, not just from the audit record.

    The intake gate recorded the redaction and then let the bootstrap prepare
    state from the same ``research_goal`` column, so the original survived in
    the database and in every read built on it. The title is scrubbed with the
    same spans because it is generated from the goal. Done here, inside the
    gate, so the redaction is an effect of the decision itself rather than
    something each caller has to remember.

    Args:
        run_id: Identifier of the run being gated.
        result: The decision to act on; a no-op unless it redacts at intake.
        db_path: Optional override for the SQLite database path.
    """
    if result.stage != "intake" or result.decision != "redact":
        return
    run = store.get_run(run_id, db_path=db_path)
    if run is None:
        return
    matches = list(result.matches)
    store.redact_run_goal(
        run_id,
        redact_matched_spans(run.research_goal, matches),
        redact_matched_spans(run.title or "", matches),
        db_path=db_path,
    )
    logger.warning(
        "Redacted %d matched span(s) from run %s's goal at the intake gate.",
        len(matches),
        run_id,
    )


def _record_safety_decision(
    run_id: str,
    result: SafetyDecision,
    *,
    db_path: str | None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Persist the decision and log it at a level matching its severity."""
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run_id,
            stage=result.stage,
            decision=result.decision,
            reason=result.reason,
            matches=result.matches,
            category=result.category,
            policy_version=result.policy_version,
            risk_domains=result.risk_domains,
            requires_review=result.requires_review,
            assessor=result.assessor,
        ),
        db_path=db_path,
        conn=conn,
    )
    if result.decision in {"block", "hold"}:
        logger.warning(
            "Safety gate withheld run %s at %s stage: %s",
            run_id,
            result.stage,
            result.reason,
        )
    else:
        logger.info(
            "Safety gate %s run %s at %s stage.",
            result.decision,
            run_id,
            result.stage,
        )


def _commit_task_safety_events(
    run_id: str,
    result: SafetyDecision,
    task: ScientificTask,
    db_path: str | None,
) -> list[dict[str, Any]]:
    """Fence a durable task's safety decision and terminal status effects."""
    from app.engine_tasks_support import _assert_task_commit_allowed

    decision_payload = result.to_dict()
    event_type = f"safety.{result.stage}"
    events: list[dict[str, Any]] = []
    with store.transaction(db_path) as conn:
        _assert_task_commit_allowed(task, conn)
        _record_safety_decision(run_id, result, db_path=db_path, conn=conn)
        seq = store.append_event(
            run_id, event_type, decision_payload, conn=conn
        )
        events.append(
            {"seq": seq, "type": event_type, "payload": decision_payload}
        )
        if result.decision == "block":
            status = RunStatus.BLOCKED
            payload = {"status": "blocked", "error": result.reason}
        elif result.decision == "hold":
            status = RunStatus.PAUSED
            payload = {
                "status": "paused",
                "reason": "safety_review",
                "error": result.reason,
            }
        else:
            return events
        store.update_run_status(
            run_id, status, error=result.reason, db_path=db_path, conn=conn
        )
        seq = store.append_event(run_id, "status", payload, conn=conn)
        events.append({"seq": seq, "type": "status", "payload": payload})
    return events


def _commit_gate_status_event(
    run_id: str,
    status: RunStatus,
    error: str | None,
    payload: dict[str, Any],
    *,
    status_guard: tuple[str | None, tuple[str, str | None, int] | None],
) -> dict[str, Any] | None:
    """Write a safety stop only while the run is still nonterminal.

    The run transition and its status event share one transaction. Otherwise
    cancellation could commit between them, leaving a late paused/blocked
    event after the user's completed cancel.
    """
    active_statuses = (
        RunStatus.DRAFT,
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.SYNTHESIZING,
        RunStatus.PAUSED,
    )
    db_path, lease_guard = status_guard
    with store.transaction(db_path) as conn:
        if lease_guard is not None and not store.bootstrap_task_lease_matches(
            conn, run_id, *lease_guard
        ):
            return None
        changed = store.update_run_status_if_current(
            conn, run_id, status, active_statuses, error
        )
        if not changed:
            return None
        seq = store.append_event(run_id, "status", payload, conn=conn)
    return {"seq": seq, "type": "status", "payload": payload}


async def _yield_terminal_status_event(
    run_id: str,
    result: SafetyDecision,
    *,
    db_path: str | None,
    lease_guard: tuple[str, str | None, int] | None,
) -> AsyncIterator[dict[str, Any]]:
    """Update the run's status and yield its event when the result is final."""
    if result.decision == "block":
        event = _commit_gate_status_event(
            run_id,
            RunStatus.BLOCKED,
            result.reason,
            {"status": "blocked", "error": result.reason},
            status_guard=(db_path, lease_guard),
        )
        if event is not None:
            yield event
    elif result.decision == "hold":
        payload = {
            "status": "paused",
            "reason": "safety_review",
            "error": result.reason,
        }
        event = _commit_gate_status_event(
            run_id,
            RunStatus.PAUSED,
            result.reason,
            payload,
            status_guard=(db_path, lease_guard),
        )
        if event is not None:
            yield event


async def apply_safety_gate(  # noqa: PLR0913
    run_id: str,
    result: SafetyDecision,
    emit: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    db_path: str | None = None,
    lease_guard: tuple[str, str | None, int] | None = None,
    task: ScientificTask | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Record a safety decision, emit it, and gate the run on a hard block.

    Shared by the intake and final safety gates so the record -> emit ->
    block-and-stop sequence lives in one place. Yields the events to forward
    on the workflow's stream: the ``safety.{stage}`` decision, plus a
    blocked ``status`` event when the decision blocks. The caller must
    return from its workflow when ``result.decision == "block"``.

    Args:
        run_id: Identifier of the run being gated.
        result: The safety screening outcome to record and act on.
        emit: The provider's event emitter, called as ``emit(type, payload)``.
        db_path: Optional override for the SQLite database path.
        lease_guard: Optional bootstrap task lease to fence intake verdicts.
        task: Optional durable task whose lease fences all gate writes.

    Yields:
        Event dicts to forward on the workflow's event stream.
    """
    if task is not None:
        events = _commit_task_safety_events(run_id, result, task, db_path)
        _apply_intake_redaction(run_id, result, db_path=db_path)
        for event in events:
            yield event
        return
    _record_safety_decision(run_id, result, db_path=db_path)
    _apply_intake_redaction(run_id, result, db_path=db_path)
    yield await emit(f"safety.{result.stage}", result.to_dict())
    async for event in _yield_terminal_status_event(
        run_id, result, db_path=db_path, lease_guard=lease_guard
    ):
        yield event

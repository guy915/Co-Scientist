"""Recording a safety decision and gating the run on it.

Split from ``app.safety`` so the policy layer (what a decision is) and the
effect layer (what the run does about it) stay independently readable while
the module stays under the repository's file-length ceiling. Every name here
is re-exported from ``app.safety``, which remains the import surface.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app import store
from app.safety_redaction import redact_matched_spans
from app.safety_types import SafetyDecision
from app.store import RunStatus

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
    run_id: str, result: SafetyDecision, *, db_path: str | None
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


async def _yield_terminal_status_event(
    run_id: str,
    result: SafetyDecision,
    emit: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    db_path: str | None,
) -> AsyncIterator[dict[str, Any]]:
    """Update the run's status and yield its event when the result is final."""
    if result.decision == "block":
        store.update_run_status(
            run_id, RunStatus.BLOCKED, error=result.reason, db_path=db_path
        )
        yield await emit(
            "status", {"status": "blocked", "error": result.reason}
        )
    elif result.decision == "hold":
        store.update_run_status(
            run_id, RunStatus.PAUSED, error=result.reason, db_path=db_path
        )
        yield await emit(
            "status",
            {
                "status": "paused",
                "reason": "safety_review",
                "error": result.reason,
            },
        )


async def apply_safety_gate(
    run_id: str,
    result: SafetyDecision,
    emit: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    db_path: str | None = None,
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

    Yields:
        Event dicts to forward on the workflow's event stream.
    """
    _record_safety_decision(run_id, result, db_path=db_path)
    _apply_intake_redaction(run_id, result, db_path=db_path)
    yield await emit(f"safety.{result.stage}", result.to_dict())
    async for event in _yield_terminal_status_event(
        run_id, result, emit, db_path=db_path
    ):
        yield event

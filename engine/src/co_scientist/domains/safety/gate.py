from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import co_scientist.platform.llm.process_mode as process_mode
from co_scientist.core.config import settings
from co_scientist.domains.research_state.repository import records
from co_scientist.domains.research_state.repository.records import NewSafetyDecision
from co_scientist.domains.safety.rules import (
    POLICY_VERSION,
    SafetyOutcome,
    review_content_safety,
    review_hypothesis_safety,
)
from co_scientist.domains.safety.semantic import (
    run_semantic_safety_model,
    semantic_credential_missing_decision,
    semantic_safety_error_decision,
)
from co_scientist.domains.safety.types import SafetyDecision, redact_matched_spans
from co_scientist.domains.safety.types import redact_payload_text as redact_payload_text
from co_scientist.orchestration.repository import events as store_events
from co_scientist.orchestration.repository import runs
from co_scientist.platform import db
from co_scientist.platform.db.models import RunStatus, ScientificTask

logger = logging.getLogger(__name__)


def _apply_intake_redaction(
    run_id: str,
    result: SafetyDecision,
    *,
    db_path: str | None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Apply redaction to stored goal and derived title inside the gate; an
    audit label alone leaves unsafe content readable.
    """
    if result.stage != "intake" or result.decision != "redact":
        return
    run = runs.get_run(run_id, db_path=db_path, conn=conn)
    if run is None:
        return
    matches = list(result.matches)
    runs.redact_run_goal(
        run_id,
        redact_matched_spans(run.research_goal, matches),
        redact_matched_spans(run.title or "", matches),
        db_path=db_path,
        conn=conn,
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
    records.add_safety_decision(
        NewSafetyDecision(
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


def _assert_bootstrap_intake_lease(
    run_id: str, task: ScientificTask, conn: sqlite3.Connection
) -> None:
    if task.run_id == run_id and runs.bootstrap_task_lease_matches(
        conn, run_id, task.id, task.lease_owner, task.attempt
    ):
        return
    from co_scientist.orchestration.task_worker.outcomes import LeaseLostError

    raise LeaseLostError(f"bootstrap task {task.id} lost its lease before intake commit")


def _event_record(seq: int, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"seq": seq, "type": event_type, "payload": payload}


def _commit_task_safety_events(
    run_id: str,
    result: SafetyDecision,
    task: ScientificTask,
    db_path: str | None,
) -> list[dict[str, Any]]:
    from co_scientist.orchestration.engine_tasks.support import assert_task_commit_allowed

    decision_payload = result.to_dict()
    event_type = f"safety.{result.stage}"
    with db.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        if result.stage == "intake":
            _assert_bootstrap_intake_lease(run_id, task, conn)
        _record_safety_decision(run_id, result, db_path=db_path, conn=conn)
        _apply_intake_redaction(run_id, result, db_path=db_path, conn=conn)
        seq = store_events.append_event(run_id, event_type, decision_payload, conn=conn)
        events = [_event_record(seq, event_type, decision_payload)]
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
        runs.update_run_status(run_id, status, error=result.reason, db_path=db_path, conn=conn)
        seq = store_events.append_event(run_id, "status", payload, conn=conn)
        events.append(_event_record(seq, "status", payload))
    return events


def _commit_gate_status_event(
    run_id: str,
    status: RunStatus,
    error: str | None,
    payload: dict[str, Any],
    *,
    status_guard: tuple[str | None, tuple[str, str | None, int] | None],
) -> dict[str, Any] | None:
    """Transition and terminal event share one transaction so cancellation
    cannot be followed by a late safety-stop event.
    """
    active_statuses = (
        RunStatus.DRAFT,
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.SYNTHESIZING,
        RunStatus.PAUSED,
    )
    db_path, lease_guard = status_guard
    with db.transaction(db_path) as conn:
        if lease_guard is not None and not runs.bootstrap_task_lease_matches(
            conn, run_id, *lease_guard
        ):
            return None
        changed = runs.update_run_status_if_current(conn, run_id, status, active_statuses, error)
        if not changed:
            return None
        seq = store_events.append_event(run_id, "status", payload, conn=conn)
    return {"seq": seq, "type": "status", "payload": payload}


async def _yield_terminal_status_event(
    run_id: str,
    result: SafetyDecision,
    *,
    db_path: str | None,
    lease_guard: tuple[str, str | None, int] | None,
) -> AsyncIterator[dict[str, Any]]:
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


async def apply_safety_gate(
    run_id: str,
    result: SafetyDecision,
    emit: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    db_path: str | None = None,
    lease_guard: tuple[str, str | None, int] | None = None,
    task: ScientificTask | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Callers must stop workflow execution after a block; emitting a
    terminal verdict cannot itself stop the caller.
    """
    if task is not None:
        events = _commit_task_safety_events(run_id, result, task, db_path)
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


def _decision_from_review(stage: str, review: Any) -> SafetyDecision:
    return SafetyDecision(
        stage=stage,
        decision=review.decision,
        reason=review.reason,
        matches=list(review.matches),
        category=review.category,
        risk_domains=list(review.risk_domains),
        requires_review=review.requires_review,
        policy_version=review.policy_version,
    )


_DECISION_SEVERITY = {"allow": 0, "redact": 1, "hold": 2, "block": 3}


def _severity(decision: SafetyDecision) -> int:
    return _DECISION_SEVERITY.get(decision.decision, 0)


def _more_severe(first: SafetyDecision, second: SafetyDecision) -> SafetyDecision:
    return second if _severity(second) > _severity(first) else first


_OUTCOME_TO_CONTENT_DECISION: dict[SafetyOutcome, tuple[str, str, str]] = {
    SafetyOutcome.PROHIBITED: (
        "block",
        "prohibited",
        "cbrn_weaponization",
    ),
    SafetyOutcome.ETHICAL_CONCERN: (
        "block",
        "ethical_concern",
        "research_ethics",
    ),
    SafetyOutcome.UNCERTAIN: (
        "hold",
        "uncertain",
        "obfuscated_intent",
    ),
}


def _hypothesis_policy_decision(stage: str, text: str) -> SafetyDecision | None:
    """Use the canonical hypothesis classifier here too so intake/final
    cannot permit hazards the hypothesis gate disqualifies.
    """
    review = review_hypothesis_safety(text or "", detect_obfuscation=stage != "final")
    mapped = _OUTCOME_TO_CONTENT_DECISION.get(review.outcome)
    if mapped is None:
        return None
    decision, category, risk_domain = mapped
    return SafetyDecision(
        stage=stage,
        decision=decision,
        reason=f"Content {review.reason}.",
        matches=list(review.matches),
        category=category,
        risk_domains=[risk_domain],
        requires_review=decision == "hold",
        policy_version=review.policy_version,
    )


def _screen_both_tiers(stage: str, text: str) -> SafetyDecision:
    review = review_content_safety(text or "", stage)
    baseline = _decision_from_review(stage, review)
    parity = _hypothesis_policy_decision(stage, text)
    return baseline if parity is None else _more_severe(baseline, parity)


def screen_intake(goal: str) -> SafetyDecision:
    return _screen_both_tiers("intake", goal)


def screen_final(report_markdown: str) -> SafetyDecision:
    return _screen_both_tiers("final", report_markdown)


async def screen_contextual(
    text: str,
    stage: str,
    *,
    deterministic: SafetyDecision | None = None,
) -> SafetyDecision:
    """Rules are hard floors the model cannot lower; deliberate offline mode
    skips assessment, while a missing configured credential refuses.
    """
    baseline = deterministic or (screen_intake(text) if stage == "intake" else screen_final(text))
    if baseline.decision == "block":
        return baseline
    model = settings.semantic_safety_model or settings.supervisor_model_name or settings.model_name
    assert model is not None
    if not settings.semantic_safety_enabled or process_mode.offline_mode():
        return baseline
    if not process_mode.credential_available(model):
        return semantic_credential_missing_decision(stage, model, baseline)
    try:
        assessment = await run_semantic_safety_model(text, stage, model)
    except Exception as exc:  # Provider failure must not silently clear risk.
        return semantic_safety_error_decision(stage, model, baseline, exc)
    # Deterministic content floors cannot be cleared by a permissive model;
    # contextual assessment may only raise their severity.
    return _more_severe(assessment, baseline)


def _should_escalate_to_semantic(run_id: str, stage: str, *, db_path: str | None) -> bool:
    """Historical eligibility follows the persisted run backend, not current
    process mode.
    """
    approved = records.safety_stage_is_approved(run_id, stage, POLICY_VERSION, db_path=db_path)
    offline = runs.run_offline_backed(run_id, db_path=db_path)
    return not offline and not approved


async def assess_hold_contextually(
    run_id: str,
    text: str,
    stage: str,
    *,
    db_path: str | None = None,
) -> SafetyDecision | None:
    """Tier B needs a verdict distinct from absence: disabled, offline,
    missing credentials or provider failure must never become an allow.
    """
    if not _should_escalate_to_semantic(run_id, stage, db_path=db_path):
        return None
    model = settings.semantic_safety_model or settings.supervisor_model_name or settings.model_name
    assert model is not None
    if not settings.semantic_safety_enabled or process_mode.offline_mode():
        return None
    if not process_mode.credential_available(model):
        return None
    try:
        return await run_semantic_safety_model(text, stage, model)
    except Exception as exc:  # An outage must never read as a clean pass.
        logger.warning("Contextual hold assessment failed: %s", exc)
        return None


@dataclass(frozen=True)
class ScreenSubject:
    stage: str
    text: str
    deterministic: SafetyDecision


async def screen_with_escalation(
    run_id: str,
    subject: ScreenSubject,
    *,
    provider: str,
    db_path: str | None = None,
) -> SafetyDecision:
    """Already human-approved stages and offline runs retain their
    deterministic verdict; historical backend comes from the run row.
    """
    if _should_escalate_to_semantic(run_id, subject.stage, db_path=db_path):
        return ensure_redactable(
            await screen_contextual(
                subject.text,
                subject.stage,
                deterministic=subject.deterministic,
            )
        )
    return ensure_redactable(subject.deterministic)


def ensure_redactable(decision: SafetyDecision) -> SafetyDecision:
    """A redact verdict without matched spans cannot remove text; hold it
    rather than publish untouched content under a redaction label.
    """
    if decision.decision != "redact" or decision.matches:
        return decision
    return SafetyDecision(
        stage=decision.stage,
        decision="hold",
        reason=(
            "Content was marked for redaction but no removable span was "
            "identified; human review required."
        ),
        category=decision.category,
        policy_version=decision.policy_version,
        risk_domains=list(decision.risk_domains) or ["unredactable"],
        requires_review=True,
        assessor=decision.assessor,
    )


__all__ = [
    "POLICY_VERSION",
    "SafetyDecision",
    "ScreenSubject",
    "apply_safety_gate",
    "ensure_redactable",
    "redact_matched_spans",
    "redact_payload_text",
    "screen_contextual",
    "screen_final",
    "screen_intake",
    "screen_with_escalation",
]

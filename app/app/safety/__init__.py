"""Content safety policy for a run's intake goal and final output."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from co_scientist.safety import (
    POLICY_VERSION,
    SafetyOutcome,
    review_content_safety,
    review_hypothesis_safety,
)

import app.process_mode as process_mode
import app.store as store
from app.config import settings
from app.execution_policy import effective_execution_model
from app.safety.semantic import (
    run_semantic_safety_model,
    semantic_credential_missing_decision,
    semantic_safety_error_decision,
)
from app.safety.types import SafetyDecision, redact_matched_spans
from app.safety.types import SafetyMode as SafetyMode
from app.safety.types import redact_payload_text as redact_payload_text
from app.store import RunStatus
from app.store.models import ScientificTask

logger = logging.getLogger(__name__)


def _apply_intake_redaction(
    run_id: str,
    result: SafetyDecision,
    *,
    db_path: str | None,
    conn: sqlite3.Connection | None = None,
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
        conn: Optional open connection to reuse within the transaction.
    """
    if result.stage != "intake" or result.decision != "redact":
        return
    run = store.get_run(run_id, db_path=db_path, conn=conn)
    if run is None:
        return
    matches = list(result.matches)
    store.redact_run_goal(
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


def _assert_bootstrap_intake_lease(
    run_id: str, task: ScientificTask, conn: sqlite3.Connection
) -> None:
    """Require the bootstrap's unexpired lease before an intake commit."""
    if task.run_id == run_id and store.bootstrap_task_lease_matches(
        conn, run_id, task.id, task.lease_owner, task.attempt
    ):
        return
    from app.task_worker.outcomes import _LeaseLostError

    raise _LeaseLostError(
        f"bootstrap task {task.id} lost its lease before intake commit"
    )


def _event_record(
    seq: int, event_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return {"seq": seq, "type": event_type, "payload": payload}


def _commit_task_safety_events(
    run_id: str,
    result: SafetyDecision,
    task: ScientificTask,
    db_path: str | None,
) -> list[dict[str, Any]]:
    """Fence a durable task's safety decision and terminal status effects."""
    from app.engine_tasks.support import assert_task_commit_allowed

    decision_payload = result.to_dict()
    event_type = f"safety.{result.stage}"
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        if result.stage == "intake":
            _assert_bootstrap_intake_lease(run_id, task, conn)
        _record_safety_decision(run_id, result, db_path=db_path, conn=conn)
        _apply_intake_redaction(run_id, result, db_path=db_path, conn=conn)
        seq = store.append_event(
            run_id, event_type, decision_payload, conn=conn
        )
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
        store.update_run_status(
            run_id, status, error=result.reason, db_path=db_path, conn=conn
        )
        seq = store.append_event(run_id, "status", payload, conn=conn)
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


async def apply_safety_gate(
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


def _resolve_safety_mode() -> SafetyMode:
    """Coerce the configured safety mode, defaulting to STANDARD if invalid."""
    try:
        return SafetyMode(settings.safety_mode.lower())
    except ValueError:
        return SafetyMode.STANDARD


SAFETY_MODE = _resolve_safety_mode()


def _decision_from_review(stage: str, review: Any) -> SafetyDecision:
    """Build a :class:`SafetyDecision` from a policy ``review`` result."""
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


# Ordered least to most restrictive; used to keep the strictest verdict when
# two classifiers see the same text. A later assessment may raise the
# severity, never lower it.
_DECISION_SEVERITY = {"allow": 0, "redact": 1, "hold": 2, "block": 3}


def _severity(decision: SafetyDecision) -> int:
    """Return the ordering rank of a decision, unknown values reading lowest."""
    return _DECISION_SEVERITY.get(decision.decision, 0)


def _more_severe(
    first: SafetyDecision, second: SafetyDecision
) -> SafetyDecision:
    """Return the decision that withholds more, preferring ``first`` on ties."""
    return second if _severity(second) > _severity(first) else first


# How a blocking per-hypothesis outcome reads as a content-stage decision.
# Only the outcomes that exclude a hypothesis from the pool are carried over:
# dual-use and redact are non-blocking there too, so the content policy's own
# handling of them already matches.
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
    """Apply the canonical per-hypothesis policy to intake/final content.

    The narrow content policy only prohibits a harmful verb and a named agent
    in the same clause, so a bare "design a bioweapon for mass-casualty
    deployment" cleared it while the per-hypothesis gate disqualified the same
    sentence. Running the canonical classifier here makes the two agree by
    construction rather than by two lists being kept in step by hand.

    Args:
        stage: Safety stage being screened (``"intake"`` or ``"final"``).
        text: The content to classify.

    Returns:
        The decision when the per-hypothesis policy withholds the content,
        else ``None``.
    """
    review = review_hypothesis_safety(text or "")
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


def screen_intake(goal: str) -> SafetyDecision:
    """Run the input gate. Returns block / hold / redact / allow."""
    review = review_content_safety(
        goal or "",
        "intake",
        strict_intake=SAFETY_MODE == SafetyMode.STRICT,
    )
    baseline = _decision_from_review("intake", review)
    parity = _hypothesis_policy_decision("intake", goal)
    return baseline if parity is None else _more_severe(baseline, parity)


def screen_final(report_markdown: str) -> SafetyDecision:
    """Final-output gate. Block on hard hits; annotate dual-use otherwise."""
    review = review_content_safety(report_markdown or "", "final")
    return _decision_from_review("final", review)


async def screen_contextual(
    text: str,
    stage: str,
    *,
    deterministic: SafetyDecision | None = None,
) -> SafetyDecision:
    """Assess content contextually, behind the deterministic hard pre-blocks.

    The model is the primary classifier: it sees content the pattern rules
    cannot describe and its verdict is what the caller gates on. The rules run
    first and bound it from below -- a rule-level block short-circuits before
    any call, and nothing the model returns can lower a rule-level verdict.

    A forced-offline or keyless process pins every model call to the offline
    backend, so no contextual screen is expected to run: that is a deployment
    mode, not a safety control that failed, and it must not hold every run
    for review. It is the carve-out ``_should_escalate_to_semantic`` already
    makes for an offline-backed run, at process rather than run scope. A
    *partially* configured deployment -- one holding a provider credential but
    not the safety model's -- is the opposite case and still refuses, which is
    the failure this guard must not swallow.
    """
    baseline = deterministic or (
        screen_intake(text) if stage == "intake" else screen_final(text)
    )
    if baseline.decision == "block":
        return baseline
    model = effective_execution_model(
        settings.semantic_safety_model
        or settings.supervisor_model_name
        or settings.model_name
    )
    assert model is not None
    if not settings.semantic_safety_enabled or process_mode.offline_mode():
        return baseline
    if not process_mode.credential_available(model):
        return semantic_credential_missing_decision(stage, model, baseline)
    try:
        assessment = await run_semantic_safety_model(text, stage, model)
    except Exception as exc:  # Provider failure must not silently clear risk.
        return semantic_safety_error_decision(stage, model, baseline, exc)
    # The model is the primary classifier, but the deterministic rules are
    # hard pre-blocks: the model may raise the verdict and never lower it, so
    # a rule-matched redaction cannot be cleared by a permissive assessment.
    return _more_severe(assessment, baseline)


def _should_escalate_to_semantic(
    run_id: str, stage: str, provider: str, *, db_path: str | None
) -> bool:
    """Return whether the stage should escalate to the contextual model.

    Deliberate (Task 2): offline-backed runs skip app-side escalation. The
    contextual screen calls a real configured safety model that is NOT
    offline-routed, so wiring app-side LLM calls through the offline router
    is out of scope for this campaign. Keyed on the run's persisted backend
    (falling back to the provider when the row is gone), not the process
    offline_mode() -- a real engine run created while offline still escalates.
    """
    approved = store.safety_stage_is_approved(
        run_id, stage, POLICY_VERSION, db_path=db_path
    )
    offline = store.run_offline_backed(
        run_id, missing_run_fallback=provider == "mock", db_path=db_path
    )
    return not offline and not approved


async def assess_hold_contextually(
    run_id: str,
    text: str,
    stage: str,
    *,
    db_path: str | None = None,
) -> SafetyDecision | None:
    """Return the model's own verdict on a held item, or None if it did not run.

    The counterpart to :func:`screen_contextual` for the one case that
    screen cannot serve: a deterministic verdict that is a *question*
    rather than a floor. ``screen_contextual`` applies ``_more_severe``
    against its baseline, which is exactly right for intake and final --
    the rules there assert risk and the model may only add to it -- but it
    means a permissive answer is indistinguishable from no answer, so a
    caller that needs to act on "the model said this is fine" cannot.
    Tier B of the hypothesis policy is that caller: its hold means "a
    category term matched and the rules cannot tell what the sentence
    asks for" (see ``app.hypothesis.safety``, the only caller,
    which is also where the guards that make acting on this safe live).

    Returning ``None`` rather than a decision for every non-answer keeps
    those two states apart at the type level: a caller cannot mistake
    "disabled", "offline", "no credential" or "provider failed" for a
    verdict, which is the mistake that would turn an outage into a
    permissive pass.

    Args:
        run_id: Run the content belongs to, for offline/approval gating.
        text: The content under review, passed as data, never as
            instructions.
        stage: Safety stage recorded on the decision.
        db_path: Optional override for the SQLite database path.

    Returns:
        The model's unmodified decision, or None when no assessment ran.
    """
    if not _should_escalate_to_semantic(
        run_id, stage, "engine", db_path=db_path
    ):
        return None
    model = effective_execution_model(
        settings.semantic_safety_model
        or settings.supervisor_model_name
        or settings.model_name
    )
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
    """What one safety stage is screening, with its deterministic verdict.

    The deterministic hard blocks always run first and produce
    ``deterministic``; this bundle carries their result to the escalation
    decision, never ahead of it.

    Attributes:
        stage: Safety stage being screened (``"intake"`` or ``"final"``).
        text: The content the contextual screen would re-assess.
        deterministic: The already-computed deterministic decision.
    """

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
    """Escalate a deterministic screen to contextual assessment when warranted.

    Both the intake and final gates first run their deterministic screen, then
    escalate to the contextual model unless the run is offline-backed or this
    stage was already human-approved on the run. Returns the deterministic
    decision unchanged when no escalation applies, so callers can gate on the
    result either way.

    Args:
        run_id: Identifier of the run being gated.
        subject: The stage, its content, and its deterministic decision.
        provider: The active workflow provider; only a fallback signal used
            when the run row is gone (the run's persisted backend wins).
        db_path: Optional override for the SQLite database path.

    Returns:
        The decision to gate on: escalated when applicable, else deterministic.
    """
    if _should_escalate_to_semantic(
        run_id, subject.stage, provider, db_path=db_path
    ):
        return ensure_redactable(
            await screen_contextual(
                subject.text,
                subject.stage,
                deterministic=subject.deterministic,
            )
        )
    return ensure_redactable(subject.deterministic)


def ensure_redactable(decision: SafetyDecision) -> SafetyDecision:
    """Hold a redaction the app has no way to apply.

    Redaction removes the spans the policy matched. A ``redact`` verdict
    naming no span -- which is every redaction the contextual model returns,
    since it reports a category rather than offsets -- leaves nothing to
    remove, and proceeding would publish the original under a redaction
    label. That is the exact shape of the defect this guards: the record said
    redacted and the content was untouched.

    Args:
        decision: The decision both content gates are about to act on.

    Returns:
        The decision unchanged, or a hold when it cannot be applied.
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
    "SAFETY_MODE",
    "SafetyDecision",
    "SafetyMode",
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

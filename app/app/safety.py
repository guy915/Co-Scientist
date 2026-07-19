"""Lightweight safety filter for intake and final output.

Goals:
- Block obviously hazardous CBRN / weaponization asks at intake.
- Redact or annotate dual-use scientific content at final-output stage.
- Keep allow lists explicit; default to allow.
- Determinism: same input always yields the same decision.
"""

from __future__ import annotations

import enum
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from co_scientist.safety import POLICY_VERSION, review_content_safety

from app import store
from app.config import deepseek_thinking_kwargs, settings
from app.store import RunStatus

logger = logging.getLogger(__name__)

__all__ = [
    "POLICY_VERSION",
    "SAFETY_MODE",
    "SafetyDecision",
    "SafetyMode",
    "screen_contextual",
    "screen_final",
    "screen_intake",
    "screen_with_escalation",
]


class SafetyMode(str, enum.Enum):
    """How aggressively the safety filter treats dual-use content."""

    STANDARD = "standard"
    STRICT = "strict"


def _resolve_safety_mode() -> SafetyMode:
    """Coerce the configured safety mode, defaulting to STANDARD if invalid."""
    try:
        return SafetyMode(settings.safety_mode.lower())
    except ValueError:
        return SafetyMode.STANDARD


SAFETY_MODE = _resolve_safety_mode()


@dataclass
class SafetyDecision:
    """Outcome of a safety pass."""

    stage: str  # "intake" | "final"
    decision: str  # "allow" | "redact" | "block"
    reason: str = ""
    matches: list[str] = field(default_factory=list)
    category: str = "allowed"
    policy_version: str = POLICY_VERSION
    risk_domains: list[str] = field(default_factory=list)
    requires_review: bool = False
    assessor: str = "deterministic"

    def to_dict(self) -> dict[str, str | list[str] | bool]:
        """Serialize this decision for the `safety.{stage}` event payload."""
        return {
            "stage": self.stage,
            "decision": self.decision,
            "reason": self.reason,
            "matches": self.matches,
            "category": self.category,
            "policy_version": self.policy_version,
            "risk_domains": self.risk_domains,
            "requires_review": self.requires_review,
            "assessor": self.assessor,
        }


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


def screen_intake(goal: str) -> SafetyDecision:
    """Run the input gate. Returns block / redact / allow."""
    review = review_content_safety(
        goal or "",
        "intake",
        strict_intake=SAFETY_MODE == SafetyMode.STRICT,
    )
    return _decision_from_review("intake", review)


def screen_final(report_markdown: str) -> SafetyDecision:
    """Final-output gate. Block on hard hits; annotate dual-use otherwise."""
    review = review_content_safety(report_markdown or "", "final")
    return _decision_from_review("final", review)


def _semantic_credential_available(model: str) -> bool:
    """Return whether the configured provider has a usable credential."""
    provider = model.split("/", 1)[0].lower()
    env_names = {
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "deepseek": ("DEEPSEEK_API_KEY",),
        "dashscope": ("DASHSCOPE_API_KEY",),
        "openai": ("OPENAI_API_KEY",),
        "anthropic": ("ANTHROPIC_API_KEY",),
    }.get(provider, ())
    return any(os.getenv(name) for name in env_names)


def _semantic_prompt(text: str, stage: str) -> str:
    """Build a bounded contextual-risk classification prompt."""
    return (
        "Classify the scientific content under a research safety policy. "
        "Return JSON only with category, reason, risk_domains, and "
        "operational_detail. category must be one of prohibited, "
        "ethical_concern, uncertain, redacted, allowed. Treat requests that "
        "meaningfully enable weaponization, harmful pathogen enhancement, "
        "mass-casualty capability, non-consensual human experimentation, or "
        "evasion as prohibited or ethical_concern. Legitimate dual-use work "
        "with actionable harmful operational detail is redacted. Ambiguous "
        "risk is uncertain. Do not reproduce or elaborate unsafe detail.\n"
        f"Stage: {stage}\nContent:\n{text[:16000]}"
    )


async def screen_contextual(
    text: str,
    stage: str,
    *,
    deterministic: SafetyDecision | None = None,
) -> SafetyDecision:
    """Combine hard deterministic rules with contextual model assessment."""
    baseline = deterministic or (
        screen_intake(text) if stage == "intake" else screen_final(text)
    )
    if baseline.decision == "block":
        return baseline
    model = (
        settings.semantic_safety_model
        or settings.supervisor_model_name
        or settings.model_name
    )
    if (
        not settings.semantic_safety_enabled
        or not _semantic_credential_available(model)
    ):
        return baseline
    try:
        import litellm

        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "user", "content": _semantic_prompt(text, stage)}
            ],
            response_format={"type": "json_object"},
            temperature=0,
            timeout=20,
            **deepseek_thinking_kwargs(model),
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        category = str(parsed.get("category") or "uncertain")
        if category not in {
            "prohibited",
            "ethical_concern",
            "uncertain",
            "redacted",
            "allowed",
        }:
            category = "uncertain"
        decision = {
            "prohibited": "block",
            "ethical_concern": "block",
            "uncertain": "hold",
            "redacted": "redact",
            "allowed": "allow",
        }[category]
        domains = parsed.get("risk_domains")
        return SafetyDecision(
            stage=stage,
            decision=decision,
            reason=str(parsed.get("reason") or "Contextual safety assessment."),
            category=category,
            risk_domains=(
                [str(item) for item in domains]
                if isinstance(domains, list)
                else []
            ),
            requires_review=decision in {"hold", "redact"},
            assessor=f"semantic:{model}",
        )
    except Exception as exc:  # Provider failure must not silently clear risk.
        logger.warning("Contextual safety assessment failed: %s", exc)
        if baseline.decision == "redact":
            return baseline
        return SafetyDecision(
            stage=stage,
            decision="hold",
            reason=(
                "Contextual safety assessment was unavailable; human review "
                "required."
            ),
            category="uncertain",
            risk_domains=["assessment_unavailable"],
            requires_review=True,
            assessor=f"semantic:{model}:error",
        )


async def screen_with_escalation(
    run_id: str,
    stage: str,
    text: str,
    deterministic: SafetyDecision,
    *,
    provider: str,
    db_path: str | None = None,
) -> SafetyDecision:
    """Escalate a deterministic screen to contextual assessment when warranted.

    Both the intake and final gates first run their deterministic screen, then
    escalate to the contextual model unless the run is offline-backed or this
    stage was already human-approved on the run. Returns ``deterministic``
    unchanged when no escalation applies, so callers can gate on the result
    either way.

    Args:
        run_id: Identifier of the run being gated.
        stage: Safety stage being screened (``"intake"`` or ``"final"``).
        text: The content the contextual screen would re-assess.
        deterministic: The already-computed deterministic decision.
        provider: The active workflow provider; only a fallback signal used
            when the run row is gone (the run's persisted backend wins).
        db_path: Optional override for the SQLite database path.

    Returns:
        The decision to gate on: escalated when applicable, else deterministic.
    """
    approved = store.safety_stage_is_approved(
        run_id, stage, POLICY_VERSION, db_path=db_path
    )
    # Deliberate (Task 2): offline-backed runs skip app-side escalation. The
    # contextual screen calls a real configured safety model that is NOT
    # offline-routed, so wiring app-side LLM calls through the offline router
    # is out of scope for this campaign. Keyed on the run's persisted backend
    # (falling back to the provider when the row is gone), not the process
    # offline_mode() -- a real engine run created while offline still escalates.
    run = store.get_run(run_id, db_path=db_path)
    offline = (
        store.run_used_offline(run) if run is not None else provider == "mock"
    )
    if not offline and not approved:
        return await screen_contextual(text, stage, deterministic=deterministic)
    return deterministic


async def apply_safety_gate(
    run_id: str,
    result: SafetyDecision,
    emit: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    db_path: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Record a safety decision, emit it, and gate the run on a hard block.

    Shared by both workflow providers so the record -> emit -> block-and-stop
    sequence lives in one place. Yields the events to forward on the workflow's
    stream: the ``safety.{stage}`` decision, plus a blocked ``status`` event
    when the decision blocks. The caller must return from its workflow when
    ``result.decision == "block"``.

    Args:
        run_id: Identifier of the run being gated.
        result: The safety screening outcome to record and act on.
        emit: The provider's event emitter, called as ``emit(type, payload)``.
        db_path: Optional override for the SQLite database path.

    Yields:
        Event dicts to forward on the workflow's event stream.
    """
    store.add_safety_decision(
        run_id,
        result.stage,
        result.decision,
        result.reason,
        result.matches,
        category=result.category,
        policy_version=result.policy_version,
        risk_domains=result.risk_domains,
        requires_review=result.requires_review,
        assessor=result.assessor,
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
    yield await emit(f"safety.{result.stage}", result.to_dict())
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

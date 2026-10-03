"""Per-hypothesis screening and monitoring of the research direction.

Safety is a cross-cutting concern alongside the six scientific agents.
The ``safety_screen`` node keeps blocked hypotheses out of the tournament,
holds uncertain hypotheses for manual review, and redacts dual-use details.
The meta-review node calls ``monitor_research_direction`` after each synthesis
to halt a run whose direction reaches content the final report gate blocks.
Both paths retain their existing audit records and graph node keys.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any, NamedTuple

from co_scientist.constants import (
    PROGRESS_META_REVIEW_COMPLETE,
    PROGRESS_SAFETY_SCREEN_COMPLETE,
    PROGRESS_SAFETY_SCREEN_START,
)
from co_scientist.models import Hypothesis, create_metrics_update, phase_message
from co_scientist.progress import emit_progress
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.safety import (
    ContentSafetyReview,
    SafetyOutcome,
    redact_hypothesis_fields,
    review_content_safety,
    review_hypothesis_safety,
)
from co_scientist.state import ReplaceHypotheses, WorkflowState

logger = logging.getLogger(__name__)

__all__ = [
    "MONITOR_STAGE",
    "monitor_research_direction",
    "review_direction_safety",
    "safety_screen_node",
]


def _screen_text(h: Hypothesis) -> str:
    """Concatenate the screenable fields of a hypothesis."""
    parts = [h.text]
    if h.explanation:
        parts.append(h.explanation)
    if h.experiment:
        parts.append(h.experiment)
    return " ".join(parts)


def _meta_review_context(state: WorkflowState) -> str:
    """Render the run's meta-review critique as safety adjudication context.

    Audit E7. The screen is deterministic, so the critique is threaded as
    context for the humans who adjudicate its holds and blocks -- never
    as an input that can move an outcome: policy stays conservative and
    fails closed. Renders "" on iteration 1, when no critique exists yet.
    """
    return _format_meta_review_context(state.get("meta_review"))


def _build_safety_decision(
    review: Any, h: Hypothesis, meta_review_context: str = ""
) -> dict[str, Any] | None:
    """Build the audit-trail decision entry for an UNCERTAIN/blocked review.

    The meta-review critique (audit E7) rides on the entry as adjudication
    context only; it plays no part in the outcome. The key is omitted on
    iteration 1, when there is no critique yet, keeping those records
    byte-identical to the pre-E7 shape.

    Returns None for a review outcome that neither holds nor blocks.
    """
    if review.outcome == SafetyOutcome.UNCERTAIN or review.blocks_tournament:
        decision: dict[str, Any] = {
            "hypothesis_id": h.id,
            "text_prefix": h.text[:120],
            **review.to_dict(),
        }
        if meta_review_context:
            decision["meta_review_context"] = meta_review_context
        return decision
    return None


def _redact_if_needed(h: Hypothesis, review: Any) -> None:
    """Redact operational-detail fields for a DUAL_USE/REDACT review."""
    if review.outcome in (SafetyOutcome.DUAL_USE, SafetyOutcome.REDACT):
        _, h.explanation, h.experiment = redact_hypothesis_fields(
            h.text, h.explanation, h.experiment
        )


def _screen_one_hypothesis(
    h: Hypothesis, meta_review_context: str = ""
) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None]:
    """Screen one hypothesis, applying redaction as a side effect.

    Mutates h.safety_status, and h.explanation/h.experiment for a
    DUAL_USE/REDACT outcome that stays in the pool.

    Args:
        h: Hypothesis to screen.
        meta_review_context: Rendered meta-review critique (audit E7);
            recorded on any decision for adjudication, never consulted
            by the outcome.

    Returns:
        Tuple of (is_safe, decision, held): decision is None unless
        UNCERTAIN/blocked; held is None unless UNCERTAIN.
    """
    if h.safety_status is not None:
        return True, None, None

    review = review_hypothesis_safety(_screen_text(h))
    h.safety_status = review.outcome.value
    decision = _build_safety_decision(review, h, meta_review_context)

    if review.outcome == SafetyOutcome.UNCERTAIN:
        logger.warning(
            "Safety screen: UNCERTAIN hypothesis held for review: "
            "%s... (id=%s)",
            h.text[:80],
            h.id,
        )
        return False, decision, h.to_dict()

    if review.blocks_tournament:
        logger.warning(
            "Safety screen: blocked hypothesis (%s): %s... (id=%s)",
            review.outcome.value,
            h.text[:80],
            h.id,
        )
        return False, decision, None

    _redact_if_needed(h, review)
    return True, decision, None


class _ScreenOutcome(NamedTuple):
    """What one screening pass over the pool produced.

    Attributes:
        safe: Hypotheses cleared to continue into ranking.
        decisions: Safety-decision records for the blocked hypotheses.
        held: Records for hypotheses held for manual review.
    """

    safe: list[Hypothesis]
    decisions: list[dict[str, Any]]
    held: list[dict[str, Any]]


def _screen_hypothesis_pool(
    hypotheses: list[Hypothesis], meta_review_context: str = ""
) -> _ScreenOutcome:
    """Screen every hypothesis in the pool, splitting safe from blocked/held.

    Args:
        hypotheses: Hypotheses to screen.
        meta_review_context: Rendered meta-review critique (audit E7)
            recorded on any decision, for adjudication.

    Returns:
        The pass's safe hypotheses, decision records, and held records.
    """
    safe: list[Hypothesis] = []
    new_decisions: list[dict[str, Any]] = []
    new_held: list[dict[str, Any]] = []

    for h in hypotheses:
        is_safe, decision, held = _screen_one_hypothesis(h, meta_review_context)
        if decision is not None:
            new_decisions.append(decision)
        if held is not None:
            new_held.append(held)
        if is_safe:
            safe.append(h)

    return _ScreenOutcome(safe, new_decisions, new_held)


def _log_screen_summary(
    hypotheses: list[Hypothesis],
    safe: list[Hypothesis],
    blocked_count: int,
    held_count: int,
) -> None:
    """Log the blocked/held counts, and warn if the pool is now empty."""
    if blocked_count:
        logger.info(
            "Safety screen: %d/%d hypotheses blocked (%d held for review)",
            blocked_count,
            len(hypotheses),
            held_count,
        )

    if not safe and hypotheses:
        logger.warning(
            "Safety screen: ALL %d hypotheses blocked; pool is now empty",
            len(hypotheses),
        )


def _build_screen_result(
    hypotheses: list[Hypothesis],
    outcome: _ScreenOutcome,
    state: WorkflowState,
    elapsed: float,
) -> dict[str, Any]:
    """Build the safety_screen_node state-update dict."""
    safe = outcome.safe
    blocked_count = len(hypotheses) - len(safe)
    held_count = len(outcome.held)
    # ``or []`` (not a .get default): a checkpoint restore can carry an
    # explicit None for a field that was unset when the run was serialized.
    existing_decisions: list[dict[str, Any]] = (
        state.get("safety_decisions") or []
    )
    existing_held: list[dict[str, Any]] = state.get("held_for_review") or []
    return {
        "hypotheses": ReplaceHypotheses(safe),
        "safety_decisions": existing_decisions + outcome.decisions,
        "held_for_review": existing_held + outcome.held,
        "messages": phase_message(
            "safety_screen",
            f"Screened {len(hypotheses)} hypotheses: "
            f"{len(safe)} safe, {blocked_count} blocked"
            f" ({held_count} held for review)",
        ),
        "metrics": create_metrics_update(
            phase_times={"safety_screen": elapsed}
        ),
    }


async def safety_screen_node(
    state: WorkflowState,
) -> dict[str, Any]:
    """Screen hypotheses for safety before ranking.

    Returns:
        State update with filtered hypothesis pool, safety decisions, and
        any hypotheses held for manual review.
    """
    start = time.time()
    hypotheses: list[Hypothesis] = state.get("hypotheses", [])
    await emit_progress(
        state,
        "safety_screen",
        "Screening hypotheses for safety",
        PROGRESS_SAFETY_SCREEN_START,
        hypotheses_count=len(hypotheses),
    )

    outcome = _screen_hypothesis_pool(hypotheses, _meta_review_context(state))
    safe = outcome.safe
    blocked_count = len(hypotheses) - len(safe)
    held_count = len(outcome.held)
    _log_screen_summary(hypotheses, safe, blocked_count, held_count)
    elapsed = time.time() - start

    await emit_progress(
        state,
        "safety_screen_complete",
        f"Safety screening complete ({blocked_count} blocked)",
        PROGRESS_SAFETY_SCREEN_COMPLETE,
        blocked_count=blocked_count,
        held_count=held_count,
    )

    return _build_screen_result(hypotheses, outcome, state, elapsed)


# Stage recorded on the monitor's audit entry. Distinct from the
# per-hypothesis screen's records, which are keyed by hypothesis id: this one
# is about the run's direction and names no single idea.
MONITOR_STAGE = "research_direction"

# Overview fields the monitor reads. Every part of the synthesis the model
# writes prose into -- a direction that drifted shows up in the
# recommendations at least as often as in the summary, and reading only the
# summary would miss it.
_MONITORED_FIELDS: tuple[str, ...] = (
    "summary",
    "common_strengths",
    "common_weaknesses",
    "emerging_themes",
    "strategic_recommendations",
)


def _field_text(value: Any) -> str:
    """Flatten one overview field into screenable text.

    Handles both shapes a field can arrive in: a string, or a list of them.
    Anything else is stringified rather than skipped -- production runs
    structured output through providers that do not enforce the schema, and a
    field that came back as a dict still has to be screened.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_field_text(item) for item in value)
    return "" if value is None else str(value)


def _direction_text(meta_review: Mapping[str, Any] | None) -> str:
    """Concatenate the monitored fields of one meta-review overview."""
    overview = meta_review or {}
    return " ".join(
        _field_text(overview.get(field)) for field in _MONITORED_FIELDS
    ).strip()


def review_direction_safety(
    meta_review: Mapping[str, Any] | None,
) -> ContentSafetyReview:
    """Screen the run's synthesized direction under the report gate's policy.

    Args:
        meta_review: The overview the meta-review node just assembled.

    Returns:
        The policy decision: ``block`` halts the run, everything else lets
        it continue unchanged.
    """
    return review_content_safety(_direction_text(meta_review), "final")


def _halt_record(review: ContentSafetyReview) -> dict[str, Any]:
    """Build the audit-trail entry for a halt, matching the screen's shape."""
    return {
        "stage": MONITOR_STAGE,
        "outcome": review.category,
        "reason": review.reason,
        "matches": list(review.matches),
        "policy_version": review.policy_version,
    }


def _halt_update(
    state: WorkflowState, review: ContentSafetyReview
) -> dict[str, Any]:
    """Build the state delta that halts the run.

    ``safety_decisions`` has no reducer, so this pass carries the existing
    audit trail forward explicitly; ``or []`` rather than a ``.get`` default
    because a checkpoint restore can carry an explicit None.
    """
    existing: list[dict[str, Any]] = state.get("safety_decisions") or []
    return {
        "safety_blocked": True,
        "safety_decisions": [*existing, _halt_record(review)],
        "messages": phase_message(
            "safety_monitor",
            "Run halted: the research direction reached prohibited content",
            outcome=review.category,
        ),
    }


async def monitor_research_direction(
    state: WorkflowState, meta_review: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Monitor one meta-review synthesis and halt the run if it must stop.

    Args:
        state: Current workflow state, for the audit trail and progress.
        meta_review: The overview the meta-review node just assembled.

    Returns:
        The halting state delta, or an empty dict when the direction is
        allowed -- a healthy run's state is left byte-identical.
    """
    review = review_direction_safety(meta_review)
    if review.decision != "block":
        return {}

    logger.error(
        "Safety monitor: halting the run; the research direction matches a "
        "prohibited policy rule (matches=%s)",
        list(review.matches),
    )
    # Reported at the meta-review boundary's own value: the monitor reads
    # that node's output, and the progress numbers name phases rather than a
    # completion fraction, so several checkpoints sharing one is the norm.
    await emit_progress(
        state,
        "safety_monitor_halt",
        "Run halted by the safety monitor",
        PROGRESS_META_REVIEW_COMPLETE,
        outcome=review.category,
    )
    return _halt_update(state, review)

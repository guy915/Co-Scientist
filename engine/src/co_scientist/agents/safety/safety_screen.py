"""Safety screen node - pre-ranking per-hypothesis safety gate.

Runs after review and before ranking (and before any direct orchestrator
route to ranking) so an unsafe hypothesis never enters the tournament,
evolution parent set, meta-review, or final report. The node:

1. Screens every hypothesis in the pool against the safety classifier.
2. Removes blocked hypotheses (PROHIBITED, ETHICAL_CONCERN, UNCERTAIN)
   from the pool via ReplaceHypotheses.
3. Holds UNCERTAIN hypotheses in ``held_for_review`` (full dict, not a
   stub) so the app can surface them for manual review.
4. Redacts operational-detail fields for DUAL_USE/REDACT outcomes on
   hypotheses that remain in the pool.
5. Records an audit trail in ``safety_decisions``.
"""

import logging
import time
from typing import Any, NamedTuple

from co_scientist.constants import (
    PROGRESS_SAFETY_SCREEN_COMPLETE,
    PROGRESS_SAFETY_SCREEN_START,
)
from co_scientist.models import Hypothesis, create_metrics_update, phase_message
from co_scientist.progress import emit_progress
from co_scientist.safety import (
    SafetyOutcome,
    redact_hypothesis_fields,
    review_hypothesis_safety,
)
from co_scientist.state import ReplaceHypotheses, WorkflowState

logger = logging.getLogger(__name__)


def _screen_text(h: Hypothesis) -> str:
    """Concatenate the screenable fields of a hypothesis."""
    parts = [h.text]
    if h.explanation:
        parts.append(h.explanation)
    if h.experiment:
        parts.append(h.experiment)
    return " ".join(parts)


def _build_safety_decision(review: Any, h: Hypothesis) -> dict[str, Any] | None:
    """Build the audit-trail decision entry for an UNCERTAIN/blocked review.

    Returns None for a review outcome that neither holds nor blocks.
    """
    if review.outcome == SafetyOutcome.UNCERTAIN or review.blocks_tournament:
        return {
            "hypothesis_id": h.id,
            "text_prefix": h.text[:120],
            **review.to_dict(),
        }
    return None


def _redact_if_needed(h: Hypothesis, review: Any) -> None:
    """Redact operational-detail fields for a DUAL_USE/REDACT review."""
    if review.outcome in (SafetyOutcome.DUAL_USE, SafetyOutcome.REDACT):
        _, h.explanation, h.experiment = redact_hypothesis_fields(
            h.text, h.explanation, h.experiment
        )


def _screen_one_hypothesis(
    h: Hypothesis,
) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None]:
    """Screen one hypothesis, applying redaction as a side effect.

    Mutates h.safety_status, and h.explanation/h.experiment for a
    DUAL_USE/REDACT outcome that stays in the pool.

    Returns:
        Tuple of (is_safe, decision, held): decision is None unless
        UNCERTAIN/blocked; held is None unless UNCERTAIN.
    """
    if h.safety_status is not None:
        return True, None, None

    review = review_hypothesis_safety(_screen_text(h))
    h.safety_status = review.outcome.value
    decision = _build_safety_decision(review, h)

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
    hypotheses: list[Hypothesis],
) -> _ScreenOutcome:
    """Screen every hypothesis in the pool, splitting safe from blocked/held.

    Returns:
        The pass's safe hypotheses, decision records, and held records.
    """
    safe: list[Hypothesis] = []
    new_decisions: list[dict[str, Any]] = []
    new_held: list[dict[str, Any]] = []

    for h in hypotheses:
        is_safe, decision, held = _screen_one_hypothesis(h)
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

    outcome = _screen_hypothesis_pool(hypotheses)
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

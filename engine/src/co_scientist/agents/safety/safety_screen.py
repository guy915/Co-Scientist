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
from typing import Any

from co_scientist.constants import (
    PROGRESS_SAFETY_SCREEN_COMPLETE,
    PROGRESS_SAFETY_SCREEN_START,
)
from co_scientist.models import Hypothesis, create_metrics_update, phase_message
from co_scientist.nodes.progress import emit_progress
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


async def safety_screen_node(
    state: WorkflowState,
) -> dict[str, Any]:
    """Screen hypotheses for safety before ranking.

    Args:
        state: Current workflow state.

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

    safe: list[Hypothesis] = []
    new_decisions: list[dict[str, Any]] = []
    new_held: list[dict[str, Any]] = []

    for h in hypotheses:
        if h.safety_status is not None:
            safe.append(h)
            continue
        review = review_hypothesis_safety(_screen_text(h))
        h.safety_status = review.outcome.value

        if (
            review.outcome == SafetyOutcome.UNCERTAIN
            or review.blocks_tournament
        ):
            new_decisions.append(
                {
                    "hypothesis_id": h.id,
                    "text_prefix": h.text[:120],
                    **review.to_dict(),
                }
            )
        if review.outcome == SafetyOutcome.UNCERTAIN:
            new_held.append(h.to_dict())
            logger.warning(
                "Safety screen: UNCERTAIN hypothesis held for review: "
                "%s... (id=%s)",
                h.text[:80],
                h.id,
            )
        elif review.blocks_tournament:
            logger.warning(
                "Safety screen: blocked hypothesis (%s): %s... (id=%s)",
                review.outcome.value,
                h.text[:80],
                h.id,
            )
        else:
            if review.outcome in (
                SafetyOutcome.DUAL_USE,
                SafetyOutcome.REDACT,
            ):
                _, h.explanation, h.experiment = redact_hypothesis_fields(
                    h.text, h.explanation, h.experiment
                )
            safe.append(h)

    blocked_count = len(hypotheses) - len(safe)
    held_count = len(new_held)

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

    # ``or []`` (not a .get default): a checkpoint restore can carry an
    # explicit None for a field that was unset when the run was serialized.
    existing_decisions: list[dict[str, Any]] = (
        state.get("safety_decisions") or []
    )
    existing_held: list[dict[str, Any]] = state.get("held_for_review") or []

    elapsed = time.time() - start

    await emit_progress(
        state,
        "safety_screen_complete",
        f"Safety screening complete ({blocked_count} blocked)",
        PROGRESS_SAFETY_SCREEN_COMPLETE,
        blocked_count=blocked_count,
        held_count=held_count,
    )

    return {
        "hypotheses": ReplaceHypotheses(safe),
        "safety_decisions": existing_decisions + new_decisions,
        "held_for_review": existing_held + new_held,
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

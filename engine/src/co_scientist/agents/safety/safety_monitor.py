"""Mid-flight safety monitor over the run's own meta-review synthesis.

Safety screening used to happen only at the two ends of a run: the goal at
intake, and the report at the end. Nothing watched the run in between, so a
run whose direction drifted somewhere unsafe kept generating, ranking, and
evolving until the final gate withheld the report -- the whole budget spent
on work that was never publishable, and no signal to the scientist until it
was over (finding J6).

The meta-review overview is what this reads. It is the run's own summary of
where its ideas are going, synthesized from every review and every debate,
which makes it the one artifact that describes the *direction* rather than a
single hypothesis -- and it is re-synthesized on every cycle, so the monitor
runs as often as the direction can change.

The policy is the report gate's policy (``review_content_safety`` at the
``final`` stage), applied earlier rather than tuned separately. Two things
follow, both deliberate: the monitor cannot halt a run whose direction the
final gate would have published, and only the prohibited band halts --
dual-use content is redacted at the boundary, as it always was, not treated
as grounds to stop the science.

The halt itself is written into ``safety_blocked``, which the scheduler
already reads as a hard stop signal (``scheduling.policy_checks``), so a
halted run terminates with ``TerminationReason.SAFETY`` rather than needing
its own exit path.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from co_scientist.constants import PROGRESS_META_REVIEW_COMPLETE
from co_scientist.models import phase_message
from co_scientist.progress import emit_progress
from co_scientist.safety import ContentSafetyReview, review_content_safety
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

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

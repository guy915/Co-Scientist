"""Application adapter for the engine-canonical hypothesis safety policy.

The engine owns the versioned classifier used before tournaments. The app uses
the same implementation for manual admission, persistence, and publication so
there is one policy definition rather than two regex copies that can drift.
"""

from __future__ import annotations

from co_scientist.safety import (
    POLICY_VERSION,
    REDACTED_PLACEHOLDER,
    SafetyOutcome,
    SafetyReview,
    is_blocking_status,
    review_hypothesis_safety,
)

# Leaf module (only imports co_scientist.safety itself), so this is safe at
# module scope unlike app.safety below -- app.safety pulls in app.store,
# and app.store.hypotheses imports this module, which would be a real
# import cycle if app.safety were imported here eagerly instead of lazily
# inside escalate_review.
from app.safety_types import SafetyDecision

# Compatibility names retained for existing API/store callers. They are aliases
# of the canonical engine types, not parallel policy implementations.
HypothesisSafetyOutcome = SafetyOutcome
HypothesisSafetyReview = SafetyReview


def redact_fields(fields: dict[str, str]) -> dict[str, str]:
    """Redact operational hypothesis fields under the canonical policy."""
    sensitive = {"mechanism", "experiment", "experimental_context"}
    return {
        key: (REDACTED_PLACEHOLDER if key in sensitive and value else value)
        for key, value in fields.items()
    }


def _held_baseline_decision(review: SafetyReview) -> SafetyDecision:
    """Build the SafetyDecision baseline for an escalated held review.

    ``decision="hold"`` (not "allow"): the deterministic layer never clears
    a Tier B match, so nothing reaching this function is a clean allow to
    begin with -- see the module docstring on ``escalate_review``. A "hold"
    baseline is what makes ``app.safety``'s severity ordering
    (allow < redact < hold < block) do the right thing automatically: the
    model may raise it to "block", but nothing it reports -- "allow"
    included -- can ever read as lower severity than "hold", so this call
    can raise the verdict and can never clear it.
    """
    return SafetyDecision(
        stage="hypothesis",
        decision="hold",
        reason=review.reason,
        matches=list(review.matches),
        category=review.outcome.value,
        policy_version=review.policy_version,
        requires_review=True,
    )


async def escalate_review(
    review: SafetyReview,
    text: str,
    *,
    run_id: str,
    db_path: str | None = None,
) -> SafetyReview:
    """Give a contextual model a chance to raise a held Tier B verdict.

    Only meaningful for a review the deterministic layer held as UNCERTAIN
    on a Tier B category-only match (``review.needs_context``): the
    deterministic layer never clears such a match to ALLOW by itself (see
    the module docstring in ``co_scientist.safety`` -- an earlier version
    of this design did, and it was a bypass, not a fix). A Tier A certain
    verdict is already at the ceiling escalation could report, since a
    contextual assessment may raise a verdict but never lower one (the same
    "model may raise, never lower" contract ``app.safety.screen_with_
    escalation`` applies to intake/final, reused here rather than
    re-implemented). This call cannot clear a hold to allow either --
    "hold" is baselined, and the severity ordering only lets the model raise
    it to "block". Only human adjudication clears a hold. Callers should
    only invoke this for a ``needs_context`` UNCERTAIN; other reviews pass
    through unchanged if called anyway.

    Fails closed: an offline-backed run, a missing credential, or a
    provider error all leave the held verdict unchanged rather than
    inventing a new one (``screen_with_escalation`` already encodes this).
    Runs no store write and holds no transaction; the caller decides when
    to persist the result.

    Note on the current blast radius: this is wired into the scientist-
    authored-hypothesis admission path only (``app.human_input``). The bulk
    engine-generated hypothesis path (``app.engine_adapter.drain``) still
    screens with the deterministic layer alone and does not call this --
    see that module's own docstring.

    Args:
        review: The deterministic review to (possibly) escalate.
        text: The hypothesis text the review was computed from.
        run_id: Run the hypothesis belongs to, for offline/approval gating.
        db_path: Optional override for the SQLite database path.

    Returns:
        The escalated :class:`SafetyReview`, or ``review`` unchanged when
        escalation does not apply or does not raise the verdict.
    """
    if not review.needs_context or review.outcome != SafetyOutcome.UNCERTAIN:
        return review
    from app.safety import ScreenSubject, screen_with_escalation

    decision = await screen_with_escalation(
        run_id,
        ScreenSubject("hypothesis", text, _held_baseline_decision(review)),
        provider="engine",
        db_path=db_path,
    )
    if decision.decision != "block":
        return review
    return SafetyReview(
        SafetyOutcome.PROHIBITED,
        decision.reason,
        tuple(decision.matches) or review.matches,
        review.policy_version,
        True,
    )


__all__ = [
    "POLICY_VERSION",
    "REDACTED_PLACEHOLDER",
    "HypothesisSafetyOutcome",
    "HypothesisSafetyReview",
    "escalate_review",
    "is_blocking_status",
    "redact_fields",
    "review_hypothesis_safety",
]

"""Application adapter for the engine-canonical hypothesis safety policy.

The engine owns the versioned classifier used before tournaments. The app uses
the same implementation for manual admission, persistence, and publication so
there is one policy definition rather than two regex copies that can drift.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

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

logger = logging.getLogger(__name__)


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

    Two callers reach this today: the scientist-authored-hypothesis
    admission path (``app.human_input``, one hypothesis at a time, awaited
    directly on the request's own event loop) and the bulk engine-generated
    hypothesis path (``app.engine_adapter.drain``, via
    ``escalate_held_hypotheses`` below, which fans a batch of held
    hypotheses out across worker threads so the drain's own synchronous
    call site never has to become async).

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


@dataclasses.dataclass(frozen=True)
class HeldHypothesis:
    """A hypothesis whose deterministic verdict a contextual model may raise.

    Populated only for a fresh review that holds UNCERTAIN with
    ``needs_context=True`` -- the sole shape :func:`escalate_review` acts
    on; every other outcome is already at the ceiling escalation could
    report, or was never held to begin with. Carries the review and the
    exact text it was computed from, so escalation (which must run outside
    any transaction, see :func:`escalate_held_hypotheses`) needs no second
    read of the hypothesis or its store row.
    """

    hyp_id: str
    text: str
    review: SafetyReview


@dataclasses.dataclass(frozen=True)
class EscalatedVerdict:
    """One held hypothesis's outcome after a contextual escalation attempt.

    ``raised`` is True only when the model actually moved the verdict off
    its deterministic hold -- escalation can raise a verdict, never lower
    it (see :func:`escalate_review`), so an unraised verdict is exactly the
    held outcome the first screening pass already persisted and needs no
    further write.
    """

    hyp_id: str
    review: SafetyReview
    raised: bool


# Bounded so a run holding many hypotheses does not open one provider call
# per hypothesis at once. Small because only HELD (UNCERTAIN, needs-context)
# verdicts ever reach here -- the common case is zero or a handful per run,
# never the whole pool, since a clean allow and a Tier A certain block both
# skip escalation entirely (see ``_held_for_escalation`` in
# ``app.hypothesis_screening``).
_ESCALATION_CONCURRENCY = 8


def _escalate_one_on_worker_thread(
    item: HeldHypothesis, run_id: str, db_path: str | None
) -> EscalatedVerdict:
    """Run one hypothesis's escalation on a fresh, thread-local event loop.

    A ``ThreadPoolExecutor`` worker owns no event loop of its own, so
    ``asyncio.run`` here starts and tears down one scoped to this single
    call -- it never touches the run's own per-run event loop (AGENTS.md:
    "No process-global asyncio primitives"). Mirrors how
    ``app.claim_grounding_assess`` drives its own LLM assessor from a
    synchronous ``ThreadPoolExecutor.map`` call, for the same reason: the
    engine drain that calls this is itself synchronous.
    """
    escalated = asyncio.run(
        escalate_review(item.review, item.text, run_id=run_id, db_path=db_path)
    )
    return EscalatedVerdict(
        hyp_id=item.hyp_id,
        review=escalated,
        raised=escalated.outcome != item.review.outcome,
    )


def escalate_held_hypotheses(
    run_id: str,
    held: Sequence[HeldHypothesis],
    *,
    db_path: str | None = None,
) -> list[EscalatedVerdict]:
    """Escalate a batch of held hypotheses, holding no store connection.

    This is the drain's escalation phase: pure provider work, run strictly
    between the drain's two write transactions (see
    ``app.engine_adapter.drain._persist_final_state`` -- never inside
    either, since ``store.transaction`` takes SQLite's write lock the
    instant it opens, and this must never hold that lock across network
    I/O). Synchronous at this boundary so the drain, itself synchronous,
    can call it directly without becoming async end to end; each
    hypothesis's escalation still runs the async ``escalate_review`` to
    completion, just on a worker thread (see
    ``_escalate_one_on_worker_thread``).

    An empty batch (the common case: most runs hold nothing) never spins up
    a thread pool at all.

    Args:
        run_id: Run the held hypotheses belong to.
        held: The batch's held (UNCERTAIN, needs-context) hypotheses.
        db_path: Optional override for the SQLite database path.

    Returns:
        One :class:`EscalatedVerdict` per input hypothesis, in order.
    """
    if not held:
        return []

    logger.info(
        "Escalating %d held hypothesis verdict(s) for run %s.",
        len(held),
        run_id,
    )

    def _escalate_one(item: HeldHypothesis) -> EscalatedVerdict:
        return _escalate_one_on_worker_thread(item, run_id, db_path)

    with ThreadPoolExecutor(
        max_workers=min(_ESCALATION_CONCURRENCY, len(held))
    ) as pool:
        return list(pool.map(_escalate_one, held))


__all__ = [
    "POLICY_VERSION",
    "REDACTED_PLACEHOLDER",
    "EscalatedVerdict",
    "HeldHypothesis",
    "HypothesisSafetyOutcome",
    "HypothesisSafetyReview",
    "escalate_held_hypotheses",
    "escalate_review",
    "is_blocking_status",
    "redact_fields",
    "review_hypothesis_safety",
]

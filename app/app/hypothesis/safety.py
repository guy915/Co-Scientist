"""Application adapter for the engine-canonical hypothesis safety policy."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeAlias

from co_scientist.safety import (
    POLICY_VERSION,
    REDACTED_PLACEHOLDER,
    SafetyOutcome,
    SafetyReview,
    is_blocking_status,
    review_hypothesis_safety,
)

from app.async_bridge import propagate_context, run_in_scoped_loop

logger = logging.getLogger(__name__)

_STAGE = "hypothesis"

_CLEARED_REASON = (
    "matched a sensitive category term, and a contextual assessment read "
    "the surrounding text as descriptive rather than operational"
)


def is_resolvable_hold(review: SafetyReview) -> bool:
    """Return whether this verdict is a Tier B hold this module may resolve.

    The single gate that keeps Tier A out. ``needs_context`` is set only
    by ``co_scientist.safety._resolve_context_hit``, the Tier B resolver;
    a Tier A verdict never carries it, so no combination of model output
    can route one here.

    Args:
        review: The deterministic verdict to test.

    Returns:
        True only for an UNCERTAIN, needs-context (Tier B) verdict.
    """
    return bool(review.needs_context) and (
        review.outcome == SafetyOutcome.UNCERTAIN
    )


def _cleared(review: SafetyReview) -> SafetyReview:
    """Build the allow that a clean contextual assessment produces."""
    return SafetyReview(
        SafetyOutcome.ALLOW,
        _CLEARED_REASON,
        review.matches,
        POLICY_VERSION,
        True,
    )


def _raised(
    review: SafetyReview, reason: str, matches: tuple[str, ...]
) -> SafetyReview:
    """Build the prohibition that an adverse contextual assessment produces."""
    return SafetyReview(
        SafetyOutcome.PROHIBITED,
        reason,
        matches or review.matches,
        POLICY_VERSION,
        True,
    )


async def resolve_hold(
    review: SafetyReview,
    text: str,
    *,
    run_id: str,
    db_path: str | None = None,
) -> SafetyReview:
    """Answer a Tier B hold with a contextual assessment, in either direction.

    Fails closed at every step: anything other than an affirmative,
    successfully-parsed clean assessment returns ``review`` untouched.

    Args:
        review: The deterministic Tier B hold to resolve.
        text: The hypothesis text the hold was computed from.
        run_id: Run the hypothesis belongs to, for offline/approval gating.
        db_path: Optional override for the SQLite database path.

    Returns:
        An ALLOW, a PROHIBITED, or ``review`` unchanged when the
        assessment did not run or did not resolve the question.
    """
    if not is_resolvable_hold(review):
        return review
    import app.safety as app_safety

    decision = await app_safety.assess_hold_contextually(
        run_id, text, _STAGE, db_path=db_path
    )
    if decision is None:
        return review
    if decision.decision == "block":
        return _raised(review, decision.reason, tuple(decision.matches))
    if decision.decision == "allow":
        logger.info(
            "Contextual assessment cleared a held hypothesis in run %s "
            "(category term %s).",
            run_id,
            ", ".join(review.matches) or "unrecorded",
        )
        return _cleared(review)
    return review


# Compatibility names retained for existing API/store callers. They are aliases
# of the canonical engine types, not parallel policy implementations.
HypothesisSafetyOutcome: TypeAlias = SafetyOutcome
HypothesisSafetyReview: TypeAlias = SafetyReview


def redact_fields(fields: dict[str, str]) -> dict[str, str]:
    """Redact operational hypothesis fields under the canonical policy."""
    sensitive = {"mechanism", "experiment", "experimental_context"}
    return {
        key: (REDACTED_PLACEHOLDER if key in sensitive and value else value)
        for key, value in fields.items()
    }


async def escalate_review(
    review: SafetyReview,
    text: str,
    *,
    run_id: str,
    db_path: str | None = None,
) -> SafetyReview:
    """Resolve a held Tier B verdict with a contextual assessment.

    Only meaningful for a review the deterministic layer held as UNCERTAIN
    on a Tier B category-only match (``review.needs_context``). A Tier A
    certain verdict never carries that flag and is refused here, which is
    the property that keeps this from becoming the bypass an earlier
    version of the policy shipped -- see
    ``app.hypothesis.safety``, which owns the resolution and the
    reasoning. Every other review passes through unchanged if called
    anyway.

    Resolution runs in both directions, unlike the intake/final gates.
    Those apply "the model may raise, never lower", because a
    deterministic hit there asserts risk. A Tier B hold asserts the
    opposite -- that the rules *cannot tell* what the sentence asks for --
    so leaving it permanently held made legitimate near-boundary research
    (disaster triage, detection assays, treaty history, research-ethics
    review) indistinguishable from an attack, which is the false-positive
    half of ``J13``. The model may clear such a hold to ALLOW or raise it
    to PROHIBITED; only a Tier B hold is eligible either way.

    Fails closed: an offline-backed run, a disabled contextual screen, a
    missing credential, a provider error, and any answer that is not a
    clean allow or block all leave the held verdict exactly as it was.
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
        The resolved :class:`SafetyReview`, or ``review`` unchanged when
        resolution does not apply or did not answer the question.
    """
    if not review.needs_context or review.outcome != SafetyOutcome.UNCERTAIN:
        return review
    pass

    return await resolve_hold(review, text, run_id=run_id, db_path=db_path)


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

    ``raised`` is True whenever the assessment moved the verdict off its
    deterministic hold, in either direction -- a Tier B hold may be
    cleared to allow as well as raised to prohibited (see
    :func:`escalate_review`). The name predates the downward case and is
    kept because callers key on it; read it as "resolved". An unmoved
    verdict is exactly the held outcome the first screening pass already
    persisted and needs no further write.
    """

    hyp_id: str
    review: SafetyReview
    raised: bool


# Bounded so a run holding many hypotheses does not open one provider call
# per hypothesis at once. Small because only HELD (UNCERTAIN, needs-context)
# verdicts ever reach here -- the common case is zero or a handful per run,
# never the whole pool, since a clean allow and a Tier A certain block both
# skip escalation entirely (see ``_held_for_escalation`` in
# ``app.hypothesis``).
_ESCALATION_CONCURRENCY = 8


def _escalate_one_on_worker_thread(
    item: HeldHypothesis, run_id: str, db_path: str | None
) -> EscalatedVerdict:
    """Run one hypothesis's escalation on a fresh, thread-local event loop.

    A ``ThreadPoolExecutor`` worker owns no event loop of its own, so
    ``run_in_scoped_loop`` here starts and tears down one scoped to this
    single call -- it never touches the run's own per-run event loop
    (AGENTS.md: "No process-global asyncio primitives"), and it closes
    litellm's logging worker with it (see ``app.async_bridge``).
    Mirrors how
    ``app.claims.grounding`` drives its own LLM assessor from a
    synchronous ``ThreadPoolExecutor.map`` call, for the same reason: the
    engine drain that calls this is itself synchronous.
    """
    escalated = run_in_scoped_loop(
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
    ``app.engine_adapter.drain.persist_final_state`` -- never inside
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
        futures = [
            pool.submit(propagate_context(_escalate_one), item) for item in held
        ]
        return [future.result() for future in futures]


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

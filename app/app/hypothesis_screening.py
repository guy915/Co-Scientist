"""Pre-tournament per-hypothesis safety screening (Milestone 6 / M9 wiring).

SSR §4 (Reflection preliminary safety), §10; RGV §9: every hypothesis is
reviewed *before* it enters the tournament, its outcome is persisted as the
hypothesis's ``safety_status``, and any blocking outcome removes it from
ranking and synthesis. A REDACT/DUAL_USE outcome keeps the hypothesis rankable
but rewrites its operational-detail fields with the redaction placeholder
first, with an audit row. Uncertainty routes to safe abstention (see
``hypothesis_safety``), never optimistic inclusion.

The review *logic* lives in :mod:`app.hypothesis_safety` (pure, no store). This
module is the store-aware wiring: the engine drain calls it after persisting
hypotheses so their status is recorded and the report path excludes the
blocked ones, and a scientist-authored hypothesis re-runs the same screen
when it is admitted.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from app import store
from app.hypothesis_safety import (
    EscalatedVerdict,
    HeldHypothesis,
    HypothesisSafetyOutcome,
    HypothesisSafetyReview,
    is_blocking_status,
    redact_fields,
    review_hypothesis_safety,
)

logger = logging.getLogger(__name__)

# Hypothesis fields that carry safety-relevant text, screened together so an
# unsafe mechanism or experiment is caught even when the headline statement is
# benign.
_SCREENED_FIELDS = (
    "statement",
    "mechanism",
    "expected_effect",
    "experimental_context",
)

# Outcomes whose hypotheses stay in the tournament but must have their
# operational-detail fields redacted first (see hypothesis_safety).
_REDACTING_OUTCOMES = frozenset(
    {HypothesisSafetyOutcome.REDACT, HypothesisSafetyOutcome.DUAL_USE}
)

# A blocking-or-redacting outcome is sticky across re-screens once persisted.
# A redaction wipes the trigger text, so a fresh review over the (now
# redacted) text would misread it as ALLOW and silently downgrade the
# recorded status. A certain block (prohibited/ethical_concern) can also
# carry a contextual resolution's raise -- resolution moves a held UNCERTAIN
# up to prohibited (see hypothesis_safety.escalate_review), but the
# hypothesis's underlying text is unchanged, so a fresh deterministic pass
# would re-derive the same Tier B UNCERTAIN it started from and silently
# undo the raise. A resolution in the *other* direction (a hold cleared to
# allow) is deliberately not sticky: for a Tier B hit a re-screen re-holds
# and re-resolves, which reaches the same answer again rather than losing
# it, and paying one assessor call to re-confirm a clear is the cheaper
# mistake than making a clear permanent across text the scientist edited.
# Re-screening the whole pool happens whenever a scientist
# adds an input, so preserving a prior blocking/redacting status keeps the
# audited decision truthful (and skips redundant re-work / duplicate audit
# rows). UNCERTAIN itself is deliberately excluded: it must stay open to a
# fresh escalation attempt on every pass, in case the run's eligibility
# (offline/credential) changes between passes.
_STICKY_STATUSES = frozenset(o.value for o in _REDACTING_OUTCOMES) | frozenset(
    {
        HypothesisSafetyOutcome.PROHIBITED.value,
        HypothesisSafetyOutcome.ETHICAL_CONCERN.value,
    }
)

# Detail columns the redaction rewrites; the statement/expected effect stay so
# the high-level idea remains rankable.
_REDACTED_FIELDS = ("mechanism", "experimental_context")


def hypothesis_text(hyp: Mapping[str, Any]) -> str:
    """Return the combined safety-relevant text of a hypothesis row/payload."""
    parts = [str(hyp.get(field) or "") for field in _SCREENED_FIELDS]
    return "\n".join(part for part in parts if part)


def _apply_redaction(
    run_id: str,
    hyp: Mapping[str, Any],
    review: HypothesisSafetyReview,
    *,
    conn: sqlite3.Connection | None,
    db_path: str | None,
) -> None:
    """Redact a REDACT/DUAL_USE hypothesis's detail fields, with an audit row.

    Persists the redacted columns, mutates the caller's row in place when a
    plain dict (so downstream event stubs and pool bookkeeping see the
    redacted text), and records a ``redact`` audit decision.
    """
    changed = _changed_redacted_fields(hyp)
    if not changed:
        return
    store.redact_hypothesis_fields(
        str(hyp["id"]), changed, conn=conn, db_path=db_path
    )
    if isinstance(hyp, dict):
        hyp.update(changed)
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run_id,
            stage="hypothesis",
            decision="redact",
            reason=f"hypothesis {hyp['id']}: {review.outcome.value} "
            f"({review.reason}); redacted {sorted(changed)}",
            matches=list(review.matches),
        ),
        db_path=db_path,
        conn=conn,
    )
    # Info, not warning: redaction is the screen doing its job on a
    # dual-use idea, one line per redacted hypothesis is a per-item verdict
    # rather than a problem report, and the decision is already persisted as
    # the ``redact`` safety_decision row written just above. As a warning it
    # put a row per flagged idea into a log whose readable window is the
    # newest hundred records.
    logger.info(
        "Redacted detail fields of hypothesis %s: %s",
        hyp["id"],
        review.outcome.value,
    )


def _changed_redacted_fields(hyp: Mapping[str, Any]) -> dict[str, str]:
    """Return the redacted detail fields that actually changed from source."""
    fields = {f: str(hyp.get(f) or "") for f in _REDACTED_FIELDS}
    redacted = redact_fields(fields)
    return {k: v for k, v in redacted.items() if v != fields[k]}


def _hypothesis_decision_row(
    run_id: str,
    hyp_id: Any,
    review: HypothesisSafetyReview,
    decision: str,
) -> store.NewSafetyDecision:
    """Build one hypothesis's ``safety_decisions`` audit row.

    ``decision`` is a parameter rather than always ``"block"`` because a
    contextual assessment can now resolve a held verdict *downward* as
    well as upward (``app.hypothesis_safety_resolve``). Writing a clear
    through a hardcoded ``"block"`` would put a block row in the audit
    trail for a hypothesis that was published -- the adjudication UI reads
    these rows, so that is a lie about what happened, not a label
    mismatch.
    """
    return store.NewSafetyDecision(
        run_id=run_id,
        stage="hypothesis",
        decision=decision,
        reason=(
            f"hypothesis {hyp_id}: {review.outcome.value} ({review.reason})"
        ),
        matches=list(review.matches),
    )


def record_hypothesis_block(
    run_id: str,
    hyp_id: Any,
    review: HypothesisSafetyReview,
    *,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> None:
    """Record the ``safety_decisions`` audit row for a blocked hypothesis.

    Shared by the pre-tournament screen and the report path's legacy
    fallback so the block decision's stage/reason/matches shape has a
    single definition. Both callers only ever record blocks; the
    resolution path builds its own row so it can record a clear.
    """
    store.add_safety_decision(
        _hypothesis_decision_row(run_id, hyp_id, review, "block"),
        db_path=db_path,
        conn=conn,
    )


@dataclasses.dataclass(frozen=True)
class ScreeningResult:
    """Outcome of screening a run's hypotheses before the tournament."""

    # Store ids of hypotheses whose review blocks tournament/synthesis.
    blocked_ids: frozenset[str]
    # Store id -> persisted safety_status (outcome value) for every hypothesis.
    status_by_id: Mapping[str, str]
    # Held UNCERTAIN hypotheses a contextual model may still raise; see
    # ``app.hypothesis_safety.escalate_held_hypotheses``. Populated
    # regardless of whether any escalation actually runs afterwards -- an
    # offline or keyless caller simply never consumes it.
    escalatable: tuple[HeldHypothesis, ...] = ()

    @property
    def blocked_count(self) -> int:
        """Number of hypotheses excluded from the tournament."""
        return len(self.blocked_ids)

    @property
    def screened_count(self) -> int:
        """Total number of hypotheses screened."""
        return len(self.status_by_id)


def screen_hypotheses(
    run_id: str,
    hyps: Sequence[Mapping[str, Any]],
    *,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> ScreeningResult:
    """Screen each hypothesis, persist its safety status, and flag blocked ones.

    For every hypothesis this persists ``safety_status`` (the review outcome)
    on its state row and, for a blocking outcome, records a ``safety_decisions``
    audit row. Benign hypotheses (the common case) are marked ``allow`` and
    pass through. Callers use ``blocked_ids`` to keep those hypotheses out of
    the tournament and synthesis.

    Args:
        run_id: Identifier of the run being screened.
        hyps: The run's hypotheses (store rows or payloads with an ``id`` and
            the screened text fields).
        conn: Optional open connection to reuse (e.g. from ``transaction``).
        db_path: Optional override for the SQLite database path.

    Returns:
        A :class:`ScreeningResult` with the blocked ids, per-id statuses,
        and any hypotheses a contextual escalation may still raise.
    """
    blocked: set[str] = set()
    status_by_id: dict[str, str] = {}
    escalatable: list[HeldHypothesis] = []
    for hyp in hyps:
        screened = _screen_one_hypothesis(
            run_id, hyp, conn=conn, db_path=db_path
        )
        if screened is None:
            continue
        hyp_id, status, is_blocked, held = screened
        status_by_id[hyp_id] = status
        if is_blocked:
            blocked.add(hyp_id)
        if held is not None:
            escalatable.append(held)
    return ScreeningResult(
        blocked_ids=frozenset(blocked),
        status_by_id=status_by_id,
        escalatable=tuple(escalatable),
    )


def _held_for_escalation(
    hyp_id: str, text: str, review: HypothesisSafetyReview
) -> HeldHypothesis | None:
    """Return the escalation candidate for a fresh held review, or None.

    Only a Tier B category-only match reaches UNCERTAIN with
    ``needs_context=True`` -- see ``hypothesis_safety.escalate_review`` --
    so that is the sole shape worth handing to the drain's escalation
    phase; every other outcome is either already at the ceiling escalation
    could report or was never held in the first place.
    """
    if review.outcome is not HypothesisSafetyOutcome.UNCERTAIN:
        return None
    if not review.needs_context:
        return None
    return HeldHypothesis(hyp_id=hyp_id, text=text, review=review)


def _screen_one_hypothesis(
    run_id: str,
    hyp: Mapping[str, Any],
    *,
    conn: sqlite3.Connection | None,
    db_path: str | None,
) -> tuple[str, str, bool, HeldHypothesis | None] | None:
    """Screen one hypothesis, persist its status, and report block/redact.

    Returns ``(hyp_id, status, blocked, escalatable)``, or None when the
    hypothesis carries no id. ``escalatable`` is populated only for a fresh
    held UNCERTAIN review a contextual escalation may still raise -- see
    ``_held_for_escalation``.
    """
    hyp_id = str(hyp.get("id") or "")
    if not hyp_id:
        return None
    # A hypothesis already redacted or blocked keeps its recorded status;
    # see the ``_STICKY_STATUSES`` comment for why both kinds are sticky.
    prior = str(hyp.get("safety_status") or "")
    if prior in _STICKY_STATUSES:
        return hyp_id, prior, is_blocking_status(prior), None
    text = hypothesis_text(hyp)
    review = review_hypothesis_safety(text)
    store.update_hypothesis_state(
        hyp_id,
        store.HypothesisStateChanges(safety_status=review.outcome.value),
        db_path=db_path,
        conn=conn,
    )
    if review.outcome in _REDACTING_OUTCOMES:
        _apply_redaction(run_id, hyp, review, conn=conn, db_path=db_path)
    if review.blocks_tournament:
        record_hypothesis_block(
            run_id, hyp_id, review, conn=conn, db_path=db_path
        )
        logger.warning(
            "Excluding hypothesis %s from the tournament: %s",
            hyp_id,
            review.outcome.value,
        )
    return (
        hyp_id,
        review.outcome.value,
        review.blocks_tournament,
        _held_for_escalation(hyp_id, text, review),
    )


def persist_escalated_verdicts(
    run_id: str,
    verdicts: Sequence[EscalatedVerdict],
    *,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> int:
    """Persist every verdict a contextual escalation actually raised.

    Pure database work -- the escalation itself (an async model call per
    held hypothesis) has already run, outside any transaction; see
    ``app.hypothesis_safety.escalate_held_hypotheses`` and
    ``app.engine_adapter.drain._persist_final_state`` for the transaction
    boundaries this must stay inside of. A verdict the model did not raise
    is skipped: the deterministic ``hold`` status and its audit row are
    already persisted from the first screening pass over that hypothesis,
    and re-recording an unchanged verdict would only duplicate that row.

    Args:
        run_id: Identifier of the run being screened.
        verdicts: Escalation outcomes to persist, raised or not.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
        db_path: Optional override for the SQLite database path.

    Returns:
        The number of verdicts actually raised and persisted.
    """
    resolved = 0
    for verdict in verdicts:
        if not verdict.raised:
            continue
        _persist_one_resolved_verdict(run_id, verdict, conn, db_path)
        resolved += 1
    return resolved


def _persist_one_resolved_verdict(
    run_id: str,
    verdict: EscalatedVerdict,
    conn: sqlite3.Connection | None,
    db_path: str | None,
) -> None:
    """Persist one resolved verdict's status and its audit row."""
    outcome = verdict.review.outcome.value
    blocking = is_blocking_status(outcome)
    store.update_hypothesis_state(
        verdict.hyp_id,
        store.HypothesisStateChanges(safety_status=outcome),
        db_path=db_path,
        conn=conn,
    )
    store.add_safety_decision(
        _hypothesis_decision_row(
            run_id,
            verdict.hyp_id,
            verdict.review,
            "block" if blocking else "allow",
        ),
        db_path=db_path,
        conn=conn,
    )
    logger.warning(
        "Contextual assessment resolved held hypothesis %s to %s.",
        verdict.hyp_id,
        outcome,
    )

"""Pre-tournament per-hypothesis safety screening (Milestone 6 / M9 wiring).

SSR §4 (Reflection preliminary safety), §10; RGV §9: every hypothesis is
reviewed *before* it enters the tournament, its outcome is persisted as the
hypothesis's ``safety_status``, and any blocking outcome removes it from
ranking and synthesis. A REDACT/DUAL_USE outcome keeps the hypothesis rankable
but rewrites its operational-detail fields with the redaction placeholder
first, with an audit row. Uncertainty routes to safe abstention (see
``hypothesis_safety``), never optimistic inclusion.

The review *logic* lives in :mod:`app.hypothesis_safety` (pure, no store). This
module is the store-aware wiring both providers share: the mock calls it after
reflection and drops blocked hypotheses before the tournament seeds; the
real-engine drain calls it after persisting hypotheses so their status is
recorded and the report path excludes the blocked ones.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from app import store
from app.hypothesis_safety import (
    HypothesisSafetyOutcome,
    HypothesisSafetyReview,
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

# A redaction is sticky across re-screens: once a hypothesis's detail fields
# are redacted its trigger text is gone, so a fresh review would read ALLOW and
# silently downgrade the recorded status. Re-screening the whole pool happens
# whenever a scientist adds an input, so preserving a prior redacting status
# keeps the audited decision truthful (and skips redundant re-work).
_STICKY_STATUSES = frozenset(o.value for o in _REDACTING_OUTCOMES)

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

    Persists the redacted columns, mutates the caller's row in place when it is
    a plain dict (so downstream event stubs and pool bookkeeping see the
    redacted text, not the original), and records a ``redact`` audit decision.
    """
    fields = {f: str(hyp.get(f) or "") for f in _REDACTED_FIELDS}
    redacted = redact_fields(fields)
    changed = {k: v for k, v in redacted.items() if v != fields[k]}
    if not changed:
        return
    store.redact_hypothesis_fields(
        str(hyp["id"]), changed, conn=conn, db_path=db_path
    )
    if isinstance(hyp, dict):
        hyp.update(changed)
    store.add_safety_decision(
        run_id,
        stage="hypothesis",
        decision="redact",
        reason=(
            f"hypothesis {hyp['id']}: {review.outcome.value} "
            f"({review.reason}); redacted {sorted(changed)}"
        ),
        matches=list(review.matches),
        conn=conn,
        db_path=db_path,
    )
    logger.warning(
        "Redacted detail fields of hypothesis %s: %s",
        hyp["id"],
        review.outcome.value,
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

    Shared by the pre-tournament screen and the report path's legacy fallback
    so the block decision's stage/reason/matches shape has a single definition.

    Args:
        run_id: Identifier of the run being screened.
        hyp_id: The blocked hypothesis's id, interpolated into the reason.
        review: The blocking safety review supplying the outcome and matches.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
        db_path: Optional override for the SQLite database path.
    """
    store.add_safety_decision(
        run_id,
        stage="hypothesis",
        decision="block",
        reason=(
            f"hypothesis {hyp_id}: {review.outcome.value} ({review.reason})"
        ),
        matches=list(review.matches),
        conn=conn,
        db_path=db_path,
    )


@dataclasses.dataclass(frozen=True)
class ScreeningResult:
    """Outcome of screening a run's hypotheses before the tournament."""

    # Store ids of hypotheses whose review blocks tournament/synthesis.
    blocked_ids: frozenset[str]
    # Store id -> persisted safety_status (outcome value) for every hypothesis.
    status_by_id: Mapping[str, str]

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
        A :class:`ScreeningResult` with the blocked ids and per-id statuses.
    """
    blocked: set[str] = set()
    status_by_id: dict[str, str] = {}
    for hyp in hyps:
        hyp_id = str(hyp.get("id") or "")
        if not hyp_id:
            continue
        # A hypothesis already redacted keeps its recorded status: its trigger
        # text is gone, so re-reviewing it would falsely relax it to ALLOW.
        prior = str(hyp.get("safety_status") or "")
        if prior in _STICKY_STATUSES:
            status_by_id[hyp_id] = prior
            continue
        review = review_hypothesis_safety(hypothesis_text(hyp))
        status_by_id[hyp_id] = review.outcome.value
        store.update_hypothesis_state(
            hyp_id,
            safety_status=review.outcome.value,
            conn=conn,
            db_path=db_path,
        )
        if review.outcome in _REDACTING_OUTCOMES:
            _apply_redaction(run_id, hyp, review, conn=conn, db_path=db_path)
        if review.blocks_tournament:
            blocked.add(hyp_id)
            record_hypothesis_block(
                run_id, hyp_id, review, conn=conn, db_path=db_path
            )
            logger.warning(
                "Excluding hypothesis %s from the tournament: %s",
                hyp_id,
                review.outcome.value,
            )
    return ScreeningResult(
        blocked_ids=frozenset(blocked), status_by_id=status_by_id
    )

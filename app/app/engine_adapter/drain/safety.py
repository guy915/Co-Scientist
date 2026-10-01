"""Held-for-review persistence for the final-state drain.

The engine's safety screen holds UNCERTAIN hypotheses in
``held_for_review``, out of the ranked pool; without this step they would
vanish at the app boundary, never inspected or adjudicated. Each becomes a
``hold`` decision at the hypothesis stage carrying the idea's identity and
the screen's rationale, reviewable through the existing safety-adjudication
path.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping
from typing import Any

from app import store
from app.hypothesis_safety import POLICY_VERSION, HypothesisSafetyOutcome

logger = logging.getLogger(__name__)

# How much of a held hypothesis's statement its decision row carries: enough
# for a reviewer to recognize the idea, not so much the audit trail reprints
# it. Matches the text-prefix width of the engine's own audit entries.
_HELD_TEXT_PREFIX_CHARS = 120


def _final_state_list(
    final_state: dict[str, Any], key: str
) -> list[dict[str, Any]]:
    """Return a list-valued key from the engine's final state, or empty."""
    return final_state.get(key) or []


def _engine_audit_by_hypothesis_id(
    final_state: dict[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Index the engine's per-hypothesis safety audit entries by id.

    The safety screen records one ``safety_decisions`` entry per blocked or
    held hypothesis; the drain joins a held hypothesis to its entry for the
    screen's rationale, matches, and policy version.
    """
    return {
        str(item.get("hypothesis_id")): item
        for item in _final_state_list(final_state, "safety_decisions")
        if isinstance(item, Mapping) and item.get("hypothesis_id")
    }


def _held_decision_reason(
    hyp_id: str,
    outcome: str,
    text: str,
    audit: Mapping[str, Any],
) -> str:
    """Build the audit reason for one held hypothesis.

    Follows the shape of the other hypothesis-stage rows (``hypothesis
    <id>: <outcome> (<rationale>)``), appending a prefix of the held idea's
    text: the engine keeps held hypotheses out of the pool, so no hypothesis
    row is persisted for one and its decision row is the only copy of it.
    """
    engine_reason = str(audit.get("reason") or "") or (
        "the safety screen held this hypothesis for manual review"
    )
    reason = f"hypothesis {hyp_id}: {outcome} ({engine_reason})"
    prefix = text[:_HELD_TEXT_PREFIX_CHARS]
    if prefix:
        reason = f"{reason}; idea: {prefix}"
    return reason


def _held_decision(
    run_id: str,
    entry: Mapping[str, Any],
    audit_by_id: Mapping[str, Mapping[str, Any]],
) -> store.NewSafetyDecision | None:
    """Build one held-for-review decision row from a held entry.

    Args:
        run_id: Run the drained final state belongs to.
        entry: One ``held_for_review`` entry (a hypothesis dict).
        audit_by_id: Engine audit entries keyed by hypothesis id.

    Returns:
        The decision to record, or None when the entry carries neither an
        id nor text and so cannot be identified for review.
    """
    hyp_id = str(entry.get("id") or "")
    text = str(entry.get("text") or "")
    if not hyp_id and not text:
        return None
    audit = audit_by_id.get(hyp_id, {})
    outcome = str(
        entry.get("safety_status") or HypothesisSafetyOutcome.UNCERTAIN.value
    )
    return store.NewSafetyDecision(
        run_id=run_id,
        stage="hypothesis",
        decision="hold",
        reason=_held_decision_reason(hyp_id, outcome, text, audit),
        matches=[str(m) for m in (audit.get("matches") or [])],
        category=outcome,
        policy_version=(
            str(audit.get("policy_version") or "") or POLICY_VERSION
        ),
        requires_review=True,
        assessor="engine:safety_screen",
    )


def _persist_held_for_review(
    run_id: str,
    final_state: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist a reviewable decision row for each held hypothesis.

    Args:
        run_id: Run the drained final state belongs to.
        final_state: The engine's final state (held entries are plain dicts).
        conn: Open connection of the caller's transaction.
    """
    held = _final_state_list(final_state, "held_for_review")
    if not held:
        return
    audit_by_id = _engine_audit_by_hypothesis_id(final_state)
    recorded = 0
    for entry in held:
        if not isinstance(entry, Mapping):
            continue
        decision = _held_decision(run_id, entry, audit_by_id)
        if decision is None:
            continue
        store.add_safety_decision(decision, conn=conn)
        recorded += 1
    logger.info(
        "Recorded %d held-for-review decision(s) for run %s.",
        recorded,
        run_id,
    )

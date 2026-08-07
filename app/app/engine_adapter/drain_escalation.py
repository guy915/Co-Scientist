"""Contextual safety-verdict escalation for the final-state drain.

Extracted from ``app.engine_adapter.drain`` to keep that module within the
size cap. This is phases 2 and 3 of the drain's safety handling (see
``drain._persist_final_state`` for the full three-phase split):

1. Deterministic screening and persistence already happened, inside the
   drain's *first* transaction (``hypothesis_screening.screen_hypotheses``,
   called from ``drain._screen_and_collect_grounding_inputs``).
2. ``_escalate_screened_hypotheses`` below runs every hypothesis the screen
   held as UNCERTAIN (``ScreeningResult.escalatable``) through contextual
   escalation -- provider work only, holding no store connection.
3. ``_persist_escalated_verdicts`` below persists whatever escalation
   raised. Pure database work, called from inside the drain's *second*
   transaction (alongside claim grounding, matches, and proximity) only
   once phase 2 has fully returned.

``drain`` re-exports both names, so the original module namespace keeps
resolving.
"""

from __future__ import annotations

import sqlite3

from app.hypothesis_safety import (
    EscalatedVerdict,
    HeldHypothesis,
    escalate_held_hypotheses,
)
from app.hypothesis_screening import persist_escalated_verdicts


def _escalate_screened_hypotheses(
    run_id: str,
    escalatable: tuple[HeldHypothesis, ...],
    db_path: str | None,
) -> list[EscalatedVerdict]:
    """Run the drain's escalation phase: provider work only, no store handle.

    Must run strictly between the drain's two write transactions -- never
    inside either, since ``store.transaction`` takes SQLite's write lock
    the instant it opens, and this must never hold that lock across
    network I/O.

    Args:
        run_id: Run the drained final state belongs to.
        escalatable: The batch of held (UNCERTAIN, needs-context)
            hypotheses the first transaction's screening pass collected.
        db_path: Optional override for the SQLite database path.

    Returns:
        One :class:`~app.hypothesis_safety.EscalatedVerdict` per input.
    """
    return escalate_held_hypotheses(run_id, escalatable, db_path=db_path)


def _persist_escalated_verdicts(
    run_id: str,
    escalated: list[EscalatedVerdict],
    conn: sqlite3.Connection,
) -> int:
    """Persist any verdict a contextual escalation raised. Pure DB work.

    Args:
        run_id: Run the drained final state belongs to.
        escalated: The escalation phase's per-hypothesis outcomes.
        conn: Open connection of the caller's transaction.

    Returns:
        The number of verdicts actually raised and persisted.
    """
    return persist_escalated_verdicts(run_id, escalated, conn=conn)

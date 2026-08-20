"""Persisting what a run's deep-research phase did.

The engine's literature review can go back for the questions its reading
left open, and its deep reviews can do the same for one hypothesis's own
claim (``co_scientist.research``). Each research request carries
everything it did out on the final state as plain data -- every question
asked, every query issued against every source, the ranking each one
returned, and which of those results the evidence budget could afford to
read -- and the state accumulates one ledger per request rather than
keeping only the last researcher's.

This module is where that lands in the store. It is deliberately thin --
the mapping from a research result to insertable rows is
``app.research_provenance``, and the ledger's own decoding belongs to the
engine package that wrote it -- so the only judgement here is *when* to
write, which is inside the drain's first transaction, before the evidence
rows that point at these calls.

A run that did no research leaves no ledger, which is not a gap: express
and standard runs do not buy the phase, and neither does a run whose
literature tools were unreachable.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from co_scientist.research import result_from_dict

from app import research_provenance, store

logger = logging.getLogger(__name__)


def _persist_retrieval_calls(
    run_id: str,
    final_state: dict[str, Any],
    conn: sqlite3.Connection,
) -> int:
    """Write this run's searches, if it made any.

    Args:
        run_id: The run being drained.
        final_state: The engine's accumulated final state.
        conn: Open connection of the caller's transaction.

    Returns:
        How many rows were inserted -- fewer than the ledgers hold
        whenever a resumed run re-offered searches it already paid for,
        or whenever two researchers issued the same search, which the
        content-addressed id makes one row rather than two.
    """
    ledgers = final_state.get("research_ledgers")
    if not isinstance(ledgers, list):
        return 0
    rows = [
        row
        for ledger in ledgers
        if isinstance(ledger, dict) and ledger
        for row in research_provenance.retrieval_call_rows(
            run_id, result_from_dict(ledger)
        )
    ]
    if not rows:
        return 0
    written = store.add_retrieval_calls(rows, conn=conn)
    logger.info(
        "Recorded %s of %s research searches for run %s",
        written,
        len(rows),
        run_id,
    )
    return written

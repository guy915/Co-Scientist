"""Durable structured facts and contradictions (audit G14).

Store I/O for the ``knowledge_facts`` table (schema in
``schema_knowledge_facts.py``): one durable, per-run row per settled
claim-evidence edge. See ``app.knowledge_facts`` for how a row is derived.
Split out of ``app.store.records`` so the derivation feature stays
independently nameable; re-exported from ``app.store`` like every other
record module.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.store.db import _now, _use_conn
from app.store.records_support import _list_by_run


def replace_knowledge_facts(
    run_id: str,
    facts: list[dict[str, Any]],
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Replace a run's knowledge-facts rows wholesale.

    Matches the ``claim_evidence``/``run_metrics`` pattern used elsewhere in
    this store: rows are fully reconstructed from the claim-evidence graph
    each time a report is finalized, so re-finalizing a resumed run never
    accumulates duplicates.

    Args:
        run_id: Owning run.
        facts: Rows as built by
            ``app.knowledge_facts.derive_knowledge_facts`` --
            ``{hypothesis_id, evidence_id, kind, statement, entities,
            state}`` dicts.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute("DELETE FROM knowledge_facts WHERE run_id = ?", (run_id,))
        now = _now()
        conn.executemany(
            "INSERT INTO knowledge_facts (run_id, hypothesis_id, "
            "evidence_id, kind, statement, entities_json, state, "
            "created_at) VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    run_id,
                    fact["hypothesis_id"],
                    fact.get("evidence_id"),
                    fact["kind"],
                    fact["statement"],
                    json.dumps(fact.get("entities") or []),
                    fact["state"],
                    now,
                )
                for fact in facts
            ],
        )


def list_knowledge_facts(
    run_id: str,
    *,
    kind: str | None = None,
    entity: str | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's durable facts/contradictions, decoded and filterable.

    Args:
        run_id: Owning run.
        kind: Optional filter to ``"fact"`` or ``"contradiction"``.
        entity: Optional case-insensitive entity-name filter.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        Rows oldest first, each with ``entities`` decoded to a list.
    """
    rows = _list_by_run("knowledge_facts", run_id, db_path, conn)
    for row in rows:
        row["entities"] = json.loads(row.pop("entities_json") or "[]")
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    if entity is not None:
        needle = entity.strip().upper()
        rows = [r for r in rows if needle in {e.upper() for e in r["entities"]}]
    return rows

"""Safety-gate decision rows for a run.

Split out of ``app.store.records`` to keep that module within the size
cap. Holds the insert/list helpers for safety-gate decisions plus the
human-adjudication resolution path. Every name is re-exported from
``app.store.records``, so callers and monkeypatching tests are
unaffected.

Every helper accepts ``db_path`` (override for the SQLite database path)
and, where applicable, ``conn`` (an open connection to reuse, e.g. from
``transaction``).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn
from app.store.records_support import _list_by_run


@dataclass(frozen=True)
class NewSafetyDecision:
    """One safety-gate decision to record, mirroring the row.

    ``stage`` is the gate that ran ('intake', 'hypothesis', or 'final'),
    ``decision`` its verdict, and ``matches`` the policy patterns that
    fired. ``requires_review`` marks a decision a human must adjudicate,
    and ``assessor`` is the provenance id of whatever produced it.
    """

    run_id: str
    stage: str
    decision: str
    reason: str
    matches: list[str]
    category: str | None = None
    policy_version: str | None = None
    risk_domains: list[str] | None = None
    requires_review: bool = False
    assessor: str | None = None


def add_safety_decision(
    decision: NewSafetyDecision,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Record a safety-gate decision.

    Args:
        decision: The decision to record (see
            :class:`NewSafetyDecision`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO safety_decisions (run_id, stage, decision, reason, "
            "matches_json, category, policy_version, risk_domains_json, "
            "requires_review, assessor, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                decision.run_id,
                decision.stage,
                decision.decision,
                decision.reason,
                json.dumps(decision.matches),
                decision.category,
                decision.policy_version,
                json.dumps(decision.risk_domains or []),
                1 if decision.requires_review else 0,
                decision.assessor,
                _now(),
            ),
        )


def list_safety_decisions(
    run_id: str, db_path: str | None = None
) -> list[dict[str, Any]]:
    """Return a run's safety decisions with the matches list decoded."""
    out = []
    for d in _list_by_run("safety_decisions", run_id, db_path):
        # Expose decoded 'matches' instead of the raw matches_json column.
        d["matches"] = json.loads(d.pop("matches_json") or "[]")
        d["risk_domains"] = json.loads(d.pop("risk_domains_json", None) or "[]")
        d["requires_review"] = bool(d.get("requires_review"))
        out.append(d)
    return out


def resolve_safety_decision(
    run_id: str,
    decision_id: int,
    resolution: str,
    resolved_by: str,
    db_path: str | None = None,
) -> bool:
    """Resolve one held/redacted safety decision exactly once."""
    if resolution not in {"approved", "rejected"}:
        raise ValueError("resolution must be approved or rejected")
    with _use_conn(None, db_path) as conn:
        cursor = conn.execute(
            "UPDATE safety_decisions SET resolution=?, resolved_by=?, "
            "resolved_at=? WHERE id=? AND run_id=? AND requires_review=1 "
            "AND resolution IS NULL",
            (resolution, resolved_by, _now(), decision_id, run_id),
        )
        return cursor.rowcount == 1


def safety_stage_is_approved(
    run_id: str,
    stage: str,
    policy_version: str,
    db_path: str | None = None,
) -> bool:
    """Return whether a reviewer approved the latest matching policy stage."""
    with _use_conn(None, db_path) as conn:
        row = conn.execute(
            "SELECT resolution FROM safety_decisions WHERE run_id=? AND "
            "stage=? AND policy_version=? ORDER BY id DESC LIMIT 1",
            (run_id, stage, policy_version),
        ).fetchone()
    return bool(row and row["resolution"] == "approved")

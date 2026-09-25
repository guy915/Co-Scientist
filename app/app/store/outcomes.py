"""Append-only researcher-recorded hypothesis outcomes."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn, transaction
from app.store.events import _append_event


class InvalidOutcomeReferencesError(ValueError):
    """A hypothesis or evidence reference does not belong to the run."""


@dataclass(frozen=True)
class NewHypothesisOutcome:
    """Fields supplied by a researcher for one measured outcome."""

    run_id: str
    hypothesis_id: str
    method_protocol: str
    conditions: str
    measured_observation: str
    units: str | None
    controls: str
    interpretation: str
    referenced_evidence_ids: list[str]
    author: str


def _decode_outcome(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    outcome = dict(row)
    outcome["referenced_evidence_ids"] = json.loads(
        outcome.pop("referenced_evidence_ids_json")
    )
    outcome["hypothesis_snapshot"] = json.loads(
        outcome.pop("hypothesis_snapshot_json", "{}")
    )
    outcome["referenced_evidence"] = json.loads(
        outcome.pop("referenced_evidence_snapshots_json", "[]")
    )
    return outcome


def _hypothesis_snapshot(
    conn: sqlite3.Connection, outcome: NewHypothesisOutcome
) -> dict[str, str]:
    """Read the hypothesis display identity while it belongs to this run."""
    row = conn.execute(
        "SELECT title, statement FROM hypotheses WHERE id=? AND run_id=?",
        (outcome.hypothesis_id, outcome.run_id),
    ).fetchone()
    if row is None:
        raise InvalidOutcomeReferencesError
    return {"title": row["title"], "statement": row["statement"]}


def _evidence_snapshots(
    conn: sqlite3.Connection, run_id: str, evidence_ids: list[str]
) -> list[dict[str, Any]]:
    """Validate evidence ownership and capture only stable source metadata."""
    if not evidence_ids:
        return []
    placeholders = ",".join("?" for _ in evidence_ids)
    rows = conn.execute(
        "SELECT id, title, source, url, doi, pmid, sha256 FROM evidence "
        f"WHERE run_id=? AND id IN ({placeholders})",
        (run_id, *evidence_ids),
    ).fetchall()
    evidence_by_id = {row["id"]: row for row in rows}
    if set(evidence_by_id) != set(evidence_ids):
        raise InvalidOutcomeReferencesError
    fields = ("id", "title", "source", "url", "doi", "pmid", "sha256")
    return [
        {key: evidence_by_id[evidence_id][key] for key in fields}
        for evidence_id in evidence_ids
    ]


def _insert_outcome(
    conn: sqlite3.Connection,
    record: dict[str, Any],
) -> None:
    """Persist the outcome and its immutable identity snapshots."""
    conn.execute(
        "INSERT INTO hypothesis_outcomes (id, run_id, hypothesis_id, "
        "method_protocol, conditions, measured_observation, units, "
        "controls, interpretation, referenced_evidence_ids_json, "
        "hypothesis_snapshot_json, referenced_evidence_snapshots_json, "
        "author, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            record["id"],
            record["run_id"],
            record["hypothesis_id"],
            record["method_protocol"],
            record["conditions"],
            record["measured_observation"],
            record["units"],
            record["controls"],
            record["interpretation"],
            json.dumps(record["referenced_evidence_ids"]),
            json.dumps(record["hypothesis_snapshot"]),
            json.dumps(record["referenced_evidence"]),
            record["author"],
            record["recorded_at"],
        ),
    )


def _append_outcome_event(
    conn: sqlite3.Connection,
    record: dict[str, Any],
) -> None:
    """Write only metadata to the replay log; the observation stays private."""
    _append_event(
        conn,
        record["run_id"],
        "scientist.outcome",
        {
            "outcome_id": record["id"],
            "hypothesis_id": record["hypothesis_id"],
            "author": record["author"],
            "recorded_at": record["recorded_at"],
        },
        record["recorded_at"],
    )


def _outcome_response(
    outcome: NewHypothesisOutcome,
    outcome_id: str,
    recorded_at: float,
    evidence_ids: list[str],
    snapshots: dict[str, Any],
) -> dict[str, Any]:
    """Shape the appended outcome for the POST response."""
    return {
        "id": outcome_id,
        "run_id": outcome.run_id,
        "hypothesis_id": outcome.hypothesis_id,
        "method_protocol": outcome.method_protocol,
        "conditions": outcome.conditions,
        "measured_observation": outcome.measured_observation,
        "units": outcome.units,
        "controls": outcome.controls,
        "interpretation": outcome.interpretation,
        "referenced_evidence_ids": evidence_ids,
        **snapshots,
        "author": outcome.author,
        "recorded_at": recorded_at,
    }


def add_hypothesis_outcome(
    outcome: NewHypothesisOutcome,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Append an outcome and its metadata-only replay event atomically."""
    outcome_id = str(uuid.uuid4())
    recorded_at = _now()
    evidence_ids = list(outcome.referenced_evidence_ids)
    with transaction(db_path) as conn:
        snapshots = {
            "hypothesis_snapshot": _hypothesis_snapshot(conn, outcome),
            "referenced_evidence": _evidence_snapshots(
                conn, outcome.run_id, evidence_ids
            ),
        }
        record = _outcome_response(
            outcome, outcome_id, recorded_at, evidence_ids, snapshots
        )
        _insert_outcome(conn, record)
        _append_outcome_event(conn, record)
    return record


def list_hypothesis_outcomes(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return outcomes in append order for one run."""
    with _use_conn(conn, db_path) as conn:
        rows = conn.execute(
            "SELECT id, run_id, hypothesis_id, method_protocol, conditions, "
            "measured_observation, units, controls, interpretation, "
            "referenced_evidence_ids_json, hypothesis_snapshot_json, "
            "referenced_evidence_snapshots_json, author, recorded_at "
            "FROM hypothesis_outcomes WHERE run_id=? "
            "ORDER BY recorded_at ASC, id ASC",
            (run_id,),
        ).fetchall()
        return [_decode_outcome(row) for row in rows]


def get_hypothesis_outcome(
    run_id: str,
    outcome_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Return one immutable outcome only when it belongs to the given run."""
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT id, run_id, hypothesis_id, method_protocol, conditions, "
            "measured_observation, units, controls, interpretation, "
            "referenced_evidence_ids_json, hypothesis_snapshot_json, "
            "referenced_evidence_snapshots_json, author, recorded_at "
            "FROM hypothesis_outcomes WHERE run_id=? AND id=?",
            (run_id, outcome_id),
        ).fetchone()
        return _decode_outcome(row) if row is not None else None

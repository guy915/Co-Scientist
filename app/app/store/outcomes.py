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
        hypothesis = conn.execute(
            "SELECT title, statement FROM hypotheses WHERE id=? AND run_id=?",
            (outcome.hypothesis_id, outcome.run_id),
        ).fetchone()
        if hypothesis is None:
            raise InvalidOutcomeReferencesError
        hypothesis_snapshot = {
            "title": hypothesis["title"],
            "statement": hypothesis["statement"],
        }

        referenced_evidence: list[dict[str, Any]] = []
        if evidence_ids:
            placeholders = ",".join("?" for _ in evidence_ids)
            rows = conn.execute(
                f"SELECT id, title, source, url, doi, pmid, sha256 "
                f"FROM evidence WHERE run_id=? "
                f"AND id IN ({placeholders})",
                (outcome.run_id, *evidence_ids),
            ).fetchall()
            evidence_by_id = {row["id"]: row for row in rows}
            if set(evidence_by_id) != set(evidence_ids):
                raise InvalidOutcomeReferencesError
            referenced_evidence = [
                {
                    key: evidence_by_id[evidence_id][key]
                    for key in (
                        "id",
                        "title",
                        "source",
                        "url",
                        "doi",
                        "pmid",
                        "sha256",
                    )
                }
                for evidence_id in evidence_ids
            ]

        conn.execute(
            "INSERT INTO hypothesis_outcomes (id, run_id, hypothesis_id, "
            "method_protocol, conditions, measured_observation, units, "
            "controls, interpretation, referenced_evidence_ids_json, "
            "hypothesis_snapshot_json, referenced_evidence_snapshots_json, "
            "author, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                outcome_id,
                outcome.run_id,
                outcome.hypothesis_id,
                outcome.method_protocol,
                outcome.conditions,
                outcome.measured_observation,
                outcome.units,
                outcome.controls,
                outcome.interpretation,
                json.dumps(evidence_ids),
                json.dumps(hypothesis_snapshot),
                json.dumps(referenced_evidence),
                outcome.author,
                recorded_at,
            ),
        )
        _append_event(
            conn,
            outcome.run_id,
            "scientist.outcome",
            {
                "outcome_id": outcome_id,
                "hypothesis_id": outcome.hypothesis_id,
                "author": outcome.author,
                "recorded_at": recorded_at,
            },
            recorded_at,
        )

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
        "hypothesis_snapshot": hypothesis_snapshot,
        "referenced_evidence": referenced_evidence,
        "author": outcome.author,
        "recorded_at": recorded_at,
    }


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

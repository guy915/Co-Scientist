from __future__ import annotations

import gzip
import json
import logging
import sqlite3
from importlib import resources
from typing import Any

from app.store import db
from app.store import runs_views as views
from app.store.models import DEMO_CLIENT_ID

logger = logging.getLogger(__name__)

# Tables in foreign-key-safe insert order, as written into the snapshot.
_RUN_SCOPED = (
    "hypotheses",
    "evidence",
    "citations",
    "reviews",
    "matches",
    "claim_evidence",
    "proximity_edges",
    "run_events",
    "run_metrics",
    "reports",
    "messages",
)


def _read_snapshot() -> dict[str, Any]:
    raw = resources.files("app").joinpath("data/demo_runs.json.gz").read_bytes()
    snapshot: dict[str, Any] = json.loads(gzip.decompress(raw))
    return snapshot


def _is_current(run: Any, version: int, db_path: str | None) -> bool:
    """A demo run is current when its example chat, report and version stamps match."""
    interview_id = str(run.config.get("interview_id") or "")
    with db.connect(db_path) as conn:
        interview = conn.execute(
            "SELECT 1 FROM interviews WHERE id=? AND client_id=?",
            (interview_id, DEMO_CLIENT_ID),
        ).fetchone()
        report = conn.execute("SELECT 1 FROM reports WHERE run_id=?", (run.id,)).fetchone()
    return bool(
        interview
        and report
        and run.config.get("demo_seed_version") == version
        and run.config.get("example_chat_version") == version
    )


def _insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    columns = ", ".join(row)
    marks = ", ".join("?" * len(row))
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", list(row.values()))


def _load_run(
    snapshot: dict[str, Any], run_row: dict[str, Any], stale: Any, db_path: str | None
) -> None:
    tables = snapshot["tables"]
    snapshot_id = run_row["id"]
    run_id = stale.id if stale else snapshot_id
    interview_id = json.loads(run_row["config_json"])["interview_id"]
    with db.transaction(db_path) as conn:
        if stale:
            old_interview = stale.config.get("interview_id")
            conn.execute("DELETE FROM runs WHERE id=?", (stale.id,))
            conn.execute(
                "DELETE FROM interviews WHERE id=? AND client_id=?", (old_interview, DEMO_CLIENT_ID)
            )
        _insert(conn, "runs", {**run_row, "id": run_id})
        for table in ("interviews", "interview_turns"):
            for row in tables[table]:
                if row.get("id") == interview_id or row.get("interview_id") == interview_id:
                    _insert(conn, table, row)
        for table in _RUN_SCOPED:
            for row in tables[table]:
                if row["run_id"] == snapshot_id:
                    row = {**row, "run_id": run_id}
                    if table == "reports":
                        row["payload_json"] = row["payload_json"].replace(snapshot_id, run_id)
                    _insert(conn, table, row)
        hypothesis_ids = {h["id"] for h in tables["hypotheses"] if h["run_id"] == snapshot_id}
        for row in tables["hypothesis_state"]:
            if row["hypothesis_id"] in hypothesis_ids:
                _insert(conn, "hypothesis_state", row)


async def seed_demo_runs(db_path: str | None = None) -> None:
    """Never raises: a failed example must not abort startup or later examples."""
    try:
        snapshot = _read_snapshot()
    except Exception:
        logger.exception("Failed to read the demo run snapshot")
        return
    existing = {
        run.research_goal: run for run in views.list_runs(client_id=DEMO_CLIENT_ID, db_path=db_path)
    }
    for run_row in snapshot["tables"]["runs"]:
        goal = run_row["research_goal"]
        stale = existing.get(goal)
        if stale and _is_current(stale, snapshot["version"], db_path):
            logger.info("demo run %s is current, skipping", stale.id[:8])
            continue
        try:
            _load_run(snapshot, run_row, stale, db_path)
            logger.info("Loaded demo run %.60s", goal)
        except Exception:
            logger.exception("Failed to load demo run for goal: %.60s", goal)

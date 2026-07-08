"""Report persistence: structured JSON rows plus Markdown artifacts.

A report is stored as a JSON payload row in the reports table, with the
rendered Markdown kept both in the database (durable across container
restarts) and as an on-disk file (backwards compatibility and local dev
convenience).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from app.store.db import _now, _reports_dir, _use_conn, connect

logger = logging.getLogger(__name__)


def save_report(
    run_id: str,
    payload: dict[str, Any],
    markdown: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, str]:
    """Persist a report as a JSON row plus a rendered Markdown file.

    The markdown is stored in both the database (markdown_text column, for
    durability across container restarts) and on disk (markdown_path, kept
    for backwards-compatibility and local dev convenience).

    Args:
        run_id: Identifier of the run the report belongs to.
        payload: Structured report payload serialized to JSON.
        markdown: Rendered Markdown report written to disk.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        A dict with the new report 'id' and the 'markdown_path' on disk.
    """
    report_id = str(uuid.uuid4())
    md_path = _reports_dir() / f"{run_id}.md"
    try:
        md_path.write_text(markdown, encoding="utf-8")
    except OSError:
        logger.warning("Could not write report markdown to disk at %s", md_path)
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO reports "
            "(id, run_id, payload_json, markdown_path, markdown_text, created_at) "  # pylint: disable=line-too-long
            "VALUES (?,?,?,?,?,?)",
            (report_id, run_id, json.dumps(payload), str(md_path), markdown,
             _now()),
        )
    return {"id": report_id, "markdown_path": str(md_path)}


def get_latest_report(run_id: str,
                      db_path: str | None = None) -> dict[str, Any] | None:
    """Return the most recent report row for a run, or None."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE run_id=? ORDER BY created_at DESC LIMIT 1",  # pylint: disable=line-too-long
            (run_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "payload": json.loads(row["payload_json"]),
            "markdown_path": row["markdown_path"],
            "markdown_text": row["markdown_text"],
            "created_at": row["created_at"],
        }


def read_report_markdown(run_id: str, db_path: str | None = None) -> str | None:
    """Return the markdown text for the latest report of a run.

    Prefers the markdown_text column stored in the database (durable across
    container restarts). Falls back to reading the on-disk file for rows that
    predate the markdown_text column.

    Args:
        run_id: Identifier of the run.
        db_path: Optional override for the SQLite database path.

    Returns:
        The markdown string, or None if no report exists.
    """
    latest = get_latest_report(run_id, db_path=db_path)
    if not latest:
        return None
    # Prefer the DB-stored text (resilient to filesystem loss).
    markdown_text = latest.get("markdown_text")
    if isinstance(markdown_text, str) and markdown_text:
        return markdown_text
    # Fallback: read from disk for rows written before the markdown_text column.
    md_path = latest.get("markdown_path")
    if not md_path:
        return None
    path = Path(md_path)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")

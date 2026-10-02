"""Report persistence: structured JSON rows plus Markdown artifacts.

A report is stored as a JSON payload row in the reports table, with the
rendered Markdown kept both in the database (durable across container
restarts) and as an on-disk file (backwards compatibility and local dev
convenience).

R14-11 split a run's report into two documents for a time, persisted via a
second column (``markdown_text_ranking``) on this same row rather than a
second table -- see the reports table's own comment in schema.py. That
split was reversed 2026-09-04 (docs/PARITY.md's REPORT-DOCUMENT-SPLIT-001
row); ``save_report`` writes only ``markdown_text`` again, exactly as
before the split, and ``markdown_text_ranking`` is never written by any
code path from here on. The column itself stays -- a forward migration
cannot be un-run against the production SQLite volume, so dropping it is
not an option -- and ``read_report_markdown`` below still checks it: a
run whose report was built during the split window has its full "Top
hypotheses" write-up sitting only in that column, and without this check
``/report.md`` for that run would silently read as the shorter overview-
only half.
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


def write_report_markdown(markdown_path: str, markdown: str) -> None:
    """Write a report's Markdown artifact after its database row commits."""
    try:
        Path(markdown_path).write_text(markdown, encoding="utf-8")
    except OSError:
        logger.warning(
            "Could not write report markdown to disk at %s", markdown_path
        )


def save_report(  # noqa: PLR0913
    run_id: str,
    payload: dict[str, Any],
    markdown: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
    write_markdown: bool = True,
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
        write_markdown: Whether to write the best-effort disk copy now.

    Returns:
        A dict with the new report 'id' and the 'markdown_path' on disk.
    """
    report_id = str(uuid.uuid4())
    md_path = _reports_dir() / f"{run_id}.md"
    if write_markdown:
        write_report_markdown(str(md_path), markdown)
    with _use_conn(conn, db_path) as active:
        # The retired split-document column retains its NULL default.
        active.execute(
            "INSERT INTO reports "
            "(id, run_id, payload_json, markdown_path, markdown_text, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (
                report_id,
                run_id,
                json.dumps(payload),
                str(md_path),
                markdown,
                _now(),
            ),
        )
    return {"id": report_id, "markdown_path": str(md_path)}


def get_latest_report(
    run_id: str, db_path: str | None = None
) -> dict[str, Any] | None:
    """Return the most recent report row for a run, or None."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE run_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "payload": json.loads(row["payload_json"]),
            "markdown_path": row["markdown_path"],
            "markdown_text": row["markdown_text"],
            # Legacy split-window column, kept for the read-side fallback
            # below -- see this module's docstring. Always None for a row
            # saved after the split's reversal.
            "markdown_text_ranking": row["markdown_text_ranking"],
            "created_at": row["created_at"],
        }


def _read_markdown_from_disk(latest: dict[str, Any]) -> str | None:
    """Read a report row's on-disk markdown file, or None if unavailable.

    Fallback path for rows written before the markdown_text column existed.
    """
    md_path = latest.get("markdown_path")
    if not md_path:
        return None
    path = Path(md_path)
    return path.read_text(encoding="utf-8") if path.exists() else None


def _with_legacy_ranking_half(latest: dict[str, Any], markdown: str) -> str:
    """Append a legacy split-window row's second document, when present.

    A report saved while the R14-11 split was live has its "Top
    hypotheses" write-up and tournament comparison sitting only in
    ``markdown_text_ranking`` (``markdown_text`` there is the overview-only
    half). Every other row -- pre-split, post-reversal, or the legacy
    single-document shape -- has this column NULL and passes through
    unchanged.
    """
    ranking_text = latest.get("markdown_text_ranking")
    if isinstance(ranking_text, str) and ranking_text:
        return f"{markdown}\n\n{ranking_text}"
    return markdown


def read_report_markdown(run_id: str, db_path: str | None = None) -> str | None:
    """Return the markdown text for the latest report of a run.

    Prefers the markdown_text column stored in the database (durable across
    container restarts). Falls back to reading the on-disk file for rows that
    predate the markdown_text column. A row saved during the R14-11 split
    window gets its ranking-document half appended -- see
    ``_with_legacy_ranking_half``.

    Args:
        run_id: Identifier of the run.
        db_path: Optional override for the SQLite database path.

    Returns:
        The markdown string, or None if no report exists.
    """
    latest = get_latest_report(run_id, db_path=db_path)
    if not latest:
        return None
    # Prefer the DB-stored text (resilient to filesystem loss). The
    # isinstance check stays inline so mypy narrows the row value to str.
    markdown_text = latest.get("markdown_text")
    if isinstance(markdown_text, str) and markdown_text:
        return _with_legacy_ranking_half(latest, markdown_text)
    return _read_markdown_from_disk(latest)

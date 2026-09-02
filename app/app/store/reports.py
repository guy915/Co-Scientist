"""Report persistence: structured JSON rows plus Markdown artifacts.

A report is stored as a JSON payload row in the reports table, with the
rendered Markdown kept both in the database (durable across container
restarts) and as an on-disk file (backwards compatibility and local dev
convenience).

R14-11: a run now renders two separately-purposed markdown documents (the
Research Overview and the Top Ranking Hypotheses documents -- see
``report_markdown_documents.py``). The smaller persistence change wins
here: one more nullable column (``markdown_text_ranking``) on the existing
``reports`` row, rather than a second table or a second row per report --
both documents already share one payload, one ``created_at``, and one
lifecycle (``get_latest_report`` picks the newest row by that timestamp),
so splitting the row would only add a join for no gained flexibility. The
existing ``markdown_text`` column keeps meaning "the Research Overview
document" going forward; ``markdown_text_ranking`` is the second one. A
row saved before this column existed has it NULL -- that is the
discriminator: NULL means ``markdown_text`` instead holds the older,
single combined document (every hypothesis, meta-review, and comparison
content in one file), and a reader must render/share it as that one
document, not assume a Top Ranking Hypotheses document exists to pair
with it. The on-disk file (``_write_report_markdown``, already a stated
legacy fallback) is not duplicated for the second document -- the
markdown_text_ranking column is that document's only durable copy.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.store.db import _now, _reports_dir, _use_conn, connect

logger = logging.getLogger(__name__)


def _write_report_markdown(md_path: Path, markdown: str) -> None:
    """Best-effort write of the rendered markdown to disk."""
    try:
        md_path.write_text(markdown, encoding="utf-8")
    except OSError:
        logger.warning("Could not write report markdown to disk at %s", md_path)


@dataclass(frozen=True)
class ReportMarkdownDocuments:
    """The rendered markdown document(s) one report is persisted with.

    R14-11: a run's report is two separately-purposed documents, not one
    -- bundled here (rather than as two positional ``save_report``
    parameters) to keep that function's own signature under the
    5-argument ceiling. ``ranking`` is None for a caller that only has
    the legacy single combined document -- a direct test/tooling call
    that pre-dates the split, or one that intentionally persists a
    reduced report.

    Attributes:
        overview: The Research Overview document. Also written to disk
            (``markdown_path``) -- see ``save_report``.
        ranking: The Top Ranking Hypotheses document, or None.
    """

    overview: str
    ranking: str | None = None


@dataclass(frozen=True)
class _NewReportFields:
    """Fields needed to insert one report row."""

    report_id: str
    run_id: str
    payload: dict[str, Any]
    md_path: Path
    documents: ReportMarkdownDocuments


def _insert_report_row(conn: sqlite3.Connection, f: _NewReportFields) -> None:
    """Insert the report row on an open connection."""
    conn.execute(
        "INSERT INTO reports "
        "(id, run_id, payload_json, markdown_path, "
        "markdown_text, markdown_text_ranking, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            f.report_id,
            f.run_id,
            json.dumps(f.payload),
            str(f.md_path),
            f.documents.overview,
            f.documents.ranking,
            _now(),
        ),
    )


def save_report(
    run_id: str,
    payload: dict[str, Any],
    documents: ReportMarkdownDocuments,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, str]:
    """Persist a report as a JSON row plus its rendered Markdown document(s).

    ``documents.overview`` (the Research Overview document) is stored in
    both the database (markdown_text column, for durability across
    container restarts) and on disk (markdown_path, kept for
    backwards-compatibility and local dev convenience). ``documents.ranking``
    (the Top Ranking Hypotheses document, R14-11) is stored in the
    database only (markdown_text_ranking) -- see this module's docstring
    for why a second on-disk file is not also written. Every caller
    through the real finalize path supplies both; ``documents.ranking``
    is None only for direct test/tooling calls that pre-date the split
    and only want the single legacy document.

    Args:
        run_id: Identifier of the run the report belongs to.
        payload: Structured report payload serialized to JSON.
        documents: The rendered markdown document(s) -- see
            :class:`ReportMarkdownDocuments`.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        A dict with the new report 'id' and the 'markdown_path' on disk.
    """
    report_id = str(uuid.uuid4())
    md_path = _reports_dir() / f"{run_id}.md"
    _write_report_markdown(md_path, documents.overview)
    with _use_conn(conn, db_path) as conn:
        _insert_report_row(
            conn,
            _NewReportFields(
                report_id=report_id,
                run_id=run_id,
                payload=payload,
                md_path=md_path,
                documents=documents,
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
            # R14-11: None on a row saved before this column existed --
            # that is the back-compat signal a reader checks (see this
            # module's docstring) to tell a legacy single-document report
            # from a new two-document one, e.g. shares.py forwards this
            # whole dict to a public reader unchanged.
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
    # Prefer the DB-stored text (resilient to filesystem loss). The
    # isinstance check stays inline so mypy narrows the row value to str.
    markdown_text = latest.get("markdown_text")
    if isinstance(markdown_text, str) and markdown_text:
        return markdown_text
    return _read_markdown_from_disk(latest)


def read_report_ranking_markdown(
    run_id: str, db_path: str | None = None
) -> str | None:
    """Return the Top Ranking Hypotheses document for a run's latest report.

    R14-11: the second of the two documents a run now produces -- see this
    module's docstring. Unlike ``read_report_markdown``, there is no
    on-disk fallback (the second document was never written to disk) and
    no legacy content to fall back to: a run whose latest report predates
    this column, or one saved without a ranking document, correctly
    returns None here rather than the older single combined document --
    callers that want "whatever this run has" read ``markdown_text``
    instead, exactly as they did before this column existed.

    Args:
        run_id: Identifier of the run.
        db_path: Optional override for the SQLite database path.

    Returns:
        The markdown string, or None if this run has no ranking document.
    """
    latest = get_latest_report(run_id, db_path=db_path)
    if not latest:
        return None
    markdown_text = latest.get("markdown_text_ranking")
    if isinstance(markdown_text, str) and markdown_text:
        return markdown_text
    return None

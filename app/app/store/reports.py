"""Report persistence: structured JSON rows plus Markdown artifacts."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from app.store.db import _list_by_run, _now, _reports_dir, _use_conn, connect

logger = logging.getLogger(__name__)


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
    rows = _list_by_run(
        "knowledge_facts", run_id, db_path, conn, json_fields=("entities",)
    )
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    if entity is not None:
        needle = entity.strip().upper()
        rows = [r for r in rows if needle in {e.upper() for e in r["entities"]}]
    return rows


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


def read_report_markdown(run_id: str, db_path: str | None = None) -> str | None:
    """Return the markdown text for the latest report of a run.

    Prefers the markdown_text column stored in the database (durable across
    container restarts). Falls back to reading the on-disk file for rows that
    predate the markdown_text column. A row saved during the R14-11 split
    window gets its ranking-document half appended.

    Args:
        run_id: Identifier of the run.
        db_path: Optional override for the SQLite database path.

    Returns:
        The markdown string, or None if no report exists.
    """
    latest = get_latest_report(run_id, db_path=db_path)
    if not latest:
        return None
    markdown_text = latest.get("markdown_text")
    if isinstance(markdown_text, str) and markdown_text:
        ranking_text = latest.get("markdown_text_ranking")
        if isinstance(ranking_text, str) and ranking_text:
            return f"{markdown_text}\n\n{ranking_text}"
        return markdown_text
    # Legacy rows saved before Markdown was stored in the database.
    path = Path(latest["markdown_path"] or "")
    return path.read_text(encoding="utf-8") if path.is_file() else None

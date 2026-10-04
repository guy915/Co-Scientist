from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from app.store.db import _list_by_run, _now, _use_conn, connect


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
            ``app.report.content.derive_knowledge_facts`` --
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


def save_report(
    run_id: str,
    payload: dict[str, Any],
    markdown: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, str]:
    report_id = str(uuid.uuid4())
    with _use_conn(conn, db_path) as active:
        # Empty paths preserve the string API contract without new files;
        # legacy readers stay until the verified store reset.
        active.execute(
            "INSERT INTO reports "
            "(id, run_id, payload_json, markdown_path, markdown_text, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (
                report_id,
                run_id,
                json.dumps(payload),
                "",
                markdown,
                _now(),
            ),
        )
    return {"id": report_id}


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
            # Older rows may split their report across both text columns.
            "markdown_text_ranking": row["markdown_text_ranking"],
            "created_at": row["created_at"],
        }


def read_report_markdown(run_id: str, db_path: str | None = None) -> str | None:
    # Older reports may contain only a file path or split their Markdown text.
    # Keep both readers until production export and reset have been verified.
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


def _hash_token(token: str) -> str:
    """Hash one bearer token before persistence or lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_report_share(
    run_id: str,
    client_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Create a unique public capability for an owned run."""
    token = secrets.token_urlsafe(32)
    share_id = str(uuid.uuid4())
    created_at = _now()
    with _use_conn(conn, db_path) as active:
        active.execute(
            "INSERT INTO report_shares (id, run_id, token_hash, "
            "created_by_client, created_at) VALUES (?,?,?,?,?)",
            (share_id, run_id, _hash_token(token), client_id, created_at),
        )
    return {
        "id": share_id,
        "run_id": run_id,
        "token": token,
        "created_at": created_at,
    }


def resolve_report_share(
    token: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Resolve an active token without returning its stored hash."""
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT id, run_id, created_by_client, created_at FROM "
            "report_shares WHERE token_hash=? AND revoked_at IS NULL",
            (_hash_token(token),),
        ).fetchone()
    return dict(row) if row else None


def list_report_shares(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """List active grants without exposing bearer tokens."""
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            "SELECT id, run_id, created_by_client, created_at FROM "
            "report_shares WHERE run_id=? AND revoked_at IS NULL "
            "ORDER BY created_at DESC",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def revoke_report_share(
    share_id: str,
    run_id: str,
    client_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Revoke one grant only when its creator still owns the run."""
    with _use_conn(conn, db_path) as active:
        changed = active.execute(
            "UPDATE report_shares SET revoked_at=? WHERE id=? AND run_id=? "
            "AND created_by_client=? AND revoked_at IS NULL",
            (_now(), share_id, run_id, client_id),
        ).rowcount
    return bool(changed)

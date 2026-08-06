"""Client-scoped documents staged before an interview or a run exists.

A scientist attaches a paper in the composer, which is *before* there is
any run to attach it to. Storing the extraction here, keyed to the caller's
identity, is what lets the same upload ground the interview that scopes the
goal and then be carried into the run at creation time -- instead of being
uploaded after the run already exists, which is both too late to inform the
plan and a second write that can fail on its own.

Rows are never returned across owners: every read takes the client id and
filters on it.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn, connect

# How much of one document's text is quoted into the interview prompt. The
# interview is a short chat, not the run: it needs enough to know what the
# scientist attached and to ask better questions about it, not the whole
# paper (which the run's own corpus retrieval serves).
INTERVIEW_EXCERPT_CHARS = 4_000


@dataclass(frozen=True)
class NewStagedDocument:
    """One extracted upload to stage against a client identity."""

    client_id: str
    title: str
    text: str
    mime_type: str
    sha256: str
    byte_size: int
    extraction_tool: str


def add_staged_document(
    document: NewStagedDocument, *, db_path: str | None = None
) -> str:
    """Persist one staged document and return its id."""
    document_id = str(uuid.uuid4())
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO staged_documents (id, client_id, title, text, "
            "mime_type, sha256, byte_size, extraction_tool, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                document_id,
                document.client_id,
                document.title,
                document.text,
                document.mime_type,
                document.sha256,
                document.byte_size,
                document.extraction_tool,
                _now(),
            ),
        )
    return document_id


def _rows_to_documents(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Decode staged-document rows into plain dicts."""
    return [dict(row) for row in rows]


def get_staged_documents(
    document_ids: list[str],
    client_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return the caller's own documents among ``document_ids``.

    A document belonging to another client is simply absent from the
    result, so callers detect it as a missing id rather than a refusal that
    confirms it exists.

    Args:
        document_ids: Ids to resolve, in the caller's order.
        client_id: Owning identity; rows are never returned across owners.
        db_path: Optional database override.
        conn: Optional open connection to reuse.

    Returns:
        The resolved rows, ordered to match ``document_ids``.
    """
    if not document_ids:
        return []
    placeholders = ",".join("?" for _ in document_ids)
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            f"SELECT * FROM staged_documents WHERE id IN ({placeholders}) "
            "AND client_id=?",
            (*document_ids, client_id),
        ).fetchall()
    by_id = {str(row["id"]): dict(row) for row in rows}
    return [by_id[doc_id] for doc_id in document_ids if doc_id in by_id]


def attach_documents_to_interview(
    interview_id: str,
    document_ids: list[str],
    client_id: str,
    *,
    db_path: str | None = None,
) -> int:
    """Link the caller's staged documents to one interview.

    Returns:
        How many rows were linked.
    """
    if not document_ids:
        return 0
    placeholders = ",".join("?" for _ in document_ids)
    with connect(db_path) as conn:
        return int(
            conn.execute(
                "UPDATE staged_documents SET interview_id=? "
                f"WHERE id IN ({placeholders}) AND client_id=?",
                (interview_id, *document_ids, client_id),
            ).rowcount
        )


def list_interview_documents(
    interview_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return every document attached to one interview, oldest first."""
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            "SELECT * FROM staged_documents WHERE interview_id=? "
            "ORDER BY created_at ASC",
            (interview_id,),
        ).fetchall()
    return _rows_to_documents(rows)


def interview_document_excerpts(
    interview_id: str, *, db_path: str | None = None
) -> list[dict[str, str]]:
    """Return title/excerpt pairs for one interview's attached documents.

    The excerpt is capped (``INTERVIEW_EXCERPT_CHARS``) and truncation is
    marked, so the Agent can tell a short document from a clipped one and
    does not answer as though it read the whole thing.
    """
    documents = list_interview_documents(interview_id, db_path=db_path)
    excerpts = []
    for document in documents:
        text = str(document["text"])
        clipped = text[:INTERVIEW_EXCERPT_CHARS]
        if len(text) > INTERVIEW_EXCERPT_CHARS:
            clipped += "\n[document continues; excerpt truncated]"
        excerpts.append({"title": str(document["title"]), "excerpt": clipped})
    return excerpts


def list_staged_documents_for_client(
    client_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return every document the caller has staged, newest first.

    Used by the account-level data export (N11): a scientist's own upload
    is part of their data whether or not it was ever carried into a run.
    """
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            "SELECT * FROM staged_documents WHERE client_id=? "
            "ORDER BY created_at DESC",
            (client_id,),
        ).fetchall()
    return _rows_to_documents(rows)


def delete_staged_document(
    document_id: str, client_id: str, *, db_path: str | None = None
) -> bool:
    """Delete one staged document the caller owns.

    A document belonging to another client is left untouched and the call
    reports no deletion, matching ``get_staged_documents``' owner-scoping.

    Args:
        document_id: Id of the document to delete.
        client_id: Owning identity; a mismatched row is not deleted.
        db_path: Optional override for the SQLite database path.

    Returns:
        True if a row was deleted, False if unknown or owned by another
        client.
    """
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM staged_documents WHERE id=? AND client_id=?",
            (document_id, client_id),
        )
    return cur.rowcount > 0


def delete_staged_documents_older_than(
    cutoff: float, *, db_path: str | None = None
) -> int:
    """Delete every staged document created before ``cutoff``.

    Used by the retention sweep (``app.retention``). Age is judged by
    creation time, not last use, since a staged document is never updated
    after its extraction is stored.

    Args:
        cutoff: Unix timestamp; older rows are deleted.
        db_path: Optional override for the SQLite database path.

    Returns:
        How many rows were deleted.
    """
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM staged_documents WHERE created_at < ?", (cutoff,)
        )
    return cur.rowcount


def mark_documents_used_by_run(
    run_id: str, document_ids: list[str], *, db_path: str | None = None
) -> None:
    """Record which run carried these staged documents into its corpus."""
    if not document_ids:
        return
    placeholders = ",".join("?" for _ in document_ids)
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE staged_documents SET run_id=? "
            f"WHERE id IN ({placeholders})",
            (run_id, *document_ids),
        )

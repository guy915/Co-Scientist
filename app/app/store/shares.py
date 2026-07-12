"""Revocable, hashed capability links for public Goal Reports."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from typing import Any

from app.store.db import _now, _use_conn


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

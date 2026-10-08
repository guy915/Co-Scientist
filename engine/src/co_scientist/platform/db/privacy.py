from __future__ import annotations

import hashlib
from collections.abc import Sequence

from co_scientist.platform.db import Connection, Error, connect, current_time

_TOMBSTONE_SECONDS = 86_400
_CLIENT_TABLES = (
    "runs",
    "interviews",
    "staged_documents",
    "feedback",
    "run_credentials",
    "run_creation_receipts",
    "anonymous_admissions",
    "app_llm_usage",
    "provider_token_reservations",
    "feedback_admissions",
    "run_admissions",
    "free_run_usage",
)


def ownership_digest(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_erased_owner(owner: str) -> bool:
    with connect() as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='privacy_erased_clients'"
        ).fetchone():
            return False
        return bool(
            conn.execute(
                "SELECT 1 FROM privacy_erased_clients WHERE digest=? AND expires_at>?",
                (ownership_digest(owner), current_time()),
            ).fetchone()
        )


def _guard(conn: Connection, table: str, operation: str, condition: str, action: str) -> None:
    conn.execute(
        f"CREATE TRIGGER IF NOT EXISTS privacy_{table}_{operation.lower()} "
        f"BEFORE {operation} ON {table} WHEN {condition} "
        f"BEGIN SELECT {action}; END"
    )


def _ensure_erasure_guards(conn: Connection) -> None:
    for table in ("privacy_erased_clients", "privacy_erased_runs"):
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} "
            "(digest TEXT PRIMARY KEY, expires_at REAL NOT NULL)"
        )
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_expiry ON {table}(expires_at)")
    client_erased = (
        "EXISTS (SELECT 1 FROM privacy_erased_clients "
        "WHERE digest=cosci_owner_digest(NEW.client_id) AND expires_at>unixepoch('now'))"
    )
    run_erased = (
        "EXISTS (SELECT 1 FROM privacy_erased_runs "
        "WHERE digest=cosci_owner_digest(NEW.run_id) AND expires_at>unixepoch('now'))"
    )
    refusal = "RAISE(ABORT, 'owner data erased')"
    for table in _CLIENT_TABLES:
        for operation in ("INSERT", "UPDATE"):
            _guard(conn, table, operation, client_erased, refusal)
    for table in ("provider_admissions", "input_admissions"):
        condition = (
            "NEW.scope='client' AND EXISTS (SELECT 1 FROM privacy_erased_clients "
            "WHERE digest=cosci_owner_digest(NEW.subject) AND expires_at>unixepoch('now'))"
        )
        for operation in ("INSERT", "UPDATE"):
            _guard(conn, table, operation, condition, refusal)
    for operation in ("INSERT", "UPDATE"):
        # Queued logs are best-effort; ignoring them avoids a failure-message
        # loop while preventing erased content from reappearing.
        _guard(
            conn,
            "app_logs",
            operation,
            f"{client_erased} OR (NEW.client_id IS NULL AND {run_erased})",
            "RAISE(IGNORE)",
        )
        _guard(conn, "reviews", operation, run_erased, "RAISE(ABORT, 'run data erased')")


def record_erasure(conn: Connection, owner: str, run_ids: Sequence[str]) -> None:
    _ensure_erasure_guards(conn)
    expires_at = current_time() + _TOMBSTONE_SECONDS
    conn.execute(
        "INSERT OR REPLACE INTO privacy_erased_clients VALUES (?,?)",
        (ownership_digest(owner), expires_at),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO privacy_erased_runs VALUES (?,?)",
        [(ownership_digest(run), expires_at) for run in run_ids],
    )


def purge_expired_tombstones(*, now: float | None = None) -> int:
    cutoff = current_time() if now is None else now
    count = 0
    with connect() as conn:
        for table in ("privacy_erased_clients", "privacy_erased_runs"):
            try:
                deleted = conn.execute(
                    f"DELETE FROM {table} WHERE digest IN "
                    f"(SELECT digest FROM {table} WHERE expires_at<=? LIMIT 500)",
                    (cutoff,),
                )
                count += max(0, deleted.rowcount)
            except Error as error:
                if "no such table" not in str(error):
                    raise
    return count


def purge_expired_admission_history(*, now: float | None = None) -> int:
    now = current_time() if now is None else now
    cutoff = now - 7 * 86_400
    day = int(now // 86_400) - 6
    count = 0
    policies: list[tuple[str, str, int | float]] = [
        (table, "day<?", day)
        for table in (
            "anonymous_admissions",
            "provider_admissions",
            "input_admissions",
            "app_llm_usage",
            "provider_token_reservations",
        )
    ]
    policies.extend(
        (table, "created_at<?", cutoff) for table in ("feedback_admissions", "free_run_usage")
    )
    policies.extend(
        (
            ("log_ingest_admissions", "minute<?", int(cutoff // 60)),
            # A live run's host mapping is needed for future continuation and
            # concurrency admission, even when the run is months old.
            (
                "run_admissions",
                "day<? AND NOT EXISTS (SELECT 1 FROM runs WHERE id=run_admissions.run_id)",
                day,
            ),
        )
    )
    for table, condition, boundary in policies:
        with connect() as conn:
            deleted = conn.execute(
                f"DELETE FROM {table} WHERE rowid IN "
                f"(SELECT rowid FROM {table} WHERE {condition} LIMIT 500)",
                (boundary,),
            )
            count += max(0, deleted.rowcount)
    return count

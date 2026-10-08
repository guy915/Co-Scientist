from __future__ import annotations

import json
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

from co_scientist.platform.db import Connection, connect, current_time, transaction
from co_scientist.platform.db.models import DEMO_CLIENT_ID
from co_scientist.platform.db.privacy import record_erasure

_RUN_SCOPE = "run_id IN (SELECT id FROM runs WHERE client_id=?)"
_CHAT_SCOPE = "interview_id IN (SELECT id FROM interviews WHERE client_id=?)"
_RUN_TABLES = (
    "run_events",
    "hypotheses",
    "evidence",
    "citations",
    "reviews",
    "matches",
    "safety_decisions",
    "reports",
    "messages",
    "checkpoints",
    "run_metrics",
    "claim_evidence",
    "knowledge_facts",
    "supervisor_plan",
    "supervisor_allocations",
    "scientific_tasks",
    "retrieval_calls",
    "proximity_edges",
    "run_announcements",
    "run_creation_receipts",
    "run_call_admissions",
)
_OWNER_TABLES = ("runs", "interviews", "staged_documents", "feedback")
_LOG_SCOPE = "client_id=? OR (client_id IS NULL AND " + _RUN_SCOPE + ")"


def _require_owner(owner: str) -> None:
    if not owner or owner == DEMO_CLIENT_ID:
        raise ValueError("a private owner scope is required")


def _export_tables(owner: str) -> list[tuple[str, str, tuple[str, ...]]]:
    tables: list[tuple[str, str, tuple[str, ...]]] = [
        (table, "client_id=?", (owner,)) for table in _OWNER_TABLES
    ]
    tables.extend((table, _RUN_SCOPE, (owner,)) for table in _RUN_TABLES)
    tables.extend(
        [
            ("interview_turns", _CHAT_SCOPE, (owner,)),
            (
                "hypothesis_state",
                "hypothesis_id IN (SELECT id FROM hypotheses WHERE " + _RUN_SCOPE + ")",
                (owner,),
            ),
            ("app_logs", _LOG_SCOPE, (owner, owner)),
            ("run_credentials", "client_id=? AND " + _RUN_SCOPE, (owner, owner)),
            (
                "llm_spend",
                "id IN (SELECT id FROM provider_token_reservations WHERE client_id=?)",
                (owner,),
            ),
        ]
    )
    for table in (
        "anonymous_admissions",
        "run_admissions",
        "provider_token_reservations",
        "app_llm_usage",
        "feedback_admissions",
        "free_run_usage",
    ):
        tables.append((table, "client_id=?", (owner,)))
    for table in ("provider_admissions", "input_admissions"):
        tables.append((table, "scope='client' AND subject=?", (owner,)))
    return tables


def export_data(owner: str, browser_settings: dict[str, Any]) -> Path:
    _require_owner(owner)
    with tempfile.NamedTemporaryFile(
        prefix="cosci-export-", suffix=".zip", delete=False
    ) as temporary:
        path = Path(temporary.name)
    try:
        # Stream a read snapshot to a private temporary file, then close it
        # before serving bytes; exports neither take the writer nor grow RAM.
        with connect() as conn, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            conn.execute("BEGIN")
            with archive.open("data.json", "w") as output:
                output.write(b'{"tables":{')
                for index, (table, scope, args) in enumerate(_export_tables(owner)):
                    if index:
                        output.write(b",")
                    output.write(json.dumps(table).encode() + b":[")
                    for row_index, row in enumerate(
                        conn.execute(f"SELECT * FROM {table} WHERE {scope}", args)
                    ):
                        if row_index:
                            output.write(b",")
                        data = dict(row)
                        if table == "run_credentials":
                            data = {
                                key: value
                                for key, value in data.items()
                                if not key.startswith("encrypted_")
                            }
                        output.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
                    output.write(b"]")
                output.write(b"}}")
            conn.execute("COMMIT")
            archive.writestr(
                "settings.json", json.dumps(browser_settings, ensure_ascii=False, indent=2)
            )
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format_version": 1,
                        "created_at": current_time(),
                        "scope": "current browser identity",
                        "credentials": "Provider keys and vault tokens are excluded for security.",
                        "documents": "Extracted text is included; original bytes are not stored.",
                        "external_copies": "Live database only; excludes providers and backups.",
                    },
                    indent=2,
                ),
            )
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def delete_data(owner: str) -> dict[str, int]:
    _require_owner(owner)
    with transaction() as conn:
        conn.execute("PRAGMA secure_delete=ON")
        run_ids = [
            str(row[0]) for row in conn.execute("SELECT id FROM runs WHERE client_id=?", (owner,))
        ]
        counts = {
            table: int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE client_id=?",
                    (owner,),
                ).fetchone()[0]
            )
            for table in _OWNER_TABLES
        }
        # Revoke leases before cascading so in-flight tasks cannot commit science.
        conn.execute(
            "UPDATE scientific_tasks SET status='cancelled', lease_owner=NULL, "
            "lease_expires_at=NULL "
            "WHERE " + _RUN_SCOPE,
            (owner,),
        )
        conn.execute("DELETE FROM app_logs WHERE " + _LOG_SCOPE, (owner, owner))
        conn.execute("DELETE FROM run_call_admissions WHERE " + _RUN_SCOPE, (owner,))
        # A run FK is absent on reviews; deletion must also cover legacy orphans.
        conn.execute("DELETE FROM reviews WHERE " + _RUN_SCOPE, (owner,))
        conn.execute("DELETE FROM run_credentials WHERE client_id=?", (owner,))
        for table in ("staged_documents", "feedback", "interviews", "runs"):
            conn.execute(f"DELETE FROM {table} WHERE client_id=?", (owner,))
        _detach_admission_history(conn, owner)
        record_erasure(conn, owner, run_ids)
    return counts


def _detach_admission_history(conn: Connection, owner: str) -> None:
    # Preserve spent host/global allowance while removing ownership and run links.
    # A fresh random identifier has no mapping back to the erased browser identity.
    detached = "deleted-" + uuid.uuid4().hex
    for table in (
        "anonymous_admissions",
        "app_llm_usage",
        "provider_token_reservations",
        "feedback_admissions",
    ):
        conn.execute(f"UPDATE {table} SET client_id=? WHERE client_id=?", (detached, owner))
    for table in ("provider_admissions", "input_admissions"):
        conn.execute(
            f"UPDATE {table} SET subject=? WHERE scope='client' AND subject=?", (detached, owner)
        )
    for table in ("run_admissions", "free_run_usage"):
        rows = conn.execute(f"SELECT run_id FROM {table} WHERE client_id=?", (owner,)).fetchall()
        for row in rows:
            conn.execute(
                f"UPDATE {table} SET client_id=?, run_id=? WHERE run_id=?",
                (
                    detached,
                    "deleted-" + uuid.uuid4().hex,
                    row[0],
                ),
            )

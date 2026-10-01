"""Run-create receipts against older persisted schemas and concurrent owners."""

from __future__ import annotations

import hashlib
import io
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import credentials
from app.config import settings
from tests._client import make_client

_PAYLOAD = {
    "research_goal": "Study a defined signaling pathway",
    "tier": "express",
}


def _post_run(
    client: TestClient,
    owner: str,
    key: str | None,
    payload: dict[str, Any] | None = None,
) -> Any:
    headers = {"X-Client-ID": owner}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(
        "/api/runs",
        headers=headers,
        json=payload if payload is not None else _PAYLOAD,
    )


def test_post_run_adds_receipts_to_a_persisted_pre_receipt_database(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Current startup adds the new table while preserving the old run/event."""
    legacy_run_id = "pre-receipt-run"
    raw = sqlite3.connect(isolated_db)
    try:
        # Minimal older-schema subset with owned runs, credentials, and
        # events. A copied production backup is rehearsed separately.
        raw.executescript(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                research_goal TEXT NOT NULL,
                title TEXT,
                profile TEXT NOT NULL,
                status TEXT NOT NULL,
                provider TEXT NOT NULL,
                config_json TEXT NOT NULL,
                client_id TEXT NOT NULL DEFAULT '',
                execution_policy TEXT NOT NULL DEFAULT 'standard',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                error TEXT,
                llm_backend TEXT,
                goal_restatement TEXT
            );
            CREATE TABLE run_credentials (
                run_id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                encrypted_key TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            CREATE TABLE run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            INSERT INTO runs (
                id, research_goal, profile, status, provider, config_json,
                client_id, created_at, updated_at, llm_backend
            ) VALUES (
                'pre-receipt-run', 'Persisted before receipt support',
                'standard', 'completed', 'engine', '{}',
                'legacy-owner', 1, 1, 'offline'
            );
            INSERT INTO run_events (
                run_id, seq, type, payload_json, created_at
            ) VALUES (
                'pre-receipt-run', 1, 'lifecycle', '{"event":"created"}', 1
            );
            """
        )
        assert (
            raw.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='run_creation_receipts'"
            ).fetchone()
            is None
        )
        raw.commit()
    finally:
        raw.close()

    client = make_client()
    created = _post_run(client, "new-owner", "after-upgrade")

    assert created.status_code == 200, created.text
    assert _post_run(client, "new-owner", "after-upgrade").json() == (
        created.json()
    )
    owned = client.get("/api/runs", headers={"X-Client-ID": "legacy-owner"})
    assert owned.status_code == 200, owned.text
    assert [run["id"] for run in owned.json()["runs"]] == [legacy_run_id]

    with sqlite3.connect(isolated_db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "run_creation_receipts" in tables
        assert (
            conn.execute(
                "SELECT payload_json FROM run_events WHERE run_id=? AND seq=1",
                (legacy_run_id,),
            ).fetchone()[0]
            == '{"event":"created"}'
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM runs WHERE id IN (?, ?)",
                (legacy_run_id, created.json()["id"]),
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT run_id FROM run_creation_receipts "
                "WHERE client_id=? AND idempotency_key=?",
                ("new-owner", "after-upgrade"),
            ).fetchone()[0]
            == created.json()["id"]
        )

    document_bytes = b"ERK1 phosphorylation supports tissue repair.\n"
    staged = client.post(
        "/api/documents",
        headers={"X-Client-ID": "new-owner"},
        files={
            "file": ("lab-notes.txt", io.BytesIO(document_bytes), "text/plain")
        },
        data={"consent": "true"},
    )
    assert staged.status_code == 200, staged.text
    document = staged.json()
    digest = hashlib.sha256(document_bytes).hexdigest()
    assert document["sha256"] == digest

    api_key = "sk-receipt-private-value"
    validated: list[str] = []
    mocked_background: list[str] = []

    async def accept_byok(credential: credentials.ByokCredential) -> None:
        validated.append(credential.api_key)

    async def mock_title(*_args: Any, **_kwargs: Any) -> None:
        mocked_background.append("title")

    async def mock_restatement(*_args: Any, **_kwargs: Any) -> None:
        mocked_background.append("restatement")

    monkeypatch.setattr(settings, "byok_encryption_key", "receipt-test-key")
    monkeypatch.setattr(credentials, "validate_byok_credential", accept_byok)
    monkeypatch.setattr("app.runs.crud.generate_run_title", mock_title)
    monkeypatch.setattr(
        "app.runs.crud.generate_goal_restatement", mock_restatement
    )

    byok_payload = {**_PAYLOAD, "document_ids": [document["id"]]}
    byok_headers = {
        "X-Client-ID": "new-owner",
        "Idempotency-Key": "byok-with-document",
        credentials.PROVIDER_HEADER: "deepseek",
        credentials.API_KEY_HEADER: api_key,
    }
    byok_run = client.post("/api/runs", headers=byok_headers, json=byok_payload)
    assert byok_run.status_code == 200, byok_run.text
    assert api_key not in byok_run.text

    run_id = byok_run.json()["id"]
    evidence_response = client.get(
        f"/api/runs/{run_id}/evidence", headers={"X-Client-ID": "new-owner"}
    )
    assert evidence_response.status_code == 200, evidence_response.text
    evidence = evidence_response.json()["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["title"] == "lab-notes.txt"
    assert evidence[0]["abstract"] == document_bytes.decode()
    assert evidence[0]["source"] == "attachment"
    assert evidence[0]["sha256"] == digest
    assert evidence[0]["document_version"] == digest
    assert evidence[0]["extraction_tool"] == "utf8-decoder-v1"
    assert evidence[0]["mime_type"] == "text/plain"
    assert evidence[0]["byte_size"] == len(document_bytes)

    replay = client.post("/api/runs", headers=byok_headers, json=byok_payload)
    assert replay.status_code == 200, replay.text
    assert replay.json() == byok_run.json()
    assert api_key not in replay.text
    evidence_after_replay = client.get(
        f"/api/runs/{run_id}/evidence", headers={"X-Client-ID": "new-owner"}
    ).json()["evidence"]
    assert evidence_after_replay == evidence
    assert validated == [api_key]
    assert mocked_background == ["title", "restatement"]

    stored_credential = credentials.get_run_credential(
        run_id, db_path=isolated_db
    )
    assert stored_credential is not None
    assert stored_credential.api_key == api_key
    assert stored_credential.provider == "deepseek"
    with sqlite3.connect(isolated_db) as conn:
        encrypted_key = conn.execute(
            "SELECT encrypted_key FROM run_credentials WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]
        receipt_digest = conn.execute(
            "SELECT request_digest FROM run_creation_receipts "
            "WHERE client_id=? AND idempotency_key=?",
            ("new-owner", "byok-with-document"),
        ).fetchone()[0]
        assert api_key not in encrypted_key
        assert api_key not in receipt_digest
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM runs WHERE client_id=?", ("new-owner",)
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_credentials WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM evidence WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_creation_receipts "
                "WHERE client_id=? AND idempotency_key=?",
                ("new-owner", "byok-with-document"),
            ).fetchone()[0]
            == 1
        )

    legacy_first = _post_run(client, "new-owner", None)
    legacy_second = _post_run(client, "new-owner", None)
    assert legacy_first.status_code == legacy_second.status_code == 200
    assert legacy_first.json()["id"] != legacy_second.json()["id"]


def test_concurrent_changed_payloads_commit_one_same_key_run(
    isolated_db: str,
) -> None:
    """A same-owner race with different intent creates one run and one 409."""
    client = make_client()
    owner = "changed-race-owner"
    key = "changed-payload-race"
    payloads = (
        _PAYLOAD,
        {**_PAYLOAD, "research_goal": "Study a different pathway"},
    )
    start_together = Barrier(len(payloads))

    def submit(payload: dict[str, Any]) -> Any:
        start_together.wait(timeout=5)
        return _post_run(client, owner, key, payload)

    with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        futures = [pool.submit(submit, payload) for payload in payloads]
        responses = [future.result(timeout=10) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 409]
    accepted = next(
        response for response in responses if response.status_code == 200
    )
    listed = client.get("/api/runs", headers={"X-Client-ID": owner})
    assert listed.status_code == 200, listed.text
    assert [run["id"] for run in listed.json()["runs"]] == [
        accepted.json()["id"]
    ]

    with sqlite3.connect(isolated_db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM runs WHERE client_id=?", (owner,)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_creation_receipts "
                "WHERE client_id=? AND idempotency_key=?",
                (owner, key),
            ).fetchone()[0]
            == 1
        )


def test_concurrent_same_key_requests_are_isolated_by_owner() -> None:
    """Simultaneous identical keys make one replayable run per owner."""
    client = make_client()
    owners = ("owner-one", "owner-two")
    start_together = Barrier(len(owners))

    def submit(owner: str) -> tuple[str, Any]:
        start_together.wait(timeout=5)
        return owner, _post_run(client, owner, "shared-key")

    with ThreadPoolExecutor(max_workers=len(owners)) as pool:
        futures = [pool.submit(submit, owner) for owner in owners]
        responses = [future.result(timeout=10) for future in futures]

    run_payloads: dict[str, dict[str, Any]] = {}
    for owner, response in responses:
        assert response.status_code == 200, response.text
        run_payloads[owner] = response.json()
    assert run_payloads["owner-one"]["id"] != run_payloads["owner-two"]["id"]

    for owner in owners:
        replay = _post_run(client, owner, "shared-key")
        assert replay.status_code == 200, replay.text
        assert replay.json() == run_payloads[owner]
        listed = client.get("/api/runs", headers={"X-Client-ID": owner})
        assert [run["id"] for run in listed.json()["runs"]] == [
            run_payloads[owner]["id"]
        ]

    hidden_from_other_owner = client.get(
        f"/api/runs/{run_payloads['owner-two']['id']}",
        headers={"X-Client-ID": "owner-one"},
    )
    assert hidden_from_other_owner.status_code == 404

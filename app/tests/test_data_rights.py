from __future__ import annotations

import io
import json
import zipfile

from co_scientist.api.data_rights import router
from co_scientist.domains.chat.repository.interviews import create_interview
from co_scientist.domains.documents.repository import NewStagedDocument, add_staged_document
from co_scientist.platform.db import connect
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests._client import create_run, make_client


def _rights_client(owner: str) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"X-Client-ID": owner})


def _seed(owner: str) -> tuple[str, str, str]:
    run = create_run(
        make_client(), f"private goal for {owner}", headers={"X-Client-ID": owner}
    ).json()["id"]
    chat = str(create_interview(owner, f"private chat for {owner}")["id"])
    doc = add_staged_document(
        NewStagedDocument(
            client_id=owner,
            title=f"{owner}.txt",
            text=f"private document for {owner}",
            mime_type="text/plain",
            sha256=owner,
            byte_size=30,
            extraction_tool="test",
        )
    )
    with connect() as conn:
        conn.execute(
            "INSERT INTO run_credentials "
            "(run_id,client_id,provider,model,encrypted_key,created_at) VALUES (?,?,?,?,?,0)",
            (run, owner, "openrouter", "test-model", f"ciphertext-{owner}"),
        )
        conn.execute(
            "INSERT INTO app_logs (created_at,level,levelno,logger,message,client_id) "
            "VALUES (0,'INFO',20,'ui',?,?)",
            (f"private log for {owner}", owner),
        )
    return run, chat, doc


def test_export_only_contains_owner_runs_chats_documents_and_no_keys() -> None:
    own = _seed("owner-a")
    other = _seed("owner-b")
    response = _rights_client("owner-a").post("/api/data/export", json={"theme": "dark"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        exported = archive.read("data.json").decode()
        settings = json.loads(archive.read("settings.json"))
        assert settings["theme"] == "dark"
        tables = json.loads(exported)["tables"]
        assert tables["runs"][0]["id"] == own[0]
        assert tables["interviews"][0]["id"] == own[1]
        assert tables["staged_documents"][0]["id"] == own[2]
        for identifier in other:
            assert identifier not in exported
        assert "owner-b" not in exported
        assert "ciphertext" not in exported
        assert "encrypted_key" not in exported


def test_delete_removes_private_content_keys_and_preserves_another_owner() -> None:
    own = _seed("owner-a")
    other = _seed("owner-b")
    response = _rights_client("owner-a").post("/api/data/delete", json={"confirmation": "DELETE"})
    assert response.status_code == 200
    with connect() as conn:
        for table in ("runs", "interviews", "staged_documents", "run_credentials", "app_logs"):
            assert (
                conn.execute(f"SELECT COUNT(*) FROM {table} WHERE client_id='owner-a'").fetchone()[
                    0
                ]
                == 0
            )
            assert (
                conn.execute(f"SELECT COUNT(*) FROM {table} WHERE client_id='owner-b'").fetchone()[
                    0
                ]
                == 1
            )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM interview_turns WHERE interview_id=?", (own[1],)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM interview_turns WHERE interview_id=?", (other[1],)
            ).fetchone()[0]
            == 1
        )
    client = make_client()
    assert client.get(f"/api/runs/{own[0]}", headers={"X-Client-ID": "owner-a"}).status_code == 404
    assert (
        client.get(f"/api/runs/{other[0]}", headers={"X-Client-ID": "owner-b"}).status_code == 200
    )


def test_owned_spend_export_and_erasure_preserve_shared_funding_and_late_settlement(
    isolated_db: str,
) -> None:
    from co_scientist.platform.db import current_time
    from co_scientist.platform.db.admission import reserve_provider, settle_provider
    from co_scientist.platform.db.spend import SpendReservation

    receipts = [
        reserve_provider(
            owner,
            "synthetic-shared-host",
            100,
            app=False,
            db_path=isolated_db,
            spend=SpendReservation(
                "azure/test", "worker", 100, 1000, current_time() + 600, 100, 100, "{}"
            ),
        )
        for owner in ("owner-a", "owner-b")
    ]
    response = _rights_client("owner-a").post("/api/data/export", json={})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        tables = json.loads(archive.read("data.json"))["tables"]
    assert [row["id"] for row in tables["llm_spend"]] == [receipts[0].id]
    assert tables["llm_spend"][0]["charged_microeur"] == 100
    assert receipts[1].id not in json.dumps(tables)

    assert (
        _rights_client("owner-a")
        .post("/api/data/delete", json={"confirmation": "DELETE"})
        .status_code
        == 200
    )
    with connect() as conn:
        assert conn.execute("SELECT SUM(charged_microeur) FROM llm_spend").fetchone()[0] == 200
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM provider_token_reservations WHERE client_id='owner-a'"
            ).fetchone()[0]
            == 0
        )
    assert _rights_client("owner-a").post("/api/data/export", json={}).status_code == 410
    response = _rights_client("owner-b").post("/api/data/export", json={})
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        tables = json.loads(archive.read("data.json"))["tables"]
    assert [row["id"] for row in tables["llm_spend"]] == [receipts[1].id]
    assert receipts[0].id not in json.dumps(tables)

    settle_provider(receipts[0], 30, money=(30, 20, 10, 0, 0))
    settle_provider(receipts[0], 0, money=(0, 0, 0, 0, 0))
    with connect() as conn:
        assert conn.execute("SELECT SUM(charged_microeur) FROM llm_spend").fetchone()[0] == 130
        assert conn.execute(
            "SELECT charged_microeur,settled FROM llm_spend WHERE id=?", (receipts[0].id,)
        ).fetchone()[:] == (30, 1)


def test_rights_routes_refuse_empty_demo_or_overlong_identity_and_owner_override() -> None:
    from co_scientist.platform.db.models import DEMO_CLIENT_ID

    for owner in ("", DEMO_CLIENT_ID, "a" * 129):
        client = _rights_client(owner)
        assert client.post("/api/data/export", json={}).status_code == 400
        assert client.post("/api/data/delete", json={"confirmation": "DELETE"}).status_code == 400
    client = _rights_client("owner-a")
    assert client.post("/api/data/export", json={"client_id": "owner-b"}).status_code == 422
    assert (
        client.post(
            "/api/data/delete", json={"confirmation": "DELETE", "client_id": "owner-b"}
        ).status_code
        == 422
    )
    assert client.post("/api/data/delete", json={"confirmation": "yes"}).status_code == 422


def test_erasure_blocks_late_owner_writes_and_discards_queued_logs() -> None:
    import sqlite3

    import pytest
    from co_scientist.orchestration.repository.tasks import NewTask, enqueue_task
    from co_scientist.orchestration.repository.tasks_lifecycle import complete_task
    from co_scientist.platform.db.logs import NewLogRecord, append_log
    from co_scientist.platform.db.privacy import ownership_digest

    own = _seed("owner-a")
    task = enqueue_task(NewTask(own[0], "test", {}, "private-task"))
    with connect() as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased',lease_owner='worker' WHERE id=?",
            (task.id,),
        )
    response = _rights_client("owner-a").post("/api/data/delete", json={"confirmation": "DELETE"})
    assert response.status_code == 200
    assert not complete_task(task.id, "worker", {"private": "late result"})
    with pytest.raises(sqlite3.IntegrityError):
        enqueue_task(NewTask(own[0], "test", {}, "late-task"))
    with pytest.raises(sqlite3.IntegrityError, match="owner data erased"):
        create_interview("owner-a", "late private chat")
    for client in ("owner-a", None):
        append_log(
            NewLogRecord("INFO", 20, "test", "late private text", run_id=own[0], client_id=client)
        )
    with connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM app_logs WHERE message='late private text'"
            ).fetchone()[0]
            == 0
        )
        row = conn.execute("SELECT digest FROM privacy_erased_clients").fetchone()
        assert row[0] == ownership_digest("owner-a")
        assert "owner-a" not in row[0]
    assert _rights_client("owner-a").post("/api/data/export", json={}).status_code == 410
    assert (
        create_run(make_client(), "late goal", headers={"X-Client-ID": "owner-a"}).status_code
        == 410
    )


def test_erasure_rolls_back_all_content_if_guard_installation_fails(monkeypatch: object) -> None:
    import pytest
    from co_scientist.domains.access import data_rights

    own = _seed("owner-a")

    def fail(*args: object) -> None:
        raise RuntimeError("guard failure")

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.setattr(data_rights, "record_erasure", fail)
    with pytest.raises(RuntimeError, match="guard failure"):
        data_rights.delete_data("owner-a")
    with connect() as conn:
        assert conn.execute("SELECT 1 FROM runs WHERE id=?", (own[0],)).fetchone()
        assert (
            conn.execute(
                "SELECT encrypted_key FROM run_credentials WHERE run_id=?", (own[0],)
            ).fetchone()[0]
            == "ciphertext-owner-a"
        )
        assert conn.execute("SELECT 1 FROM staged_documents WHERE id=?", (own[2],)).fetchone()
        assert conn.execute("SELECT 1 FROM interviews WHERE id=?", (own[1],)).fetchone()


def test_erasure_preserves_spent_quota_and_late_provider_settlement() -> None:
    from co_scientist.domains.access.data_rights import delete_data
    from co_scientist.platform.db.admission import reserve_provider, settle_provider

    _seed("owner-a")
    receipt = reserve_provider("owner-a", "synthetic-host-hash", 100, app=True, db_path=None)
    with connect() as conn:
        before = [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM provider_admissions WHERE scope IN ('global','host') "
                "ORDER BY scope,subject"
            )
        ]
    delete_data("owner-a")
    with connect() as conn:
        after = [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM provider_admissions WHERE scope IN ('global','host') "
                "ORDER BY scope,subject"
            )
        ]
        assert before == after
        assert not conn.execute(
            "SELECT 1 FROM provider_token_reservations WHERE client_id='owner-a'"
        ).fetchone()
    settle_provider(receipt, 30)
    settle_provider(receipt, 0)
    with connect() as conn:
        assert (
            conn.execute("SELECT tokens FROM provider_admissions WHERE scope='global'").fetchone()[
                0
            ]
            == 30
        )
        assert (
            conn.execute(
                "SELECT used_tokens FROM provider_token_reservations WHERE id=?", (receipt.id,)
            ).fetchone()[0]
            == 30
        )


def test_export_cleanup_releases_capacity_after_success_and_refuses_excess(
    tmp_path: object, monkeypatch: object
) -> None:
    import threading
    from pathlib import Path

    import pytest
    from co_scientist.api import data_rights

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(data_rights, "_EXPORT_SLOTS", slots)
    _seed("owner-a")
    created: list[Path] = []
    from co_scientist.domains.access.data_rights import export_data as real_export

    def export(owner: str, settings: dict[str, object]) -> Path:
        path = real_export(owner, settings)
        created.append(path)
        return path

    monkeypatch.setattr(data_rights, "export_data", export)
    assert _rights_client("owner-a").post("/api/data/export", json={}).status_code == 200
    assert created and not created[0].exists()
    assert slots.acquire(blocking=False)
    assert slots.acquire(blocking=False)
    denied = _rights_client("owner-a").post("/api/data/export", json={})
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "60"
    slots.release()
    slots.release()


def test_erased_text_is_absent_from_future_database_snapshots(
    isolated_db: str, tmp_path: object
) -> None:
    import sqlite3
    from pathlib import Path

    from co_scientist.domains.access.data_rights import delete_data

    assert isinstance(tmp_path, Path)
    own = _seed("owner-a")
    secret = "unique-erased-document-payload-" * 10_000
    with connect() as conn:
        conn.execute("UPDATE staged_documents SET text=? WHERE id=?", (secret, own[2]))
    delete_data("owner-a")
    snapshot = tmp_path / "post-erasure.db"
    with connect() as conn, sqlite3.connect(snapshot) as backup:
        conn.backup(backup)
    assert b"unique-erased-document-payload-" not in snapshot.read_bytes()


def test_export_disconnect_unlinks_file_and_holds_no_writer_lock(
    tmp_path: object, monkeypatch: object
) -> None:
    import asyncio
    import threading
    from pathlib import Path
    from typing import Any

    import pytest
    from co_scientist.api import data_rights
    from co_scientist.domains.access.data_rights import export_data
    from starlette.types import Message

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    _seed("owner-a")
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(data_rights, "_EXPORT_SLOTS", slots)
    assert slots.acquire(blocking=False)
    path = export_data("owner-a", {})
    response = data_rights.PrivateExportResponse(path)

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        with connect() as conn:
            conn.execute("PRAGMA busy_timeout=50")
            conn.execute(
                "INSERT INTO app_logs (created_at,level,levelno,logger,message,client_id) "
                "VALUES (0,'INFO',20,'test','writer remained available','owner-b')"
            )
        if message["type"] == "http.response.body":
            raise ConnectionError("disconnected")

    with pytest.raises(ConnectionError, match="disconnected"):
        asyncio.run(response({"type": "http", "method": "GET", "headers": []}, receive, send))
    assert not path.exists()
    assert slots.acquire(blocking=False)
    assert slots.acquire(blocking=False)
    slots.release()
    slots.release()

"""Tests for the persisted-log access controls.

The app-wide log carries other tenants' research goals, run activity, and
server internals, so a remote caller must only ever see records that are
theirs. Operators (loopback, or a configured admin token) keep the
app-wide view the CLI needs.
"""

from __future__ import annotations

import logging

from app import store
from tests._client import make_client


def _seed(
    isolated_db: str,
    message: str,
    *,
    run_id: str | None = None,
    client_id: str | None = None,
    logger_name: str = "app.seeded",
) -> int:
    return store.append_log(
        level="INFO",
        levelno=logging.INFO,
        logger_name=logger_name,
        message=message,
        run_id=run_id,
        client_id=client_id,
        db_path=isolated_db,
    )


def test_records_are_scoped_to_the_owning_client(isolated_db: str) -> None:
    client = make_client()
    created = client.post(
        "/api/runs",
        json={"research_goal": "alice private goal"},
        headers={"X-Client-ID": "alice"},
    )
    alice_run = created.json()["id"]
    _seed(isolated_db, "alice run record", run_id=alice_run)
    _seed(isolated_db, "alice ui record", client_id="alice")
    _seed(isolated_db, "bob ui record", client_id="bob")
    _seed(isolated_db, "server startup record")

    rows = store.list_logs(scope_client_id="alice", db_path=isolated_db)
    messages = [r["message"] for r in rows]
    # Own run records and own ingested records, nothing else -- not
    # another tenant's, and not un-owned server internals.
    assert "alice run record" in messages
    assert "alice ui record" in messages
    assert "bob ui record" not in messages
    assert "server startup record" not in messages
    # Creating the run also logged alice's own lifecycle stage record,
    # so assert the invariant rather than a fixed number.
    assert store.count_logs(
        scope_client_id="alice", db_path=isolated_db
    ) == len(rows)
    assert all("bob" not in m for m in messages)


def test_unscoped_read_still_sees_everything(isolated_db: str) -> None:
    _seed(isolated_db, "alice ui record", client_id="alice")
    _seed(isolated_db, "server startup record")
    assert store.count_logs(db_path=isolated_db) == 2


def test_clear_can_be_scoped_to_one_client(isolated_db: str) -> None:
    _seed(isolated_db, "alice ui record", client_id="alice")
    _seed(isolated_db, "bob ui record", client_id="bob")
    deleted = store.clear_logs(scope_client_id="alice", db_path=isolated_db)
    assert deleted == 1
    remaining = [r["message"] for r in store.list_logs(db_path=isolated_db)]
    assert remaining == ["bob ui record"]


# --------------------------------------------------------------------------
# Endpoint access control. TestClient requests report a non-loopback host,
# so they exercise the remote path unless an admin token is supplied.
# --------------------------------------------------------------------------


def _admin_token(monkeypatch: object, token: str) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "logs_admin_token", token)  # type: ignore[attr-defined]


def test_remote_read_is_scoped_to_the_caller(isolated_db: str) -> None:
    _seed(isolated_db, "alice ui record", client_id="alice")
    _seed(isolated_db, "bob ui record", client_id="bob")
    _seed(isolated_db, "server internals")
    client = make_client()

    body = client.get("/api/logs", headers={"X-Client-ID": "alice"}).json()
    messages = [r["message"] for r in body["logs"]]
    assert messages == ["alice ui record"]
    assert body["total"] == 1


def test_remote_read_without_identity_sees_nothing(isolated_db: str) -> None:
    _seed(isolated_db, "alice ui record", client_id="alice")
    _seed(isolated_db, "server internals")
    body = make_client().get("/api/logs").json()
    assert body["logs"] == []


def test_admin_token_grants_the_app_wide_view(
    isolated_db: str, monkeypatch: object
) -> None:
    _admin_token(monkeypatch, "s3cret")
    _seed(isolated_db, "alice ui record", client_id="alice")
    _seed(isolated_db, "server internals")
    client = make_client()

    body = client.get("/api/logs", headers={"X-Logs-Token": "s3cret"}).json()
    assert len(body["logs"]) == 2
    # A wrong token must not fall back to the app-wide view.
    body = client.get("/api/logs", headers={"X-Logs-Token": "nope"}).json()
    assert body["logs"] == []


def test_remote_delete_only_clears_the_callers_records(
    isolated_db: str,
) -> None:
    _seed(isolated_db, "alice ui record", client_id="alice")
    _seed(isolated_db, "bob ui record", client_id="bob")
    _seed(isolated_db, "server internals")
    client = make_client()

    response = client.request(
        "DELETE", "/api/logs", headers={"X-Client-ID": "alice"}
    )
    assert response.json()["deleted"] == 1
    remaining = [r["message"] for r in store.list_logs(db_path=isolated_db)]
    assert remaining == ["bob ui record", "server internals"]


def test_ingested_records_are_stamped_with_the_caller(
    isolated_db: str,
) -> None:
    client = make_client()
    client.post(
        "/api/logs",
        json={"records": [{"message": "alice clicked"}]},
        headers={"X-Client-ID": "alice"},
    )
    rows = store.list_logs(scope_client_id="alice", db_path=isolated_db)
    assert [r["message"] for r in rows] == ["alice clicked"]
    # And it is not visible to another tenant.
    assert store.list_logs(scope_client_id="bob", db_path=isolated_db) == []


def test_ingestion_strips_control_characters(isolated_db: str) -> None:
    client = make_client()
    client.post(
        "/api/logs",
        json={
            "records": [
                {
                    "message": "real\n2026-01-01\tINFO\tapp.fake\tforged",
                    "logger": "sess\nion",
                }
            ]
        },
        headers={"X-Client-ID": "alice"},
    )
    row = store.list_logs(scope_client_id="alice", db_path=isolated_db)[0]
    # Newlines and tabs would let a submitted message forge extra lines
    # in the CLI's tab-delimited output.
    assert "\n" not in row["message"]
    assert "\t" not in row["message"]
    assert "\n" not in row["logger"]


def test_ingestion_is_rate_limited(isolated_db: str) -> None:
    client = make_client()
    headers = {"X-Client-ID": "flooder"}
    last = None
    for _ in range(200):
        last = client.post(
            "/api/logs",
            json={"records": [{"message": "spam"}]},
            headers=headers,
        )
        if last.status_code == 429:
            break
    assert last is not None and last.status_code == 429

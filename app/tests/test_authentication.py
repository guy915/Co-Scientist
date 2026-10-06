from __future__ import annotations

import io
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import auth
from app.config import Settings, settings
from app.operator_access import is_operator
from app.store import runs
from app.store import runs_views as views
from app.store.models import RunStatus
from tests._client import create_run as _create_run
from tests._client import make_client, wait_for

_OWNER = {"X-Client-ID": "export-owner"}
_OTHER = {"X-Client-ID": "someone-else"}


def _wait_owned_status(
    client: TestClient, run_id: str, status: str, *, timeout: float = 30.0
) -> bool:

    def _reached() -> bool:
        response = client.get(f"/api/runs/{run_id}", headers=_OWNER)
        return response.status_code == 200 and bool(response.json().get("status") == status)

    return wait_for(_reached, timeout=timeout)


def test_export_includes_a_run_its_report_and_a_document(
    isolated_db: str,
) -> None:
    client = make_client()
    client.post(
        "/api/documents",
        headers=_OWNER,
        files={"file": ("mine.txt", io.BytesIO(b"my private notes"), "text/plain")},
        data={"consent": "true"},
    )
    created = _create_run(client, "Export goal", headers=_OWNER, tier="express")
    run_id = created.json()["id"]
    client.post(f"/api/runs/{run_id}/start", headers=_OWNER, json={})
    assert _wait_owned_status(client, run_id, "completed")

    response = client.get("/api/account/export", headers=_OWNER)

    assert response.status_code == 200
    payload = response.json()
    assert payload["client_id"] == "export-owner"
    run_ids = [row["id"] for row in payload["runs"]]
    assert run_id in run_ids
    exported_run = next(r for r in payload["runs"] if r["id"] == run_id)
    assert exported_run["status"] == "completed"
    assert exported_run["report_markdown"]
    titles = [doc["title"] for doc in payload["documents"]]
    assert "mine.txt" in titles
    document = next(d for d in payload["documents"] if d["title"] == "mine.txt")
    assert document["text"] == "my private notes"


def test_export_is_scoped_to_the_caller() -> None:
    client = make_client()
    _create_run(client, "Private goal", headers=_OWNER)

    other_export = client.get("/api/account/export", headers=_OTHER)

    assert other_export.status_code == 200
    assert other_export.json()["runs"] == []


def _configure_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "auth_secret", "test-signing-secret")
    monkeypatch.setattr(
        settings,
        "researcher_access_codes",
        '{"researcher-a":"invite-a","researcher-b":"invite-b"}',
    )


def test_signed_session_rejects_tampering_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_auth(monkeypatch)
    token = auth.create_session_token("researcher-a", now=100)
    assert auth.verify_session_token(token, now=101).subject == "researcher-a"

    with pytest.raises(HTTPException):
        auth.verify_session_token(f"{token}x", now=101)
    with pytest.raises(HTTPException):
        auth.verify_session_token(token, now=100 + 12 * 3600)


def test_required_auth_exchanges_invite_and_isolates_runs(
    monkeypatch: pytest.MonkeyPatch,
    isolated_db: str,
) -> None:
    _configure_auth(monkeypatch)
    app = _configure_allowlisted_cors(monkeypatch)
    client = TestClient(app, headers={"X-Client-ID": "pytest-default-client"})
    unauthenticated = client.get("/api/runs")
    assert unauthenticated.status_code == 401

    session_a = client.post("/api/auth/exchange", json={"access_code": "invite-a"})
    session_b = client.post("/api/auth/exchange", json={"access_code": "invite-b"})
    assert session_a.status_code == 200
    headers_a = {"Authorization": f"Bearer {session_a.json()['access_token']}"}
    headers_b = {"Authorization": f"Bearer {session_b.json()['access_token']}"}
    created = _create_run(client, "Private researcher goal", headers=headers_a)
    assert created.status_code == 200
    run_id = created.json()["id"]

    owned = client.get(
        f"/api/runs/{run_id}",
        headers={**headers_a, "Origin": "https://ai-co-scientist.com"},
    )
    assert owned.status_code == 200
    assert owned.headers["access-control-allow-origin"] == ("https://ai-co-scientist.com")

    runs.update_run_status(run_id, RunStatus.COMPLETED, db_path=isolated_db)
    events = client.get(
        f"/api/runs/{run_id}/events",
        headers={**headers_a, "Origin": "https://ai-co-scientist.com"},
    )
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert events.headers["access-control-allow-origin"] == ("https://ai-co-scientist.com")

    assert client.get(f"/api/runs/{run_id}", headers=headers_b).status_code == 404


@pytest.mark.parametrize("auth_mode", ["compatibility", "required"])
def test_invalid_bearer_returns_401_json(monkeypatch: pytest.MonkeyPatch, auth_mode: str) -> None:
    _configure_auth(monkeypatch)
    monkeypatch.setattr(settings, "auth_mode", auth_mode)
    expired = auth.create_session_token("researcher-a", now=100)
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    for token in ("invalid", expired):
        response = client.get("/api/runs", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid session"}
    client.close()


def _configure_allowlisted_cors(
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    from fastapi.middleware.cors import CORSMiddleware

    from app.main import app

    cors = next(
        middleware
        for middleware in app.user_middleware
        if cast(Any, middleware.cls) is CORSMiddleware
    )
    monkeypatch.setitem(cors.kwargs, "allow_origins", ["https://ai-co-scientist.com"])
    monkeypatch.setitem(cors.kwargs, "allow_credentials", True)
    monkeypatch.setattr(app, "middleware_stack", None)
    return app


def test_allowed_origin_can_read_ownership_denial(
    monkeypatch: pytest.MonkeyPatch, isolated_db: str
) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    app = _configure_allowlisted_cors(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)
    created = _create_run(client, "Private run", headers={"X-Client-ID": "run-owner"})

    run_path = f"/api/runs/{created.json()['id']}"
    response = client.get(
        run_path,
        headers={
            "X-Client-ID": "different-client",
            "Origin": "https://ai-co-scientist.com",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "run not found"}
    assert response.headers["access-control-allow-origin"] == ("https://ai-co-scientist.com")
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "origin" in response.headers["vary"].lower()

    unlisted = client.get(
        run_path,
        headers={
            "X-Client-ID": "different-client",
            "Origin": "https://evil.example",
        },
    )

    assert unlisted.status_code == 404
    assert "access-control-allow-origin" not in unlisted.headers
    client.close()


def _headerless_client() -> TestClient:
    # Identityless clients must not acquire a default identity header.
    from app.main import app

    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/api/runs", {"json": {"research_goal": "Anonymous goal"}}),
        (
            "post",
            "/api/documents",
            {
                "files": {"file": ("notes.txt", b"private notes", "text/plain")},
                "data": {"consent": "true"},
            },
        ),
        (
            "post",
            "/api/interviews",
            {"json": {"research_challenge": "Anonymous challenge"}},
        ),
        # Anonymous exports must fail rather than imply an empty dataset.
        ("get", "/api/account/export", {}),
    ],
)
def test_headerless_caller_is_refused_and_creates_nothing(
    isolated_db: str, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    response = getattr(_headerless_client(), method)(path, **kwargs)

    assert response.status_code == 400
    assert "X-Client-ID" in response.json()["detail"]
    assert views.list_runs(client_id="") == []


def test_configuration_failure_does_not_print_access_codes() -> None:
    invite = "private-invite"
    with pytest.raises(ValidationError) as captured:
        Settings(
            _env_file=None,
            auth_mode="required",
            auth_secret="",
            researcher_access_codes='{"p":"' + invite + '"}',
        )
    assert invite not in str(captured.value)
    assert "AUTH_SECRET" in str(captured.value)


@pytest.mark.parametrize("host", ["example.com/#", "example.com/?"])
def test_host_cannot_bypass_required_auth(host: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "required")
    client = make_client()
    response = client.get("/api/runs", headers={"Host": host})
    assert response.status_code == 401


@pytest.mark.parametrize("host", ["example.com/#", "example.com/?"])
def test_host_cannot_hide_another_researchers_run(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "auth_secret", "test-signing-secret")
    from app.main import app

    client = TestClient(app)
    owner = {"Authorization": f"Bearer {auth.create_session_token('owner')}"}
    stranger = {
        "Authorization": f"Bearer {auth.create_session_token('stranger')}",
        "Host": host,
    }
    created = _create_run(client, "Explore mitochondrial dynamics in neurons", headers=owner)
    assert created.status_code == 200
    response = client.get(f"/api/runs/{created.json()['id']}", headers=stranger)
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("configured_token", "supplied_token", "host", "expected"),
    [
        ("", "", "127.0.0.1", True),
        ("", "", "::1", True),
        ("", "", "localhost", True),
        ("", "", "127.0.0.2", False),
        ("", "", "remote.example", False),
        ("", "", None, False),
        ("", "admin-token", "remote.example", False),
        ("admin-token", "admin-token", "remote.example", True),
        ("admin-token", "admin-token", None, True),
        ("admin-token", "wrong-token", "remote.example", False),
        ("admin-token", "", "remote.example", False),
        ("admin-token", "wrong-token", "127.0.0.1", True),
        ("admin-token", "", "::1", True),
    ],
)
def test_operator_access(
    monkeypatch: pytest.MonkeyPatch,
    configured_token: str,
    supplied_token: str,
    host: str | None,
    expected: bool,
) -> None:
    monkeypatch.setattr(settings, "logs_admin_token", configured_token)
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-logs-token", supplied_token.encode())],
            "client": (host, 50000) if host else None,
        }
    )

    assert is_operator(request) is expected


@pytest.mark.parametrize(
    "header",
    [
        (b"host", b"localhost"),
        (b"x-forwarded-for", b"127.0.0.1"),
        (b"forwarded", b"for=127.0.0.1;host=localhost"),
    ],
)
def test_request_headers_cannot_supply_loopback_address(
    monkeypatch: pytest.MonkeyPatch, header: tuple[bytes, bytes]
) -> None:
    monkeypatch.setattr(settings, "logs_admin_token", "")
    request = Request(
        {
            "type": "http",
            "headers": [header],
            "client": ("remote.example", 50000),
        }
    )

    assert is_operator(request) is False

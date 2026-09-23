"""Researcher invite exchange, signed sessions, and ownership isolation."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth, store
from app.config import settings
from tests._client import make_client


def _configure_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable required auth with two isolated researcher invites."""
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
    """Session authenticity and expiration are both enforced."""
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
    """Only a verified owner can create and retrieve its private run."""
    _configure_auth(monkeypatch)
    client = make_client()
    unauthenticated = client.get("/api/runs")
    assert unauthenticated.status_code == 401

    session_a = client.post(
        "/api/auth/exchange", json={"access_code": "invite-a"}
    )
    session_b = client.post(
        "/api/auth/exchange", json={"access_code": "invite-b"}
    )
    assert session_a.status_code == 200
    headers_a = {"Authorization": f"Bearer {session_a.json()['access_token']}"}
    headers_b = {"Authorization": f"Bearer {session_b.json()['access_token']}"}
    created = client.post(
        "/api/runs",
        headers=headers_a,
        json={"research_goal": "Private researcher goal"},
    )
    assert created.status_code == 200
    run_id = created.json()["id"]

    assert (
        client.get(f"/api/runs/{run_id}", headers=headers_a).status_code == 200
    )
    assert (
        client.get(f"/api/runs/{run_id}", headers=headers_b).status_code == 404
    )


def test_invalid_invite_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unconfigured access codes never mint a session."""
    _configure_auth(monkeypatch)
    response = make_client().post(
        "/api/auth/exchange", json={"access_code": "wrong"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("auth_mode", ["compatibility", "required"])
def test_invalid_bearer_returns_401_json(
    monkeypatch: pytest.MonkeyPatch, auth_mode: str
) -> None:
    _configure_auth(monkeypatch)
    monkeypatch.setattr(settings, "auth_mode", auth_mode)
    expired = auth.create_session_token("researcher-a", now=100)
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    for token in ("invalid", expired):
        response = client.get(
            "/api/runs", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid session"}
    client.close()


def test_run_ownership_allows_cors_preflight(isolated_db: str) -> None:
    """A browser can preflight an owner-authenticated lifecycle mutation."""
    client = make_client()
    created = client.post(
        "/api/runs",
        headers={"X-Client-ID": "browser-owner"},
        json={"research_goal": "Cross-origin research goal"},
    )
    assert created.status_code == 200

    response = client.options(
        f"/api/runs/{created.json()['id']}/start",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-client-id",
        },
    )

    assert response.status_code == 200
    # This process's CORS config depends on whether ALLOWED_ORIGINS is set
    # in its environment (a real allowlist in CI/production; the wildcard
    # fallback for a bare local checkout with no .env), so the header value
    # itself is not pinned here -- see the two `_resolve_cors_config` unit
    # tests below for that. What must hold in both cases is the invariant
    # `_resolve_cors_config` exists to guarantee: an unreflected wildcard
    # origin is never paired with an allow-credentials response, since that
    # pairing is what let any origin on the internet ride compatibility
    # auth's spoofable X-Client-ID header.
    origin_header = response.headers["access-control-allow-origin"]
    credentialed = "access-control-allow-credentials" in response.headers
    assert (origin_header == "*") != credentialed


def test_wildcard_cors_never_reflects_a_credentialed_origin() -> None:
    """Deployments with no ALLOWED_ORIGINS must serve a real wildcard.

    Exercises the exact ``CORSMiddleware`` configuration ``app.main``
    builds from an unset ``ALLOWED_ORIGINS``, on a throwaway app rather
    than the live ``app.main.app`` -- that instance's CORS config is fixed
    at import time from *this test process's own* environment, which may
    itself have ``ALLOWED_ORIGINS`` set (e.g. a developer's local ``.env``),
    so asserting against it would not reliably exercise the fallback.
    Before this fix, ``allow_credentials`` was unconditionally True, and
    Starlette's ``CORSMiddleware`` reflects the requesting origin as an
    explicit allow whenever credentials are on -- so a wildcard origin list
    was not actually a wildcard: it granted a credentialed cross-origin
    allow to literally any origin that asked, including this one.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient as FastAPITestClient

    from app.main import _resolve_cors_config

    origins, allow_credentials = _resolve_cors_config("")
    probe = FastAPI()
    probe.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @probe.get("/x")
    def _probe_route() -> dict[str, bool]:
        return {"ok": True}

    response = FastAPITestClient(probe).options(
        "/x",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


def test_cors_config_wildcard_is_never_credentialed() -> None:
    """The unset-env fallback is a real wildcard, not a reflected origin."""
    from app.main import _resolve_cors_config

    origins, allow_credentials = _resolve_cors_config("")

    assert origins == ["*"]
    assert allow_credentials is False


def test_cors_config_explicit_allowlist_is_credentialed() -> None:
    """A configured allowlist (e.g. production) keeps credentialed CORS."""
    from app.main import _resolve_cors_config

    origins, allow_credentials = _resolve_cors_config(
        "https://ai-co-scientist.com, https://www.ai-co-scientist.com"
    )

    assert origins == [
        "https://ai-co-scientist.com",
        "https://www.ai-co-scientist.com",
    ]
    assert allow_credentials is True


# ---------------------------------------------------------------------------
# An identity-less compatibility caller (no X-Client-ID header at all) must
# get no private scope: it cannot create a run, list one, or read one --
# including a run some other identity-less caller happened to create,
# which is exactly the pool every such caller used to share.
# ---------------------------------------------------------------------------


def _headerless_client() -> TestClient:
    """A TestClient sending no default identity header at all.

    Unlike ``tests._client.make_client``, which now carries a default
    ``X-Client-ID`` so the rest of the suite keeps working under the new
    rule this file tests -- these tests need a caller with genuinely no
    identity.
    """
    from app.main import app

    return TestClient(app)


def test_headerless_caller_cannot_create_a_run(isolated_db: str) -> None:
    """No X-Client-ID at all is refused, not silently pooled as ''."""
    response = _headerless_client().post(
        "/api/runs", json={"research_goal": "Anonymous goal"}
    )
    assert response.status_code == 400
    assert "X-Client-ID" in response.json()["detail"]
    assert store.list_runs(client_id="") == []


def test_headerless_callers_no_longer_share_a_run(isolated_db: str) -> None:
    """Two callers who both send no header must not see the same run.

    Before this fix, both resolved to the same empty-string subject: the
    second caller's ``GET`` and its run listing both reached the first
    caller's run. Since creation is now refused for an empty subject (see
    the sibling test), this proves the read side independently: a run
    persisted directly with an empty ``client_id`` -- the shape every
    pre-fix headerless run was created with -- is unreachable to anyone,
    not just to a different caller.
    """
    legacy = store.create_run(
        "Pre-fix headerless goal",
        "express",
        "engine",
        {},
        store.RunCreateOptions(client_id="", db_path=isolated_db),
    )
    client = _headerless_client()

    assert client.get(f"/api/runs/{legacy.id}").status_code == 404
    assert client.get("/api/runs").json()["runs"] == []


def test_headerless_caller_cannot_stage_a_document(isolated_db: str) -> None:
    """The same identity-less refusal applies to staged documents."""
    response = _headerless_client().post(
        "/api/documents",
        files={"file": ("notes.txt", b"private notes", "text/plain")},
        data={"consent": "true"},
    )
    assert response.status_code == 400
    assert "X-Client-ID" in response.json()["detail"]


def test_headerless_caller_cannot_create_an_interview(
    isolated_db: str,
) -> None:
    """The same identity-less refusal applies to interviews."""
    response = _headerless_client().post(
        "/api/interviews", json={"research_challenge": "Anonymous challenge"}
    )
    assert response.status_code == 400
    assert "X-Client-ID" in response.json()["detail"]


def test_headerless_caller_cannot_export_an_account(isolated_db: str) -> None:
    """The data export refuses rather than exporting the shared pool.

    An empty export would read as "you have no data" rather than "you did
    not say who you are", so this is the one read that refuses instead of
    returning nothing.
    """
    response = _headerless_client().get("/api/account/export")

    assert response.status_code == 400
    assert "X-Client-ID" in response.json()["detail"]

"""Researcher invite exchange, signed sessions, and ownership isolation."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import auth
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

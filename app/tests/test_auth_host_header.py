"""Caller-controlled Host headers cannot change the authorization path."""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import settings
from tests._client import make_client


@pytest.mark.parametrize("host", ["example.com/#", "example.com/?"])
def test_host_cannot_bypass_required_auth(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    created = client.post(
        "/api/runs",
        json={"research_goal": "Explore mitochondrial dynamics in neurons"},
        headers=owner,
    )
    assert created.status_code == 200
    response = client.get(f"/api/runs/{created.json()['id']}", headers=stranger)
    assert response.status_code == 404

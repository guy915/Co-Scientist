"""Authentication configuration and caller-controlled headers fail closed."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import auth
from app.config import Settings, settings
from tests._client import make_client


@pytest.mark.parametrize("mode", ["requried", "disabled", ""])
def test_unknown_auth_mode_is_rejected(mode: str) -> None:
    with pytest.raises(ValidationError, match="auth_mode"):
        Settings(_env_file=None, auth_mode=mode)


@pytest.mark.parametrize("secret", ["", " "])
def test_required_auth_needs_a_secret(secret: str) -> None:
    with pytest.raises(ValidationError, match="AUTH_SECRET"):
        Settings(_env_file=None, auth_mode="required", auth_secret=secret)


@pytest.mark.parametrize("hours", [0, -1])
def test_session_duration_must_be_positive(hours: int) -> None:
    with pytest.raises(ValidationError, match="auth_session_hours"):
        Settings(_env_file=None, auth_session_hours=hours)


def test_local_compatibility_remains_keyless() -> None:
    settings = Settings(
        _env_file=None, auth_mode="compatibility", auth_secret=""
    )
    assert settings.auth_mode == "compatibility"


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

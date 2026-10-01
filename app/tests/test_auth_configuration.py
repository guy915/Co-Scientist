"""Authentication misconfiguration fails before private routes are served."""

import pytest
from pydantic import ValidationError

from app.config import Settings


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

import pytest
from fastapi.testclient import TestClient

import app.auth as auth_rate_limit
from app.config import settings


@pytest.fixture(autouse=True)
def isolated_exchange_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_rate_limit, "_exchange_hits", {})
    monkeypatch.setattr(settings, "auth_secret", "test-signing-secret")
    monkeypatch.setattr(settings, "researcher_access_codes", '{"a":"invite"}')
    monkeypatch.setattr(settings, "auth_exchange_per_minute", 2)


def _client(host: str = "203.0.113.1") -> TestClient:
    from app.main import app

    return TestClient(app, client=(host, 1234))


def test_guessing_budget_includes_successful_exchanges() -> None:
    with _client() as client:
        assert client.post("/api/auth/exchange", json={"access_code": "invite"}).status_code == 200
        assert client.post("/api/auth/exchange", json={"access_code": "wrong"}).status_code == 401
        blocked = client.post("/api/auth/exchange", json={"access_code": "invite"})
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"


def test_caller_headers_do_not_refresh_the_ip_budget() -> None:
    client = _client()
    for index in range(3):
        response = client.post(
            "/api/auth/exchange",
            json={"access_code": "wrong"},
            headers={
                "X-Client-ID": f"rotated-{index}",
                "X-Forwarded-For": f"198.51.100.{index}",
            },
        )
        assert response.status_code == (401 if index < 2 else 429)
    assert (
        _client("203.0.113.2")
        .post("/api/auth/exchange", json={"access_code": "invite"})
        .status_code
        == 200
    )

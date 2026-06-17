"""Backend health + status endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from app.main import app  # pylint: disable=import-outside-toplevel

    return TestClient(app)


def test_health_ok() -> None:
    client = _client()
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "model_name" in data


def test_status_reports_mock_mode() -> None:
    client = _client()
    res = client.get("/status")
    assert res.status_code == 200
    data = res.json()
    assert data["mock_mode"] is True
    assert data["provider"] == "mock"

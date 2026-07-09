"""Backend health + status endpoints."""

from __future__ import annotations

import pytest

from tests._client import make_client as _client


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


def test_status_supervisor_model_falls_back_to_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With SUPERVISOR_MODEL_NAME unset, /status mirrors the engine fallback."""
    from app.config import settings  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(settings, "model_name", "worker/model")
    monkeypatch.setattr(settings, "supervisor_model_name", None)
    data = _client().get("/status").json()
    assert data["supervisor_model_name"] == "worker/model"


def test_status_reports_configured_supervisor_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured supervisor model is surfaced distinctly from the worker."""
    from app.config import settings  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(settings, "model_name", "worker/model")
    monkeypatch.setattr(settings, "supervisor_model_name", "strategic/model")
    data = _client().get("/status").json()
    assert data["supervisor_model_name"] == "strategic/model"
    assert data["model_name"] == "worker/model"

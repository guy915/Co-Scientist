from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import free_usage
from app.config import settings
from app.execution_policy import CAMPAIGN
from app.main import app
from app.store.db import connect
from tests._process_mode_helpers import FakeProcessMode

_CLIENT = {"X-Client-ID": "free-usage-scientist"}


@pytest.fixture
def real_backend(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    fake_process_mode.online()

    async def _no_title(goal: str) -> None:
        return None

    monkeypatch.setattr("app.runs.crud.generate_run_title", _no_title)


def _create(
    client: TestClient,
    headers: dict[str, str] | None = None,
    **body: Any,
) -> Any:
    return client.post(
        "/api/runs",
        json={"research_goal": "free goal", "tier": "express", **body},
        headers=headers or _CLIENT,
    )


def test_applies_only_to_keyless_real_non_campaign_runs() -> None:
    assert free_usage.applies(None, "standard", "real")
    assert not free_usage.applies(None, "standard", "offline")
    assert not free_usage.applies(None, CAMPAIGN, "real")


def test_free_run_must_be_express(real_backend: None) -> None:
    with TestClient(app) as client:
        response = _create(client, tier="standard")
        assert response.status_code == 403
        assert "Express" in response.json()["detail"]
        assert client.get("/api/runs", headers=_CLIENT).json()["runs"] == []


def test_free_run_without_a_tier_defaults_to_express(
    real_backend: None,
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/runs", json={"research_goal": "free goal"}, headers=_CLIENT
        )
    assert response.status_code == 200, response.text
    assert response.json()["config"]["tier"] == "express"


def test_free_run_rejects_numeric_overrides(real_backend: None) -> None:
    with TestClient(app) as client:
        response = _create(client, max_iterations=9)
        assert response.status_code == 403


def test_free_runs_are_capped_per_day(real_backend: None) -> None:
    with TestClient(app) as client:
        for _ in range(3):
            assert _create(client).status_code == 200
        response = _create(client)
        assert response.status_code == 429
        assert "3 free runs" in response.json()["detail"]
        runs = client.get("/api/runs", headers=_CLIENT).json()["runs"]
        assert len(runs) == 3
        other = _create(client, headers={"X-Client-ID": "another-device"})
        assert other.status_code == 200


def test_deleting_a_run_does_not_return_its_slot(real_backend: None) -> None:
    with TestClient(app) as client:
        run_ids = [_create(client).json()["id"] for _ in range(3)]
        deleted = client.delete(f"/api/runs/{run_ids[0]}", headers=_CLIENT)
        assert deleted.status_code in (200, 204)
        assert _create(client).status_code == 429


def test_zero_limit_removes_the_cap(
    real_backend: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "free_runs_per_day", 0)
    with TestClient(app) as client:
        for _ in range(4):
            assert _create(client).status_code == 200
        usage = client.get("/api/free-usage", headers=_CLIENT).json()
        assert usage["limit"] is None
        assert usage["remaining"] is None


def test_usage_endpoint_counts_todays_runs(real_backend: None) -> None:
    with TestClient(app) as client:
        _create(client)
        usage = client.get("/api/free-usage", headers=_CLIENT).json()
    assert usage["enforced"] is True
    assert usage["tier"] == "express"
    assert (usage["limit"], usage["used"], usage["remaining"]) == (3, 1, 2)


def test_offline_runs_are_not_free_usage() -> None:
    with TestClient(app) as client:
        for _ in range(4):
            assert _create(client, tier="standard").status_code == 200
        usage = client.get("/api/free-usage", headers=_CLIENT).json()
    assert usage["enforced"] is False
    assert usage["used"] == 0


def test_yesterdays_runs_do_not_count(real_backend: None) -> None:
    with TestClient(app) as client:
        for _ in range(3):
            _create(client)
        with connect() as conn:
            conn.execute(
                "UPDATE free_run_usage SET created_at = created_at - 86400"
            )
        assert _create(client).status_code == 200

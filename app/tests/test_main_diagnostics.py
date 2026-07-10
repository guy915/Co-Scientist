"""Tests for the diagnostics endpoints and lifespan startup/shutdown wiring.

``/health`` and the mock-mode branch of ``/status`` are already covered by
``test_health.py``; this file adds the untested ``/`` and ``/config``
endpoints, the full ASGI lifespan (startup reconciliation + demo seeding,
then shutdown checkpoint) via ``TestClient`` used as a context manager, and
the module-level settings-to-environment bridging that runs once per import.
"""

from __future__ import annotations

import importlib
import logging
import os

import pytest
from fastapi.testclient import TestClient

from app import store
from app.run_modes import DEFAULT_RUN_TIER, RUN_TIER_DEFAULTS
from app.store import DEMO_CLIENT_ID
from tests._client import make_client as _client


def test_root_endpoint_returns_api_metadata() -> None:
    res = _client().get("/")
    assert res.status_code == 200
    data = res.json()
    assert data == {
        "message": "Co-Scientist API",
        "version": "0.1.0",
        "docs": "/docs",
    }


def test_config_endpoint_returns_standard_tier_defaults() -> None:
    res = _client().get("/config")
    assert res.status_code == 200
    defaults = RUN_TIER_DEFAULTS[DEFAULT_RUN_TIER]
    assert res.json() == {
        "max_iterations": defaults["max_iterations"],
        "initial_hypotheses_count": defaults["initial_hypotheses_count"],
        "evolution_max_count": defaults["evolution_max_count"],
    }


def test_lifespan_reconciles_interrupted_runs_and_seeds_demo_data(
    isolated_db: str,
) -> None:
    """Startup reconciles stuck runs and seeds demo runs; shutdown cleans up.

    Constructing TestClient does not itself run the ASGI lifespan; using it
    as a context manager does, which is what actually exercises startup and
    shutdown. ``tools_config`` is unset by default, so this also covers
    startup's "not set" logging fallback.
    """
    import app.main as main_module

    interrupted = store.create_run(
        "interrupted goal", "default", "mock", {}, db_path=isolated_db
    )
    store.update_run_status(
        interrupted.id, store.RunStatus.RUNNING, db_path=isolated_db
    )

    with TestClient(main_module.app) as client:
        res = client.get("/health")
        assert res.status_code == 200

    reconciled = store.get_run(interrupted.id, db_path=isolated_db)
    assert reconciled is not None
    assert reconciled.status == store.RunStatus.FAILED.value
    assert reconciled.error and "restart" in reconciled.error

    demo_runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(demo_runs) == 3


def test_lifespan_logs_configured_tools_config(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured ``tools_config`` logs the "configured" branch at startup."""
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "tools_config", "some/tools.yaml")

    with TestClient(main_module.app) as client:
        res = client.get("/health")
        assert res.status_code == 200


def test_module_import_bridges_settings_and_logs_missing_mcp_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Module-level env bridging (gemini key, MCP URL) runs on (re)import.

    Reloads ``app.main`` twice: once with settings tweaked to hit both
    conditional branches, then again with the original settings restored so
    later tests see a normally-configured module.
    """
    import app.main as main_module
    from app.config import settings

    original_gemini_key = settings.gemini_api_key
    original_mcp_url = settings.mcp_server_url
    # Recorded as absent so the fixture teardown deletes whatever the reload
    # below sets, regardless of the key's value at that point.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    settings.gemini_api_key = "test-gemini-key"
    settings.mcp_server_url = ""
    try:
        with caplog.at_level(logging.INFO, logger="app.main"):
            importlib.reload(main_module)
        assert os.environ["GEMINI_API_KEY"] == "test-gemini-key"
        assert (
            "mcp_server_url not set - literature review will be disabled"
            in caplog.text
        )
    finally:
        settings.gemini_api_key = original_gemini_key
        settings.mcp_server_url = original_mcp_url
        importlib.reload(main_module)

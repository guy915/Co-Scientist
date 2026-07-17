"""Shared pytest fixtures."""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import pytest

# Provider credentials LiteLLM/the engine may read from the environment. The
# suite must be hermetic: a dev machine's real keys must never leak in and let
# an offline-intended run make a paid call, so every fixture deletes all of
# them before a test runs.
_PROVIDER_KEYS = (
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_API_KEY",
    "DEEPSEEK_API_KEY",
)


@pytest.fixture(scope="session", autouse=True)
def _offline_router() -> None:
    """Install the deterministic offline LLM router once for the whole suite.

    Every workflow-driving test runs the real engine graph pinned to the
    ``offline/`` model backend (the mock provider has been retired), so the
    router must intercept ``litellm.acompletion`` for the entire session. It is
    idempotent and a harmless passthrough for any non-offline model.
    """
    from co_scientist.offline_llm import install_offline_router

    install_offline_router()


@pytest.fixture(autouse=True)
def isolated_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> Iterator[str]:
    """Point the SQLite store at a per-test database and force offline mode."""
    db_path = str(tmp_path / "test.db")
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    monkeypatch.setenv("COSCIENTIST_DB_PATH", db_path)
    monkeypatch.setenv("COSCIENTIST_REPORTS_DIR", reports_dir)
    # Hermetic + offline: strip any real provider credentials and force the
    # deterministic offline backend so tests never make a paid call and every
    # run is reproducible.
    for key in _PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    # Hard kill switch for the literature-review node: never probe the (possibly
    # live) local MCP server. Without it every workflow-driving test pays the
    # per-run MCP-probe cost that dominates an engine run's wall time.
    monkeypatch.setenv("FORCE_LITERATURE_REVIEW", "0")
    # Offline tests prove deterministic behavior without spending provider
    # calls; production real-engine runs use the semantic default.
    from app.config import settings

    monkeypatch.setattr(settings, "claim_assessor", "deterministic")
    # The app-level contextual safety screen is not disabled here: offline-
    # backed runs already skip escalation (safety.screen_with_escalation keys
    # on the run's offline backend), so no offline run makes a real safety call,
    # and the dedicated safety tests keep the default (enabled) screen.
    # Wipe any cached default-path init flags from previous tests.
    from app.store import (
        db as _store_db,
    )

    _store_db._initialized.discard(db_path)
    yield db_path

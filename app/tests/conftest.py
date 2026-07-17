"""Shared pytest fixtures."""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def isolated_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> Iterator[str]:
    """Point the SQLite store at a per-test database and force mock mode."""
    db_path = str(tmp_path / "test.db")
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    monkeypatch.setenv("COSCIENTIST_DB_PATH", db_path)
    monkeypatch.setenv("COSCIENTIST_REPORTS_DIR", reports_dir)
    monkeypatch.setenv("COSCIENTIST_FORCE_MOCK", "1")
    # Offline tests prove deterministic behavior without spending provider
    # calls; production real-engine runs use the semantic default.
    from app.config import settings

    monkeypatch.setattr(settings, "claim_assessor", "deterministic")
    # Wipe any cached default-path init flags from previous tests.
    from app.store import (
        db as _store_db,
    )

    _store_db._initialized.discard(db_path)
    yield db_path
    # Stop any persistent log capture while this test's env is still bound:
    # importing app.main installs capture at import time, and leaving it
    # running would spill stray records into later tests' databases (or
    # drain into the wrong one). Runs before monkeypatch undoes the env, so
    # queued records land in THIS test's db. TestClient lifespans reinstall.
    from app.logging_setup import shutdown_log_capture

    shutdown_log_capture()

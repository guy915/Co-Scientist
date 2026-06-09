"""Shared pytest fixtures."""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[str]:
    """Point the SQLite store at a per-test database and force mock mode."""
    db_path = str(tmp_path / "test.db")
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    monkeypatch.setenv("COSCIENTIST_DB_PATH", db_path)
    monkeypatch.setenv("COSCIENTIST_REPORTS_DIR", reports_dir)
    monkeypatch.setenv("COSCIENTIST_FORCE_MOCK", "1")
    # Wipe any cached default-path init flags from previous tests.
    from app import store as _store

    _store._initialized.discard(db_path)
    yield db_path

"""Shared TestClient factory for the app's FastAPI endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient


def make_client() -> TestClient:
    """Return a TestClient bound to the app.

    A fresh instance per call, so tests that need to simulate a restart can
    build a second client against the same (isolated) database.
    """
    from app.main import app  # pylint: disable=import-outside-toplevel
    return TestClient(app)

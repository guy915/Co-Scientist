"""Shared TestClient factory and polling helpers for the app's endpoints."""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi.testclient import TestClient


def make_client() -> TestClient:
    """Return a TestClient bound to the app.

    A fresh instance per call, so tests that need to simulate a restart can
    build a second client against the same (isolated) database.
    """
    from app.main import app

    return TestClient(app)


def wait_for(
    predicate: Callable[[], bool],
    *,
    timeout: float = 10.0,
    interval: float = 0.05,
) -> bool:
    """Poll ``predicate`` until it is true or the timeout elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def wait_for_status(
    client: TestClient,
    run_id: str,
    status: str,
    *,
    timeout: float = 15.0,
    interval: float = 0.05,
) -> bool:
    """Poll ``GET /api/runs/{id}`` until the run reaches ``status``."""

    def _reached() -> bool:
        response = client.get(f"/api/runs/{run_id}")
        return response.status_code == 200 and bool(
            response.json().get("status") == status
        )

    return wait_for(_reached, timeout=timeout, interval=interval)

"""Shared TestClient factory and polling helpers for the app's endpoints."""

from __future__ import annotations

import asyncio
import time
import types
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any, TypeVar

from fastapi.testclient import TestClient

_T = TypeVar("_T")


def drain(gen: AsyncIterator[_T]) -> list[_T]:
    """Collect every item an async generator yields into a list."""

    async def _run() -> list[_T]:
        return [item async for item in gen]

    return asyncio.run(_run())


def make_client() -> TestClient:
    """Return a TestClient bound to the app.

    A fresh instance per call, so tests that need to simulate a restart can
    build a second client against the same (isolated) database.
    """
    from app.main import app

    return TestClient(app)


def make_operator_client() -> TestClient:
    """Return a TestClient that looks like a loopback (operator) caller.

    The log endpoints grant the app-wide view to loopback callers -- the
    local CLI and agents -- and scope everyone else to their own
    records. Tests covering app-wide behaviour use this; tests covering
    remote access control use :func:`make_client`, whose requests report
    a non-loopback host.
    """
    from app.main import app

    return TestClient(app, client=("127.0.0.1", 50000))


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


def fake_litellm(
    chunks: list[str], *, raise_exc: Exception | None = None
) -> types.SimpleNamespace:
    """Build a fake ``litellm`` module streaming ``chunks`` as deltas.

    Args:
        chunks: Plain-text deltas to stream back, one per fake chunk.
        raise_exc: If set, ``acompletion`` raises this instead of streaming.

    Returns:
        A module-like object exposing an ``acompletion`` matching the shape
        ``qa._stream_llm_deltas`` expects: an async function returning an
        object that supports ``async for``.
    """

    async def _chunk_stream() -> AsyncIterator[Any]:
        for content in chunks:
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(delta=SimpleNamespace(content=content))
                ]
            )

    async def _acompletion(**_kwargs: Any) -> AsyncIterator[Any]:
        if raise_exc is not None:
            raise raise_exc
        return _chunk_stream()

    return types.SimpleNamespace(acompletion=_acompletion)

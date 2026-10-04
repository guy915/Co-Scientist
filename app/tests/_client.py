from __future__ import annotations

import asyncio
import logging
import time
import types
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any, TypeVar

from fastapi.testclient import TestClient

_T = TypeVar("_T")

# A fixed identity supports restarts within isolated test databases; anonymous
# requests have no private scope.
DEFAULT_TEST_CLIENT_ID = "pytest-default-client"
_DEFAULT_HEADERS = {"X-Client-ID": DEFAULT_TEST_CLIENT_ID}


def drain(gen: AsyncIterator[_T]) -> list[_T]:

    async def _run() -> list[_T]:
        return [item async for item in gen]

    return asyncio.run(_run())


def make_client() -> TestClient:
    # Stable client identity survives reconnections and restarts.
    from app.main import app

    return TestClient(app, headers=_DEFAULT_HEADERS)


def make_operator_client() -> TestClient:
    # Loopback operator access differs from remote client scope.
    from app.main import app

    return TestClient(
        app, client=("127.0.0.1", 50000), headers=_DEFAULT_HEADERS
    )


def append_log_row(db_path: str, message: str, **fields: Any) -> int:
    from app.store import logs
    from app.store.logs import NewLogRecord

    record: dict[str, Any] = {
        "level": "INFO",
        "levelno": logging.INFO,
        "logger_name": "app.seeded",
        "message": message,
    }
    record.update(fields)
    return logs.append_log(NewLogRecord(**record), db_path=db_path)


def wait_for(
    predicate: Callable[[], bool],
    *,
    timeout: float = 10.0,
    interval: float = 0.05,
) -> bool:
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
    # Poll with the owner identity; other identities receive 404.

    def _reached() -> bool:
        response = client.get(f"/api/runs/{run_id}")
        return response.status_code == 200 and bool(
            response.json().get("status") == status
        )

    return wait_for(_reached, timeout=timeout, interval=interval)


def fake_litellm(
    chunks: list[str], *, raise_exc: Exception | None = None
) -> types.SimpleNamespace:

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

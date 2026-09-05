"""Tests for the sync/async context-propagation bridge (app/async_bridge.py)."""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor

from app.async_bridge import propagate_context, run_coroutine_sync

_probe: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "test_async_bridge_probe", default=None
)


def test_propagate_context_carries_value_into_a_new_thread() -> None:
    """A ContextVar set on the submitting thread reaches the pool worker."""
    token = _probe.set("scoped-value")
    try:

        def _read() -> str | None:
            return _probe.get()

        wrapped = propagate_context(_read)
    finally:
        _probe.reset(token)

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(wrapped).result() == "scoped-value"


def test_run_coroutine_sync_carries_value_onto_the_bridge_loop() -> None:
    """A ContextVar set on the calling thread reaches the bridge coroutine."""
    token = _probe.set("bridge-value")
    try:

        async def _read() -> str | None:
            return _probe.get()

        result = run_coroutine_sync(_read)
    finally:
        _probe.reset(token)

    assert result == "bridge-value"


def test_run_coroutine_sync_runs_many_calls_concurrently() -> None:
    """Several blocked calls resolve together, not one loop teardown apiece."""
    import time

    async def _slow() -> float:
        start = time.monotonic()
        import asyncio

        await asyncio.sleep(0.05)
        return start

    with ThreadPoolExecutor(max_workers=5) as pool:
        starts = list(pool.map(lambda _: run_coroutine_sync(_slow), range(5)))

    spread = max(starts) - min(starts)
    assert spread < 0.05, f"calls did not overlap (start spread {spread})"

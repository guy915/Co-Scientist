from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import threading
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _ensure_bridge_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(
                target=loop.run_forever,
                name="app-async-bridge",
                daemon=True,
            ).start()
            _loop = loop
        return _loop


def propagate_context(fn: Callable[..., _T]) -> Callable[..., _T]:
    """Capture at submission: one Context cannot be entered concurrently.
    Replay independent values and reset reused workers.
    """
    items = list(contextvars.copy_context().items())

    @functools.wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> _T:
        tokens = [(var, var.set(value)) for var, value in items]
        try:
            return fn(*args, **kwargs)
        finally:
            for var, token in reversed(tokens):
                var.reset(token)

    return _wrapped


def run_coroutine_sync(coro_factory: Callable[[], Awaitable[_T]]) -> _T:
    """A persistent bridge loop preserves LiteLLM's loop-bound clients;
    scoped values reset before later calls to prevent cross-run
    contamination.
    """
    loop = _ensure_bridge_loop()
    items = list(contextvars.copy_context().items())

    async def _runner() -> _T:
        tokens = [(var, var.set(value)) for var, value in items]
        try:
            return await coro_factory()
        finally:
            for var, token in reversed(tokens):
                var.reset(token)

    future = asyncio.run_coroutine_threadsafe(_runner(), loop)
    return future.result()


async def run_off_loop(call: Callable[[], _T]) -> _T:
    """A dedicated thread keeps the task loop free to renew leases;
    explicitly propagate budget and telemetry context.
    """
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as host:
        return await loop.run_in_executor(host, propagate_context(call))


# Bound logging-worker shutdown even if a callback ignores cancellation; cohort
# exit cannot wait indefinitely.
_STOP_TIMEOUT_SECONDS = 10.0


async def stop_litellm_logging_worker() -> None:
    """Only the owning event loop can cancel LiteLLM's logging worker;
    logging cleanup must never change the scientific outcome.
    """
    try:
        from litellm.litellm_core_utils.logging_worker import (
            GLOBAL_LOGGING_WORKER,
        )
    except Exception:
        logger.debug("litellm logging worker unavailable", exc_info=True)
        return

    # LiteLLM's private _bound_loop is its only record of the worker task's
    # owning loop.
    bound_loop = getattr(GLOBAL_LOGGING_WORKER, "_bound_loop", None)
    if bound_loop is not asyncio.get_running_loop():
        return

    try:
        await asyncio.wait_for(GLOBAL_LOGGING_WORKER.stop(), timeout=_STOP_TIMEOUT_SECONDS)
    except Exception:
        logger.debug("Stopping the litellm logging worker failed", exc_info=True)


def run_in_scoped_loop(coro: Coroutine[Any, Any, _T]) -> _T:
    """Close the loop's own logging worker before discarding the temporary
    cohort loop.
    """

    async def _runner() -> _T:
        try:
            return await coro
        finally:
            await stop_litellm_logging_worker()

    return asyncio.run(_runner())

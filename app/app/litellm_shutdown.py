"""Tear down litellm's background logging worker with its event loop.

LiteLLM keeps one process-global ``LoggingWorker`` whose ``_worker_loop``
task is created lazily on whichever event loop first makes a completion
call, and it is never stopped on its own. This process runs many
short-lived loops -- one per durable-run cohort thread, plus the scoped
``asyncio.run`` calls that drive provider work off a ``ThreadPoolExecutor``
-- so that task routinely outlives the loop that owns it. When the worker
later rebinds to a new loop it drops the old task, which is then garbage
collected while still pending and logs an ERROR through ``asyncio``:

    Task was destroyed but it is pending!
    task: <Task pending name='Task-1676'
      coro=<LoggingWorker._worker_loop() ...>>

Nothing is actually broken when that fires -- the worker only carries
best-effort logging callbacks -- but it lands in the persisted app log at
ERROR against whatever run happened to be executing, which is exactly the
signal an operator is meant to trust. Stopping the worker before its loop
closes removes the pending task instead of hiding the message.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Ceiling on the worker's own shutdown. ``stop()`` cancels the loop task,
# whose CancelledError handler drains the queue under litellm's own 5s cap,
# so this only guards against a callback that ignores cancellation -- a
# cohort's exit must not wait on one.
_STOP_TIMEOUT_SECONDS = 10.0


async def stop_litellm_logging_worker() -> None:
    """Stop litellm's logging worker when it belongs to the running loop.

    Skips the shutdown when the worker is bound elsewhere: several cohort
    loops are live at once in this process, on different threads, and
    cancelling a task that belongs to another loop is the same
    cross-loop trap the ranking semaphore hit (AGENTS.md: "No
    process-global asyncio primitives"). The loop that does own it runs
    this on its own way out.

    Best effort throughout -- this is logging plumbing, and a failure
    here must never become the outcome of the work it followed.
    """
    try:
        from litellm.litellm_core_utils.logging_worker import (
            GLOBAL_LOGGING_WORKER,
        )
    except Exception:
        logger.debug("litellm logging worker unavailable", exc_info=True)
        return

    # ``_bound_loop`` is private, but it is the only record litellm keeps of
    # which loop the worker's task was created on, and reading it is what
    # makes the guard above possible.
    bound_loop = getattr(GLOBAL_LOGGING_WORKER, "_bound_loop", None)
    if bound_loop is not asyncio.get_running_loop():
        return

    try:
        await asyncio.wait_for(
            GLOBAL_LOGGING_WORKER.stop(), timeout=_STOP_TIMEOUT_SECONDS
        )
    except Exception:
        logger.debug(
            "Stopping the litellm logging worker failed", exc_info=True
        )


def run_in_scoped_loop(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` on a private loop, closing litellm's worker with it.

    Drop-in replacement for ``asyncio.run`` at every site that opens a
    loop this process will later discard.

    Args:
        coro: The coroutine to drive to completion.

    Returns:
        Whatever ``coro`` returns.
    """

    async def _runner() -> T:
        try:
            return await coro
        finally:
            await stop_litellm_logging_worker()

    return asyncio.run(_runner())

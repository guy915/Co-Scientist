"""Shared stand-ins for the durable task-worker test suites.

Leading underscore so pytest does not collect this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app import store


def make_cancellable_executor(
    started: asyncio.Event, interrupted: asyncio.Event
) -> Callable[..., Awaitable[dict[str, bool]]]:
    """Build an executor stub that records its own cancellation.

    The stub matches the ``execute_engine_task`` signature. It sets
    ``started``, then waits forever; when the surrounding task is
    cancelled it sets ``interrupted`` and re-raises, proving the
    cancellation reached the payload coroutine.

    Args:
        started: Set as soon as the stub begins executing.
        interrupted: Set when the stub is cancelled.

    Returns:
        The async executor stub to patch over ``execute_engine_task``.
    """

    async def _execute(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, bool]:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            interrupted.set()
            raise
        return {"completed": True}

    return _execute

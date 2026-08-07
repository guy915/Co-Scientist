"""A scoped loop must not leave litellm's logging worker task behind.

The worker's ``_worker_loop`` task is created on whichever loop first makes
a completion call and never stopped, so every short-lived loop in this
process (a run cohort, a ThreadPoolExecutor escalation) used to close over
a pending task that later logged ``Task was destroyed but it is pending!``
at ERROR against an unrelated run. These tests pin both halves of the fix:
the loop that owns the worker stops it, and a loop that does not own it
leaves it alone.
"""

from __future__ import annotations

import asyncio

from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER

from app.litellm_shutdown import run_in_scoped_loop


async def _noop() -> None:
    """Stand in for the best-effort callbacks litellm actually queues."""
    return None


def test_scoped_loop_stops_a_worker_it_started() -> None:
    run_in_scoped_loop(_start_worker_on_running_loop())

    # Nothing pending survives the loop, so no task is left to be garbage
    # collected into an ERROR record later.
    assert GLOBAL_LOGGING_WORKER._worker_task is None


def test_scoped_loop_leaves_a_worker_bound_elsewhere_alone() -> None:
    other_loop = asyncio.new_event_loop()
    try:
        # Bind the worker to a loop this process keeps running: cancelling
        # its task from another loop is the cross-loop trap the guard exists
        # to avoid.
        other_loop.run_until_complete(
            _start_worker_on_running_loop(),
        )
        foreign_task = GLOBAL_LOGGING_WORKER._worker_task
        assert foreign_task is not None

        run_in_scoped_loop(_noop())

        assert GLOBAL_LOGGING_WORKER._worker_task is foreign_task
        assert not foreign_task.cancelled()
    finally:
        other_loop.run_until_complete(GLOBAL_LOGGING_WORKER.stop())
        other_loop.close()


async def _start_worker_on_running_loop() -> None:
    """Start the global worker on whichever loop is currently running."""
    GLOBAL_LOGGING_WORKER.start()
    # Let the worker task reach its first await so it is genuinely pending.
    await asyncio.sleep(0)
    assert GLOBAL_LOGGING_WORKER._worker_task is not None

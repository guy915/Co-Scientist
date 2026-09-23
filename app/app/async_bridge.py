"""Bridges the app's synchronous claim-assessment threads to asyncio work.

The claim gate and the finalize grounding pass both assess many claims
concurrently on a plain ``ThreadPoolExecutor`` (``claim_grounding_assess.
_assess_flat_claims``), because the entailment ``Assessor`` protocol is
synchronous. ``ThreadPoolExecutor`` does not copy the submitting thread's
``contextvars`` into its worker threads (unlike ``asyncio.to_thread``), so
a run-scoped context -- ``co_scientist.llm_call_budget.scoped_llm_call_
budget``, ``co_scientist.llm_telemetry.scoped_telemetry`` -- set on the
durable task's own coroutine would otherwise silently vanish for every
claim assessed on a pool thread, which is exactly the blindness this
module exists to close (see the root AGENTS.md entailment-gate finding).

``propagate_context`` replays the calling thread's contextvar values at
the start of the wrapped call rather than trying to hand the *same*
``contextvars.Context`` object across threads: a ``Context`` raises if
entered concurrently by more than one thread, which up to
``ASSESSMENT_CONCURRENCY`` claims running at once would trigger. Replaying
plain ``(var, value)`` pairs has no such restriction -- each thread just
sets its own copies.

``run_coroutine_sync`` is the second half: it lets a synchronous assessor
call the engine's async ``call_llm_json`` seam. It runs every submitted
coroutine on one persistent, lazily-started background event loop rather
than ``asyncio.run()`` per call -- litellm caches its async HTTP client
keyed to the loop that created it, and tearing that loop down (as
``asyncio.run()`` does on return) invalidates the cached client for the
very next call, surfacing as "Event loop is closed" under concurrent
claim assessment. One long-lived loop side-steps that entirely; multiple
callers still run concurrently because ``run_coroutine_threadsafe``
schedules each awaited coroutine independently on it.

``run_off_loop`` is the third: it hands a whole blocking assessment wave
to one dedicated thread and awaits it, so the durable task's own event
loop -- and the lease heartbeat renewing on it -- stays responsive for
the wave's duration.
schedules each awaited coroutine independently on it.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

_T = TypeVar("_T")

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _ensure_bridge_loop() -> asyncio.AbstractEventLoop:
    """Return the shared background loop, starting it on first use."""
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
    """Wrap ``fn`` so a new thread running it sees the caller's contextvars.

    Call this at the point a callable is *submitted* to a thread pool (not
    inside the pool worker), so the snapshot is the submitting thread's
    ambient context, not the pool worker's own (empty) one. Every replayed
    value is reset afterward because executor threads are reused across runs.
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
    """Run one coroutine on the shared bridge loop and block for its result.

    Replays the *calling thread's* contextvars inside the coroutine before
    awaiting the real work, so a run-scoped budget/telemetry context set
    on the calling thread (itself possibly already replayed there by
    ``propagate_context``) reaches the provider call made on the bridge
    loop's own thread. Replayed values are reset before the shared loop accepts
    later work, so a campaign call cannot contaminate a standard call.

    Args:
        coro_factory: Builds the coroutine to run. A factory rather than a
            bare coroutine object, since a coroutine created on one loop's
            thread must not be scheduled on this call before its context
            replay wrapper (below) has had a chance to run first.
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
    """Run a blocking claim-assessment wave off the caller's event loop.

    ``call`` is expected to itself fan out across ``ASSESSMENT_CONCURRENCY``
    worker threads (see ``claim_grounding_assess``), but that inner pool
    still blocks whichever thread calls it for the wave's whole duration.
    Both callers of this helper (the pre-ranking claim gate and the
    finalize grounding pass) run inside a durable task on the cohort's
    event loop, whose ``task_worker._heartbeat_lease`` renews the task's
    lease from that same loop -- running the wave there directly starves
    the heartbeat for the wave's duration, which cost a healthy finalize
    task its lease and its retry budget in production (run b82f9162,
    2026-09-06: the wave ran long enough for the 300s lease to expire
    while the loop thread was blocked). One dedicated single-worker
    thread, awaited via ``run_in_executor``, keeps the loop free to renew
    the lease while the wave runs.

    ``run_in_executor`` does not copy this coroutine's contextvars into
    the dedicated thread (unlike ``asyncio.to_thread``) -- wrap the call so
    the run's scoped LLM-call budget and telemetry phase (entered by the
    caller) reach the entailment calls this wave makes.
    """
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as host:
        return await loop.run_in_executor(host, propagate_context(call))

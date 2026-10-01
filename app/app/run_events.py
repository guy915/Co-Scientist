"""Run-event emission for the durable engine tasks and the engine adapter.

Homed separately from ``engine_adapter`` so the per-run event emitter and the
minimal JSON-safe event stubs stay independently nameable/testable, and so
the streamed SSE payload shapes have one implementation. It sits outside
the report package on purpose: every ``engine_tasks_*`` module and
``engine_adapter.events`` emit run events, and none of them should pull the
Goal Report in to do so.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app import store
from app.store import RunStatus
from app.text_utils import hypothesis_id, hypothesis_title

# The durable engine tasks build one of these per run: records an event and
# returns its stub.
EmitFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def make_emitter(
    run_id: str,
    *,
    db_path: str | None = None,
    sleep_seconds: float = 0.0,
) -> EmitFn:
    """Build the per-run event emitter the durable engine tasks stream through.

    Records an event via ``store.append_event`` and returns the streamed stub
    ``{"seq", "type", "payload"}`` -- the single home for that SSE contract
    shape. ``sleep_seconds`` is available for callers that want to pace a
    synthetic timeline; every current caller leaves it at 0 (the generator's
    ``yield`` already cedes control).

    Args:
        run_id: Identifier of the run whose events are recorded.
        db_path: Optional override for the SQLite database path.
        sleep_seconds: Optional per-event pacing delay; unused today.

    Returns:
        An async emitter callable matching ``EmitFn``.
    """

    async def emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        # append_event assigns and returns the monotonic per-run sequence
        # number used by the SSE stream's replay-then-live protocol.
        seq = store.append_event(run_id, type_, payload, db_path=db_path)
        if sleep_seconds:
            await asyncio.sleep(sleep_seconds)
        return {"seq": seq, "type": type_, "payload": payload}

    return emit


def hypothesis_stub(h: dict[str, Any]) -> dict[str, str]:
    """Project a hypothesis to a minimal JSON-safe stub for event payloads."""
    return {
        "id": hypothesis_id(h),
        "title": hypothesis_title(h),
    }


def article_stub(a: dict[str, Any]) -> dict[str, str]:
    """Project an article to a minimal JSON-safe stub for event payloads."""
    return {
        "title": str(a.get("title") or "Untitled"),
        "url": str(a.get("url") or ""),
    }


def match_stub(m: dict[str, Any]) -> dict[str, str]:
    """Project a tournament matchup to a minimal JSON-safe stub."""
    return {"winner": str(m.get("winner") or "")}


async def emit_cancel_or_pause(
    run_id: str, db_path: str | None, emit: EmitFn
) -> dict[str, Any]:
    """Persist and emit the terminal status for a stopped run.

    The stop signal covers both cancel and pause (the pause endpoint marks
    the run PAUSED durably before the workflow observes the signal), so the
    run's persisted status decides which terminal event a stopped stream
    emits: a paused run stays ``paused`` (resumable) rather than being
    overwritten as ``cancelled``.
    """
    run = store.get_run(run_id, db_path=db_path)
    if run is not None and run.status == RunStatus.PAUSED.value:
        return await emit("status", {"status": "paused"})
    store.update_run_status(run_id, RunStatus.CANCELLED, db_path=db_path)
    return await emit("status", {"status": "cancelled"})

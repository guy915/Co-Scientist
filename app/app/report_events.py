"""Event-payload helpers for the workflow provider.

Homed separately from ``engine_adapter`` so the per-run event emitter and the
minimal JSON-safe event stubs stay independently nameable/testable, and so
the streamed SSE payload shapes have one implementation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app import store
from app.store import RunStatus
from app.text_utils import hypothesis_id, hypothesis_title

# Emitter both providers pass in: records an event and returns its stub.
EmitFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def make_emitter(
    run_id: str,
    *,
    db_path: str | None = None,
    sleep_seconds: float = 0.0,
) -> EmitFn:
    """Build the per-run event emitter both providers stream through.

    Records an event via ``store.append_event`` and returns the streamed stub
    ``{"seq", "type", "payload"}`` -- the single home for that SSE contract
    shape. The mock passes ``sleep_seconds`` to pace its synthetic timeline; the
    engine leaves it at 0 (the generator's ``yield`` already cedes control).

    Args:
        run_id: Identifier of the run whose events are recorded.
        db_path: Optional override for the SQLite database path.
        sleep_seconds: Optional per-event pacing delay (mock only).

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

    The pause endpoint reuses the cancel signal, so a pause-flagged run is
    persisted/emitted as ``paused`` (resumable) rather than ``cancelled``.
    Both workflow providers call this to ensure identical event/persistence
    behaviour on stop.
    """
    from app.runs_registry import is_pause_requested

    if is_pause_requested(run_id):
        store.update_run_status(run_id, RunStatus.PAUSED, db_path=db_path)
        return await emit("status", {"status": "paused"})
    store.update_run_status(run_id, RunStatus.CANCELLED, db_path=db_path)
    return await emit("status", {"status": "cancelled"})

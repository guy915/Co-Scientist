"""Run-event emission for the durable engine tasks and the engine adapter.

Homed separately from ``engine_adapter`` so the per-run event emitter and the
minimal JSON-safe event stubs stay independently nameable/testable, and so
the streamed SSE payload shapes have one implementation. It sits outside
the report package on purpose: every ``app.engine_tasks`` module and
``engine_adapter.events`` emit run events, and none of them should pull the
Goal Report in to do so.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app import store
from app.text_utils import hypothesis_id, hypothesis_title

# The durable engine tasks build one of these per run: records an event and
# returns its stub.
EmitFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def make_emitter(
    run_id: str,
    *,
    db_path: str | None = None,
) -> EmitFn:
    """Build the per-run event emitter the durable engine tasks stream through.

    Records an event via ``store.append_event`` and returns the streamed stub
    ``{"seq", "type", "payload"}`` -- the single home for that SSE contract
    shape.

    Args:
        run_id: Identifier of the run whose events are recorded.
        db_path: Optional override for the SQLite database path.

    Returns:
        An async emitter callable matching ``EmitFn``.
    """

    async def emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        # append_event assigns and returns the monotonic per-run sequence
        # number used by the SSE stream's replay-then-live protocol.
        seq = store.append_event(run_id, type_, payload, db_path=db_path)
        return {"seq": seq, "type": type_, "payload": payload}

    return emit


def hypothesis_stub(h: dict[str, Any]) -> dict[str, str]:
    """Project a hypothesis to a minimal JSON-safe stub for event payloads."""
    return {
        "id": hypothesis_id(h),
        "title": hypothesis_title(h),
    }

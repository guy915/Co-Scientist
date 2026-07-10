"""Event-payload helpers shared by both workflow providers.

Homed here (rather than inside a single provider) so the real-engine drain
(``engine_adapter``) and the deterministic mock (``mock_workflow``) build the
per-run event emitter and the minimal JSON-safe event stubs through one
implementation -- keeping the streamed SSE payload shapes identical across
providers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app import store

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
        "id": str(h.get("id") or h.get("hypothesis_id") or ""),
        "title": str(h.get("title") or h.get("text") or "Untitled")[:140],
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

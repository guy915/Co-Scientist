from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Request

from app.sse import sse_frame
from app.store import events as store
from app.store import runs
from app.store.models import TERMINAL_STATUSES, RunRow, RunStatus

# Paused runs are resumable but stop producing events; close the stream until
# clients
# reconnect after resume.
_STREAM_END_STATUSES: tuple[RunStatus, ...] = (
    *TERMINAL_STATUSES,
    RunStatus.PAUSED,
)


def _terminal_frame(status: str, seq: int) -> str:
    """The synthetic terminal frame closes a connection and is never
    persisted.
    """
    return sse_frame({"type": "_terminal", "payload": {"status": status}, "seq": seq})


def _terminal_status_from_event(ev: dict[str, Any]) -> str | None:
    if ev["type"] != "status":
        return None
    payload = ev.get("payload") or {}
    status = payload.get("status")
    if isinstance(status, str) and status in _STREAM_END_STATUSES:
        return status
    return None


def _terminal_status_from_run(run_id: str) -> str | None:
    current = runs.get_run(run_id)
    if current and current.status in _STREAM_END_STATUSES:
        return current.status
    return None


def _resolve_tick_terminal(terminal_status: str | None, run_id: str, tick: int) -> str | None:
    """Periodic run-row checks cover terminal writes that append no status
    event without querying on every tick.
    """
    if terminal_status is not None:
        return terminal_status
    if tick % 10 == 9:
        return _terminal_status_from_run(run_id)
    return None


def _drain_tick_frames(
    run_id: str,
    last_seq: int,
) -> tuple[int, str | None, list[str]]:
    new_events = store.list_events(run_id, after_seq=last_seq)
    frames: list[str] = []
    terminal_status: str | None = None
    for ev in new_events:
        last_seq = ev["seq"]
        frames.append(sse_frame(ev))
        terminal_status = _terminal_status_from_event(ev) or terminal_status
    return last_seq, terminal_status, frames


_TICK_SECONDS = 0.5
# Railway closes HTTP responses that send nothing for 5 minutes, and one model
# call can outlast that; an SSE comment keeps the stream open and clients
# ignore it.
_KEEPALIVE_TICKS = 30
_KEEPALIVE_FRAME = ": keepalive\n\n"


def _poll_tick(run_id: str, last_seq: int, tick: int) -> tuple[int, str | None, list[str]]:
    last_seq, terminal_status, frames = _drain_tick_frames(run_id, last_seq)
    return last_seq, _resolve_tick_terminal(terminal_status, run_id, tick), frames


async def _stream_live_tail(
    run_id: str,
    request: Request,
    last_seq: int,
) -> AsyncGenerator[str, None]:
    """The producer can live in another process; the persisted event log is
    the only reliable signal. Each viewer polls twice a second, so the store
    reads run off the event loop.
    """
    idle_ticks = 0
    for tick in range(10_000):  # 10k * 0.5s = ~83 minutes max stream
        if await request.is_disconnected():
            return
        await asyncio.sleep(_TICK_SECONDS)

        last_seq, terminal_status, frames = await asyncio.to_thread(
            _poll_tick, run_id, last_seq, tick
        )
        for frame in frames:
            yield frame
        idle_ticks = 0 if frames else idle_ticks + 1
        if idle_ticks >= _KEEPALIVE_TICKS:
            idle_ticks = 0
            yield _KEEPALIVE_FRAME

        if terminal_status is not None:
            yield _terminal_frame(terminal_status, last_seq)
            return


async def _event_stream(
    run_id: str,
    request: Request,
    after: int,
    run: RunRow,
) -> AsyncGenerator[str, None]:
    """Reconnection resumes after the last observed sequence without replay
    gaps.
    """
    last_seq = after

    # Historical replay can be large; offload its blocking read rather than
    # stalling the
    # event loop.
    history = await asyncio.to_thread(store.list_events, run_id, after_seq=last_seq)
    for ev in history:
        last_seq = ev["seq"]
        yield sse_frame(ev)

    if run.status in _STREAM_END_STATUSES:
        yield _terminal_frame(run.status, last_seq)
        return

    async for frame in _stream_live_tail(run_id, request, last_seq):
        yield frame

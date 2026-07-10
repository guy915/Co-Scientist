"""SSE streaming helpers for the run events endpoint.

Backs ``runs.stream_events``: replays the persisted event log from a client's
last-seen sequence, then tails live events. Streams are driven by the store so
they survive client reconnects and full backend restarts; the in-process
``runs_registry`` handle only cuts latency when this process is the producer.
Every name is re-exported from ``app.runs`` so the ``app.runs.<name>`` import
paths stay stable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Request

from app import qa, store
from app.runs_registry import _active, _active_lock, _RunHandle
from app.store import TERMINAL_STATUSES, RunRow


def _terminal_frame(status: str, seq: int) -> str:
    """Format the synthetic ``_terminal`` SSE frame that ends a stream.

    This frame is never persisted; it only tells clients to close.
    """
    return qa.sse_frame(
        {"type": "_terminal", "payload": {"status": status}, "seq": seq}
    )


async def _should_skip_tick(handle: _RunHandle | None, tick: int) -> bool:
    """Wait out one poll tick and report whether to skip the store query.

    Wakes early on the producer's pulse; the event is cleared before
    returning so a set that races this wait is caught next iteration. With
    an in-process producer, every appended event sets `new_event`, so a
    timed-out wait means nothing was written -- skip the query, except on
    the every-10th-tick terminal-status safety net.

    Args:
        handle: In-process run handle, or None when this process is not the
            producer (falls back to plain fixed-interval polling and never
            skips).
        tick: The current tick index within the streaming loop.

    Returns:
        True if this tick's event query should be skipped.
    """
    if handle is None:
        await asyncio.sleep(0.5)
        return False
    try:
        await asyncio.wait_for(handle.new_event.wait(), timeout=0.5)
        handle.new_event.clear()
        return False
    except asyncio.TimeoutError:
        return tick % 10 != 9


def _terminal_status_from_event(ev: dict[str, Any]) -> str | None:
    """Return the terminal run status carried by a status event, if any."""
    if ev["type"] != "status":
        return None
    payload = ev.get("payload") or {}
    status = payload.get("status")
    if isinstance(status, str) and status in TERMINAL_STATUSES:
        return status
    return None


def _terminal_status_from_run(run_id: str) -> str | None:
    """Return the run's current status if it has reached a terminal state."""
    current = store.get_run(run_id)
    if current and current.status in TERMINAL_STATUSES:
        return current.status
    return None


def _resolve_tick_terminal(
    terminal_status: str | None, run_id: str, tick: int
) -> str | None:
    """Resolve this tick's terminal status, falling back to the safety net.

    A terminal transition normally rides on a new event (all workflow paths
    append a `status` event), so ticks without one skip the run-row query;
    the every-10th tick check covers terminal writes that append no event.

    Args:
        terminal_status: Terminal status already found among this tick's
            events, if any.
        run_id: Identifier of the run being streamed.
        tick: The current tick index within the streaming loop.

    Returns:
        The terminal status to end the stream on, or None to keep polling.
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
    """Fetch and format one tick's new events for `_stream_live_tail`.

    No `await` separates one event's formatting from the next in the
    original inline loop, so collecting frames here and yielding them from
    the caller afterward produces the same frames in the same order.

    Args:
        run_id: Identifier of the run being streamed.
        last_seq: Highest sequence number already yielded.

    Returns:
        A ``(last_seq, terminal_status, frames)`` tuple: the updated highest
        sequence number, the terminal run status carried by these events (if
        any), and the SSE frames to yield in order.
    """
    new_events = store.list_events(run_id, after_seq=last_seq)
    frames: list[str] = []
    terminal_status: str | None = None
    for ev in new_events:
        last_seq = ev["seq"]
        frames.append(qa.sse_frame(ev))
        terminal_status = _terminal_status_from_event(ev) or terminal_status
    return last_seq, terminal_status, frames


async def _stream_live_tail(
    run_id: str,
    request: Request,
    handle: _RunHandle | None,
    last_seq: int,
) -> AsyncGenerator[str, None]:
    """Poll and yield live SSE frames after replay, until terminal or gone.

    Polls the store; the in-process handle's `new_event` cuts latency when
    this process is the producer. Caps with a wall-clock so a stale
    connection doesn't hang forever.

    Args:
        run_id: Identifier of the run being streamed.
        request: Incoming HTTP request, used to detect client disconnects.
        handle: In-process run handle, or None when this process is not the
            producer (falls back to plain fixed-interval polling).
        last_seq: Highest sequence number already yielded by replay.

    Yields:
        SSE-formatted frame strings, ending with a synthetic `_terminal`
        frame once the run reaches a terminal status.
    """
    for tick in range(10_000):  # 10k * 0.5s = ~83 minutes max stream
        if await request.is_disconnected():
            return

        if await _should_skip_tick(handle, tick):
            continue

        last_seq, terminal_status, frames = _drain_tick_frames(run_id, last_seq)
        for frame in frames:
            yield frame

        terminal_status = _resolve_tick_terminal(terminal_status, run_id, tick)
        if terminal_status is not None:
            yield _terminal_frame(terminal_status, last_seq)
            return


async def _event_stream(
    run_id: str,
    request: Request,
    after: int,
    run: RunRow,
) -> AsyncGenerator[str, None]:
    """Yield SSE frames: full replay from `after`, then a live tail.

    Clients reconnect with ?after= set to their last seen seq, so replay is
    idempotent and gap-free.
    """
    last_seq = after

    # Replay historical events first.
    history = store.list_events(run_id, after_seq=last_seq)
    for ev in history:
        last_seq = ev["seq"]
        yield qa.sse_frame(ev)

    # If terminal already, send a final marker and return.
    if run.status in TERMINAL_STATUSES:
        yield _terminal_frame(run.status, last_seq)
        return

    # Handle is present only when this process runs the workflow; other
    # processes (or post-restart streams) fall back to pure polling.
    async with _active_lock:
        handle = _active.get(run_id)

    async for frame in _stream_live_tail(run_id, request, handle, last_seq):
        yield frame

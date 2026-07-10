"""In-process active-run registry for cancellation and event signalling.

Holds the per-process map of workflows running in THIS process. Presence of a
run_id doubles as the "already active" guard in ``runs.start_run``; entries are
removed in the runner's finally block. Both the run router (``runs``) and the
SSE streaming helpers (``runs_events``) import this shared state, so a single
registry backs cancellation and the in-process new-event fast path.
"""

from __future__ import annotations

import asyncio


class _RunHandle:
    """Per-run handle tracking cancellation and new-event signalling."""

    def __init__(self) -> None:
        # Set by /cancel; the workflow checks it between steps and stops.
        self.cancelled = asyncio.Event()
        # Set by /pause (alongside cancelled): distinguishes a cooperative
        # pause (resumable -> PAUSED) from an outright cancel (-> CANCELLED).
        self.paused = False
        # Pulsed by the runner after each workflow event so in-process SSE
        # streams can wake immediately instead of waiting out a poll tick.
        self.new_event = asyncio.Event()


# In-memory registry of workflows running in THIS process. Presence of a
# run_id doubles as the "already active" guard in start_run; entries are
# removed in the runner's finally block. After a restart the map is empty,
# which is why reconcile_interrupted_runs exists on the store side.
_active: dict[str, _RunHandle] = {}
_active_lock = asyncio.Lock()


def is_pause_requested(run_id: str) -> bool:
    """True when the run's stop signal is a cooperative pause, not a cancel.

    Read by the workflow's terminal-event paths so a paused run persists and
    emits ``paused`` rather than a wrong terminal ``cancelled``. A plain dict
    read is safe here: the event loop never preempts synchronous code, and a
    stale False only degrades to the old cancel-then-override behavior.
    """
    handle = _active.get(run_id)
    return bool(handle and handle.paused)

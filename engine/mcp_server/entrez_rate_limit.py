"""Process-wide pacing for outbound NCBI Entrez requests.

NCBI allows a client 3 requests/second, or 10 with a registered API key, and
answers anything over that with HTTP 429.

Biopython enforces that cap itself, in ``Bio.Entrez._open`` -- but with an
unsynchronized read-modify-write of a module global. Every thread reads the
same "previous request" timestamp, computes the same wait, sleeps it, and then
issues its request in the same instant as all the others: precisely the burst
the limit exists to prevent. Its 429 handling then makes the outcome worse,
retrying twice with no delay at all before giving up.

That fan-out is the normal case here, not an edge: a literature review runs
several searches at once and each dispatches its per-paper efetch/elink calls
through ``asyncio.to_thread``. The result was 429s that the engine surfaced as
transient search failures ("retrying in 1.2s (attempt 3 of 4)") and, when the
retries ran out, as a whole evidence source dropped from the run.

So requests are paced here instead, before they are issued: a caller takes a
numbered slot under a lock, waits for it outside the lock (so the pacing never
serializes the responses themselves), and only then calls Entrez. This is the
one place that knows about the rate limit -- the per-call ``sleep`` that used
to sit in the response readers paced nothing, since by the time a handle is
open its request has already gone out.
"""

import threading
import time
from collections.abc import Callable
from typing import Any

from Bio import Entrez

from mcp_server.entrez import initialize_entrez

# Minimum seconds between two requests leaving this process, just inside
# NCBI's documented ceilings (10/s with a key, 3/s without) so ordinary clock
# jitter cannot push a pair over the line.
_INTERVAL_WITH_API_KEY = 0.11
_INTERVAL_WITHOUT_API_KEY = 0.4

_lock = threading.Lock()
# Monotonic time at which the next request may be issued.
_next_slot = 0.0

# Clock and sleep hooks, indirected only so tests can drive the pacer with a
# fake clock instead of real elapsed time. Production never overrides these.
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


def _request_interval() -> float:
    """Seconds to leave between requests, given the credentials in force."""
    initialize_entrez()
    return (
        _INTERVAL_WITH_API_KEY if Entrez.api_key else _INTERVAL_WITHOUT_API_KEY
    )


def _await_slot() -> None:
    """Block until this caller's turn to issue a request comes round."""
    interval = _request_interval()
    with _lock:
        now = _clock()
        start = max(now, _next_slot)
        _claim_slot(start + interval)
    delay = start - now
    if delay > 0:
        _sleep(delay)


def _claim_slot(next_slot: float) -> None:
    """Record when the following request may go out. Call under ``_lock``."""
    global _next_slot
    _next_slot = next_slot


def entrez_call(request: Callable[..., Any], /, **kwargs: Any) -> Any:
    """Issue one Entrez request, paced against NCBI's rate limit.

    Every ``Entrez.esearch``/``efetch``/``elink`` call in this server must go
    through here; calling Entrez directly reintroduces the burst.

    Args:
        request: The Entrez entry point to call (e.g. ``Entrez.esearch``).
        **kwargs: Arguments forwarded to it verbatim.

    Returns:
        The open response handle the Entrez call returned.
    """
    _await_slot()
    return request(**kwargs)

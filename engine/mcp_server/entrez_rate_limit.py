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

import contextvars
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from Bio import Entrez

from mcp_server.campaign import campaign_free_mode
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

_PILOT_ENTREZ_CALLS = ("esearch", "efetch", "elink")
PILOT_ENTREZ_MAX_TRIES = 1
PILOT_ENTREZ_SLEEP_BETWEEN_TRIES = 0
_pilot_trace_context: contextvars.ContextVar[
    tuple[dict[str, Any], str | None] | None
] = contextvars.ContextVar("pubmed_pilot_trace", default=None)
_pilot_trace_lock = threading.Lock()


@contextmanager
def pilot_trace_context(
    trace: dict[str, Any] | None, paper_id: str | None = None
) -> Any:
    """Scopes optional trace accounting across async work and worker threads.

    ``asyncio.to_thread`` copies the current context, so individual blocking
    Entrez calls keep the correct run and paper identity without process-wide
    mutable request state.
    """
    parent = _pilot_trace_context.get()
    resolved_trace = (
        trace if trace is not None else parent[0] if parent else None
    )
    resolved_paper_id = (
        paper_id if paper_id is not None else parent[1] if parent else None
    )
    if resolved_trace is None:
        yield
        return
    token = _pilot_trace_context.set((resolved_trace, resolved_paper_id))
    try:
        yield
    finally:
        _pilot_trace_context.reset(token)


def record_pilot_fetch_error(
    stage: str, exc: Exception, paper_id: str | None = None
) -> None:
    """Records bounded, redacted fetch failure details for the active pilot."""
    context = _pilot_trace_context.get()
    if context is None:
        return
    trace, current_paper_id = context
    resolved_paper_id = paper_id if paper_id is not None else current_paper_id
    with _pilot_trace_lock:
        trace["incomplete_fetch_count"] = (
            trace.get("incomplete_fetch_count", 0) + 1
        )
        errors = trace.setdefault("fetch_errors", [])
        if len(errors) < 9:
            errors.append(
                {
                    "stage": stage,
                    "pmid": resolved_paper_id,
                    "type": type(exc).__name__,
                }
            )


def record_pilot_metadata_origin(paper_id: str, origin: str) -> None:
    """Records origin only for IDs exposed in the bounded selected-ID sample."""
    context = _pilot_trace_context.get()
    if context is None:
        return
    trace, _current_paper_id = context
    selected = trace.get("selected")
    selected_ids = selected.get("ids", []) if isinstance(selected, dict) else []
    if paper_id not in selected_ids[:9]:
        return
    with _pilot_trace_lock:
        trace.setdefault("metadata_origins", {})[paper_id] = origin


def _record_pilot_entrez_call(request: Callable[..., Any]) -> None:
    context = _pilot_trace_context.get()
    if context is None:
        return
    operation = next(
        (
            name
            for name in _PILOT_ENTREZ_CALLS
            if request is getattr(Entrez, name)
        ),
        None,
    )
    if operation is None:
        return
    trace, _paper_id = context
    with _pilot_trace_lock:
        counts = trace.setdefault(
            "entrez_calls", dict.fromkeys(_PILOT_ENTREZ_CALLS, 0)
        )
        counts[operation] += 1


def _assert_pilot_retry_policy() -> None:
    if _pilot_trace_context.get() is None:
        return
    if (
        Entrez.max_tries != PILOT_ENTREZ_MAX_TRIES
        or Entrez.sleep_between_tries != PILOT_ENTREZ_SLEEP_BETWEEN_TRIES
    ):
        raise RuntimeError("Biopython PubMed pilot retry policy changed")


def _request_interval() -> float:
    """Seconds to leave between requests, given the credentials in force."""
    initialize_entrez()
    return (
        _INTERVAL_WITH_API_KEY
        if Entrez.api_key and not campaign_free_mode()
        else _INTERVAL_WITHOUT_API_KEY
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
    # Biopython's key is process-global. Passing None suppresses it for this
    # request even when a standard user's key was loaded earlier in the process.
    if campaign_free_mode():
        kwargs["api_key"] = None
    _await_slot()
    _assert_pilot_retry_policy()
    # These count calls entering the maintained request seam. They are not
    # wire-attempt counts; Biopython retries are separately disabled and
    # attested only in the explicit pilot serving mode.
    _record_pilot_entrez_call(request)
    return request(**kwargs)

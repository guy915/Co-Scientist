"""Tests for the process-wide Entrez request pacer.

NCBI answers a burst over its rate limit with HTTP 429, and this server's
per-paper metadata fetches fan out across threads, so pacing that is merely
"a sleep somewhere on the call path" is not enough: it has to hold across
concurrent callers. These pin that, and pin that the wait happens outside the
lock so responses are never serialized behind one another.
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Any

import pytest
from mcp_server import entrez_rate_limit

# Short enough to keep the tests fast, long enough that thread scheduling
# noise cannot fake a passing spacing measurement.
_TEST_INTERVAL = 0.05


@pytest.fixture(autouse=True)
def paced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pace at a test-sized interval, with the next slot already due."""
    monkeypatch.setattr(
        entrez_rate_limit, "_request_interval", lambda: _TEST_INTERVAL
    )
    monkeypatch.setattr(entrez_rate_limit, "_next_slot", 0.0)
    # Take the overdue slot here rather than in a test: a caller whose slot is
    # already in the past issues immediately, so the moment it records is the
    # moment the interpreter gets round to it, and that lag would show up as a
    # short first gap. Every slot a test then measures is one it waited for.
    entrez_rate_limit.entrez_call(lambda **_kwargs: None)


def test_sequential_requests_are_spaced() -> None:
    """Back-to-back calls leave at least the interval between them."""
    issued: list[float] = []

    def request(**_kwargs: Any) -> str:
        issued.append(time.monotonic())
        return "handle"

    for _ in range(3):
        assert entrez_rate_limit.entrez_call(request) == "handle"

    gaps = [b - a for a, b in itertools.pairwise(issued)]
    assert all(gap >= _TEST_INTERVAL * 0.9 for gap in gaps), gaps


def test_concurrent_callers_do_not_burst() -> None:
    """Threads take separate slots instead of all firing at once.

    Biopython's own limiter reads and writes its "previous request" timestamp
    without a lock, so every thread computes the same wait and then issues
    together -- the burst the limit exists to prevent, and the source of the
    429s that cost runs whole evidence sources.
    """
    issued: list[float] = []
    guard = threading.Lock()

    def request(**_kwargs: Any) -> None:
        with guard:
            issued.append(time.monotonic())

    threads = [
        threading.Thread(target=lambda: entrez_rate_limit.entrez_call(request))
        for _ in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Measured as the span the six requests occupy rather than pair by pair:
    # a thread can be descheduled between waiting for its slot and recording
    # that it took it, which only ever pushes one timestamp later and so can
    # squeeze the pair after it. The span cannot be faked -- six requests
    # bursting together would occupy no time at all.
    assert len(issued) == 6
    span = max(issued) - min(issued)
    assert span >= 5 * _TEST_INTERVAL * 0.9, span


def test_the_wait_does_not_hold_the_lock() -> None:
    """A slow request cannot block the next caller from taking its slot.

    The pacer bounds when requests *leave*; holding the lock across the call
    would also serialize their responses, turning a fan-out of independent
    fetches into one queue at the speed of the slowest.
    """
    started = threading.Event()
    release = threading.Event()

    def slow(**_kwargs: Any) -> None:
        started.set()
        release.wait(timeout=5)

    slow_thread = threading.Thread(
        target=lambda: entrez_rate_limit.entrez_call(slow)
    )
    slow_thread.start()
    assert started.wait(timeout=5)

    quick_done = threading.Event()

    def quick() -> None:
        entrez_rate_limit.entrez_call(lambda **_kwargs: None)
        quick_done.set()

    threading.Thread(target=quick).start()

    assert quick_done.wait(timeout=5), "second caller waited on the first"
    release.set()
    slow_thread.join()


def test_arguments_reach_the_underlying_call() -> None:
    """entrez_call forwards its keyword arguments verbatim."""
    seen: dict[str, Any] = {}

    def request(**kwargs: Any) -> str:
        seen.update(kwargs)
        return "handle"

    entrez_rate_limit.entrez_call(request, db="pubmed", id="42")

    assert seen == {"db": "pubmed", "id": "42"}

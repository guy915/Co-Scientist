"""Tests for the streaming deadlines in ``app.llm_stream``.

The distinction under test is the whole point of the module: a stream that
is slow overall but never silent is healthy, and a total-duration deadline
cannot tell it apart from a provider that has stopped answering. On a
thinking model the slow-but-alive case is the normal one, so the tests pin
both directions -- long streams survive, silent ones do not.
"""

from __future__ import annotations

import asyncio

import pytest

from app.llm_stream import stream_chunks


class _FakeStream:
    """Async iterable yielding each chunk after a scripted delay."""

    def __init__(self, script: list[tuple[float, str]]) -> None:
        self._script = list(script)

    def __aiter__(self) -> _FakeStream:
        return self

    async def __anext__(self) -> str:
        if not self._script:
            raise StopAsyncIteration
        delay, chunk = self._script.pop(0)
        await asyncio.sleep(delay)
        return chunk


async def _drain(stream: _FakeStream, **kwargs: float) -> list[str]:
    return [chunk async for chunk in stream_chunks(stream, **kwargs)]


async def test_yields_every_chunk_in_order() -> None:
    """The happy path is a transparent pass-through."""
    stream = _FakeStream([(0.0, "a"), (0.0, "b"), (0.0, "c")])

    chunks = await _drain(stream, stall_seconds=1.0, total_seconds=10.0)

    assert chunks == ["a", "b", "c"]


async def test_a_long_but_talkative_stream_survives() -> None:
    """Many chunks, each well within the stall gap, are not cut off.

    This is the reasoning model's normal shape: the chain of thought arrives
    as a long run of small deltas. A total-duration deadline tight enough to
    catch a hung provider would kill exactly this.
    """
    stream = _FakeStream([(0.02, str(i)) for i in range(20)])

    chunks = await _drain(stream, stall_seconds=1.0, total_seconds=10.0)

    assert len(chunks) == 20


async def test_silence_longer_than_the_stall_gap_fails() -> None:
    """A provider that goes quiet mid-stream is the failure worth catching."""
    stream = _FakeStream([(0.0, "a"), (5.0, "b")])

    with pytest.raises(asyncio.TimeoutError):
        await _drain(stream, stall_seconds=0.05, total_seconds=30.0)


async def test_the_total_ceiling_still_backstops_a_dribbling_stream() -> None:
    """Chunks that never stall but never end are bounded by the total."""
    stream = _FakeStream([(0.02, str(i)) for i in range(1_000)])

    with pytest.raises(asyncio.TimeoutError):
        await _drain(stream, stall_seconds=1.0, total_seconds=0.1)


async def test_an_empty_stream_ends_cleanly() -> None:
    """Exhaustion is not a timeout, however tight the deadlines are."""
    assert (
        await _drain(_FakeStream([]), stall_seconds=0.01, total_seconds=0.01)
        == []
    )

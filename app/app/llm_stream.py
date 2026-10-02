"""Deadlines for streaming completions from a model that reasons first.

A total-duration deadline is the wrong instrument for a stream. It cannot
tell a provider that has stopped responding from one that is thinking hard
and delivering tokens the whole time, so any value low enough to catch the
first also kills the second -- and on a thinking model the second is the
normal case. What actually distinguishes a dead stream is silence, so these
helpers bound the gap between chunks and keep the total only as a backstop
against a stream that dribbles forever.

The gap is measured over every chunk the provider sends, including the
chain-of-thought deltas a caller discards, so stall detection still works
on a call that forwards nothing to its reader while the model is thinking.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

__all__ = ["stream_chunks"]


async def stream_chunks(
    response: Any,
    *,
    stall_seconds: float,
    total_seconds: float,
) -> AsyncIterator[Any]:
    """Yield chunks from a streaming completion under two deadlines.

    Args:
        response: The streaming completion returned by litellm.
        stall_seconds: Longest silence tolerated between two chunks. This is
            the real health check: a thinking model streams its chain of
            thought continuously, so a gap this long means the provider has
            stopped, not that it is reasoning.
        total_seconds: Backstop on the whole stream, for the pathological
            case of a provider that keeps emitting without ever finishing.

    Yields:
        Each chunk, in order.

    Raises:
        asyncio.TimeoutError: If either deadline passes.
    """
    try:
        async for chunk in _timed_chunks(
            response, stall_seconds, total_seconds
        ):
            yield chunk
    finally:
        close = getattr(response, "aclose", None)
        if close is not None:
            await close()


async def _timed_chunks(
    response: Any, stall_seconds: float, total_seconds: float
) -> AsyncIterator[Any]:
    """Apply both clocks while the outer iterator guarantees cleanup."""
    deadline = asyncio.get_running_loop().time() + total_seconds
    iterator = response.__aiter__()
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError(
                f"stream exceeded {total_seconds}s in total"
            )
        try:
            chunk = await asyncio.wait_for(
                iterator.__anext__(), timeout=min(stall_seconds, remaining)
            )
        except StopAsyncIteration:
            return
        yield chunk

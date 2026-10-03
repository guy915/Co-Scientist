"""Separate call budgets and usage summaries for app operations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Coroutine,
    Iterator,
)
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from co_scientist.llm import scoped_completion_budget, scoped_telemetry

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

_active: ContextVar[bool] = ContextVar("app_call_scope_active", default=False)
# asyncio holds weak task references. Keep producers alive until their stream
# finalizers can cancel/join them, even when a consumer is collected in a cycle.
_stream_producers: set[asyncio.Task[None]] = set()


def in_app_call_scope() -> bool:
    """Whether the current task already belongs to an app operation."""
    return _active.get()


@contextmanager
def app_call_scope(surface: str) -> Iterator[None]:
    """Count retries/tool rounds together, apart from scientific run spend."""
    from app.config import settings

    token = _active.set(True)
    with (
        scoped_completion_budget(settings.app_llm_max_calls) as budget,
        scoped_telemetry(f"app.{surface}") as telemetry,
    ):
        try:
            yield
        finally:
            _active.reset(token)
            if budget.count:
                logger.info(
                    "App completion usage surface=%s calls=%s usage=%s",
                    surface,
                    budget.count,
                    telemetry.snapshot(),
                )


def budgeted(
    surface: str,
) -> Callable[
    [Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]
]:
    """Scope an asynchronous app operation and all its child tasks."""

    def decorate(
        function: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(function)
        async def invoke(*args: P.args, **kwargs: P.kwargs) -> T:
            if in_app_call_scope():
                return await function(*args, **kwargs)
            with app_call_scope(surface):
                return await function(*args, **kwargs)

        return invoke

    return decorate


async def _produce(
    iterator: AsyncIterator[Any],
    queue: asyncio.Queue[tuple[str, Any]],
    surface: str,
) -> None:
    """Own the generator and its context on one task across every yield."""
    with app_call_scope(surface):
        try:
            async for value in iterator:
                acknowledged = asyncio.get_running_loop().create_future()
                await queue.put(("item", (value, acknowledged)))
                await acknowledged
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            await queue.put(("error", error))
        else:
            await queue.put(("done", None))
        finally:
            await _close_iterator(iterator)


async def _close_iterator(iterator: AsyncIterator[Any]) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        await close()


async def _scoped_stream(
    iterator: AsyncIterator[T], surface: str
) -> AsyncGenerator[T, None]:
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=1)
    producer = asyncio.create_task(_produce(iterator, queue, surface))
    _stream_producers.add(producer)
    producer.add_done_callback(_stream_producers.discard)
    try:
        while True:
            kind, value = await queue.get()
            if kind == "done":
                return
            if kind == "error":
                raise value
            item, acknowledged = value
            yield item
            acknowledged.set_result(None)
    finally:
        producer.cancel()
        with suppress(asyncio.CancelledError):
            await producer


def budgeted_stream(
    surface: str,
) -> Callable[
    [Callable[P, AsyncIterator[T]]], Callable[P, AsyncGenerator[T, None]]
]:
    """Keep stream context on its producer, apart from its consumer."""

    def decorate(
        function: Callable[P, AsyncIterator[T]],
    ) -> Callable[P, AsyncGenerator[T, None]]:
        @wraps(function)
        def invoke(
            *args: P.args, **kwargs: P.kwargs
        ) -> AsyncGenerator[T, None]:
            return _scoped_stream(function(*args, **kwargs), surface)

        return invoke

    return decorate


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


__all__ = ["stream_chunks"]

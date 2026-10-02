"""Budgeted streams preserve context, backpressure and cancellation."""

import asyncio
import gc
import sys
import weakref
from collections.abc import AsyncIterator
from typing import Any

import pytest
from co_scientist.llm import current_api_key, scoped_api_key

from app.llm_scope import budgeted_stream, in_app_call_scope


async def test_stream_context_does_not_leak_or_prefetch_across_yields() -> None:
    steps: list[int] = []

    @budgeted_stream("context_test")
    async def stream() -> AsyncIterator[int]:
        with scoped_api_key("test-scope"):
            for number in range(2):
                assert in_app_call_scope()
                assert current_api_key() == "test-scope"
                steps.append(number)
                yield number

    response = stream()
    assert await anext(response) == 0
    await asyncio.sleep(0)
    assert steps == [0]
    assert not in_app_call_scope()
    assert current_api_key() is None
    assert await anext(response) == 1
    assert [item async for item in response] == []
    assert not in_app_call_scope()


async def test_closing_consumer_cancels_and_closes_the_producer() -> None:
    closed = asyncio.Event()

    @budgeted_stream("close_test")
    async def stream() -> AsyncIterator[str]:
        try:
            yield "first"
            await asyncio.sleep(3600)
        finally:
            closed.set()

    response = stream()
    assert await anext(response) == "first"
    close = response.aclose
    await close()
    assert closed.is_set()


async def test_abandoned_cyclic_stream_closes_without_destroying_its_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop_errors: list[dict[str, Any]] = []
    unraisable_errors: list[BaseException] = []
    closed = asyncio.Event()
    existing_tasks = asyncio.all_tasks()

    def capture_unraisable(args: Any) -> None:
        unraisable_errors.append(args.exc_value)

    monkeypatch.setattr(sys, "unraisablehook", capture_unraisable)
    loop.set_exception_handler(lambda _, context: loop_errors.append(context))

    @budgeted_stream("abandoned_stream")
    async def stream() -> AsyncIterator[str]:
        try:
            yield "first"
            await asyncio.Event().wait()
        finally:
            closed.set()

    try:
        response = stream()
        assert await anext(response) == "first"
        producers = [
            weakref.ref(task) for task in asyncio.all_tasks() - existing_tasks
        ]
        assert len(producers) == 1
        abandoned: list[Any] = [response]
        abandoned.append(abandoned)
        del response, abandoned
        gc.collect()
        for _ in range(10):
            await asyncio.sleep(0)
            gc.collect()
        assert closed.is_set()
        assert not loop_errors
        assert not unraisable_errors
        assert not (asyncio.all_tasks() - existing_tasks)
        assert producers[0]() is None
        assert not in_app_call_scope()
        assert current_api_key() is None
    finally:
        loop.set_exception_handler(previous_handler)

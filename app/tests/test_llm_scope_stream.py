"""Budgeted streams preserve context, backpressure and cancellation."""

import asyncio
from collections.abc import AsyncIterator

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

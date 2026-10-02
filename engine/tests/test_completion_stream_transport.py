"""Physical stream usage and cancellation stay attributable and bounded."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.llm import complete_request, scoped_telemetry
from tests._llm_fake import install_fake_backend


async def test_usage_is_recorded_once_after_the_stream_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final = SimpleNamespace(
        model="gpt-4o-mini",
        choices=[],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
    )

    async def chunks() -> AsyncIterator[Any]:
        yield SimpleNamespace(choices=[], usage=None)
        yield final

    async def provider(**kwargs: Any) -> Any:
        return chunks()

    install_fake_backend(monkeypatch, provider)
    with scoped_telemetry("app_stream") as telemetry:
        response = await complete_request(
            {"model": "gpt-4o-mini", "stream": True},
            "gpt-4o-mini",
            byok=False,
            timeout_seconds=1,
        )
        assert telemetry.snapshot() == {}
    assert len([chunk async for chunk in response]) == 2
    await response.aclose()
    usage = telemetry.snapshot()["app_stream::gpt-4o-mini"]
    assert usage["calls"] == 1
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 3
    assert usage["reported_usage_calls"] == 1
    assert usage["errors"] == {}


async def test_partial_stream_close_records_unknown_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = asyncio.Event()

    async def chunks() -> AsyncIterator[Any]:
        try:
            yield "reasoning"
            await asyncio.sleep(3600)
        finally:
            closed.set()

    async def provider(**kwargs: Any) -> Any:
        return chunks()

    install_fake_backend(monkeypatch, provider)
    with scoped_telemetry("cancelled") as telemetry:
        response = await complete_request(
            {"model": "gpt-4o-mini", "stream": True},
            "gpt-4o-mini",
            byok=False,
            timeout_seconds=1,
        )
        assert await anext(response) == "reasoning"
        await response.aclose()
    assert closed.is_set()
    usage = telemetry.snapshot()["cancelled::gpt-4o-mini"]
    assert usage["calls"] == 1
    assert usage["reported_usage_calls"] == 0
    assert usage["errors"] == {"CancelledError": 1}

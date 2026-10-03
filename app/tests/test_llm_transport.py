from __future__ import annotations

import asyncio
import contextvars
import gc
import sys
import weakref
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist.exceptions import LLMCallBudgetExceededError, LLMTimeoutError
from co_scientist.llm import (
    campaign_free_mode,
    current_api_key,
    current_run_call_count,
    release_run_call_budget,
    scoped_api_key,
    scoped_campaign_mode,
    scoped_llm_call_budget,
)
from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER

from app import llm_request, offline_guard
from app.async_bridge import (
    propagate_context,
    run_coroutine_sync,
    run_in_scoped_loop,
)
from app.config import settings
from app.llm_scope import (
    app_call_scope,
    budgeted,
    budgeted_stream,
    in_app_call_scope,
    stream_chunks,
)
from tests._llm_fake_backend import install_completion_backend

_probe: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "test_async_bridge_probe", default=None
)


def test_propagate_context_carries_value_into_a_new_thread() -> None:
    token = _probe.set("scoped-value")
    try:

        def _read() -> str | None:
            return _probe.get()

        wrapped = propagate_context(_read)
    finally:
        _probe.reset(token)

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(wrapped).result() == "scoped-value"


def test_run_coroutine_sync_carries_value_onto_the_bridge_loop() -> None:
    token = _probe.set("bridge-value")
    try:

        async def _read() -> str | None:
            return _probe.get()

        result = run_coroutine_sync(_read)
    finally:
        _probe.reset(token)

    assert result == "bridge-value"


def test_run_coroutine_sync_runs_many_calls_concurrently() -> None:
    import time

    async def _slow() -> float:
        start = time.monotonic()
        import asyncio

        await asyncio.sleep(0.05)
        return start

    with ThreadPoolExecutor(max_workers=5) as pool:
        starts = list(pool.map(lambda _: run_coroutine_sync(_slow), range(5)))

    spread = max(starts) - min(starts)
    assert spread < 0.05, f"calls did not overlap (start spread {spread})"


def test_propagate_context_restores_a_reused_worker_thread() -> None:
    with ThreadPoolExecutor(max_workers=1) as pool:
        with scoped_campaign_mode(True):
            assert (
                pool.submit(propagate_context(campaign_free_mode)).result()
                is True
            )
        assert pool.submit(campaign_free_mode).result() is False


def test_run_coroutine_sync_restores_the_shared_bridge_loop() -> None:

    async def read_campaign_mode() -> bool:
        return bool(campaign_free_mode())

    with scoped_campaign_mode(True):
        assert run_coroutine_sync(read_campaign_mode) is True
    assert run_coroutine_sync(read_campaign_mode) is False


# Tear down logging workers on their owning event loop.


async def _noop() -> None:
    return None


def test_scoped_loop_stops_a_worker_it_started() -> None:
    run_in_scoped_loop(_start_worker_on_running_loop())

    assert GLOBAL_LOGGING_WORKER._worker_task is None


def test_scoped_loop_leaves_a_worker_bound_elsewhere_alone() -> None:
    other_loop = asyncio.new_event_loop()
    try:
        other_loop.run_until_complete(
            _start_worker_on_running_loop(),
        )
        foreign_task = GLOBAL_LOGGING_WORKER._worker_task
        assert foreign_task is not None

        run_in_scoped_loop(_noop())

        assert GLOBAL_LOGGING_WORKER._worker_task is foreign_task
        assert not foreign_task.cancelled()
    finally:
        other_loop.run_until_complete(GLOBAL_LOGGING_WORKER.stop())
        other_loop.close()


async def _start_worker_on_running_loop() -> None:
    GLOBAL_LOGGING_WORKER.start()
    await asyncio.sleep(0)
    assert GLOBAL_LOGGING_WORKER._worker_task is not None


async def test_app_call_uses_the_installed_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = SimpleNamespace(choices=[], model="offline-test")

    async def provider(**kwargs: Any) -> Any:
        return answer

    async def forbidden(**kwargs: Any) -> Any:
        raise AssertionError("bypassed the installed completion backend")

    monkeypatch.setattr(offline_guard, "require_remote_chat", lambda _: None)
    monkeypatch.setattr("litellm.acompletion", forbidden)
    fake = install_completion_backend(monkeypatch, provider)

    response = await llm_request.acompletion(model="gpt-4o-mini", timeout=1)

    assert response is answer
    assert len(fake.requests) == 1


async def test_app_budget_refuses_before_dispatch_and_restores_research_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def provider(**kwargs: Any) -> Any:
        return SimpleNamespace(choices=[], model="gpt-4o-mini")

    monkeypatch.setattr(offline_guard, "require_remote_chat", lambda _: None)
    monkeypatch.setattr(settings, "app_llm_max_calls", 1)
    fake = install_completion_backend(monkeypatch, provider)
    release_run_call_budget("separate-app-budget")

    with scoped_llm_call_budget("separate-app-budget", 1):
        with app_call_scope("test"):
            await llm_request.acompletion(model="gpt-4o-mini", timeout=1)
            with pytest.raises(LLMCallBudgetExceededError):
                await llm_request.acompletion(model="gpt-4o-mini", timeout=1)
        assert current_run_call_count("separate-app-budget") == 0
        from co_scientist.llm import complete_request

        await complete_request(
            {"model": "gpt-4o-mini"},
            "gpt-4o-mini",
            byok=False,
            timeout_seconds=1,
        )
        assert current_run_call_count("separate-app-budget") == 1
    assert len(fake.requests) == 2
    release_run_call_budget("separate-app-budget")


async def test_concurrent_app_calls_share_one_operation_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def provider(**kwargs: Any) -> Any:
        await asyncio.sleep(0)
        return SimpleNamespace(choices=[], model="gpt-4o-mini")

    monkeypatch.setattr(offline_guard, "require_remote_chat", lambda _: None)
    monkeypatch.setattr(settings, "app_llm_max_calls", 2)
    fake = install_completion_backend(monkeypatch, provider)
    with app_call_scope("concurrency_test"):
        results = await asyncio.gather(
            *(llm_request.acompletion(model="gpt-4o-mini") for _ in range(4)),
            return_exceptions=True,
        )
    assert len(fake.requests) == 2
    assert sum(isinstance(r, LLMCallBudgetExceededError) for r in results) == 2


async def test_hung_app_request_is_cancelled_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled = asyncio.Event()

    async def provider(**kwargs: Any) -> Any:
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.set()

    monkeypatch.setattr(offline_guard, "require_remote_chat", lambda _: None)
    fake = install_completion_backend(monkeypatch, provider)
    with pytest.raises(LLMTimeoutError):
        await llm_request.acompletion(model="gpt-4o-mini", timeout=0.01)
    assert cancelled.is_set()
    assert len(fake.requests) == 1


async def test_nested_app_helpers_share_the_operation_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def provider(**kwargs: Any) -> Any:
        return SimpleNamespace(choices=[], model="gpt-4o-mini")

    monkeypatch.setattr(offline_guard, "require_remote_chat", lambda _: None)
    monkeypatch.setattr(settings, "app_llm_max_calls", 1)
    fake = install_completion_backend(monkeypatch, provider)

    @budgeted("nested_helper")
    async def child() -> None:
        await llm_request.acompletion(model="gpt-4o-mini", timeout=1)

    @budgeted("outer_operation")
    async def operation() -> None:
        await child()
        await child()

    with pytest.raises(LLMCallBudgetExceededError):
        await operation()
    assert len(fake.requests) == 1


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


# Silence timeout and total request duration are independent limits.


class _FakeStream:
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
    stream = _FakeStream([(0.0, "a"), (0.0, "b"), (0.0, "c")])

    chunks = await _drain(stream, stall_seconds=1.0, total_seconds=10.0)

    assert chunks == ["a", "b", "c"]


async def test_a_long_but_talkative_stream_survives() -> None:
    # Healthy reasoning deltas reset silence timeouts before content arrives.
    stream = _FakeStream([(0.02, str(i)) for i in range(20)])

    chunks = await _drain(stream, stall_seconds=1.0, total_seconds=10.0)

    assert len(chunks) == 20


async def test_silence_longer_than_the_stall_gap_fails() -> None:
    stream = _FakeStream([(0.0, "a"), (5.0, "b")])

    with pytest.raises(asyncio.TimeoutError):
        await _drain(stream, stall_seconds=0.05, total_seconds=30.0)


async def test_the_total_ceiling_still_backstops_a_dribbling_stream() -> None:
    stream = _FakeStream([(0.02, str(i)) for i in range(1_000)])

    with pytest.raises(asyncio.TimeoutError):
        await _drain(stream, stall_seconds=1.0, total_seconds=0.1)


async def test_an_empty_stream_ends_cleanly() -> None:
    assert (
        await _drain(_FakeStream([]), stall_seconds=0.01, total_seconds=0.01)
        == []
    )

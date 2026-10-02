"""App calls use the installed provider, with independent accounting."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist.exceptions import LLMCallBudgetExceededError, LLMTimeoutError
from co_scientist.llm import (
    current_run_call_count,
    release_run_call_budget,
    scoped_llm_call_budget,
)

from app import llm_request, offline_guard
from app.config import settings
from app.llm_scope import app_call_scope, budgeted
from tests._llm_fake_backend import install_completion_backend


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

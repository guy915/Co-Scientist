"""Tests for task-local campaign free-model admission."""

import asyncio
import contextvars

import pytest

from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm
from co_scientist.llm_free_policy import (
    campaign_free_mode,
    scoped_campaign_mode,
)
from tests._llm_wrapper_fakes import (
    make_completion,
    make_message,
    patch_acompletion,
)

PAID_MODEL = "openrouter/campaign/paid"
OPTIONS = LLMCallOptions(use_cache=False)


def test_campaign_scope_enables_free_mode_without_global_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)

    assert not campaign_free_mode()
    with scoped_campaign_mode(True):
        assert campaign_free_mode()
    assert not campaign_free_mode()


def test_nested_false_cannot_relax_campaign_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)

    with scoped_campaign_mode(True):
        with scoped_campaign_mode(False):
            assert campaign_free_mode()
        assert campaign_free_mode()
    assert not campaign_free_mode()


def test_global_flag_remains_authoritative_inside_false_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")

    with scoped_campaign_mode(False):
        assert campaign_free_mode()


def test_invalid_global_flag_fails_closed_even_inside_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "sometimes")

    with pytest.raises(FreeModelEligibilityError, match="setting is invalid"):
        campaign_free_mode()
    with scoped_campaign_mode(True), pytest.raises(
        FreeModelEligibilityError, match="setting is invalid"
    ):
        campaign_free_mode()


def test_campaign_scope_resets_after_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)

    with pytest.raises(RuntimeError, match="boom"), scoped_campaign_mode(True):
        assert campaign_free_mode()
        raise RuntimeError("boom")
    assert not campaign_free_mode()


async def test_campaign_scope_isolated_between_concurrent_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    ready = asyncio.Event()

    async def observe(enabled: bool) -> bool:
        with scoped_campaign_mode(enabled):
            ready.set()
            await asyncio.sleep(0)
            return campaign_free_mode()

    campaign_task = asyncio.create_task(observe(True))
    await ready.wait()
    ordinary_task = asyncio.create_task(observe(False))
    campaign_result, ordinary_result = await asyncio.gather(
        campaign_task, ordinary_task
    )
    assert campaign_result is True
    assert ordinary_result is False
    assert not campaign_free_mode()


async def test_campaign_scope_survives_copied_context_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)

    with scoped_campaign_mode(True):
        copied = contextvars.copy_context()
        assert await asyncio.to_thread(copied.run, campaign_free_mode)
    assert not campaign_free_mode()


async def test_campaign_scope_rejects_paid_byok_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Campaign and ordinary BYOK tasks keep their admission policies apart."""
    from co_scientist import llm_free_policy

    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    monkeypatch.setattr(
        llm_free_policy,
        "current_catalog",
        lambda: {
            "campaign/paid": {
                "pricing": {
                    "prompt": "0.01",
                    "completion": "0.02",
                    "request": "0.03",
                    "internal_reasoning": "0.04",
                    "input_cache_read": "0.05",
                    "input_cache_write": "0.06",
                },
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
            }
        },
    )
    requests: list[dict[str, object]] = []
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message("ordinary"))],
        requests,
    )
    spec = CompletionSpec(PAID_MODEL, api_key="byok-test-key")

    async def campaign_call() -> None:
        with scoped_campaign_mode(True), pytest.raises(
            FreeModelEligibilityError,
            match="zero-cost route has paid or invalid pricing",
        ):
            await call_llm("probe", spec, options=OPTIONS)

    async def ordinary_call() -> str:
        with scoped_campaign_mode(False):
            return await call_llm("probe", spec, options=OPTIONS)

    campaign_result, ordinary_result = await asyncio.gather(
        campaign_call(), ordinary_call()
    )
    assert campaign_result is None
    assert ordinary_result == "ordinary"
    assert len(requests) == 1
    assert requests[0]["model"] == PAID_MODEL
    assert requests[0]["api_key"] == "byok-test-key"

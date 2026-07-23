"""Tests for the per-call LLM wall-clock ceiling.

A provider that accepts a request and then never answers used to park the
caller forever, which in a durable run held the task and stalled the single
worker behind it. These cover the ceiling itself, its configuration, and the
deliberate decision not to retry a timeout.
"""

import asyncio
from typing import Any

import litellm
import pytest

from co_scientist import llm, llm_json_retry, llm_request
from co_scientist.exceptions import LLMTimeoutError
from co_scientist.llm import CompletionSpec, LLMCallOptions, ToolLoop


def test_timeout_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset env var yields the generous built-in default."""
    monkeypatch.delenv(llm_request.LLM_TIMEOUT_ENV, raising=False)
    assert (
        llm_request.llm_timeout_seconds()
        == llm_request.DEFAULT_LLM_TIMEOUT_SECONDS
    )


def test_timeout_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator-set ceiling is honoured."""
    monkeypatch.setenv(llm_request.LLM_TIMEOUT_ENV, "12.5")
    assert llm_request.llm_timeout_seconds() == 12.5


@pytest.mark.parametrize("value", ["0", "-1"])
def test_timeout_disabled_by_non_positive(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Zero or negative disables the ceiling entirely."""
    monkeypatch.setenv(llm_request.LLM_TIMEOUT_ENV, value)
    assert llm_request.llm_timeout_seconds() is None


def test_timeout_falls_back_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-numeric value falls back rather than crashing the call."""
    monkeypatch.setenv(llm_request.LLM_TIMEOUT_ENV, "soon")
    assert (
        llm_request.llm_timeout_seconds()
        == llm_request.DEFAULT_LLM_TIMEOUT_SECONDS
    )


def test_completion_args_carry_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider client is asked to give up on its own too."""
    monkeypatch.setenv(llm_request.LLM_TIMEOUT_ENV, "42")
    args = llm_request._build_completion_args(
        "prompt",
        "deepseek/deepseek-v4-flash",
        100,
        0.5,
        llm_request.CompletionShape(),
    )
    assert args["timeout"] == 42.0


def test_completion_args_omit_timeout_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled ceiling passes no timeout argument at all."""
    monkeypatch.setenv(llm_request.LLM_TIMEOUT_ENV, "0")
    args = llm_request._build_completion_args(
        "prompt",
        "deepseek/deepseek-v4-flash",
        100,
        0.5,
        llm_request.CompletionShape(),
    )
    assert "timeout" not in args


async def test_hung_call_raises_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A call that never returns is cancelled and surfaces as a timeout.

    This is the regression: previously the await simply never completed.
    """
    monkeypatch.setenv(llm_request.LLM_TIMEOUT_ENV, "0.01")
    monkeypatch.setattr(llm_request, "_TIMEOUT_GRACE_SECONDS", 0.0)

    async def never_answers(**_kwargs: Any) -> Any:
        await asyncio.sleep(3600)

    monkeypatch.setattr(litellm, "acompletion", never_answers)

    with pytest.raises(LLMTimeoutError) as excinfo:
        await llm_request._acompletion_within_timeout(
            {}, "deepseek/deepseek-v4-pro"
        )
    assert "deepseek/deepseek-v4-pro" in str(excinfo.value)


async def test_hung_tool_loop_call_raises_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool loop's LLM turn sits under the same ceiling as call_llm.

    The agentic web-search path runs on call_llm_with_tools, whose
    completion call used to await litellm bare -- a wedged provider there
    parked a durable task exactly like the plain-call case.
    """
    monkeypatch.setenv(llm_request.LLM_TIMEOUT_ENV, "0.01")
    monkeypatch.setattr(llm_request, "_TIMEOUT_GRACE_SECONDS", 0.0)

    async def never_answers(**_kwargs: Any) -> Any:
        await asyncio.sleep(3600)

    monkeypatch.setattr(litellm, "acompletion", never_answers)

    async def unused_executor(_tool_call: Any) -> dict[str, Any]:
        raise AssertionError("no tool call should be executed")

    with pytest.raises(LLMTimeoutError):
        await llm.call_llm_with_tools(
            "prompt",
            CompletionSpec(model_name="deepseek/deepseek-v4-pro"),
            ToolLoop(tools=[], executor=unused_executor),
            options=LLMCallOptions(use_cache=False),
        )


async def test_timeout_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """The JSON retry loop re-raises a timeout instead of retrying it.

    Retrying would multiply one stalled call by the attempt count, which is
    the unbounded stall the ceiling exists to prevent. A generic failure is
    still retried (covered by the sibling test below), so this pins the
    difference rather than blanket no-retry behaviour.
    """
    calls = 0

    async def timing_out(**_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise LLMTimeoutError("provider stopped responding")

    monkeypatch.setattr(litellm, "acompletion", timing_out)

    with pytest.raises(LLMTimeoutError):
        await llm.call_llm_json(
            "prompt",
            CompletionSpec(model_name="deepseek/deepseek-v4-flash"),
            max_attempts=5,
            options=LLMCallOptions(use_cache=False),
        )
    assert calls == 1, "a timeout must not be retried"


async def test_generic_failure_is_still_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal provider error keeps its existing retry behaviour."""
    calls = 0

    async def failing(**_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise RuntimeError("transient provider error")

    monkeypatch.setattr(litellm, "acompletion", failing)

    with pytest.raises(RuntimeError):
        await llm.call_llm_json(
            "prompt",
            CompletionSpec(model_name="deepseek/deepseek-v4-flash"),
            max_attempts=3,
            options=LLMCallOptions(use_cache=False),
        )
    assert calls == 3, "generic failures must still exhaust retries"


def _recording_sleep(slept: list[float]) -> Any:
    """A fake ``asyncio.sleep`` that records each requested delay."""

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    return fake_sleep


class _ProviderRateLimitError(Exception):
    """Stands in for a provider SDK's throttling error.

    Named to match what litellm raises, since detection is structural: the
    engine must back off for any provider's throttling class, not just one
    it imported.
    """


async def test_rate_limited_retry_waits_before_trying_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A throttled call backs off instead of immediately firing again.

    DashScope rejects bursts with "Request rate increased too quickly ...
    scale requests more smoothly over time" -- a ramp limiter, not a QPS
    ceiling. The retry loop was built for schema failures, where an immediate
    retry with corrective feedback is right; routing throttling through the
    same path made the client answer "slow down" by retrying at once, feeding
    the burst that caused the throttle.
    """
    slept: list[float] = []
    monkeypatch.setattr(
        "co_scientist.llm_json_retry.asyncio.sleep", _recording_sleep(slept)
    )
    calls = 0

    async def throttled(**_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise _ProviderRateLimitError(
            "RateLimitError: DashscopeException - Request rate increased "
            "too quickly."
        )

    monkeypatch.setattr(litellm, "acompletion", throttled)

    with pytest.raises(_ProviderRateLimitError):
        await llm.call_llm_json(
            "prompt",
            CompletionSpec(model_name="deepseek/deepseek-v4-flash"),
            max_attempts=3,
            options=LLMCallOptions(use_cache=False),
        )
    assert calls == 3, "throttling stays retryable"
    assert len(slept) == 2, "every retry but the last waits first"
    assert slept[0] > 0
    assert slept[1] > slept[0], "the wait grows with each attempt"


async def test_rate_limit_backoff_is_jittered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent throttled callers must not retry in lockstep.

    Without jitter, N callers throttled by the same burst all wait the same
    interval and resume together, reproducing the burst exactly. The spread
    is what actually smooths the ramp.
    """
    waits = {llm_json_retry._rate_limit_backoff_seconds(1) for _ in range(40)}
    assert len(waits) > 1, "identical waits would re-synchronize the burst"


async def test_schema_failure_still_retries_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backoff is scoped to throttling; a bad payload retries immediately."""
    slept: list[float] = []
    monkeypatch.setattr(
        "co_scientist.llm_json_retry.asyncio.sleep", _recording_sleep(slept)
    )
    calls = 0

    async def failing(**_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise ValueError("provider rejected the request")

    monkeypatch.setattr(litellm, "acompletion", failing)

    with pytest.raises(ValueError):
        await llm.call_llm_json(
            "prompt",
            CompletionSpec(model_name="deepseek/deepseek-v4-flash"),
            max_attempts=3,
            options=LLMCallOptions(use_cache=False),
        )
    assert calls == 3
    assert slept == [], "only throttling should slow the retry loop"

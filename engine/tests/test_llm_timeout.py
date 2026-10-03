"""Offline contracts for llm timeout."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    BadRequestError,
    ContextWindowExceededError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
)
from litellm.exceptions import Timeout as LiteLLMTimeout

from co_scientist import backoff as _backoff_backoff
from co_scientist import llm
from co_scientist.evidence import search_query
from co_scientist.exceptions import (
    LLMRateLimitParkError,
    LLMThinkingOnlyError,
    LLMTimeoutError,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    scoped_telemetry,
)
from co_scientist.llm.attempts import retry
from co_scientist.llm.attempts import retry as _llm_rate_limit_park_backoff
from co_scientist.llm.attempts import retry as _llm_timeout_backoff
from co_scientist.llm.attempts import retry as llm_backoff
from co_scientist.llm.attempts.retry import (
    Attempt,
    AttemptPlan,
    platform_rate_limit_park,
)
from co_scientist.llm.request import completion, transport
from tests._llm_fake import install_fake_backend


def test_timeout_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset env var yields the generous built-in default."""
    monkeypatch.delenv(completion.LLM_TIMEOUT_ENV, raising=False)
    assert (
        completion.llm_timeout_seconds()
        == completion.DEFAULT_LLM_TIMEOUT_SECONDS
    )


def test_timeout_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator-set ceiling is honoured."""
    monkeypatch.setenv(completion.LLM_TIMEOUT_ENV, "12.5")
    assert completion.llm_timeout_seconds() == 12.5


@pytest.mark.parametrize("value", ["0", "-1"])
def test_timeout_disabled_by_non_positive(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Zero or negative disables the ceiling entirely."""
    monkeypatch.setenv(completion.LLM_TIMEOUT_ENV, value)
    assert completion.llm_timeout_seconds() is None


def test_timeout_falls_back_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-numeric value falls back rather than crashing the call."""
    monkeypatch.setenv(completion.LLM_TIMEOUT_ENV, "soon")
    assert (
        completion.llm_timeout_seconds()
        == completion.DEFAULT_LLM_TIMEOUT_SECONDS
    )


def test_completion_args_carry_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider client is asked to give up on its own too."""
    monkeypatch.setenv(completion.LLM_TIMEOUT_ENV, "42")
    args = completion._build_completion_args(
        "prompt",
        "deepseek/deepseek-v4-flash",
        100,
        0.5,
        completion.CompletionShape(),
    )
    assert args["timeout"] == 42.0


def test_completion_args_omit_timeout_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled ceiling passes no timeout argument at all."""
    monkeypatch.setenv(completion.LLM_TIMEOUT_ENV, "0")
    args = completion._build_completion_args(
        "prompt",
        "deepseek/deepseek-v4-flash",
        100,
        0.5,
        completion.CompletionShape(),
    )
    assert "timeout" not in args


async def test_hung_call_raises_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A call that never returns is cancelled and surfaces as a timeout.

    This is the regression: previously the await simply never completed.
    """
    monkeypatch.setenv(completion.LLM_TIMEOUT_ENV, "0.01")
    monkeypatch.setattr(completion, "_TIMEOUT_GRACE_SECONDS", 0.0)

    async def never_answers(**_kwargs: Any) -> Any:
        await asyncio.sleep(3600)

    install_fake_backend(monkeypatch, never_answers)

    with (
        scoped_telemetry("test_phase") as telemetry,
        pytest.raises(LLMTimeoutError) as excinfo,
    ):
        await completion._acompletion_within_timeout(
            {}, "deepseek/deepseek-v4-pro"
        )
    assert "deepseek/deepseek-v4-pro" in str(excinfo.value)

    # A failed physical call is still telemetry: calls=1, latency measured,
    # and classified under the exception's own kind rather than dropped.
    entry = telemetry.snapshot()["test_phase::deepseek/deepseek-v4-pro"]
    assert entry["calls"] == 1
    assert entry["errors"] == {"LLMTimeoutError": 1}
    assert entry["latency_seconds"] > 0


async def test_hung_tool_loop_call_raises_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool loop's LLM turn sits under the same ceiling as call_llm.

    The agentic web-search path runs on call_llm_with_tools, whose
    completion call used to await litellm bare -- a wedged provider there
    parked a durable task exactly like the plain-call case.
    """
    monkeypatch.setenv(completion.LLM_TIMEOUT_ENV, "0.01")
    monkeypatch.setattr(completion, "_TIMEOUT_GRACE_SECONDS", 0.0)

    async def never_answers(**_kwargs: Any) -> Any:
        await asyncio.sleep(3600)

    install_fake_backend(monkeypatch, never_answers)

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

    install_fake_backend(monkeypatch, timing_out)

    with pytest.raises(LLMTimeoutError):
        await llm.call_llm_json(
            "prompt",
            CompletionSpec(model_name="deepseek/deepseek-v4-flash"),
            max_attempts=5,
            options=LLMCallOptions(use_cache=False),
        )
    assert calls == 1, "a timeout must not be retried"


@pytest.mark.parametrize(
    ("api_key", "expected_zero_cost"), [(None, True), ("byok-key", False)]
)
async def test_native_provider_timeout_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str | None,
    expected_zero_cost: bool,
) -> None:
    """A provider-accepted request with a lost response is ambiguous once.

    LiteLLM's native Timeout is not asyncio.TimeoutError. It must enter the
    same no-in-call-replay path as the engine's own wall-clock timeout.
    """
    accepted: list[dict[str, Any]] = []
    admissions: list[bool] = []

    async def admit(_args: dict[str, Any], *, byok: bool = False) -> bool:
        admissions.append(byok)
        return True

    async def accepted_then_lost(**kwargs: Any) -> Any:
        accepted.append(kwargs)
        raise LiteLLMTimeout(
            message="read timed out after provider accepted request",
            model="deepseek/deepseek-v4-flash",
            llm_provider="deepseek",
        )

    install_fake_backend(monkeypatch, accepted_then_lost)
    monkeypatch.setattr(transport, "enforce_free_request", admit)

    with pytest.raises(LLMTimeoutError) as excinfo:
        await llm.call_llm_json(
            "prompt",
            CompletionSpec(
                model_name="deepseek/deepseek-v4-flash", api_key=api_key
            ),
            max_attempts=5,
            options=LLMCallOptions(use_cache=False),
        )

    assert len(accepted) == 1, "an ambiguous provider call must not replay"
    assert admissions == [api_key is not None]
    assert excinfo.value.zero_cost_admitted is expected_zero_cost


async def test_generic_failure_is_still_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal provider error keeps its existing retry behaviour."""
    calls = 0

    async def failing(**_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise RuntimeError("transient provider error")

    install_fake_backend(monkeypatch, failing)

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
        "co_scientist.llm.attempts.retry.asyncio.sleep", _recording_sleep(slept)
    )
    calls = 0

    async def throttled(**_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise _ProviderRateLimitError(
            "RateLimitError: DashscopeException - Request rate increased "
            "too quickly."
        )

    install_fake_backend(monkeypatch, throttled)

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
    waits = {
        _llm_timeout_backoff._rate_limit_backoff_seconds(1) for _ in range(40)
    }
    assert len(waits) > 1, "identical waits would re-synchronize the burst"


async def test_schema_failure_still_retries_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backoff is scoped to throttling; a bad payload retries immediately."""
    slept: list[float] = []
    monkeypatch.setattr(
        "co_scientist.llm.attempts.retry.asyncio.sleep", _recording_sleep(slept)
    )
    calls = 0

    async def failing(**_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise ValueError("provider rejected the request")

    install_fake_backend(monkeypatch, failing)

    with pytest.raises(ValueError):
        await llm.call_llm_json(
            "prompt",
            CompletionSpec(model_name="deepseek/deepseek-v4-flash"),
            max_attempts=3,
            options=LLMCallOptions(use_cache=False),
        )
    assert calls == 3
    assert slept == [], "only throttling should slow the retry loop"


async def test_deployment_api_key_does_not_disable_free_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment key still passes the real exact-zero admission guard."""
    accepted: list[dict[str, Any]] = []

    async def accepted_then_lost(**kwargs: Any) -> Any:
        accepted.append(kwargs)
        raise LiteLLMTimeout(
            message="read timed out after provider accepted request",
            model="openrouter/nex-agi/nex-n2.5-pro:free",
            llm_provider="openrouter",
        )

    install_fake_backend(monkeypatch, accepted_then_lost)

    with pytest.raises(LLMTimeoutError) as excinfo:
        await completion._acompletion_within_timeout(
            {
                "model": "openrouter/nex-agi/nex-n2.5-pro:free",
                "messages": [{"role": "user", "content": "prompt"}],
                "api_key": "deployment-key",
            },
            "openrouter/nex-agi/nex-n2.5-pro:free",
        )

    assert len(accepted) == 1
    assert accepted[0]["api_key"] == "deployment-key"
    assert accepted[0]["api_base"] == "https://openrouter.ai/api/v1"
    assert accepted[0]["extra_body"]["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    assert excinfo.value.zero_cost_admitted is True


async def test_an_oversized_prompt_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prompt too large for the window is still too large on a retry.

    A live run rejected single simulation prompts of 1.18M to 1.65M tokens
    and re-sent them eleven times unchanged. Nothing in the retry loop can
    shrink the caller's transcript, so every attempt after the first is one
    doomed call repeated -- the anti-pattern AGENTS.md names as "the retry
    has to change the request". Raising hands it back to the caller, which
    is the only layer that can send something shorter.
    """
    calls = 0

    async def too_big(**_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise ContextWindowExceededError(
            message="requested about 1645623 tokens",
            model="deepseek/deepseek-v4-flash",
            llm_provider="deepseek",
        )

    install_fake_backend(monkeypatch, too_big)

    with pytest.raises(ContextWindowExceededError):
        await llm.call_llm_json(
            "prompt",
            CompletionSpec(model_name="deepseek/deepseek-v4-flash"),
            max_attempts=5,
            options=LLMCallOptions(use_cache=False),
        )
    assert calls == 1, "an oversized prompt must not be sent again"


def _rate_limit_error(
    message: str, *, headers: dict[str, str] | None = None
) -> RateLimitError:
    """Build a litellm RateLimitError carrying the given response headers.

    Mirrors what litellm itself does for an OpenAI-compatible provider
    (openrouter included): the raised RateLimitError carries the original
    httpx response, headers and all, as ``.response``.
    """
    response = None
    if headers is not None:
        response = httpx.Response(
            status_code=429,
            headers=headers,
            request=httpx.Request("POST", "https://openrouter.ai/api/v1"),
        )
    return RateLimitError(
        message=message,
        llm_provider="openrouter",
        model="test-model",
        response=response,
    )


def test_x_ratelimit_reset_header_parks_the_task() -> None:
    """A platform daily-cap reset hours out should park, not retry."""
    now = time.time()
    reset_at = now + 3 * 3600
    error = _rate_limit_error(
        "RateLimitError: OpenRouterException - rate limited",
        headers={"x-ratelimit-reset": str(int(reset_at * 1000))},
    )

    park = platform_rate_limit_park(error)

    assert isinstance(park, LLMRateLimitParkError)
    assert park.resume_at == pytest.approx(reset_at, abs=1.0)
    assert park.reason == "x_ratelimit_reset_header"


def test_message_only_upstream_rate_limit_backs_off() -> None:
    """A message with no cap wording keeps its ordinary backoff."""
    error = _rate_limit_error(
        "RateLimitError: DeepseekException - rate-limited upstream, "
        "provider_code=rate_limited"
    )

    assert platform_rate_limit_park(error) is None


def test_short_retry_after_backs_off() -> None:
    """A short Retry-After stays inside the ordinary backoff, not a park."""
    error = _rate_limit_error(
        "RateLimitError: OpenRouterException - rate limited",
        headers={"retry-after": "20"},
    )

    assert platform_rate_limit_park(error) is None


def test_per_day_message_falls_back_to_next_utc_midnight() -> None:
    """No header, but the message names a daily cap: park until UTC midnight."""
    error = _rate_limit_error(
        "RateLimitError: OpenRouterException - free-models-per-day"
        " rate limit exceeded"
    )

    park = platform_rate_limit_park(error)

    assert isinstance(park, LLMRateLimitParkError)
    assert park.reason == "message_per_day"
    assert 0 < park.resume_at - time.time() <= 86400


def test_per_minute_message_stays_under_the_park_threshold() -> None:
    """A per-minute mention alone should not exceed the park threshold."""
    error = _rate_limit_error(
        "RateLimitError: OpenRouterException - free-models-per-minute"
        " rate limit exceeded"
    )

    assert platform_rate_limit_park(error) is None


def _fails_once(error: Exception) -> Callable[[Attempt], Awaitable[str]]:
    """An attempt-maker that raises ``error`` once, then answers."""

    async def make_attempt(attempt: Attempt) -> str:
        if attempt.number == 1:
            raise error
        return "answered"

    return make_attempt


@pytest.mark.asyncio
async def test_handle_json_call_failure_raises_park_error_without_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The attempt loop raises the park error: no wait, no further attempt.

    Named for the failure handler this loop replaced.
    """

    async def _fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("must not sleep out a platform-cap park")

    monkeypatch.setattr(
        "co_scientist.llm.attempts.retry.asyncio.sleep", _fail_if_called
    )
    now = time.time()
    error = _rate_limit_error(
        "RateLimitError: OpenRouterException - rate limited",
        headers={"x-ratelimit-reset": str(int((now + 7200) * 1000))},
    )

    with pytest.raises(LLMRateLimitParkError) as excinfo:
        await retry.run_attempts(
            _fails_once(error), AttemptPlan("m", max_attempts=3)
        )

    assert excinfo.value.resume_at == pytest.approx(now + 7200, abs=1.0)


@pytest.mark.asyncio
async def test_handle_json_call_failure_backs_off_ordinary_throttle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A message-only throttle still goes through the ordinary backoff.

    Named for the failure handler the attempt loop replaced.
    """
    slept: list[float] = []

    async def _record_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(
        "co_scientist.llm.attempts.retry.asyncio.sleep", _record_sleep
    )
    error = _rate_limit_error(
        "RateLimitError: DeepseekException - rate-limited upstream"
    )

    result = await retry.run_attempts(
        _fails_once(error), AttemptPlan("m", max_attempts=2)
    )

    assert result == "answered"
    assert len(slept) == 1


def _provider_error(
    factory: Callable[..., Exception], message: str
) -> Exception:
    """Build a litellm provider exception carrying the given message.

    The three constructors used below order their arguments differently,
    so each is bound by keyword rather than positionally.
    """
    return factory(message=message, llm_provider="openrouter", model="m")


_MID_STREAM_MESSAGE = (
    "LLM provider reported an error mid-stream and wrote no answer. "
    "Model: openrouter/nvidia/nemotron-3-super-120b-a12b:free "
    "(finish_reason=error, completion_tokens=0)"
)

_ROUTES_EXHAUSTED_MESSAGE = (
    "litellm.NotFoundError: OpenrouterException - "
    '{"error":{"message":"Provider returned error","code":404,'
    '"metadata":{"raw":"","provider_name":"Nvidia","is_byok":false,'
    '"previous_errors":[{"code":429,"message":"Resource exhausted",'
    '"provider_name":"Google AI Studio"}]}}}'
)


async def _sleeps_for(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> list[float]:
    """Return the waits the attempt loop took after one failed attempt."""
    slept: list[float] = []

    async def _record_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(
        "co_scientist.llm.attempts.retry.asyncio.sleep", _record_sleep
    )
    result = await retry.run_attempts(
        _fails_once(error), AttemptPlan("m", max_attempts=2)
    )
    assert result == "answered"
    return slept


def _overloaded_error() -> APIError:
    """The verbatim upstream-overload shape runs bc77950f and 49a509b0 hit."""
    return APIError(
        status_code=500,
        message=(
            "litellm.APIError: OpenrouterException - Upstream error from "
            "Nvidia: Service temporarily overloaded"
        ),
        llm_provider="openrouter",
        model="m",
    )


@pytest.mark.asyncio
async def test_overloaded_api_error_backs_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production overload shape spaces the next attempt out.

    Run bc77950f spent attempts 2-5 in four seconds against an upstream
    overload; a transient provider failure must wait like a throttle does.
    """
    error = _overloaded_error()
    before = retry.rate_limited_attempt_count()

    slept = await _sleeps_for(monkeypatch, error)

    assert len(slept) == 1
    assert slept[0] > 0
    # Rate-limit telemetry sizes the next fan-out wave; an overload is
    # not throttling and must not inflate it.
    assert retry.rate_limited_attempt_count() == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory",
    [InternalServerError, ServiceUnavailableError, APIConnectionError],
)
async def test_transient_provider_classes_back_off(
    monkeypatch: pytest.MonkeyPatch, factory: Callable[..., Exception]
) -> None:
    """Every transient litellm class spaces its retry out."""
    error = _provider_error(factory, "the provider is having a moment")

    assert len(await _sleeps_for(monkeypatch, error)) == 1


@pytest.mark.asyncio
async def test_mid_stream_provider_failure_backs_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finish_reason=error shape has no own type, so match its text."""
    error = ValueError(_MID_STREAM_MESSAGE)

    assert len(await _sleeps_for(monkeypatch, error)) == 1


@pytest.mark.asyncio
async def test_routes_exhausted_not_found_backs_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 404 carrying previous_errors is OpenRouter's routes-exhausted shape."""
    error = NotFoundError(
        message=_ROUTES_EXHAUSTED_MESSAGE,
        model="m",
        llm_provider="openrouter",
    )

    assert len(await _sleeps_for(monkeypatch, error)) == 1


@pytest.mark.asyncio
async def test_schema_failure_retries_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schema failure carries feedback, so the retry must not be delayed."""
    error = ValueError("Response failed schema validation: 'title' is required")

    assert await _sleeps_for(monkeypatch, error) == []


@pytest.mark.asyncio
async def test_thinking_only_failure_retries_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An answerless completion is answered by the ladder, not by waiting."""
    error = LLMThinkingOnlyError(
        "LLM finished its chain of thought and wrote no answer. Model: m"
    )

    assert await _sleeps_for(monkeypatch, error) == []


@pytest.mark.asyncio
async def test_bad_request_retries_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 400 has its own escalation rung; waiting would only delay it."""
    error = BadRequestError(
        message=(
            "litellm.BadRequestError: OpenrouterException - Reasoning is "
            "mandatory for this endpoint and cannot be disabled."
        ),
        model="m",
        llm_provider="openrouter",
    )

    assert await _sleeps_for(monkeypatch, error) == []


@pytest.mark.asyncio
async def test_bare_not_found_retries_at_once_and_raises_when_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare 404 is a real model-not-found: no wait, and no rescue."""
    error = NotFoundError(
        message="litellm.NotFoundError: model 'no-such-model' not found",
        model="no-such-model",
        llm_provider="openrouter",
    )

    assert await _sleeps_for(monkeypatch, error) == []

    with pytest.raises(NotFoundError):
        await retry.run_attempts(
            _fails_once(error), AttemptPlan("m", max_attempts=1)
        )


@pytest.mark.asyncio
async def test_bad_request_wrapping_upstream_text_retries_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 400 stays non-transient even when it quotes the upstream's words.

    OpenRouter wraps an upstream 4xx with the provider's own raw text, so
    a request problem can carry the very wording that marks an overload.
    The class decides here, not the message.
    """
    error = BadRequestError(
        message=(
            "litellm.BadRequestError: OpenrouterException - Upstream error "
            "from Nvidia: invalid request"
        ),
        model="m",
        llm_provider="openrouter",
    )

    assert await _sleeps_for(monkeypatch, error) == []


@pytest.mark.asyncio
async def test_provider_outage_waits_minutes_not_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An outage's first wait outlasts a throttle burst's whole schedule.

    Standard run 49a509b0 (2026-09-08) spent all five attempts of its
    terminal ``research_overview`` call in roughly 25 seconds -- 1.6, 3.6,
    6.3 and 11.6 second waits -- against an upstream outage that lasted
    minutes, so the attempt budget was gone before the provider recovered.
    """
    slept = await _sleeps_for(monkeypatch, _overloaded_error())

    assert len(slept) == 1
    # An absolute floor, not one derived from the constant under test: the
    # whole point is that the first wait alone outlasts the 25 seconds that
    # run's entire five-attempt budget fitted into.
    assert slept[0] >= 15.0


@pytest.mark.asyncio
async def test_throttle_keeps_its_own_shorter_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429's burst schedule is untouched by the outage schedule."""
    error = _rate_limit_error(
        "RateLimitError: OpenrouterException - rate-limited upstream"
    )

    slept = await _sleeps_for(monkeypatch, error)

    assert (
        slept[0]
        <= _llm_rate_limit_park_backoff._RATE_LIMIT_BACKOFF_BASE_SECONDS
    )


def test_provider_outage_backoff_grows_between_attempts() -> None:
    """A later attempt always waits longer than an earlier one can."""
    first = max(
        _llm_rate_limit_park_backoff.provider_outage_backoff_seconds(1)
        for _ in range(50)
    )
    fourth = min(
        _llm_rate_limit_park_backoff.provider_outage_backoff_seconds(4)
        for _ in range(50)
    )

    assert fourth > first


def test_provider_outage_backoff_is_capped() -> None:
    """No single wait grows without bound, however many attempts precede it."""
    assert (
        _llm_rate_limit_park_backoff.provider_outage_backoff_seconds(10)
        <= _llm_rate_limit_park_backoff._PROVIDER_OUTAGE_BACKOFF_MAX_SECONDS
    )


def test_wait_is_drawn_from_the_top_half_of_the_ceiling() -> None:
    """Every wait lands in [ceiling / 2, ceiling], for every attempt."""
    for attempt in range(1, 6):
        ceiling = 2.0 * 2 ** (attempt - 1)
        for _ in range(50):
            delay = _backoff_backoff.jittered_backoff_seconds(attempt, 2.0)
            assert ceiling / 2 <= delay <= ceiling


def test_wait_is_actually_jittered() -> None:
    """Identical waits would release every throttled caller together."""
    waits = {
        _backoff_backoff.jittered_backoff_seconds(3, 2.0) for _ in range(40)
    }
    assert len(waits) > 1


def test_ceiling_doubles_with_each_attempt() -> None:
    """The floor of a later attempt clears the ceiling of an earlier one."""
    first = max(
        _backoff_backoff.jittered_backoff_seconds(1, 2.0) for _ in range(50)
    )
    third = min(
        _backoff_backoff.jittered_backoff_seconds(3, 2.0) for _ in range(50)
    )
    assert third > first


def test_max_seconds_saturates_the_growth() -> None:
    """Past the cap the ceiling stops doubling."""
    for _ in range(50):
        assert _backoff_backoff.jittered_backoff_seconds(9, 0.5, 8.0) <= 8.0


def test_callers_keep_their_own_base_and_cap() -> None:
    """Sharing the schedule must not have merged the two callers' tuning.

    The search path waits fractions of a second and saturates at 8s; the LLM
    path starts at 2s and is deliberately uncapped.
    """
    assert search_query._search_retry_delay(1) <= 0.5
    assert llm_backoff._rate_limit_backoff_seconds(1) >= 1.0
    assert search_query._search_retry_delay(12) <= 8.0
    assert llm_backoff._rate_limit_backoff_seconds(12) > 8.0

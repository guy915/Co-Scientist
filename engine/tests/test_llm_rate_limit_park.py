"""Tests for classifying a platform rate-limit cap versus an ordinary throttle.

OpenRouter's free-model variants carry two different 429 sources: an
upstream provider hiccup the existing jittered backoff already answers,
and a platform-wide per-minute/per-day cap whose reset can be hours away.
``llm_json_retry._platform_rate_limit_park`` (shared with
``llm_text_retry`` through ``_handle_json_call_failure``) is what tells
them apart, so a durable task can be parked instead of failed on the
second kind without spending further attempts on the first.
"""

import time

import httpx
import pytest
from litellm.exceptions import RateLimitError

from co_scientist import llm_json_retry
from co_scientist.exceptions import LLMRateLimitParkError
from co_scientist.llm_json_attempt import _JsonAttempt


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

    park = llm_json_retry._platform_rate_limit_park(error)

    assert isinstance(park, LLMRateLimitParkError)
    assert park.resume_at == pytest.approx(reset_at, abs=1.0)
    assert park.reason == "x_ratelimit_reset_header"


def test_message_only_upstream_rate_limit_backs_off() -> None:
    """A message with no cap wording keeps its ordinary backoff."""
    error = _rate_limit_error(
        "RateLimitError: DeepseekException - rate-limited upstream, "
        "provider_code=rate_limited"
    )

    assert llm_json_retry._platform_rate_limit_park(error) is None


def test_short_retry_after_backs_off() -> None:
    """A short Retry-After stays inside the ordinary backoff, not a park."""
    error = _rate_limit_error(
        "RateLimitError: OpenRouterException - rate limited",
        headers={"retry-after": "20"},
    )

    assert llm_json_retry._platform_rate_limit_park(error) is None


def test_per_day_message_falls_back_to_next_utc_midnight() -> None:
    """No header, but the message names a daily cap: park until UTC midnight."""
    error = _rate_limit_error(
        "RateLimitError: OpenRouterException - free-models-per-day"
        " rate limit exceeded"
    )

    park = llm_json_retry._platform_rate_limit_park(error)

    assert isinstance(park, LLMRateLimitParkError)
    assert park.reason == "message_per_day"
    assert 0 < park.resume_at - time.time() <= 86400


def test_per_minute_message_stays_under_the_park_threshold() -> None:
    """A per-minute mention alone should not exceed the park threshold."""
    error = _rate_limit_error(
        "RateLimitError: OpenRouterException - free-models-per-minute"
        " rate limit exceeded"
    )

    assert llm_json_retry._platform_rate_limit_park(error) is None


@pytest.mark.asyncio
async def test_handle_json_call_failure_raises_park_error_without_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared failure handler raises the park error, never backs off."""

    async def _fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("must not sleep out a platform-cap park")

    monkeypatch.setattr(
        "co_scientist.llm_json_retry.asyncio.sleep", _fail_if_called
    )
    now = time.time()
    error = _rate_limit_error(
        "RateLimitError: OpenRouterException - rate limited",
        headers={"x-ratelimit-reset": str(int((now + 7200) * 1000))},
    )
    attempt = _JsonAttempt(number=1, is_final=False)

    with pytest.raises(LLMRateLimitParkError) as excinfo:
        await llm_json_retry._handle_json_call_failure(error, attempt)

    assert excinfo.value.resume_at == pytest.approx(now + 7200, abs=1.0)


@pytest.mark.asyncio
async def test_handle_json_call_failure_backs_off_ordinary_throttle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A message-only throttle still goes through the ordinary backoff."""
    slept: list[float] = []

    async def _record_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(
        "co_scientist.llm_json_retry.asyncio.sleep", _record_sleep
    )
    error = _rate_limit_error(
        "RateLimitError: DeepseekException - rate-limited upstream"
    )
    attempt = _JsonAttempt(number=1, is_final=False)

    outcome = await llm_json_retry._handle_json_call_failure(error, attempt)

    assert outcome.error is error
    assert len(slept) == 1

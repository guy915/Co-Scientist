"""Tests for classifying a platform rate-limit cap versus an ordinary throttle.

OpenRouter's free-model variants carry two different 429 sources: an
upstream provider hiccup the existing jittered backoff already answers,
and a platform-wide per-minute/per-day cap whose reset can be hours away.
``llm_json_retry._platform_rate_limit_park`` (shared with
``llm_text_retry`` through ``_handle_json_call_failure``) is what tells
them apart, so a durable task can be parked instead of failed on the
second kind without spending further attempts on the first.

The same handler also decides which *non*-throttled failures are worth
spacing out. Those cases live here too, since they share one seam:
``llm_json_escalation.is_transient_provider_error``.
"""

import time
from collections.abc import Callable

import httpx
import pytest
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
)

from co_scientist import llm_json_retry, llm_retry_backoff
from co_scientist.exceptions import (
    LLMRateLimitParkError,
    LLMThinkingOnlyError,
)
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
    """Return the waits ``_handle_json_call_failure`` took for one failure."""
    slept: list[float] = []

    async def _record_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(
        "co_scientist.llm_json_retry.asyncio.sleep", _record_sleep
    )
    attempt = _JsonAttempt(number=1, is_final=False)
    outcome = await llm_json_retry._handle_json_call_failure(error, attempt)
    assert outcome.error is error
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
    before = llm_json_retry.rate_limited_attempt_count()

    slept = await _sleeps_for(monkeypatch, error)

    assert len(slept) == 1
    assert slept[0] > 0
    # Rate-limit telemetry sizes the next fan-out wave; an overload is
    # not throttling and must not inflate it.
    assert llm_json_retry.rate_limited_attempt_count() == before


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

    # The handler re-raises with a bare ``raise``, so it has to be called
    # from inside the caller's own except block.
    try:
        raise error
    except NotFoundError:
        with pytest.raises(NotFoundError):
            await llm_json_retry._handle_json_call_failure(
                error, _JsonAttempt(number=5, is_final=True)
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

    assert slept[0] <= llm_retry_backoff._RATE_LIMIT_BACKOFF_BASE_SECONDS


def test_provider_outage_backoff_grows_between_attempts() -> None:
    """A later attempt always waits longer than an earlier one can."""
    first = max(
        llm_retry_backoff._provider_outage_backoff_seconds(1) for _ in range(50)
    )
    fourth = min(
        llm_retry_backoff._provider_outage_backoff_seconds(4) for _ in range(50)
    )

    assert fourth > first


def test_provider_outage_backoff_is_capped() -> None:
    """No single wait grows without bound, however many attempts precede it."""
    assert (
        llm_retry_backoff._provider_outage_backoff_seconds(10)
        <= llm_retry_backoff._PROVIDER_OUTAGE_BACKOFF_MAX_SECONDS
    )

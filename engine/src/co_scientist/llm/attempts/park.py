"""Telling a platform-wide rate-limit cap from an ordinary throttle.

OpenRouter's free-model variants carry two different 429 sources: an
upstream provider hiccup the attempt loop's jittered backoff already
answers, and a platform-wide per-minute or per-day cap whose reset can be
hours away. Backing off inside the call is right for the first and wasted
attempts for the second, so the loop asks this module which one a 429 is
and parks the durable task (``LLMRateLimitParkError``) for the second.

Pure classification: this module reads an error and the clock and decides.
What the loop then does about it -- raise, wait, count -- is
``llm.attempts.retry``'s.
"""

import time
from datetime import datetime, timedelta, timezone

from co_scientist.exceptions import LLMRateLimitParkError


def is_rate_limited(error: Exception) -> bool:
    """Return whether a provider error is a throttling response.

    Matched structurally (litellm raises ``RateLimitError`` for every
    provider) with a message fallback, so a provider whose SDK surfaces the
    condition as a generic error still backs off rather than hammering.
    """
    if type(error).__name__ == "RateLimitError":
        return True
    text = str(error).lower()
    return "rate limit" in text or "ratelimit" in text


# How long a wait must be before it is worth parking the whole task rather
# than absorbing it inside this call with the ordinary backoff. A
# per-minute platform cap (60s) and a short Retry-After both stay under
# this and get an ordinary throttled retry, since the five-attempt budget
# already covers waits that size; a per-day cap (hours) does not.
_PLATFORM_PARK_THRESHOLD_SECONDS = 90.0

# Conservative default for a per-minute cap (or an unqualified mention of
# the free-model pool) named only in the message, with no header to size
# the wait from -- long enough to clear a burst, and deliberately kept
# under the park threshold above so it is absorbed by the ordinary backoff
# rather than parking a task for a wait this short.
_PER_MINUTE_DEFAULT_SECONDS = 60.0


def _next_utc_midnight_epoch(now: float) -> float:
    """Return the epoch-seconds instant of the next UTC midnight after now."""
    current = datetime.fromtimestamp(now, tz=timezone.utc)
    tomorrow = (current + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return tomorrow.timestamp()


def _parse_float(value: str | None) -> float | None:
    """Parse a header value as a float, or None if it is missing/unusable."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _platform_reset_from_headers(
    error: Exception, now: float
) -> tuple[float, str] | None:
    """Read a platform rate-limit reset instant off the error's response.

    litellm's ``RateLimitError`` carries the original httpx response (when
    the upstream call had one) as ``.response``, so headers are read from
    there -- litellm surfaces no ``.headers`` shortcut of its own.
    ``Retry-After`` is checked first (it names a wait relative to now),
    then OpenRouter's ``X-RateLimit-Reset`` (an absolute epoch-millisecond
    instant).
    """
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    retry_after = _parse_float(headers.get("retry-after"))
    if retry_after is not None:
        return now + retry_after, "retry_after_header"
    reset_ms = _parse_float(headers.get("x-ratelimit-reset"))
    if reset_ms is not None:
        return reset_ms / 1000.0, "x_ratelimit_reset_header"
    return None


def _platform_reset_from_message(
    error: Exception, now: float
) -> tuple[float, str] | None:
    """Fall back to matching OpenRouter's free-model cap wording.

    Reached only when the response carried no usable header, so the wait
    is a conservative default rather than an exact instant: a "per day"
    mention parks until the next UTC reset, and a "per minute" mention (or
    a bare mention of the free-models pool) waits long enough to clear a
    burst without exceeding the park threshold above -- so it is absorbed
    by the ordinary jittered backoff instead of parking the task. A
    message naming neither a provider-cap nor a free-models phrase (e.g.
    "rate-limited upstream") matches nothing here and keeps its ordinary
    backoff.
    """
    # OpenRouter's own free-model cap message hyphenates ("free-models-
    # per-day"); match both that and a plain-English "per day" so either
    # phrasing is caught.
    text = str(error).lower()
    if "per day" in text or "per-day" in text:
        return _next_utc_midnight_epoch(now), "message_per_day"
    if "per minute" in text or "per-minute" in text or "free-models" in text:
        return now + _PER_MINUTE_DEFAULT_SECONDS, "message_per_minute"
    return None


def platform_rate_limit_park(
    error: Exception,
) -> LLMRateLimitParkError | None:
    """Return a park error when this 429 is a platform cap worth parking for.

    Only meaningful for an error ``is_rate_limited`` already matched.
    Headers are trusted before the message, since they name an exact
    instant rather than a guess; whichever source resolves, a wait short
    enough for the ordinary backoff to absorb returns ``None`` so the
    caller retries as usual instead of parking a task over a few seconds.

    Args:
        error: The provider failure to classify.

    Returns:
        An ``LLMRateLimitParkError`` carrying the resume instant and why it
        was classified as a platform cap, or ``None`` when this is an
        ordinary throttle the in-call backoff should absorb.
    """
    now = time.time()
    resolved = _platform_reset_from_headers(
        error, now
    ) or _platform_reset_from_message(error, now)
    if resolved is None:
        return None
    resume_at, reason = resolved
    if resume_at - now <= _PLATFORM_PARK_THRESHOLD_SECONDS:
        return None
    return LLMRateLimitParkError(resume_at=resume_at, reason=reason)

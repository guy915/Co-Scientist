"""Study 4's bounded Retry-After parsing rules."""

from collections.abc import Callable
from datetime import timezone
from email.utils import format_datetime, parsedate_to_datetime
from urllib.error import HTTPError

RETRY_AFTER_MAX_SECONDS = 60.0
RETRY_AFTER_DEFAULT_SECONDS = 15.0


def _canonical_seconds(value: str) -> str | None:
    if not value.isascii() or not value.isdecimal():
        return None
    seconds = value.lstrip("0") or "0"
    if len(seconds) > 2 or int(seconds) > RETRY_AFTER_MAX_SECONDS:
        return "61"
    return str(int(seconds))


def _canonical_http_date(value: str) -> str | None:
    try:
        parsed = parsedate_to_datetime(value)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return format_datetime(parsed.astimezone(timezone.utc), usegmt=True)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def retry_after_value(error: HTTPError) -> str | None:
    """Reads only the bounded Retry-After header from a response."""
    headers = error.headers
    if headers is None:
        return None
    value = headers.get("Retry-After")
    return None if value is None else str(value)


def retry_after_trace_value(
    value: str | None,
) -> tuple[str | None, str | None, bool]:
    """Returns a bounded semantic value and an explicitly bounded raw prefix."""
    if value is None:
        return None, None, False
    raw = str(value)
    stripped = raw.strip()
    canonical = _canonical_seconds(stripped)
    if canonical is None:
        canonical = _canonical_http_date(stripped)
    if canonical is None:
        canonical = stripped
        if (
            len(stripped) > 128
            or not stripped.isascii()
            or any(
                not (char == "\t" or " " <= char <= "~") for char in stripped
            )
        ):
            canonical = "!invalid"
    return canonical, raw[:128], len(raw) > 128


def _date_delay(raw: str, wall_clock: Callable[[], float]) -> float:
    try:
        retry_at = parsedate_to_datetime(raw)
        if retry_at is None:
            return RETRY_AFTER_DEFAULT_SECONDS
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, retry_at.timestamp() - wall_clock())
    except (TypeError, ValueError, OverflowError, OSError):
        return RETRY_AFTER_DEFAULT_SECONDS


def retry_after_delay(
    value: str | None, wall_clock: Callable[[], float]
) -> float | None:
    """Returns a bounded delay, or None when a valid delay exceeds 60s."""
    if value is None:
        delay = RETRY_AFTER_DEFAULT_SECONDS
    else:
        raw = value.strip()
        if raw.isascii() and raw.isdigit():
            seconds = raw.lstrip("0") or "0"
            if len(seconds) > 2:
                return None
            delay = float(int(seconds))
        else:
            delay = _date_delay(raw, wall_clock)
    return None if delay > RETRY_AFTER_MAX_SECONDS else delay


def retry_after_trace(
    error: HTTPError, wall_clock: Callable[[], float]
) -> tuple[dict[str, str | bool | None], float | None]:
    """Returns bounded trace fields alongside the unchanged policy delay."""
    raw = retry_after_value(error)
    canonical, raw_prefix, raw_truncated = retry_after_trace_value(raw)
    return (
        {
            "retry_after_value": canonical,
            "retry_after_raw_prefix": raw_prefix,
            "retry_after_raw_truncated": raw_truncated,
        },
        retry_after_delay(raw, wall_clock),
    )

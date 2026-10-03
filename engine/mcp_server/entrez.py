"""NCBI Entrez initialization, process pacing, and bounded request recovery."""

import contextvars
import logging
import os
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import timezone
from email.utils import format_datetime, parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError

from Bio import Entrez

from mcp_server.campaign import campaign_free_mode

logger = logging.getLogger(__name__)


def read_entrez(handle: Any) -> Any:
    """Parse an Entrez response and close it, including when parsing fails.

    Request pacing belongs in entrez_call, before the HTTP request is sent.
    Both metadata tools use this reader for dict- and list-shaped responses.
    """
    try:
        return Entrez.read(handle)
    except Exception:
        logger.debug("Entrez response parsing failed", exc_info=True)
        raise
    finally:
        handle.close()


# Module-level guard: Biopython's Entrez client stores credentials as
# process-global attributes (Entrez.email, Entrez.api_key) rather than on an
# instance, so initialization only needs to happen once per process even
# though multiple tool modules call initialize_entrez() at import time.
_entrez_initialized = False


def initialize_entrez() -> None:
    """Initializes Entrez with email and API key from the environment.

    Idempotent: configuration is applied and warnings logged only on the first
    call. NCBI rejects a request carrying an empty ``api_key=`` query parameter
    with HTTP 400 while accepting one that omits it, so an unset key is left
    unassigned rather than blanked.
    """
    global _entrez_initialized

    if os.environ.get("DISABLE_SSL_VERIFY", "").lower() in (
        "true",
        "1",
        "yes",
    ):
        raise RuntimeError("Disabling TLS verification is unsupported")

    if _entrez_initialized:
        return

    # Set the flag before doing the work (rather than after) so a failure
    # partway through does not cause every subsequent call to retry and
    # re-log the same warnings.
    _entrez_initialized = True
    _init_entrez_email()
    _init_entrez_api_key()


def _init_entrez_email() -> None:
    """Sets Entrez.email from ENTREZ_EMAIL if not already configured."""
    if Entrez.email:
        return

    entrez_email = os.environ.get("ENTREZ_EMAIL")
    if entrez_email:
        Entrez.email = entrez_email
        logger.info("Initialized Entrez with email: %s", entrez_email)
    else:
        # NCBI asks for a contact email to identify traffic; requests
        # still work without one but may be throttled more readily.
        logger.warning(
            "ENTREZ_EMAIL not set - PubMed may have stricter rate limits"
        )


def _init_entrez_api_key() -> None:
    """Sets Entrez.api_key from ENTREZ_API_KEY if not already configured."""
    if Entrez.api_key:
        return

    entrez_key = os.environ.get("ENTREZ_API_KEY")
    if entrez_key:
        Entrez.api_key = entrez_key
        logger.info("Initialized Entrez with API key")
    else:
        # Without a key NCBI enforces the default ~3 requests/second
        # rate limit rather than the higher registered-key limit.
        logger.info("ENTREZ_API_KEY not set - using default rate limits")


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


# Minimum seconds between two requests leaving this process, just inside
# NCBI's documented ceilings (10/s with a key, 3/s without) so ordinary clock
# jitter cannot push a pair over the line.
_INTERVAL_WITH_API_KEY = 0.11
_INTERVAL_WITHOUT_API_KEY = 0.4

_lock = threading.Lock()
# Monotonic time at which the next request may be issued.
_next_slot = 0.0

# Clock and sleep hooks, indirected only so tests can drive the pacer with a
# fake clock instead of real elapsed time. Production never overrides these.
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep
_wall_clock: Callable[[], float] = time.time

_PILOT_ENTREZ_CALLS = ("esearch", "efetch", "elink")
PILOT_ENTREZ_MAX_TRIES = 1
PILOT_ENTREZ_SLEEP_BETWEEN_TRIES = 0
STUDY4_RECOVERY_STUDY_ID = "M12-04b4-study4-20260930"
STUDY4_RECOVERY_POLICY = "study4-entrez-429-502-v1"
STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST = 1
STUDY4_MAX_RETRIES_PER_STUDY = 2
_study4_budget_lock = threading.Lock()
_study4_bound_study_id: str | None = None
_study4_retries_used = 0
_pilot_trace_context: contextvars.ContextVar[
    tuple[dict[str, Any], str | None] | None
] = contextvars.ContextVar("pubmed_pilot_trace", default=None)
_pilot_trace_lock = threading.Lock()


def bind_study4_recovery(study_id: str) -> int:
    """Binds this process to the one prospective Study 4 retry budget."""
    if study_id != STUDY4_RECOVERY_STUDY_ID:
        raise ValueError(
            "Study 4 Entrez recovery requires the protocol study ID"
        )
    global _study4_bound_study_id
    with _study4_budget_lock:
        if _study4_bound_study_id is None:
            _study4_bound_study_id = study_id
        elif _study4_bound_study_id != study_id:
            raise RuntimeError("Study 4 Entrez retry budget is already bound")
        return _study4_retries_used


def study4_retries_used(study_id: str) -> int:
    """Returns a monotonic process snapshot for the bound prospective study."""
    with _study4_budget_lock:
        if _study4_bound_study_id != study_id:
            raise RuntimeError("Study 4 Entrez retry budget is not bound")
        return _study4_retries_used


def reserve_study4_retry(study_id: str) -> int | None:
    """Atomically consumes one retry from the process-wide study ceiling."""
    global _study4_retries_used
    with _study4_budget_lock:
        if _study4_bound_study_id != study_id:
            raise RuntimeError("Study 4 Entrez retry budget is not bound")
        if _study4_retries_used >= STUDY4_MAX_RETRIES_PER_STUDY:
            return None
        _study4_retries_used += 1
        return _study4_retries_used


@contextmanager
def pilot_trace_context(
    trace: dict[str, Any] | None, paper_id: str | None = None
) -> Any:
    """Scopes optional trace accounting across async work and worker threads.

    ``asyncio.to_thread`` copies the current context, so individual blocking
    Entrez calls keep the correct run and paper identity without process-wide
    mutable request state.
    """
    parent = _pilot_trace_context.get()
    resolved_trace = (
        trace if trace is not None else parent[0] if parent else None
    )
    resolved_paper_id = (
        paper_id if paper_id is not None else parent[1] if parent else None
    )
    if resolved_trace is None:
        yield
        return
    token = _pilot_trace_context.set((resolved_trace, resolved_paper_id))
    try:
        yield
    finally:
        _pilot_trace_context.reset(token)


def record_pilot_fetch_error(
    stage: str, exc: Exception, paper_id: str | None = None
) -> None:
    """Records bounded, redacted fetch failure details for the active pilot."""
    context = _pilot_trace_context.get()
    if context is None:
        return
    trace, current_paper_id = context
    resolved_paper_id = paper_id if paper_id is not None else current_paper_id
    with _pilot_trace_lock:
        trace["incomplete_fetch_count"] = (
            trace.get("incomplete_fetch_count", 0) + 1
        )
        errors = trace.setdefault("fetch_errors", [])
        if len(errors) < 9:
            errors.append(
                {
                    "stage": stage,
                    "pmid": resolved_paper_id,
                    "type": type(exc).__name__,
                }
            )


def record_pilot_metadata_origin(paper_id: str, origin: str) -> None:
    """Records origin only for IDs exposed in the bounded selected-ID sample."""
    context = _pilot_trace_context.get()
    if context is None:
        return
    trace, _current_paper_id = context
    selected = trace.get("selected")
    selected_ids = selected.get("ids", []) if isinstance(selected, dict) else []
    if paper_id not in selected_ids[:9]:
        return
    with _pilot_trace_lock:
        trace.setdefault("metadata_origins", {})[paper_id] = origin


def _record_pilot_entrez_call(
    request: Callable[..., Any],
) -> tuple[dict[str, Any], str, int] | None:
    context = _pilot_trace_context.get()
    if context is None:
        return None
    operation = next(
        (
            name
            for name in _PILOT_ENTREZ_CALLS
            if request is getattr(Entrez, name)
        ),
        None,
    )
    if operation is None:
        return None
    trace, _paper_id = context
    with _pilot_trace_lock:
        counts = trace.setdefault(
            "entrez_calls", dict.fromkeys(_PILOT_ENTREZ_CALLS, 0)
        )
        counts[operation] += 1
        return trace, operation, counts[operation]


def _assert_pilot_retry_policy() -> None:
    if _pilot_trace_context.get() is None:
        return
    if (
        Entrez.max_tries != PILOT_ENTREZ_MAX_TRIES
        or Entrez.sleep_between_tries != PILOT_ENTREZ_SLEEP_BETWEEN_TRIES
    ):
        raise RuntimeError("Biopython PubMed pilot retry policy changed")


def _study4_recovery_metadata(
    trace: dict[str, Any],
) -> dict[str, Any] | None:
    metadata = trace.get("entrez_recovery")
    if not isinstance(metadata, dict):
        return None
    study_id = metadata.get("study_id")
    if study_id != STUDY4_RECOVERY_STUDY_ID:
        raise RuntimeError(
            "Study 4 Entrez recovery trace has an invalid study ID"
        )
    study4_retries_used(study_id)
    return metadata


def _record_recovery_entry_attempt(
    metadata: dict[str, Any], operation: str
) -> None:
    with _pilot_trace_lock:
        attempts = metadata["client_entry_attempts"]
        attempts[operation] += 1


def _update_process_retry_snapshot(metadata: dict[str, Any]) -> None:
    current = study4_retries_used(metadata["study_id"])
    with _pilot_trace_lock:
        metadata["process_retries_used_at_end"] = max(
            metadata["process_retries_used_at_end"], current
        )


def _record_recovery_call_outcome(
    trace: dict[str, Any],
    metadata: dict[str, Any],
    logical_call: tuple[str, int, int, int],
    outcome: str,
    events: list[dict[str, Any]],
) -> None:
    operation, logical_request_ordinal, retry_count, client_entry_attempts = (
        logical_call
    )
    with _pilot_trace_lock:
        for event in events:
            event["outcome"] = outcome
        outcomes = trace["entrez_recovery_call_outcomes"]
        outcomes.append(
            {
                "study_id": metadata["study_id"],
                "run_id": trace.get("run_id"),
                "operation": operation,
                "logical_request_ordinal": logical_request_ordinal,
                "retry_count": retry_count,
                "client_entry_attempts": client_entry_attempts,
                "final_outcome": outcome,
            }
        )
        if outcome == "recovered":
            metadata["recovered_calls"] += 1
        else:
            metadata["exhausted_calls"] += 1


def _study4_retry_decision(
    study_id: str, retry_after_delay: float | None, retry_count: int
) -> tuple[bool, str, int, int | None]:
    if retry_after_delay is None:
        return False, "retry_after_over_cap", retry_count, None
    if retry_count >= STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST:
        return False, "exhausted", retry_count, None
    reserved_count = reserve_study4_retry(study_id)
    if reserved_count is None:
        return False, "study_budget_exhausted", retry_count, None
    return True, "pending", retry_count + 1, reserved_count


def _handle_study4_http_error(
    error: HTTPError,
    recovery: tuple[dict[str, Any], dict[str, Any], str, int],
    retry_count: int,
    entry_attempts: int,
    events: list[dict[str, Any]],
) -> tuple[int, bool, str]:
    trace, metadata, operation, logical_request_ordinal = recovery
    retry_after_fields, delay = retry_after_trace(error, _wall_clock)
    retry_scheduled, outcome, next_retry_count, reserved_count = (
        _study4_retry_decision(metadata["study_id"], delay, retry_count)
    )
    if reserved_count is not None:
        with _pilot_trace_lock:
            metadata["retries_used"] += 1
            metadata["process_retries_used_at_end"] = max(
                metadata["process_retries_used_at_end"], reserved_count
            )
    event = {
        "study_id": metadata["study_id"],
        "run_id": trace.get("run_id"),
        "server_build_id": trace.get("server_build_id"),
        "process_id": trace.get("process_id"),
        "operation": operation,
        "logical_request_ordinal": logical_request_ordinal,
        "attempt_ordinal": entry_attempts,
        "http_status": error.code,
        **retry_after_fields,
        "wait_seconds": delay if retry_scheduled and delay else 0.0,
        "outcome": outcome,
    }
    events.append(event)
    with _pilot_trace_lock:
        trace["recovered_transient_attempts"].append(event)
    if retry_scheduled and delay:
        _sleep(delay)
    return next_retry_count, retry_scheduled, outcome


def _finish_study4_call(
    recovery: tuple[dict[str, Any], dict[str, Any], str, int],
    retry_count: int,
    entry_attempts: int,
    outcome: str,
    events: list[dict[str, Any]],
) -> None:
    trace, metadata, operation, logical_request_ordinal = recovery
    _record_recovery_call_outcome(
        trace,
        metadata,
        (operation, logical_request_ordinal, retry_count, entry_attempts),
        outcome,
        events,
    )


class _Study4CallState:
    def __init__(
        self, recovery: tuple[dict[str, Any], dict[str, Any], str, int]
    ) -> None:
        self.recovery = recovery
        self.retry_count = 0
        self.entry_attempts = 0
        self.events: list[dict[str, Any]] = []


def _run_study4_entrez_attempt(
    request: Callable[..., Any], kwargs: dict[str, Any], state: _Study4CallState
) -> Any:
    if state.entry_attempts:
        _await_slot()
        _assert_pilot_retry_policy()
    state.entry_attempts += 1
    _record_recovery_entry_attempt(state.recovery[1], state.recovery[2])
    try:
        result = request(**kwargs)
    except HTTPError as exc:
        if exc.code not in {429, 502}:
            raise
        state.retry_count, retry_scheduled, _outcome = (
            _handle_study4_http_error(
                exc,
                state.recovery,
                state.retry_count,
                state.entry_attempts,
                state.events,
            )
        )
        if retry_scheduled:
            return _run_study4_entrez_attempt(request, kwargs, state)
        raise
    return result


def _finish_study4_outcome(
    state: _Study4CallState, outcome: str | None
) -> None:
    if not state.events:
        return
    final_outcome = outcome or state.events[-1]["outcome"]
    if final_outcome == "pending":
        final_outcome = "exhausted"
    _finish_study4_call(
        state.recovery,
        state.retry_count,
        state.entry_attempts,
        final_outcome,
        state.events,
    )


def _study4_entrez_call(
    request: Callable[..., Any],
    kwargs: dict[str, Any],
    recovery: tuple[dict[str, Any], dict[str, Any], str, int],
) -> Any:
    state = _Study4CallState(recovery)
    try:
        result = _run_study4_entrez_attempt(request, kwargs, state)
    except Exception:
        _finish_study4_outcome(state, None)
        raise
    else:
        _finish_study4_outcome(state, "recovered")
        return result
    finally:
        _update_process_retry_snapshot(recovery[1])


def _request_interval() -> float:
    """Seconds to leave between requests, given the credentials in force."""
    initialize_entrez()
    return (
        _INTERVAL_WITH_API_KEY
        if Entrez.api_key and not campaign_free_mode()
        else _INTERVAL_WITHOUT_API_KEY
    )


def _await_slot() -> None:
    """Block until this caller's turn to issue a request comes round."""
    interval = _request_interval()
    with _lock:
        now = _clock()
        start = max(now, _next_slot)
        _claim_slot(start + interval)
    delay = start - now
    if delay > 0:
        _sleep(delay)


def _claim_slot(next_slot: float) -> None:
    """Record when the following request may go out. Call under ``_lock``."""
    global _next_slot
    _next_slot = next_slot


def _active_study4_metadata() -> dict[str, Any] | None:
    context = _pilot_trace_context.get()
    if context is None:
        return None
    metadata = _study4_recovery_metadata(context[0])
    if metadata is not None and not campaign_free_mode():
        raise RuntimeError(
            "Study 4 Entrez recovery requires keyless campaign mode"
        )
    return metadata


def _study4_call_context(
    call: tuple[dict[str, Any], str, int] | None,
    metadata: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], str, int] | None:
    if call is None or metadata is None:
        return None
    trace, operation, ordinal = call
    return trace, metadata, operation, ordinal


def entrez_call(request: Callable[..., Any], /, **kwargs: Any) -> Any:
    """Issue one Entrez request, paced against NCBI's rate limit.

    Every ``Entrez.esearch``/``efetch``/``elink`` call in this server must go
    through here; calling Entrez directly reintroduces the burst.

    Args:
        request: The Entrez entry point to call (e.g. ``Entrez.esearch``).
        **kwargs: Arguments forwarded to it verbatim.

    Returns:
        The open response handle the Entrez call returned.
    """
    # Biopython's key is process-global. Passing None suppresses it for this
    # request even when a standard user's key was loaded earlier in the process.
    if campaign_free_mode():
        kwargs["api_key"] = None
    active_metadata = _active_study4_metadata()
    _await_slot()
    _assert_pilot_retry_policy()
    # These count calls entering the maintained request seam. They are not
    # wire-attempt counts; Biopython retries are separately disabled and
    # attested only in the explicit pilot serving mode.
    call = _record_pilot_entrez_call(request)
    recovery = _study4_call_context(call, active_metadata)
    if recovery is not None:
        return _study4_entrez_call(request, kwargs, recovery)
    return request(**kwargs)

"""How ``call_llm_json`` follows one attempt with the next.

The retry policy lives here: whether a failure is terminal, whether it is
the provider throttling (and how long to wait before the next attempt),
and which rung of ``BudgetEscalation`` that attempt is made at. The
mechanics of running a single attempt live in ``llm_json_attempt`` and the
escalation ladder in ``llm_json_escalation``; both are re-exported here so
``co_scientist.llm_json_retry`` stays one import path for the whole retry
surface, which ``co_scientist.llm`` re-exports from in turn.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from litellm.exceptions import ContextWindowExceededError

from co_scientist.backoff import jittered_backoff_seconds
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
    LLMTimeoutError,
    short_error_text,
)
from co_scientist.llm_json_attempt import (
    _attempt_call_llm_json as _attempt_call_llm_json,
)
from co_scientist.llm_json_attempt import (
    _backfill_and_validate as _backfill_and_validate,
)
from co_scientist.llm_json_attempt import (
    _cache_validated_result as _cache_validated_result,
)
from co_scientist.llm_json_attempt import (
    _finalize_validated_result as _finalize_validated_result,
)
from co_scientist.llm_json_attempt import (
    _json_validation_failure_outcome as _json_validation_failure_outcome,
)
from co_scientist.llm_json_attempt import (
    _JsonAttempt as _JsonAttempt,
)
from co_scientist.llm_json_attempt import (
    _JsonAttemptOutcome as _JsonAttemptOutcome,
)
from co_scientist.llm_json_attempt import (
    _JsonRetryContext as _JsonRetryContext,
)
from co_scientist.llm_json_attempt import (
    _non_validating_repair_outcome as _non_validating_repair_outcome,
)
from co_scientist.llm_json_attempt import (
    _parse_or_repair_json as _parse_or_repair_json,
)
from co_scientist.llm_json_attempt import (
    _ParsedResponse as _ParsedResponse,
)
from co_scientist.llm_json_escalation import (
    _ESCALATION_LADDER as _ESCALATION_LADDER,
)
from co_scientist.llm_json_escalation import (
    BudgetEscalation as BudgetEscalation,
)
from co_scientist.llm_json_escalation import (
    _JsonCallSpec as _JsonCallSpec,
)
from co_scientist.llm_json_escalation import (
    escalated_spec as escalated_spec,
)
from co_scientist.llm_json_escalation import (
    escalation_for_error as escalation_for_error,
)
from co_scientist.llm_json_escalation import (
    log_escalation as log_escalation,
)
from co_scientist.llm_thinking import failure_context_text

logger = logging.getLogger(__name__)


# Base seconds for the throttled-retry wait; attempt N waits roughly
# BASE * 2^(N-1), jittered.
_RATE_LIMIT_BACKOFF_BASE_SECONDS = 2.0


# Count of throttled attempts observed in this process. Read by callers
# that size their own fan-out (see agents/ranking/ranking_debate.py) so a
# provider that is pushing back can shrink the next wave instead of having
# every extra call spend its time asleep in backoff. A plain counter, not
# an asyncio primitive, so it is safe to share across the worker cohort's
# several event loops.
_rate_limited_attempts = 0


def rate_limited_attempt_count() -> int:
    """Return how many throttled attempts this process has backed off from."""
    return _rate_limited_attempts


def _is_rate_limited(error: Exception) -> bool:
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


def _platform_rate_limit_park(
    error: Exception,
) -> LLMRateLimitParkError | None:
    """Return a park error when this 429 is a platform cap worth parking for.

    Only meaningful for an error ``_is_rate_limited`` already matched.
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


def _rate_limit_backoff_seconds(attempt: int) -> float:
    """Return the jittered wait before retrying a throttled attempt.

    Uncapped, unlike the search-tool retry: a provider still throttling on
    the last of a handful of attempts is asking for a longer pause, and the
    attempt budget already bounds the total. See
    ``backoff.jittered_backoff_seconds`` for why the wait is jittered.
    """
    return jittered_backoff_seconds(
        attempt, base_seconds=_RATE_LIMIT_BACKOFF_BASE_SECONDS
    )


def escalation_after(
    outcome: _JsonAttemptOutcome, current: BudgetEscalation
) -> BudgetEscalation:
    """The escalation the next attempt should use, given this one's outcome.

    An answerless attempt escalates, and so does a provider's flat refusal
    to honour disabled reasoning ("reasoning is mandatory... cannot be
    disabled") -- see ``escalation_for_error`` for that case, which is
    independent of the ladder below and always resolves to the same rung
    regardless of where it was raised from. The other two kinds enter the
    ladder at different points. Budget exhaustion climbs one rung, because
    a chain of thought cut off at the ceiling may genuinely have been close
    to finishing. A thinking-only response skips straight to the top:
    the model *chose* to stop, so it did not want for room, and the
    intermediate rung would spend a whole attempt proving that -- true
    only because a completion the provider itself aborted mid-stream
    (``finish_reason="error"``) never reaches this function as
    ``LLMThinkingOnlyError`` in the first place (see
    ``llm_response._empty_content_error``).

    A schema failure, a parse failure or an ordinary provider error
    (mid-stream provider failures included) all keep the current rung:
    they say nothing about thinking, and changing the request would spend
    more tokens on a problem tokens do not solve.

    Args:
        outcome: The outcome of the attempt that just ran.
        current: The escalation that attempt was made at.

    Returns:
        The rung for the next attempt, or ``current`` unchanged.
    """
    escalated = escalation_for_error(outcome.error, current)
    if escalated is None:
        return current
    log_escalation(outcome.error, escalated)
    return escalated


def _apply_json_attempt_outcome(
    outcome: _JsonAttemptOutcome,
    prompt: str,
    last_response_text: str | None,
) -> tuple[str, str | None]:
    """Applies a non-terminal call_llm_json attempt outcome to loop state.

    Args:
        outcome: The outcome of the attempt that just ran (``value`` is
            ``None``, i.e. the retry loop is continuing).
        prompt: The prompt used for that attempt.
        last_response_text: The most recent raw response text seen so far.

    Returns:
        The prompt and last_response_text to use for the next iteration.
    """
    if outcome.response_text is not None:
        last_response_text = outcome.response_text
    if outcome.next_prompt is not None:
        prompt = outcome.next_prompt
        logger.debug("added validation feedback to retry prompt")
    return prompt, last_response_text


def _raise_if_platform_rate_limit_park(
    error: Exception, attempt: _JsonAttempt
) -> None:
    """Raises ``LLMRateLimitParkError`` when this 429 is a platform cap.

    Checked ahead of the ordinary logging/backoff in
    ``_handle_json_call_failure``, and regardless of attempt number: a
    platform-wide cap will not have reset by the next attempt (or the final
    one), so there is nothing left in this call's own retry budget that
    answers it. Raising here -- rather than returning an outcome the loop
    backs off from -- means a caller with somewhere to park a unit of work
    (the durable task worker) can do so without this call spending further
    attempts against a cap that has not reset.

    Args:
        error: The call failure raised by this attempt.
        attempt: Which attempt of the retry loop this is.
    """
    if not _is_rate_limited(error):
        return
    park = _platform_rate_limit_park(error)
    if park is None:
        return
    logger.warning(
        "Platform rate limit cap hit on attempt %s (%s); parking "
        "until %.0f (epoch seconds) instead of retrying",
        attempt.number,
        park.reason,
        park.resume_at,
    )
    raise park


async def _handle_json_call_failure(
    error: Exception, attempt: _JsonAttempt
) -> _JsonAttemptOutcome:
    """Converts a non-timeout LLM call failure to an outcome.

    Shared by both retry loops -- ``call_llm_json``'s own and ``call_llm``'s
    escalation loop (see ``llm_text_retry``) -- so the two ladders classify
    and log a failure identically and cannot drift apart.

    Re-raises (via a bare ``raise``, so it must be called from within the
    caller's own ``except`` block) on the final attempt. A throttled failure
    waits out a jittered backoff before returning the outcome so the retry
    loop's next attempt goes out already spaced from the burst that caused
    the throttle.

    Args:
        error: The call failure raised by this attempt.
        attempt: Which attempt of the retry loop this is.

    Returns:
        An outcome carrying the error, for the retry loop to continue from.
    """
    _raise_if_platform_rate_limit_park(error, attempt)
    # This is the one layer that knows whether the failure is terminal, so
    # it is the one that decides the severity: an attempt another attempt
    # will answer is a warning, and only giving up is an error. Logging
    # every attempt at error made a run that recovered read as a broken one
    # -- one recovered answerless completion produced four ERROR records.
    #
    # It is also the only layer that writes the record at all: llm_response
    # and call_llm both stay silent under this loop (see
    # LLMCallOptions.log_failures), so this one line carries what they used
    # to report -- read off the error, which was annotated with the call's
    # own name and the budget it actually sent rather than recomputed here.
    # The name is what makes a count of these attributable: this loop is
    # shared by every node, and a production export of fifteen answerless
    # completions could only be narrowed to a budget constant that ten
    # call sites share.
    log = logger.error if attempt.is_final else logger.warning
    log(
        "LLM call failed on attempt %s%s: %s",
        attempt.number,
        failure_context_text(error),
        short_error_text(error),
    )
    if attempt.is_final:
        raise
    if _is_rate_limited(error):
        await _wait_out_rate_limit(attempt)
    return _JsonAttemptOutcome(
        value=None, error=error, response_text=None, next_prompt=None
    )


async def _wait_out_rate_limit(attempt: _JsonAttempt) -> None:
    """Space the next attempt out from the burst that caused the throttle.

    Unlike a schema failure -- where the next attempt carries corrective
    feedback and should go out at once -- throttling is answered by
    waiting. Retrying a throttled call immediately feeds the burst that
    caused it, and an unjittered backoff releases every throttled caller
    at the same moment, reproducing it.
    """
    global _rate_limited_attempts
    _rate_limited_attempts += 1
    delay = _rate_limit_backoff_seconds(attempt.number)
    logger.warning(
        "Rate limited on attempt %s; waiting %.1fs before retrying",
        attempt.number,
        delay,
    )
    await asyncio.sleep(delay)


async def _run_json_attempt(
    prompt: str, ctx: _JsonRetryContext, attempt: _JsonAttempt
) -> _JsonAttemptOutcome:
    """Runs one call_llm_json attempt, converting a call failure to an outcome.

    A genuine call failure (network, provider error, etc.) is surfaced to the
    retry loop as an outcome carrying the error, except on the final attempt,
    where it is re-raised so the caller's exception propagates unchanged.
    Three failures are deliberately never retried, for the same reason: the
    identical request cannot succeed, so retrying is one doomed call
    repeated by the attempt count. ``LLMTimeoutError`` is one -- a provider
    that accepted the request and then stopped answering will not answer
    the same request faster next time, which is the unbounded stall the
    timeout ceiling exists to prevent.

    ``LLMCallBudgetExceededError`` is a third: the run has already spent
    past its ``max_llm_calls`` ceiling, so another attempt only adds to
    the overrun rather than answering anything, and every attempt after
    the first would fail identically (the run is already over budget) --
    exactly the "same doomed call billed again" the escalation ladder
    exists to avoid for the other two shapes.

    ``ContextWindowExceededError`` is the other, and it is the one this
    repo has already been bitten by: a prompt too large for the model's
    window is still too large on the next attempt. A live run rejected
    single simulation prompts of 1.18M to 1.65M tokens and re-sent them
    **eleven times unchanged**. AGENTS.md states the rule this restores --
    "the retry has to change the request" -- and nothing here can change
    this one, since the oversized prompt is the caller's whole transcript.
    Raising hands it back to that caller, which is where a shorter
    transcript could come from; the simulation loop degrades to mental
    simulation on it, as it already did after five wasted attempts.

    Args:
        prompt: The prompt to send on this attempt.
        ctx: The retry-loop context.
        attempt: Which attempt of the retry loop this is.

    Returns:
        The outcome telling the retry loop how to continue.
    """
    try:
        return await _attempt_call_llm_json(prompt, ctx, attempt)
    except LLMCallBudgetExceededError:
        logger.error(
            "LLM-call ceiling exceeded on attempt %s; not retrying",
            attempt.number,
        )
        raise
    except LLMTimeoutError:
        logger.error(
            "LLM call timed out on attempt %s; not retrying", attempt.number
        )
        raise
    except ContextWindowExceededError:
        logger.error(
            "Prompt exceeded the model's context window on attempt %s;"
            " not retrying, since the same prompt cannot fit on a retry",
            attempt.number,
        )
        raise
    except Exception as e:
        return await _handle_json_call_failure(e, attempt)

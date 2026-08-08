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

from co_scientist.backoff import jittered_backoff_seconds
from co_scientist.exceptions import (
    LLMBudgetExhaustedError,
    LLMThinkingOnlyError,
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

    Only an answerless attempt escalates, and the two kinds enter the
    ladder at different points. Budget exhaustion climbs one rung, because
    a chain of thought cut off at the ceiling may genuinely have been close
    to finishing. A thinking-only response skips straight to the top:
    the model *chose* to stop, so it did not want for room, and the
    intermediate rung would spend a whole attempt proving that.

    A schema failure, a parse failure or an ordinary provider error all
    keep the current rung: they say nothing about thinking, and changing
    the request would spend more tokens on a problem tokens do not solve.

    Args:
        outcome: The outcome of the attempt that just ran.
        current: The escalation that attempt was made at.

    Returns:
        The rung for the next attempt, or ``current`` unchanged.
    """
    if isinstance(outcome.error, LLMThinkingOnlyError):
        logger.warning(
            "LLM finished thinking without answering; retrying with "
            "thinking disabled"
        )
        return BudgetEscalation.NO_THINKING
    if not isinstance(outcome.error, LLMBudgetExhaustedError):
        return current
    escalated = _ESCALATION_LADDER[current]
    logger.warning(
        "LLM spent its whole token budget reasoning; retrying with %s",
        "thinking disabled"
        if escalated is BudgetEscalation.NO_THINKING
        else "a raised token budget",
    )
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


async def _handle_json_call_failure(
    error: Exception, attempt: _JsonAttempt
) -> _JsonAttemptOutcome:
    """Converts a non-timeout ``call_llm_json`` call failure to an outcome.

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
    # This is the one layer that knows whether the failure is terminal, so
    # it is the one that decides the severity: an attempt another attempt
    # will answer is a warning, and only giving up is an error. Logging
    # every attempt at error made a run that recovered read as a broken one
    # -- one recovered answerless completion produced four ERROR records.
    log = logger.error if attempt.is_final else logger.warning
    log(
        "LLM call failed on attempt %s: %s",
        attempt.number,
        short_error_text(error),
    )
    if attempt.is_final:
        raise
    if _is_rate_limited(error):
        # Unlike a schema failure -- where the next attempt carries
        # corrective feedback and should go out at once -- throttling is
        # answered by waiting. Retrying a throttled call immediately feeds
        # the burst that caused it.
        global _rate_limited_attempts
        _rate_limited_attempts += 1
        delay = _rate_limit_backoff_seconds(attempt.number)
        logger.warning(
            "Rate limited on attempt %s; waiting %.1fs before retrying",
            attempt.number,
            delay,
        )
        await asyncio.sleep(delay)
    return _JsonAttemptOutcome(
        value=None, error=error, response_text=None, next_prompt=None
    )


async def _run_json_attempt(
    prompt: str, ctx: _JsonRetryContext, attempt: _JsonAttempt
) -> _JsonAttemptOutcome:
    """Runs one call_llm_json attempt, converting a call failure to an outcome.

    A genuine call failure (network, provider error, etc.) is surfaced to the
    retry loop as an outcome carrying the error, except on the final attempt,
    where it is re-raised so the caller's exception propagates unchanged.
    ``LLMTimeoutError`` is deliberately never retried: a provider that
    accepted the request and then stopped answering will not answer the same
    request faster next time, so retrying multiplies one stalled call by the
    attempt count -- exactly the unbounded stall the timeout ceiling exists
    to prevent.

    Args:
        prompt: The prompt to send on this attempt.
        ctx: The retry-loop context.
        attempt: Which attempt of the retry loop this is.

    Returns:
        The outcome telling the retry loop how to continue.
    """
    try:
        return await _attempt_call_llm_json(prompt, ctx, attempt)
    except LLMTimeoutError:
        logger.error(
            "LLM call timed out on attempt %s; not retrying", attempt.number
        )
        raise
    except Exception as e:
        return await _handle_json_call_failure(e, attempt)

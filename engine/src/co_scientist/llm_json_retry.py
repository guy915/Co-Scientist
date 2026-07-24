"""Per-attempt machinery for the ``call_llm_json`` retry loop.

Each attempt parses (and, if needed, repairs) the raw LLM response text,
validates it against the schema (applying the json_object
provider-capability backfill shim first), caches a validated result, and
reports how the retry loop should continue via ``_JsonAttemptOutcome``. The
raw LLM call itself is injected by ``co_scientist.llm.call_llm_json`` as the
``call_for_json`` callable, so this module stays free of network wiring and
the ``call_llm`` seam keeps resolving through ``co_scientist.llm``.
"""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jsonschema.exceptions import ValidationError

from co_scientist.cache import LLMCache, LLMCacheRequest, NullCache
from co_scientist.exceptions import LLMTimeoutError
from co_scientist.llm_json import (
    _backfill_required_fields,
    _validation_feedback,
    validate_json_schema,
)
from co_scientist.llm_json_repair import attempt_json_repair
from co_scientist.llm_request import _supports_json_schema_response_format

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

    The jitter matters more than the growth: a burst throttles many callers
    at once, and an unjittered wait would release all of them simultaneously,
    reproducing the burst that caused the throttle. Spreading them is what
    actually smooths the ramp the provider is asking for.
    """
    ceiling = _RATE_LIMIT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    return float(ceiling * (0.5 + random.random() / 2))


@dataclass(frozen=True)
class _JsonCallSpec:
    """Bundles the model/token/schema fields shared by json-attempt helpers."""

    model_name: str
    max_tokens: int
    temperature: float
    json_schema: dict[str, Any] | None


@dataclass(frozen=True)
class _JsonRetryContext:
    """The per-call state every attempt of one retry loop shares.

    Attributes:
        original_prompt: The prompt without validation feedback, used to
            build the next retry prompt after a schema failure.
        spec: The model/token/schema fields of the call.
        cache: The cache tier a validated result is stored in.
        call_for_json: Injected raw LLM call for one attempt's prompt.
    """

    original_prompt: str
    spec: _JsonCallSpec
    cache: LLMCache | NullCache
    call_for_json: Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class _JsonAttempt:
    """Which attempt of the retry loop is running.

    Attributes:
        number: The 1-indexed attempt number, used for logging.
        is_final: Whether this is the last attempt the loop will make.
    """

    number: int
    is_final: bool


@dataclass(frozen=True)
class _ParsedResponse:
    """What parsing (and any repair) made of one attempt's response text.

    Attributes:
        result: The parsed JSON dict, or None when nothing parsed.
        was_major_repair: Whether a major (truncation-indicating) repair was
            attempted.
        repaired: Whether the result needed JSON repair before validation.
        parse_error: The original parse failure, used by the caller only
            when every repair attempt also fails.
    """

    result: dict[str, Any] | None
    was_major_repair: bool
    repaired: bool
    parse_error: Exception | None


@dataclass
class _JsonAttemptOutcome:
    """Result of a single ``call_llm_json`` attempt.

    Attributes:
        value: The validated, parsed JSON response on success (already
            cached); ``None`` when this attempt did not succeed.
        error: The validation or parse error for this attempt, if any.
        response_text: The raw (fence-stripped) response text received this
            attempt, if the call reached that point.
        next_prompt: The retry prompt carrying validation feedback, set only
            when validation failed and feedback should be added for the next
            attempt; ``None`` otherwise.
    """

    value: dict[str, Any] | None
    error: Exception | None
    response_text: str | None
    next_prompt: str | None


def _parse_or_repair_json(
    response_text: str,
    is_final_attempt: bool,
) -> _ParsedResponse:
    """Parses response text as JSON, falling back to repair strategies.

    Args:
        response_text: Raw (fence-stripped) LLM response text.
        is_final_attempt: Whether this is the last retry attempt; major
            (truncation-indicating) repairs are only attempted then.

    Returns:
        What parsing and any repair made of the response text.
    """
    result: dict[str, Any] | None = None
    parse_error: Exception | None = None
    try:
        result = json.loads(response_text)
        if not isinstance(result, dict):
            parse_error = ValueError("Parsed JSON is not a dictionary")
            result = None
    except json.JSONDecodeError as e:
        parse_error = e
        result = None

    was_major_repair = False
    repaired = False
    if result is None:
        result, was_major_repair = attempt_json_repair(
            response_text, allow_major_repairs=is_final_attempt
        )
        repaired = result is not None

    return _ParsedResponse(result, was_major_repair, repaired, parse_error)


def _backfill_and_validate(
    result: dict[str, Any],
    json_schema: dict[str, Any],
    model_name: str,
) -> None:
    """Applies the provider-capability shim backfill, then validates.

    Args:
        result: Parsed JSON dict to validate (and possibly back-fill).
        json_schema: JSON schema dict (may have a nested "schema" key).
        model_name: Model name in litellm format, used to decide whether the
            json_object provider-capability shim applies.

    Raises:
        ValidationError: If ``result`` doesn't match ``json_schema``.
    """
    # Provider-capability shim: calls downgraded to json_object have no
    # server-side schema enforcement, so back-fill missing required fields
    # with empty defaults before validating. Keyed on the same condition as
    # the downgrade in call_llm.
    if not _supports_json_schema_response_format(model_name):
        _backfill_required_fields(
            result, json_schema.get("schema", json_schema)
        )
    validate_json_schema(result, json_schema)


def _json_validation_failure_outcome(
    error: ValidationError,
    response_text: str,
    ctx: _JsonRetryContext,
    attempt: _JsonAttempt,
    repaired: bool,
) -> _JsonAttemptOutcome:
    """Builds the attempt outcome for a schema validation failure.

    Args:
        error: The validation error raised for this attempt's result.
        response_text: The raw (fence-stripped) response text for this
            attempt.
        ctx: The retry-loop context, supplying the original prompt the next
            retry prompt is built from.
        attempt: Which attempt of the retry loop this is.
        repaired: Whether the result needed JSON repair before validation.

    Returns:
        An outcome carrying the error, plus a retry prompt with validation
        feedback appended unless this is the final attempt.
    """
    logger.warning(
        "Schema validation failed%s on attempt %s: %s",
        " after repair" if repaired else "",
        attempt.number,
        error.message,
    )
    next_prompt = None
    if not attempt.is_final:
        next_prompt = ctx.original_prompt + _validation_feedback(error)
    return _JsonAttemptOutcome(
        value=None,
        error=error,
        response_text=response_text,
        next_prompt=next_prompt,
    )


def _non_validating_repair_outcome(
    parsed: _ParsedResponse,
    attempt: _JsonAttempt,
    response_text: str,
) -> _JsonAttemptOutcome:
    """Builds the attempt outcome when no result was parsed at all.

    Args:
        parsed: The failed parse, carrying whether a major
            (truncation-oriented) repair was needed and its parse error.
        attempt: Which attempt of the retry loop this is.
        response_text: The raw (fence-stripped) response text for this
            attempt.

    Returns:
        An outcome with no error (to retry immediately) when a major repair
        still has attempts left, otherwise one carrying the parse error.
    """
    if parsed.was_major_repair and not attempt.is_final:
        logger.info(
            "Major repair needed (truncation detected), retrying immediately"
        )
        return _JsonAttemptOutcome(
            value=None,
            error=None,
            response_text=response_text,
            next_prompt=None,
        )

    last_error = parsed.parse_error or ValueError(
        "All repair strategies failed"
    )
    return _JsonAttemptOutcome(
        value=None,
        error=last_error,
        response_text=response_text,
        next_prompt=None,
    )


def _cache_validated_result(
    ctx: _JsonRetryContext, prompt: str, result: dict[str, Any]
) -> None:
    """Caches a schema-validated (or schema-less) attempt result.

    Args:
        ctx: The retry-loop context, supplying the cache and call spec.
        prompt: The prompt this attempt actually sent, which is what the
            entry is keyed on.
        result: The validated JSON dict to cache.
    """
    ctx.cache.set(
        LLMCacheRequest(
            prompt=prompt,
            model_name=ctx.spec.model_name,
            temperature=ctx.spec.temperature,
            max_tokens=ctx.spec.max_tokens,
            json_schema=ctx.spec.json_schema,
        ),
        result,
    )


def _finalize_validated_result(
    parsed: _ParsedResponse,
    response_text: str,
    prompt: str,
    ctx: _JsonRetryContext,
    attempt: _JsonAttempt,
) -> _JsonAttemptOutcome:
    """Validates a parsed result, caching it on success.

    Args:
        parsed: The successful parse, whose ``result`` is validated.
        response_text: The raw (fence-stripped) response text.
        prompt: The prompt this attempt sent, used as the cache key.
        ctx: The retry-loop context.
        attempt: Which attempt of the retry loop this is.

    Returns:
        A success outcome (already cached) when validation passes (or there
        is no schema to validate against), otherwise the failure outcome
        built by ``_json_validation_failure_outcome``.
    """
    result = parsed.result
    assert result is not None  # only called on a successful parse
    spec = ctx.spec
    try:
        if spec.json_schema is not None:
            _backfill_and_validate(result, spec.json_schema, spec.model_name)
    except ValidationError as e:
        return _json_validation_failure_outcome(
            e, response_text, ctx, attempt, parsed.repaired
        )
    _cache_validated_result(ctx, prompt, result)
    return _JsonAttemptOutcome(
        value=result, error=None, response_text=response_text, next_prompt=None
    )


async def _attempt_call_llm_json(
    prompt: str, ctx: _JsonRetryContext, attempt: _JsonAttempt
) -> _JsonAttemptOutcome:
    """Runs one call_llm_json attempt: call, parse/repair, validate, cache.

    ``prompt`` (possibly carrying validation feedback) is what gets sent and
    cached; ``ctx.original_prompt`` builds the next retry prompt on a schema
    failure. Does not raise on validation/parse failures -- callers should
    let genuine call failures (network, etc.) propagate.

    Args:
        prompt: The prompt to send on this attempt.
        ctx: The retry-loop context.
        attempt: Which attempt of the retry loop this is.

    Returns:
        The outcome telling the retry loop how to continue.
    """
    response_text = await ctx.call_for_json(prompt)

    # Parse response text as JSON, repairing if needed (minor repairs always
    # tried, major repairs only on the final attempt).
    parsed = _parse_or_repair_json(response_text, attempt.is_final)
    if parsed.result is not None:
        # Validate against the schema (when given), cache, and return.
        return _finalize_validated_result(
            parsed, response_text, prompt, ctx, attempt
        )
    return _non_validating_repair_outcome(parsed, attempt, response_text)


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
    logger.error("LLM call failed on attempt %s: %s", attempt.number, error)
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

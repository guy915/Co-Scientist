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

from co_scientist.cache import LLMCache, NullCache
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
) -> tuple[dict[str, Any] | None, bool, bool, Exception | None]:
    """Parses response text as JSON, falling back to repair strategies.

    Args:
        response_text: Raw (fence-stripped) LLM response text.
        is_final_attempt: Whether this is the last retry attempt; major
            (truncation-indicating) repairs are only attempted then.

    Returns:
        Tuple of (parsed result or None, was_major_repair, was_repaired,
        parse_error). ``parse_error`` is the original parse failure, used by
        the caller only when every repair attempt also fails.
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

    return result, was_major_repair, repaired, parse_error


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
    original_prompt: str,
    is_final_attempt: bool,
    attempt: int,
    repaired: bool,
) -> _JsonAttemptOutcome:
    """Builds the attempt outcome for a schema validation failure.

    Args:
        error: The validation error raised for this attempt's result.
        response_text: The raw (fence-stripped) response text for this
            attempt.
        original_prompt: The original prompt, without validation feedback,
            used to build the next retry prompt.
        is_final_attempt: Whether this is the last retry attempt.
        attempt: The 1-indexed attempt number, used for logging.
        repaired: Whether the result needed JSON repair before validation.

    Returns:
        An outcome carrying the error and, unless this is the final attempt,
        a retry prompt with validation feedback appended.
    """
    logger.warning(
        "Schema validation failed%s on attempt %s: %s",
        " after repair" if repaired else "",
        attempt,
        error.message,
    )

    next_prompt = None
    if not is_final_attempt:
        next_prompt = original_prompt + _validation_feedback(error)

    return _JsonAttemptOutcome(
        value=None,
        error=error,
        response_text=response_text,
        next_prompt=next_prompt,
    )


def _non_validating_repair_outcome(
    was_major_repair: bool,
    is_final_attempt: bool,
    response_text: str,
    parse_error: Exception | None,
) -> _JsonAttemptOutcome:
    """Builds the attempt outcome when no result was parsed at all.

    Args:
        was_major_repair: Whether the failed parse attempt still needed a
            major (truncation-oriented) repair.
        is_final_attempt: Whether this is the last retry attempt.
        response_text: The raw (fence-stripped) response text for this
            attempt.
        parse_error: The parse error from the final repair attempt, if any.

    Returns:
        An outcome with no error (to retry immediately) when a major repair
        still has attempts left, otherwise one carrying the parse error.
    """
    if was_major_repair and not is_final_attempt:
        logger.info(
            "Major repair needed (truncation detected), retrying immediately"
        )
        return _JsonAttemptOutcome(
            value=None,
            error=None,
            response_text=response_text,
            next_prompt=None,
        )

    last_error = parse_error or ValueError("All repair strategies failed")
    return _JsonAttemptOutcome(
        value=None,
        error=last_error,
        response_text=response_text,
        next_prompt=None,
    )


async def _attempt_call_llm_json(
    prompt: str,
    original_prompt: str,
    model_name: str,
    max_tokens: int,
    temperature: float,
    json_schema: dict[str, Any] | None,
    is_final_attempt: bool,
    attempt: int,
    cache: LLMCache | NullCache,
    call_for_json: Callable[[str], Awaitable[str]],
) -> _JsonAttemptOutcome:
    """Runs one call_llm_json attempt: call, parse/repair, validate, cache.

    Returns an outcome with ``value`` set on success (already cached), or
    ``error``/``response_text``/``next_prompt`` describing how to continue
    the retry loop otherwise. Does not raise on validation/parse failures —
    callers should let genuine call failures (network, etc.) propagate.

    Args:
        prompt: The prompt to send this attempt (may carry validation
            feedback from a previous attempt).
        original_prompt: The original prompt, without validation feedback,
            used to build the next retry prompt.
        model_name: Model name in litellm format.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        json_schema: Optional JSON schema to constrain the response format.
        is_final_attempt: Whether this is the last retry attempt.
        attempt: The 1-indexed attempt number, used for logging.
        cache: The cache to store a successful validated result in.
        call_for_json: Async callable making the raw LLM call for this
            attempt's prompt; returns the fence-stripped response text.

    Returns:
        The outcome of this attempt.
    """
    response_text = await call_for_json(prompt)

    # Steps 1-2: parse response text as JSON, repairing if needed
    # (minor repairs always tried, major repairs only on the final
    # attempt).
    result, was_major_repair, repaired, parse_error = _parse_or_repair_json(
        response_text, is_final_attempt
    )

    # Step 3: Validate against the schema (when given), cache, return
    if result is not None:
        try:
            if json_schema is not None:
                _backfill_and_validate(result, json_schema, model_name)
            cache.set(
                prompt,
                model_name,
                temperature,
                max_tokens,
                result,
                json_schema=json_schema,
            )
            return _JsonAttemptOutcome(
                value=result,
                error=None,
                response_text=response_text,
                next_prompt=None,
            )
        except ValidationError as e:
            return _json_validation_failure_outcome(
                e,
                response_text,
                original_prompt,
                is_final_attempt,
                attempt,
                repaired,
            )

    return _non_validating_repair_outcome(
        was_major_repair, is_final_attempt, response_text, parse_error
    )


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


async def _run_json_attempt(
    prompt: str,
    original_prompt: str,
    model_name: str,
    max_tokens: int,
    temperature: float,
    json_schema: dict[str, Any] | None,
    is_final_attempt: bool,
    attempt: int,
    cache: LLMCache | NullCache,
    call_for_json: Callable[[str], Awaitable[str]],
) -> _JsonAttemptOutcome:
    """Runs one call_llm_json attempt, converting a call failure to an outcome.

    A genuine call failure (network, provider error, etc.) is surfaced to the
    retry loop as an outcome carrying the error, except on the final attempt,
    where it is re-raised so the caller's exception propagates unchanged.

    Args:
        prompt: The prompt to send this attempt (may carry validation
            feedback from a previous attempt).
        original_prompt: The original prompt, without validation feedback,
            used to build the next retry prompt.
        model_name: Model name in litellm format.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        json_schema: Optional JSON schema to constrain the response format.
        is_final_attempt: Whether this is the last retry attempt.
        attempt: The 1-indexed attempt number, used for logging.
        cache: The cache to store a successful validated result in.
        call_for_json: Async callable making the raw LLM call for this
            attempt's prompt; returns the fence-stripped response text.

    Returns:
        The outcome of this attempt.

    Raises:
        Exception: The call failure, when this is the final attempt.
    """
    try:
        return await _attempt_call_llm_json(
            prompt,
            original_prompt,
            model_name,
            max_tokens,
            temperature,
            json_schema,
            is_final_attempt,
            attempt,
            cache,
            call_for_json,
        )
    except LLMTimeoutError:
        # Deliberately not retried. A provider that accepted the request and
        # then stopped answering will not answer the same request faster on
        # the next attempt, so retrying multiplies one stalled call by the
        # attempt count -- exactly the unbounded stall the ceiling exists to
        # prevent. Fail now and let the run surface the error.
        logger.error("LLM call timed out on attempt %s; not retrying", attempt)
        raise
    except Exception as e:
        logger.error("LLM call failed on attempt %s: %s", attempt, e)
        if is_final_attempt:
            raise
        if _is_rate_limited(e):
            # Unlike a schema failure -- where the next attempt carries
            # corrective feedback and should go out at once -- throttling is
            # answered by waiting. Retrying a throttled call immediately feeds
            # the burst that caused it.
            delay = _rate_limit_backoff_seconds(attempt)
            logger.warning(
                "Rate limited on attempt %s; waiting %.1fs before retrying",
                attempt,
                delay,
            )
            await asyncio.sleep(delay)
        return _JsonAttemptOutcome(
            value=None, error=e, response_text=None, next_prompt=None
        )

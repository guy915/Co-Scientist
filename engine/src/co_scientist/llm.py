"""LLM calling utilities using litellm.

Provides a clean interface for calling LLMs with proper error handling
and JSON parsing. The JSON extraction, repair, and validation helpers
live in ``co_scientist.llm_json``.
"""
# pylint: disable=inconsistent-quotes

import asyncio
from dataclasses import dataclass
import functools
import json
import logging
from typing import Any, NoReturn, cast
from collections.abc import Awaitable, Callable
import warnings

from jsonschema.exceptions import ValidationError
import litellm

from co_scientist import prompts
from co_scientist.cache import LLMCache, NullCache, get_cache
from co_scientist.llm_json import (
    _backfill_required_fields,
    _validation_feedback,
    attempt_json_repair,
    extract_response_json,
    get_fallback_response,
    validate_json_schema,
)

logger = logging.getLogger(__name__)


async def _save_prompt_if_named(
    prompt: str,
    run_id: str | None,
    prompt_name: str | None,
    prompt_metadata: dict[str, Any] | None,
) -> None:
    """Saves the filled-in prompt to disk when a prompt name is given.

    Unified save policy for every LLM call site: the prompt is saved
    whenever ``prompt_name`` is provided, under ``run_id or "unknown"``.
    Every write is still globally gated by the ``COSCIENTIST_SAVE_PROMPTS``
    env check inside ``prompts.save_prompt_to_disk`` (which also emits the
    canonical debug log for each saved prompt). The blocking file write runs
    in a worker thread so gathered LLM calls don't stall the event loop.

    ``save_prompt_to_disk`` is resolved through the ``prompts`` module at
    call time so tests can monkeypatch it there.

    Args:
        prompt: The filled-in prompt content to save.
        run_id: Optional run identifier; ``None`` falls back to "unknown".
        prompt_name: Optional debug-artifact name; ``None`` disables saving.
        prompt_metadata: Optional metadata appended to the saved file.
    """
    if prompt_name is None:
        return
    await asyncio.to_thread(
        prompts.save_prompt_to_disk,
        run_id=run_id or "unknown",
        prompt_name=prompt_name,
        content=prompt,
        metadata=prompt_metadata,
    )


# Suppress Pydantic serialization warnings from LiteLLM globally
# these occur when LiteLLM response objects (Pydantic models) are serialized
# and have mismatched field counts between streaming/non-streaming responses
warnings.filterwarnings("ignore",
                        message=r".*Pydantic serializer warnings.*",
                        category=UserWarning)


def _clamp_temperature(model_name: str, temperature: float) -> float:
    """Clamps temperature to model-specific minimums.

    Gemini 3 models require temperature >= 1.0 to avoid degraded performance.

    Args:
        model_name: LLM model identifier.
        temperature: Requested sampling temperature.

    Returns:
        The temperature to actually use for the call.
    """
    if "gemini-3" in model_name.lower() and temperature < 1.0:
        logger.debug(
            "clamping temperature %s -> 1.0 for gemini 3 model "
            "(gemini 3 requires temp >= 1.0 to avoid degraded performance)",
            temperature)
        return 1.0
    return temperature


# Provider-capability shim: some providers reject
# response_format={"type": "json_schema", ...} outright (DeepSeek returns an
# invalid-request error). For those models every schema'd call is downgraded,
# per call, to {"type": "json_object"} with the schema restated as prompt
# text, and missing required fields are back-filled with empty defaults
# before schema validation (json_object mode has no server-side schema
# enforcement, so nested required fields are routinely omitted). Models that
# support json_schema are untouched.
#
# Families listed here are checked BEFORE litellm's capability registry:
# litellm's cost map marks deepseek/* as supporting response schema, but the
# DeepSeek API only accepts json_object, so the registry alone cannot be
# trusted for these providers.
_JSON_OBJECT_ONLY_MODEL_FAMILIES: tuple[str, ...] = ("deepseek",)


@functools.lru_cache(maxsize=None)
def _supports_json_schema_response_format(model_name: str) -> bool:
    """Checks whether a model accepts the json_schema response format.

    The result is a process-static property of the model, so it is cached to
    avoid re-running litellm's registry lookup on every LLM call and retry.

    Args:
        model_name: Model name in litellm format.

    Returns:
        False when the model belongs to a known json_object-only family or
        when litellm's capability registry reports no json_schema support.
        True otherwise, including when the registry lookup itself raises, so
        the default json_schema path is preserved for unknown models.
    """
    lowered = model_name.lower()
    if any(family in lowered for family in _JSON_OBJECT_ONLY_MODEL_FAMILIES):
        return False
    try:
        return bool(litellm.supports_response_schema(model=model_name))
    except Exception:  # pylint: disable=broad-exception-caught
        return True


def _inject_schema_into_prompt(prompt: str, json_schema: dict[str, Any]) -> str:
    """Appends the JSON schema to the prompt for json_object-only models.

    Downgrading to the json_object response format loses the server-side
    schema constraint, so the schema is restated as prompt text to keep the
    model aware of the required structure.

    Args:
        prompt: The original user prompt.
        json_schema: JSON schema dict (may have a nested "schema" key).

    Returns:
        The prompt with the schema instruction block appended.
    """
    actual_schema = json_schema.get("schema", json_schema)
    schema_str = json.dumps(actual_schema, indent=2)
    return (prompt + "\n\n---\nRESPOND WITH VALID JSON ONLY. "
            "Your output MUST strictly match this JSON schema "
            "(all required fields must be present):\n" + schema_str)


def _apply_response_format(
    completion_args: dict[str, Any],
    prompt: str,
    model_name: str,
    force_json: bool,
    json_schema: dict[str, Any] | None,
) -> None:
    """Sets the response_format for a completion call, in place.

    When a schema is given, prefers the model's native json_schema response
    format; models that reject it fall back to the json_object
    provider-capability shim, which also rewrites "messages" to restate the
    schema as prompt text. Without a schema, force_json requests plain
    json_object mode.

    Args:
        completion_args: The in-progress completion kwargs dict; mutated in
            place with "response_format" and, for the shim, "messages".
        prompt: The original user prompt, used to rebuild "messages" when the
            json_object shim applies.
        model_name: Model name in litellm format.
        force_json: If True, try to force JSON mode when no schema is given.
        json_schema: Optional JSON schema to constrain the response format.
    """
    if json_schema:
        if _supports_json_schema_response_format(model_name):
            completion_args["response_format"] = {
                "type": "json_schema",
                "json_schema": json_schema,
            }
        else:
            # Provider-capability shim: this model rejects the
            # json_schema response format, so downgrade this call to
            # json_object and restate the schema in the prompt. The
            # cache keys above stay on the original prompt.
            logger.debug(
                "model %s does not support json_schema response format;"
                " downgrading to json_object with schema in prompt", model_name)
            completion_args["messages"] = [{
                "role": "user",
                "content": _inject_schema_into_prompt(prompt, json_schema),
            }]
            completion_args["response_format"] = {"type": "json_object"}
    elif force_json:
        completion_args["response_format"] = {"type": "json_object"}


def _build_completion_args(
    prompt: str,
    model_name: str,
    max_tokens: int,
    temperature: float,
    force_json: bool,
    json_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Builds the keyword arguments for a ``litellm.acompletion`` call.

    Args:
        prompt: The prompt to send to the LLM.
        model_name: Model name in litellm format.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        force_json: If True, try to force JSON mode (model support varies).
        json_schema: Optional JSON schema to constrain the response format.

    Returns:
        Keyword arguments ready to pass to ``litellm.acompletion``.
    """
    completion_args: dict[str, Any] = {
        "model": model_name,
        "messages": [{
            "role": "user",
            "content": prompt
        }],
        "max_tokens": max_tokens,
        "temperature": temperature,
        # Silently drop params a provider doesn't accept instead of
        # raising, since not every model/provider supports every arg.
        "drop_params": True,
    }

    _apply_response_format(completion_args, prompt, model_name, force_json,
                           json_schema)

    return completion_args


async def _prepare_llm_call(
    prompt: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    use_cache: bool,
    run_id: str | None,
    prompt_name: str | None,
    prompt_metadata: dict[str, Any] | None,
    **cache_key_kwargs: Any,
) -> tuple[float, "LLMCache | NullCache", dict[str, Any] | None]:
    """Runs the shared pre-call sequence for the public LLM entry points.

    Saves the prompt debug artifact (when named), clamps the temperature
    before the cache key is built so requested temperatures that execute
    identically share one cache entry, and performs the cache lookup. A
    cache miss is logged here; the hit log line differs per caller and is
    left to the call site.

    Args:
        prompt: The prompt about to be sent to the LLM.
        model_name: Model name in litellm format.
        temperature: Requested sampling temperature (clamped here).
        max_tokens: Maximum tokens in response.
        use_cache: When False, a NullCache is used so the call is fresh.
        run_id: Optional run identifier for the saved prompt's directory.
        prompt_name: Optional debug-artifact name for saving the prompt.
        prompt_metadata: Optional metadata appended to the saved prompt file.
        **cache_key_kwargs: Extra cache-key fields specific to the caller
            (e.g. ``json_schema=``, ``force_json=``, ``tools=``).

    Returns:
        A (clamped_temperature, cache, cached_response) tuple where
        cached_response is None on a cache miss.
    """
    await _save_prompt_if_named(prompt, run_id, prompt_name, prompt_metadata)

    temperature = _clamp_temperature(model_name, temperature)

    # NullCache when caching is bypassed for this call.
    cache: LLMCache | NullCache = get_cache() if use_cache else NullCache()
    cached_response = cache.get(prompt, model_name, temperature, max_tokens,
                                **cache_key_kwargs)
    if cached_response is None:
        logger.debug("cache miss for prompt: %s%s", prompt[:200],
                     '...' if len(prompt) > 200 else '')
    return temperature, cache, cached_response


def _extract_completion_content(response: Any, model_name: str) -> str:
    """Extracts and validates the text content of a completion response.

    Args:
        response: The raw response returned by ``litellm.acompletion``.
        model_name: Model name in litellm format, included in the error
            message when the response has no content.

    Returns:
        The non-empty response content.

    Raises:
        ValueError: If the response has no non-whitespace content.
    """
    content = response.choices[0].message.content

    if content is None or not content.strip():
        logger.error("LLM returned None or empty content. Response: %s",
                     response)
        raise ValueError(
            f"LLM returned None or empty content. Model: {model_name}")

    return cast(str, content)


async def call_llm(
    prompt: str,
    model_name: str,
    max_tokens: int = 4000,
    temperature: float = 0.7,
    force_json: bool = False,
    json_schema: dict[str, Any] | None = None,
    use_cache: bool = True,
    run_id: str | None = None,
    prompt_name: str | None = None,
    prompt_metadata: dict[str, Any] | None = None,
) -> str:
    """Call an LLM via litellm and return the response.

    Args:
        prompt: The prompt to send to the LLM
        model_name: Model name in litellm format
            (e.g., "gpt-4o-mini", "gemini/gemini-2.5-flash")
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature
        force_json: If True, try to force JSON mode (model support varies)
        json_schema: Optional JSON schema to constrain the response format
        use_cache: When False, bypass the LLM cache so the call is always fresh.
        run_id: Optional run identifier for the saved prompt's directory;
            ``None`` falls back to "unknown".
        prompt_name: Optional debug-artifact name. When provided, the prompt
            is saved to disk before the call — always, regardless of
            ``run_id`` (globally gated by ``COSCIENTIST_SAVE_PROMPTS``).
        prompt_metadata: Optional metadata appended to the saved prompt file.

    Returns:
        String response from the LLM

    Raises:
        Exception: If the LLM call fails
    """
    temperature, cache, cached_response = await _prepare_llm_call(
        prompt,
        model_name,
        temperature,
        max_tokens,
        use_cache,
        run_id,
        prompt_name,
        prompt_metadata,
        json_schema=json_schema,
        force_json=force_json)
    if cached_response is not None:
        logger.debug("using cached llm response")
        return cast(str, cached_response["text"])

    try:
        completion_args = _build_completion_args(prompt, model_name, max_tokens,
                                                 temperature, force_json,
                                                 json_schema)

        response = await litellm.acompletion(**completion_args)

        content = _extract_completion_content(response, model_name)

        # Cache the response (only reached if content is valid)
        cache.set(
            prompt,
            model_name,
            temperature,
            max_tokens,
            {"text": content},
            json_schema=json_schema,
            force_json=force_json,
        )

        return content

    except Exception as e:
        # call_llm never falls back or retries itself; it fails loud and
        # leaves that policy to its callers (call_llm_json's retry loop,
        # get_fallback_response for non-critical nodes). Nothing is cached
        # here, so a failed call is retried fresh next time, not replayed
        # from a broken cache entry.
        logger.error("LLM call failed: %s", e)
        logger.error("Model: %s, max_tokens: %s", model_name, max_tokens)
        raise


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
            response_text, allow_major_repairs=is_final_attempt)
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
        _backfill_required_fields(result,
                                  json_schema.get("schema", json_schema))
    validate_json_schema(result, json_schema)


def _log_first_json_error_position(text: str) -> None:
    """Logs the position of the first JSON parse error near the tail of text.

    Scans growing prefixes of ``text`` and reports the first parse error
    found once the prefix reaches within 200 chars of the end, since that is
    typically where LLM truncation breaks the JSON.

    Args:
        text: The raw response text to scan.
    """
    for i in range(0, len(text), 100):
        chunk = text[:i + 100]
        try:
            json.loads(chunk)
        except json.JSONDecodeError as e:
            if i > len(text) - 200:  # Near the end
                logger.error("JSON error near position %s: %s", e.pos, e.msg)
                logger.error("Context around error: ...%s...",
                             text[max(0, e.pos - 100):e.pos + 100])
                break


def _log_json_parse_failure_diagnostics(last_response_text: str) -> None:
    """Logs diagnostic detail about an unparseable LLM JSON response.

    Args:
        last_response_text: The last raw response text that failed to parse
            (after fence-stripping and repair attempts).
    """
    # Log the full response for debugging
    logger.error("Failed to parse JSON response after all repair attempts.")
    logger.error("Response length: %s chars", len(last_response_text))
    logger.error("First 500 chars: %s", last_response_text[:500])
    logger.error("Last 500 chars: %s", last_response_text[-500:])

    # Log middle section too (where errors often are)
    if len(last_response_text) > 1000:
        mid_point = len(last_response_text) // 2
        logger.error("Middle 500 chars (around char %s): %s", mid_point,
                     last_response_text[mid_point - 250:mid_point + 250])

    # Try to find where JSON is broken
    try:
        # Count braces
        open_braces = last_response_text.count("{")
        close_braces = last_response_text.count("}")
        logger.error("Brace count: { = %s, } = %s", open_braces, close_braces)
        _log_first_json_error_position(last_response_text)
    except Exception as debug_err:  # pylint: disable=broad-exception-caught
        logger.error("Error during debugging: %s", debug_err)


def _raise_validation_error(last_error: ValidationError,
                            max_attempts: int) -> NoReturn:
    """Re-raises a schema validation failure with an attempt-count message.

    Args:
        last_error: The schema validation failure to re-raise.
        max_attempts: Total number of attempts made.

    Raises:
        ValidationError: Always.
    """
    raise ValidationError(
        f"Schema validation failed after {max_attempts} attempts: "
        f"{last_error.message}",
        instance=last_error.instance,
        schema=last_error.schema,
        schema_path=last_error.schema_path,
        path=last_error.path,
    )


def _json_decode_error_pos(last_error: Exception | None) -> int:
    """Extracts a JSONDecodeError's character position, defaulting to 0.

    Args:
        last_error: The parse error to inspect, if any.

    Returns:
        ``last_error.pos`` when it is a ``json.JSONDecodeError``, else 0.
    """
    if isinstance(last_error, json.JSONDecodeError):
        return last_error.pos
    return 0


def _raise_json_decode_error(
    last_error: Exception | None,
    last_response_text: str | None,
    max_attempts: int,
) -> NoReturn:
    """Re-raises a parse failure with an attempt-count message.

    Args:
        last_error: The parse error to derive a position from, if any.
        last_response_text: The last raw response text, if any was received.
        max_attempts: Total number of attempts made.

    Raises:
        json.JSONDecodeError: Always.
    """
    raise json.JSONDecodeError(
        f"Could not parse LLM response as JSON after {max_attempts} attempts",
        last_response_text or "",
        _json_decode_error_pos(last_error),
    )


def _raise_json_parse_error(
    last_error: Exception | None,
    last_response_text: str | None,
    max_attempts: int,
) -> NoReturn:
    """Raises the final error after all JSON parse/repair retries fail.

    Args:
        last_error: The most recent validation or parse error, if any.
        last_response_text: The last raw response text, if any was received.
        max_attempts: Total number of attempts made.

    Raises:
        ValidationError: If ``last_error`` was a schema validation failure.
        json.JSONDecodeError: Otherwise (parse failure, or no error captured).
    """
    if isinstance(last_error, ValidationError):
        _raise_validation_error(last_error, max_attempts)
    _raise_json_decode_error(last_error, last_response_text, max_attempts)


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


async def _call_llm_for_json(
    prompt: str,
    model_name: str,
    max_tokens: int,
    temperature: float,
    json_schema: dict[str, Any] | None,
) -> str:
    """Makes the raw LLM call for one call_llm_json attempt.

    Caching is disabled on the inner call: call_llm_json keeps its own
    cache of the validated dict and returns from it before ever reaching
    this point, so a raw-text entry would only duplicate every cached
    payload on disk (and could replay an invalid response into the retry
    loop).

    Returns:
        The response text with any markdown code fences stripped.

    Raises:
        ValueError: If the LLM returns None or an empty response.
    """
    response_text = await call_llm(
        prompt,
        model_name,
        max_tokens,
        temperature,
        force_json=not json_schema,
        json_schema=json_schema,
        use_cache=False,
    )

    if not response_text:
        logger.error("LLM returned None or empty response")
        raise ValueError("LLM returned None or empty response. "
                         "Check API keys, rate limits, and model availability.")

    # Extract JSON from markdown code blocks if present.
    return extract_response_json(response_text)


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
    logger.warning("Schema validation failed%s on attempt"
                   " %s: %s", " after repair" if repaired else "", attempt,
                   error.message)

    next_prompt = None
    if not is_final_attempt:
        next_prompt = original_prompt + _validation_feedback(error)

    return _JsonAttemptOutcome(value=None,
                               error=error,
                               response_text=response_text,
                               next_prompt=next_prompt)


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
        logger.info("Major repair needed (truncation detected),"
                    " retrying immediately")
        return _JsonAttemptOutcome(value=None,
                                   error=None,
                                   response_text=response_text,
                                   next_prompt=None)

    last_error = parse_error or ValueError("All repair strategies failed")
    return _JsonAttemptOutcome(value=None,
                               error=last_error,
                               response_text=response_text,
                               next_prompt=None)


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

    Returns:
        The outcome of this attempt.
    """
    response_text = await _call_llm_for_json(prompt, model_name, max_tokens,
                                             temperature, json_schema)

    # Steps 1-2: parse response text as JSON, repairing if needed
    # (minor repairs always tried, major repairs only on the final
    # attempt).
    result, was_major_repair, repaired, parse_error = (_parse_or_repair_json(
        response_text, is_final_attempt))

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
            return _JsonAttemptOutcome(value=result,
                                       error=None,
                                       response_text=response_text,
                                       next_prompt=None)
        except ValidationError as e:
            return _json_validation_failure_outcome(e, response_text,
                                                    original_prompt,
                                                    is_final_attempt, attempt,
                                                    repaired)

    return _non_validating_repair_outcome(was_major_repair, is_final_attempt,
                                          response_text, parse_error)


def _handle_json_retries_exhausted(
    json_schema: dict[str, Any] | None,
    last_error: Exception | None,
    last_response_text: str | None,
    max_attempts: int,
) -> dict[str, Any]:
    """Resolves a call_llm_json run whose retries are all exhausted.

    Non-critical nodes (those with a registered fallback for their schema)
    degrade to fallback data; critical nodes get failure diagnostics logged
    and the most appropriate error raised.

    Returns:
        The fallback response, when one is registered for the schema.

    Raises:
        Exception: The parse/validation error via _raise_json_parse_error
            when no fallback exists.
    """
    # Check for fallback for non-critical nodes
    fallback = get_fallback_response(json_schema)
    if fallback is not None:
        logger.warning("Returning fallback data for non-critical node "
                       "after all retries exhausted")
        return fallback

    # No fallback available - raise appropriate error
    if last_response_text:
        _log_json_parse_failure_diagnostics(last_response_text)

    _raise_json_parse_error(last_error, last_response_text, max_attempts)


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

    Returns:
        The outcome of this attempt.

    Raises:
        Exception: The call failure, when this is the final attempt.
    """
    try:
        return await _attempt_call_llm_json(prompt, original_prompt, model_name,
                                            max_tokens, temperature,
                                            json_schema, is_final_attempt,
                                            attempt, cache)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("LLM call failed on attempt %s: %s", attempt, e)
        if is_final_attempt:
            raise
        return _JsonAttemptOutcome(value=None,
                                   error=e,
                                   response_text=None,
                                   next_prompt=None)


async def call_llm_json(
    prompt: str,
    model_name: str,
    max_tokens: int = 4000,
    temperature: float = 0.7,
    json_schema: dict[str, Any] | None = None,
    max_attempts: int = 5,
    use_cache: bool = True,
    run_id: str | None = None,
    prompt_name: str | None = None,
    prompt_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call LLM and parse response as JSON with validation and retry logic.

    Args:
        prompt: The prompt to send to the LLM
        model_name: Model name in litellm format
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature
        json_schema: Optional JSON schema to constrain the response format
        max_attempts: Maximum number of retry attempts (default 5)
        use_cache: When False, bypass the LLM cache so the call is always fresh
            (used for stochastic, diversity-critical generation).
        run_id: Optional run identifier for the saved prompt's directory;
            ``None`` falls back to "unknown".
        prompt_name: Optional debug-artifact name. When provided, the
            original prompt is saved to disk once, before the first attempt —
            always, regardless of ``run_id`` (globally gated by
            ``COSCIENTIST_SAVE_PROMPTS``). Retry prompts carrying validation
            feedback are not re-saved.
        prompt_metadata: Optional metadata appended to the saved prompt file.

    Returns:
        Parsed JSON response as a dictionary

    Raises:
        json.JSONDecodeError: If response is not valid JSON after all repair
        attempts (for critical nodes)
        ValidationError: If response doesn't match schema after all retries
            (for critical nodes)
        Exception: If the LLM call fails or returns empty response
    """
    temperature, cache, cached_response = await _prepare_llm_call(
        prompt,
        model_name,
        temperature,
        max_tokens,
        use_cache,
        run_id,
        prompt_name,
        prompt_metadata,
        json_schema=json_schema)
    if cached_response is not None:
        logger.debug("using cached llm json response")
        return cached_response

    last_error: Exception | None = None
    last_response_text: str | None = None
    original_prompt = prompt  # save original for retries with feedback

    for attempt in range(1, max_attempts + 1):
        is_final_attempt = attempt == max_attempts

        if attempt > 1:
            logger.debug("retrying llm call (attempt %s/%s)", attempt,
                         max_attempts)

        outcome = await _run_json_attempt(prompt, original_prompt, model_name,
                                          max_tokens, temperature, json_schema,
                                          is_final_attempt, attempt, cache)

        if outcome.value is not None:
            return outcome.value

        last_error = outcome.error
        prompt, last_response_text = _apply_json_attempt_outcome(
            outcome, prompt, last_response_text)

    return _handle_json_retries_exhausted(json_schema, last_error,
                                          last_response_text, max_attempts)


def _message_to_history_dict(message: Any) -> dict[str, Any]:
    """Converts a litellm assistant message into a plain history dict.

    litellm's message object is a Pydantic model, not a plain dict; this
    converts it so it can be cached and replayed as message history.

    Args:
        message: The assistant message from a litellm completion response.

    Returns:
        A plain dict representation, including tool_calls when present.
    """
    message_dict: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }

    # Add tool calls if present
    if hasattr(message, "tool_calls") and message.tool_calls:
        message_dict["tool_calls"] = [{
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments
            }
        } for tc in message.tool_calls]

    return message_dict


async def _execute_tool_calls(
    tool_calls: list[Any],
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Executes all requested tool calls concurrently.

    Args:
        tool_calls: The tool_calls list from the assistant message.
        tool_executor: Async callable that executes a single tool call and
            returns its tool response message.

    Returns:
        The tool response messages, in the same order as ``tool_calls``.
    """
    return await asyncio.gather(*[tool_executor(tc) for tc in tool_calls])


def _finalize_tool_call_response(message: Any, model_name: str) -> str:
    """Validates and returns the final (non-tool-call) assistant response.

    Args:
        message: The assistant message from the iteration where the LLM
            stopped requesting tool calls.
        model_name: Model name in litellm format, included in the error
            message when the response is empty.

    Returns:
        The final response text.

    Raises:
        ValueError: If the message has no non-whitespace content.
    """
    final_content = message.content if message.content else ""
    if not final_content.strip():
        logger.error("LLM returned empty final response in tool call loop")
        raise ValueError("LLM returned empty final response. "
                         f"Model: {model_name}")
    return final_content


async def _run_tool_call_iteration(
    messages: list[dict[str, Any]],
    model_name: str,
    tools: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
) -> tuple[bool, str | None]:
    """Runs one LLM-with-tools iteration; mutates `messages` in place.

    Args:
        messages: The running conversation history; appended to (and
            possibly extended with tool response messages) in place.
        model_name: Model name in litellm format.
        tools: List of tools in OpenAI format.
        max_tokens: Maximum tokens for this call.
        temperature: Sampling temperature.
        tool_executor: Async callable that executes tool calls and returns
            tool response messages.

    Returns:
        Tuple of (done, final_content). When done is True, final_content
        holds the finalized response text (already validated via
        _finalize_tool_call_response); when False, tool calls were
        dispatched and appended to `messages` and the caller should iterate
        again.
    """
    response = await litellm.acompletion(
        model=model_name,
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
        temperature=temperature,
        drop_params=True,
    )

    message = response.choices[0].message
    message_dict = _message_to_history_dict(message)
    messages.append(message_dict)

    # Check if LLM wants to call tools
    if hasattr(message, "tool_calls") and message.tool_calls:
        logger.debug("llm requested %s tool calls", len(message.tool_calls))

        # Execute all tool calls in parallel and add the results to
        # message history
        messages.extend(await _execute_tool_calls(message.tool_calls,
                                                  tool_executor))

        # Continue loop - LLM will see tool results and respond
        return False, None

    # No tool calls - this is the final response
    final_content = _finalize_tool_call_response(message, model_name)
    return True, final_content


def _cache_tool_call_result(
    cache: "LLMCache | NullCache",
    prompt: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    final_content: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> None:
    """Caches a successful tool-call loop result.

    Only called once the final content is validated, so a failed loop is
    retried fresh next time rather than replayed from a broken cache entry.
    """
    cache.set(
        prompt,
        model_name,
        temperature,
        max_tokens,
        {
            "final_response": final_content,
            "message_history": messages
        },
        tools=tools,
    )


async def call_llm_with_tools(
    prompt: str,
    model_name: str,
    tools: list[dict[str, Any]],
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
    max_tokens: int = 8000,
    temperature: float = 0.7,
    max_iterations: int = 10,
    use_cache: bool = True,
    run_id: str | None = None,
    prompt_name: str | None = None,
    prompt_metadata: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Call an LLM with tool access and handle tool execution loop.

    This function implements an agent loop where the LLM can call tools,
    see the results, and continue iterating until it produces a final response.

    Args:
        prompt: The initial user prompt
        model_name: Model name in litellm format
        tools: List of tools in OpenAI format
        tool_executor: Async callable that executes tool calls and returns
            tool response messages
        max_tokens: Maximum tokens per LLM call
        temperature: Sampling temperature
        max_iterations: Maximum number of LLM calls (prevents infinite loops)
        use_cache: When False, bypass the LLM cache so the call is always fresh
            (used for stochastic, diversity-critical generation).
        run_id: Optional run identifier for the saved prompt's directory;
            ``None`` falls back to "unknown".
        prompt_name: Optional debug-artifact name. When provided, the prompt
            is saved to disk before the call — always, regardless of
            ``run_id`` (globally gated by ``COSCIENTIST_SAVE_PROMPTS``).
        prompt_metadata: Optional metadata appended to the saved prompt file.

    Returns:
        Tuple of (final_response_text, complete_message_history)

    Raises:
        Exception: If the LLM call fails or max iterations reached
    """
    temperature, cache, cached_response = await _prepare_llm_call(
        prompt,
        model_name,
        temperature,
        max_tokens,
        use_cache,
        run_id,
        prompt_name,
        prompt_metadata,
        tools=tools)
    if cached_response is not None:
        logger.debug("using cached llm tool call response")
        return cached_response["final_response"], cached_response[
            "message_history"]

    # Running conversation history: grows with each assistant/tool turn and
    # is resent in full to acompletion on every iteration below.
    messages = [{"role": "user", "content": prompt}]

    for iteration in range(max_iterations):
        logger.debug("llm tool call iteration %s/%s", iteration + 1,
                     max_iterations)

        try:
            done, final_content = await _run_tool_call_iteration(
                messages, model_name, tools, max_tokens, temperature,
                tool_executor)
        except Exception as e:
            logger.error("Error in LLM tool call loop (iteration %s): %s",
                         iteration + 1, e)
            raise

        if done:
            # _run_tool_call_iteration only returns done=True alongside a
            # non-None final_content (see _finalize_tool_call_response).
            assert final_content is not None
            logger.debug("llm finished after %s iterations", iteration + 1)
            _cache_tool_call_result(cache, prompt, model_name, temperature,
                                    max_tokens, final_content, messages, tools)
            return final_content, messages

    # Max iterations reached
    logger.warning("Max iterations (%s) reached in tool call loop",
                   max_iterations)
    raise RuntimeError(
        f"LLM tool call loop exceeded max iterations ({max_iterations})")

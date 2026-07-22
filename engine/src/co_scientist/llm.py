"""LLM calling utilities using litellm.

Keeps the public entry points ``call_llm`` and ``call_llm_json``.
Supporting pieces live in the ``llm_request``, ``llm_json``,
``llm_json_retry``, ``llm_json_errors``, and ``llm_tool_loop`` sibling
modules — the latter also holds ``call_llm_with_tools`` and the shared
pre-call sequence ``_prepare_llm_call`` — and are re-exported here so
historical import paths keep working.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, cast

# Kept as a module attribute: tests patch the completion boundary via
# "co_scientist.llm.litellm.acompletion".
import litellm as litellm
from jsonschema.exceptions import ValidationError as ValidationError

from co_scientist import llm_request
from co_scientist import prompts as prompts
from co_scientist.cache import LLMCache as LLMCache
from co_scientist.cache import NullCache as NullCache
from co_scientist.cache import (
    cache_enabled_override as cache_enabled_override,
)

# get_cache is a pure re-export: the consumer (_prepare_llm_call) lives in
# llm_tool_loop, so stubbing the cache means patching get_cache there.
from co_scientist.cache import get_cache as get_cache
from co_scientist.constants import DEFAULT_MAX_TOKENS, HIGH_TEMPERATURE
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS as EXTENDED_MAX_TOKENS,
)
from co_scientist.llm_json import (
    _backfill_required_fields as _backfill_required_fields,
)
from co_scientist.llm_json import (
    _validation_feedback as _validation_feedback,
)
from co_scientist.llm_json import (
    attempt_json_repair as attempt_json_repair,
)
from co_scientist.llm_json import extract_response_json
from co_scientist.llm_json import (
    get_fallback_response as get_fallback_response,
)
from co_scientist.llm_json import (
    validate_json_schema as validate_json_schema,
)
from co_scientist.llm_json_errors import _handle_json_retries_exhausted
from co_scientist.llm_json_errors import (
    _json_decode_error_pos as _json_decode_error_pos,
)
from co_scientist.llm_json_errors import (
    _log_first_json_error_position as _log_first_json_error_position,
)
from co_scientist.llm_json_errors import (
    _log_json_parse_failure_diagnostics as _log_json_parse_failure_diagnostics,
)
from co_scientist.llm_json_errors import (
    _raise_json_decode_error as _raise_json_decode_error,
)
from co_scientist.llm_json_errors import (
    _raise_json_parse_error as _raise_json_parse_error,
)
from co_scientist.llm_json_errors import (
    _raise_validation_error as _raise_validation_error,
)
from co_scientist.llm_json_retry import (
    _apply_json_attempt_outcome,
    _JsonCallSpec,
    _run_json_attempt,
)
from co_scientist.llm_json_retry import (
    _attempt_call_llm_json as _attempt_call_llm_json,
)
from co_scientist.llm_json_retry import (
    _backfill_and_validate as _backfill_and_validate,
)
from co_scientist.llm_json_retry import (
    _json_validation_failure_outcome as _json_validation_failure_outcome,
)
from co_scientist.llm_json_retry import (
    _JsonAttemptOutcome as _JsonAttemptOutcome,
)
from co_scientist.llm_json_retry import (
    _non_validating_repair_outcome as _non_validating_repair_outcome,
)
from co_scientist.llm_json_retry import (
    _parse_or_repair_json as _parse_or_repair_json,
)
from co_scientist.llm_request import (
    _JSON_OBJECT_ONLY_MODEL_FAMILIES as _JSON_OBJECT_ONLY_MODEL_FAMILIES,
)
from co_scientist.llm_request import (
    _acompletion_within_timeout,
    _build_completion_args,
    _extract_completion_content,
)
from co_scientist.llm_request import (
    _apply_response_format as _apply_response_format,
)
from co_scientist.llm_request import (
    _clamp_temperature as _clamp_temperature,
)
from co_scientist.llm_request import (
    _inject_schema_into_prompt as _inject_schema_into_prompt,
)
from co_scientist.llm_request import (
    _save_prompt_if_named as _save_prompt_if_named,
)
from co_scientist.llm_tool_loop import (
    _cache_tool_call_result as _cache_tool_call_result,
)
from co_scientist.llm_tool_loop import (
    _execute_tool_calls as _execute_tool_calls,
)
from co_scientist.llm_tool_loop import (
    _finalize_tool_call_response as _finalize_tool_call_response,
)
from co_scientist.llm_tool_loop import (
    _message_to_history_dict as _message_to_history_dict,
)
from co_scientist.llm_tool_loop import (
    _prepare_llm_call,
    _PromptCallOptions,
)
from co_scientist.llm_tool_loop import (
    _run_tool_call_iteration as _run_tool_call_iteration,
)
from co_scientist.llm_tool_loop import (
    call_llm_with_tools as call_llm_with_tools,
)

logger = logging.getLogger(__name__)

# Re-exported by assignment: the alias re-export form exceeds 80 columns.
_supports_json_schema_response_format = (
    llm_request._supports_json_schema_response_format
)


async def _call_llm_and_cache(
    prompt: str,
    opts: _PromptCallOptions,
    force_json: bool,
    json_schema: dict[str, Any] | None,
    enable_thinking: bool,
    cache: "LLMCache | NullCache",
) -> str:
    """Runs the actual completion call for ``call_llm`` and caches it.

    ``opts.temperature`` is assumed already clamped. Returns the non-empty
    response content, having cached it (only reached once content is valid).
    """
    completion_args = _build_completion_args(
        prompt,
        opts.model_name,
        opts.max_tokens,
        opts.temperature,
        force_json,
        json_schema,
        enable_thinking=enable_thinking,
    )
    response = await _acompletion_within_timeout(
        completion_args, opts.model_name
    )
    content = _extract_completion_content(response, opts.model_name)
    cache.set(
        prompt,
        opts.model_name,
        opts.temperature,
        opts.max_tokens,
        {"text": content},
        json_schema=json_schema,
        force_json=force_json,
    )
    return content


async def call_llm(
    prompt: str,
    model_name: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = HIGH_TEMPERATURE,
    force_json: bool = False,
    json_schema: dict[str, Any] | None = None,
    use_cache: bool = True,
    run_id: str | None = None,
    prompt_name: str | None = None,
    prompt_metadata: dict[str, Any] | None = None,
    enable_thinking: bool = True,
) -> str:
    """Call an LLM via litellm and return the response."""
    opts = _PromptCallOptions(
        model_name,
        temperature,
        max_tokens,
        use_cache,
        run_id,
        prompt_name,
        prompt_metadata,
    )
    temperature, cache, cached_response = await _prepare_llm_call(
        prompt, opts, json_schema=json_schema, force_json=force_json
    )
    if cached_response is not None:
        logger.debug("using cached llm response")
        return cast(str, cached_response["text"])
    opts = replace(opts, temperature=temperature)
    # Never falls back/retries itself; nothing cached on failure.
    try:
        return await _call_llm_and_cache(
            prompt, opts, force_json, json_schema, enable_thinking, cache
        )
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        logger.error("Model: %s, max_tokens: %s", model_name, max_tokens)
        raise


async def _call_llm_for_json(
    prompt: str, spec: _JsonCallSpec, enable_thinking: bool = True
) -> str:
    """Makes the raw LLM call for one call_llm_json attempt.

    Caching is disabled on the inner call: call_llm_json keeps its own
    cache of the validated dict and returns from it before ever reaching
    this point, so a raw-text entry would only duplicate every cached
    payload on disk (and could replay an invalid response into the loop).

    Returns:
        The response text with any markdown code fences stripped.

    Raises:
        ValueError: If the LLM returns None or an empty response.
    """
    response_text = await call_llm(
        prompt,
        spec.model_name,
        spec.max_tokens,
        spec.temperature,
        force_json=not spec.json_schema,
        json_schema=spec.json_schema,
        use_cache=False,
        enable_thinking=enable_thinking,
    )
    if not response_text:
        logger.error("LLM returned None or empty response")
        raise ValueError(
            "LLM returned None or empty response. "
            "Check API keys, rate limits, and model availability."
        )

    # Extract JSON from markdown code blocks if present.
    return extract_response_json(response_text)


async def _run_call_llm_json_loop(
    prompt: str,
    original_prompt: str,
    spec: _JsonCallSpec,
    max_attempts: int,
    cache: "LLMCache | NullCache",
    call_for_json: Callable[[str], Awaitable[str]],
) -> dict[str, Any]:
    """Runs the ``call_llm_json`` retry loop over successive attempts.

    Returns the validated JSON dict from whichever attempt succeeds first, or
    ``_handle_json_retries_exhausted``'s result once every attempt fails.
    """
    last_error: Exception | None = None
    last_response_text: str | None = None
    for attempt in range(1, max_attempts + 1):
        is_final_attempt = attempt == max_attempts
        if attempt > 1:
            logger.debug(
                "retrying llm call (attempt %s/%s)", attempt, max_attempts
            )
        outcome = await _run_json_attempt(
            prompt,
            original_prompt,
            spec,
            is_final_attempt,
            attempt,
            cache,
            call_for_json,
        )
        if outcome.value is not None:
            return outcome.value
        last_error = outcome.error
        prompt, last_response_text = _apply_json_attempt_outcome(
            outcome, prompt, last_response_text
        )

    return _handle_json_retries_exhausted(
        spec.json_schema, last_error, last_response_text, max_attempts
    )


async def call_llm_json(
    prompt: str,
    model_name: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = HIGH_TEMPERATURE,
    json_schema: dict[str, Any] | None = None,
    max_attempts: int = 5,
    use_cache: bool = True,
    run_id: str | None = None,
    prompt_name: str | None = None,
    prompt_metadata: dict[str, Any] | None = None,
    enable_thinking: bool = True,
) -> dict[str, Any]:
    """Call LLM and parse JSON, with validation/retry logic."""
    opts = _PromptCallOptions(
        model_name,
        temperature,
        max_tokens,
        use_cache,
        run_id,
        prompt_name,
        prompt_metadata,
    )
    temperature, cache, cached_response = await _prepare_llm_call(
        prompt, opts, json_schema=json_schema
    )
    if cached_response is not None:
        logger.debug("using cached llm json response")
        return cached_response
    spec = _JsonCallSpec(model_name, max_tokens, temperature, json_schema)

    async def _call_for_json(attempt_prompt: str) -> str:
        """Raw LLM call (via call_llm) for one attempt's prompt."""
        return await _call_llm_for_json(
            attempt_prompt, spec, enable_thinking=enable_thinking
        )

    return await _run_call_llm_json_loop(
        prompt, prompt, spec, max_attempts, cache, _call_for_json
    )

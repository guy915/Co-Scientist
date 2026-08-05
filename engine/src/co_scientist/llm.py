"""LLM calling utilities using litellm.

Keeps the public entry points ``call_llm`` and ``call_llm_json``.
Supporting pieces live in the ``llm_request``, ``llm_json``,
``llm_json_retry``, ``llm_json_errors``, and ``llm_tool_loop`` sibling
modules — the latter also holds ``call_llm_with_tools`` and the shared
pre-call sequence ``_prepare_llm_call`` — and are re-exported here so
historical import paths keep working.
"""

import logging
from typing import Any, cast

# Kept as a module attribute: tests patch the completion boundary via
# "co_scientist.llm.litellm.acompletion".
import litellm as litellm
from jsonschema.exceptions import ValidationError as ValidationError

from co_scientist import llm_request
from co_scientist import prompts as prompts
from co_scientist.cache import LLMCache as LLMCache
from co_scientist.cache import LLMCacheRequest
from co_scientist.cache import NullCache as NullCache
from co_scientist.cache import (
    cache_enabled_override as cache_enabled_override,
)

# get_cache is a pure re-export: the consumer (_prepare_llm_call) lives in
# llm_tool_loop, so stubbing the cache means patching get_cache there.
from co_scientist.cache import get_cache as get_cache
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
    _JsonAttempt,
    _JsonCallSpec,
    _JsonRetryContext,
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
    CompletionShape,
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
    ToolLoop as ToolLoop,
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
from co_scientist.llm_tool_loop import _prepare_llm_call
from co_scientist.llm_tool_loop import (
    _run_tool_call_iteration as _run_tool_call_iteration,
)
from co_scientist.llm_tool_loop import (
    call_llm_with_tools as call_llm_with_tools,
)
from co_scientist.llm_types import CompletionSpec as CompletionSpec
from co_scientist.llm_types import LLMCallOptions as LLMCallOptions
from co_scientist.llm_types import (
    indexed_prompt_name as indexed_prompt_name,
)

logger = logging.getLogger(__name__)

# Re-exported by assignment: the alias re-export form exceeds 80 columns.
_supports_json_schema_response_format = (
    llm_request._supports_json_schema_response_format
)


async def _call_llm_and_cache(
    request: LLMCacheRequest,
    enable_thinking: bool,
    cache: "LLMCache | NullCache",
) -> str:
    """Runs the actual completion call for ``call_llm`` and caches it.

    ``request.temperature`` is assumed already clamped.

    Args:
        request: The request to send, and the key its response is cached
            under.
        enable_thinking: Whether DeepSeek thinking mode is requested.
        cache: The cache tier resolved for this call.

    Returns:
        The non-empty response content, having cached it (only reached once
        content is valid).
    """
    completion_args = _build_completion_args(
        request.prompt,
        request.model_name,
        request.max_tokens,
        request.temperature,
        CompletionShape(
            force_json=bool(request.force_json),
            json_schema=request.json_schema,
            enable_thinking=enable_thinking,
        ),
    )
    response = await _acompletion_within_timeout(
        completion_args, request.model_name
    )
    content = _extract_completion_content(response, request.model_name)
    cache.set(request, {"text": content})
    return content


async def call_llm(
    prompt: str,
    spec: CompletionSpec,
    options: LLMCallOptions | None = None,
) -> str:
    """Call an LLM via litellm and return the response.

    Args:
        prompt: The rendered prompt to send.
        spec: Which model to call and how to sample/shape the output.
        options: Cache, telemetry, and thinking behavior; defaults to
            ``LLMCallOptions()``.
    """
    opt = options if options is not None else LLMCallOptions()
    request = LLMCacheRequest(
        prompt=prompt,
        model_name=spec.model_name,
        temperature=spec.temperature,
        max_tokens=spec.max_tokens,
        json_schema=spec.json_schema,
        force_json=spec.force_json,
    )
    request, cache, cached_response = await _prepare_llm_call(request, opt)
    if cached_response is not None:
        logger.debug("using cached llm response")
        return cast(str, cached_response["text"])
    # Never falls back/retries itself; nothing cached on failure.
    try:
        return await _call_llm_and_cache(request, opt.enable_thinking, cache)
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        logger.error(
            "Model: %s, max_tokens: %s", spec.model_name, spec.max_tokens
        )
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
        CompletionSpec(
            model_name=spec.model_name,
            max_tokens=spec.max_tokens,
            temperature=spec.temperature,
            json_schema=spec.json_schema,
            force_json=not spec.json_schema,
        ),
        LLMCallOptions(use_cache=False, enable_thinking=enable_thinking),
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
    prompt: str, ctx: _JsonRetryContext, max_attempts: int
) -> dict[str, Any]:
    """Runs the ``call_llm_json`` retry loop over successive attempts.

    Args:
        prompt: The prompt for the first attempt; later attempts may carry
            validation feedback appended to ``ctx.original_prompt``.
        ctx: The retry-loop context shared by every attempt.
        max_attempts: How many attempts the loop makes before giving up.

    Returns:
        The validated JSON dict from whichever attempt succeeds first, or
        ``_handle_json_retries_exhausted``'s result once every attempt fails.
    """
    last_error: Exception | None = None
    last_response_text: str | None = None
    for number in range(1, max_attempts + 1):
        if number > 1:
            logger.debug(
                "retrying llm call (attempt %s/%s)", number, max_attempts
            )
        outcome = await _run_json_attempt(
            prompt, ctx, _JsonAttempt(number, number == max_attempts)
        )
        if outcome.value is not None:
            return outcome.value
        last_error = outcome.error
        prompt, last_response_text = _apply_json_attempt_outcome(
            outcome, prompt, last_response_text
        )

    return _handle_json_retries_exhausted(
        ctx.spec.json_schema, last_error, last_response_text, max_attempts
    )


async def call_llm_json(
    prompt: str,
    spec: CompletionSpec,
    max_attempts: int = 5,
    options: LLMCallOptions | None = None,
) -> dict[str, Any]:
    """Call LLM and parse JSON, with validation/retry logic.

    Args:
        prompt: The rendered prompt for the first attempt.
        spec: Which model to call and how to sample/shape the output;
            ``force_json`` is ignored because JSON is always parsed.
        max_attempts: How many attempts before giving up.
        options: Cache, telemetry, and thinking behavior; defaults to
            ``LLMCallOptions()``.
    """
    opt = options if options is not None else LLMCallOptions()
    request = LLMCacheRequest(
        prompt=prompt,
        model_name=spec.model_name,
        temperature=spec.temperature,
        max_tokens=spec.max_tokens,
        json_schema=spec.json_schema,
    )
    request, cache, cached_response = await _prepare_llm_call(request, opt)
    if cached_response is not None:
        logger.debug("using cached llm json response")
        return cached_response
    json_spec = _JsonCallSpec(
        spec.model_name, spec.max_tokens, request.temperature, spec.json_schema
    )

    async def _call_for_json(attempt_prompt: str) -> str:
        """Raw LLM call (via call_llm) for one attempt's prompt."""
        return await _call_llm_for_json(
            attempt_prompt, json_spec, enable_thinking=opt.enable_thinking
        )

    ctx = _JsonRetryContext(prompt, json_spec, cache, _call_for_json)
    return await _run_call_llm_json_loop(prompt, ctx, max_attempts)

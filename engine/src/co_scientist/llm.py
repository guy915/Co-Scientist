"""LLM calling utilities using litellm.

Keeps the public entry points (``call_llm``, ``call_llm_json``,
``call_llm_with_tools``) and the shared pre-call sequence. Supporting
pieces live in the ``llm_request``, ``llm_json``, ``llm_json_retry``,
``llm_json_errors``, and ``llm_tool_loop`` sibling modules and are
re-exported here so historical import paths keep working.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

import litellm
from jsonschema.exceptions import ValidationError as ValidationError

from co_scientist import llm_request
from co_scientist import prompts as prompts
from co_scientist.cache import LLMCache, NullCache, get_cache
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
    _apply_response_format as _apply_response_format,
)
from co_scientist.llm_request import (
    _build_completion_args,
    _clamp_temperature,
    _extract_completion_content,
    _save_prompt_if_named,
)
from co_scientist.llm_request import (
    _inject_schema_into_prompt as _inject_schema_into_prompt,
)
from co_scientist.llm_tool_loop import (
    _cache_tool_call_result,
    _run_tool_call_iteration,
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

logger = logging.getLogger(__name__)

# Re-exported by assignment: the alias re-export form exceeds 80 columns.
_supports_json_schema_response_format = (
    llm_request._supports_json_schema_response_format
)


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
    cache miss is logged here; the hit log line is left to the call site.

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
    cached_response = cache.get(
        prompt, model_name, temperature, max_tokens, **cache_key_kwargs
    )
    if cached_response is None:
        logger.debug(
            "cache miss for prompt: %s%s",
            prompt[:200],
            "..." if len(prompt) > 200 else "",
        )
    return temperature, cache, cached_response


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
        force_json=force_json,
    )
    if cached_response is not None:
        logger.debug("using cached llm response")
        return cast(str, cached_response["text"])

    try:
        completion_args = _build_completion_args(
            prompt, model_name, max_tokens, temperature, force_json, json_schema
        )

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
    payload on disk (and could replay an invalid response into the loop).

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
        raise ValueError(
            "LLM returned None or empty response. "
            "Check API keys, rate limits, and model availability."
        )

    # Extract JSON from markdown code blocks if present.
    return extract_response_json(response_text)


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
        json_schema=json_schema,
    )
    if cached_response is not None:
        logger.debug("using cached llm json response")
        return cached_response

    async def _call_for_json(attempt_prompt: str) -> str:
        """Makes the raw LLM call (via call_llm) for one attempt's prompt."""
        return await _call_llm_for_json(
            attempt_prompt, model_name, max_tokens, temperature, json_schema
        )

    last_error: Exception | None = None
    last_response_text: str | None = None
    original_prompt = prompt  # save original for retries with feedback

    for attempt in range(1, max_attempts + 1):
        is_final_attempt = attempt == max_attempts

        if attempt > 1:
            logger.debug(
                "retrying llm call (attempt %s/%s)", attempt, max_attempts
            )

        outcome = await _run_json_attempt(
            prompt,
            original_prompt,
            model_name,
            max_tokens,
            temperature,
            json_schema,
            is_final_attempt,
            attempt,
            cache,
            _call_for_json,
        )

        if outcome.value is not None:
            return outcome.value

        last_error = outcome.error
        prompt, last_response_text = _apply_json_attempt_outcome(
            outcome, prompt, last_response_text
        )

    return _handle_json_retries_exhausted(
        json_schema, last_error, last_response_text, max_attempts
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
        tools=tools,
    )
    if cached_response is not None:
        logger.debug("using cached llm tool call response")
        return cached_response["final_response"], cached_response[
            "message_history"
        ]

    # Running conversation history: grows with each assistant/tool turn and
    # is resent in full to acompletion on every iteration below.
    messages = [{"role": "user", "content": prompt}]

    for iteration in range(max_iterations):
        logger.debug(
            "llm tool call iteration %s/%s", iteration + 1, max_iterations
        )

        try:
            done, final_content = await _run_tool_call_iteration(
                messages,
                model_name,
                tools,
                max_tokens,
                temperature,
                tool_executor,
            )
        except Exception as e:
            logger.error(
                "Error in LLM tool call loop (iteration %s): %s",
                iteration + 1,
                e,
            )
            raise

        if done:
            # _run_tool_call_iteration only returns done=True alongside a
            # non-None final_content (see _finalize_tool_call_response).
            assert final_content is not None
            logger.debug("llm finished after %s iterations", iteration + 1)
            _cache_tool_call_result(
                cache,
                prompt,
                model_name,
                temperature,
                max_tokens,
                final_content,
                messages,
                tools,
            )
            return final_content, messages

    # Max iterations reached
    logger.warning(
        "Max iterations (%s) reached in tool call loop", max_iterations
    )
    raise RuntimeError(
        f"LLM tool call loop exceeded max iterations ({max_iterations})"
    )

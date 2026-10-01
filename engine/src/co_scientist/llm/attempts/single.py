"""The raw one-attempt completion primitive shared by both entry points.

``_call_llm_single_attempt`` is
what a single completion attempt actually does -- no retry, no escalation --
and both public entry points are built on it: ``call_llm``'s own retry loop
runs it once per escalation rung, and ``call_llm_json``'s per-attempt raw
call (``_call_llm_for_json``) runs it once per JSON attempt. Sharing it is
what keeps "what one attempt does" from drifting between the two callers.
"""

import logging
from typing import cast

from co_scientist.cache import LLMCache, LLMCacheRequest, NullCache
from co_scientist.llm.admission.credentials import (
    current_api_key,
    scoped_api_key,
)
from co_scientist.llm.attempts.failure import _report_call_llm_failure
from co_scientist.llm.precall import _prepare_llm_call
from co_scientist.llm.request.completion import (
    CompletionShape,
    _acompletion_within_timeout,
    _apply_api_key,
    _build_completion_args,
)
from co_scientist.llm.request.response import _extract_completion_content
from co_scientist.llm.values import CompletionSpec, LLMCallOptions

logger = logging.getLogger(__name__)


async def _call_llm_and_cache(
    request: LLMCacheRequest,
    enable_thinking: bool,
    cache: "LLMCache | NullCache",
) -> str:
    """Runs the actual completion call for one attempt and caches it.

    ``request.temperature`` is assumed already clamped.

    The credential is read from ``llm.admission.credentials.current_api_key`` at
    call time rather than passed in: ``request`` is deliberately
    credential-free (it is the cache key), and the caller already scoped
    the effective key -- an explicit ``CompletionSpec.api_key`` or the
    run's scoped key -- into the current task's context.

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
    _apply_api_key(completion_args, current_api_key())
    response = await _acompletion_within_timeout(
        completion_args, request.model_name
    )
    content = _extract_completion_content(response, request.model_name)
    cache.set(request, {"text": content})
    return content


async def _call_llm_single_attempt(
    prompt: str,
    spec: CompletionSpec,
    opt: LLMCallOptions,
) -> str:
    """Makes exactly one completion attempt: no retry, no escalation.

    Args:
        prompt: The rendered prompt to send.
        spec: Which model to call and how to sample/shape the output.
        opt: Cache, telemetry, and thinking behavior for this one attempt.

    Returns:
        The non-empty response content.
    """
    # An explicit spec key temporarily overrides any run-scoped key for
    # exactly this call; the completion args read the effective key back
    # from the context (see _call_llm_and_cache).
    with scoped_api_key(spec.api_key):
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
            return await _call_llm_and_cache(
                request, opt.enable_thinking, cache
            )
        except Exception as e:
            _report_call_llm_failure(spec, opt, e)
            raise

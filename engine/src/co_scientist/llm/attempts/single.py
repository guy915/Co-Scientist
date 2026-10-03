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
from co_scientist.exceptions import short_error_text
from co_scientist.llm.admission.credentials import (
    current_api_key,
    scoped_api_key,
)
from co_scientist.llm.precall import _prepare_llm_call
from co_scientist.llm.request.completion import (
    CompletionShape,
    _acompletion_within_timeout,
    _apply_api_key,
    _build_completion_args,
)
from co_scientist.llm.request.response import _extract_completion_content
from co_scientist.llm.request.thinking import (
    annotate_failure_context,
    effective_max_tokens,
)
from co_scientist.llm.values import CompletionSpec, LLMCallOptions

logger = logging.getLogger(__name__)


# Keep the persisted failure logger stable for the Logs panel filter.
_failure_logger = logging.getLogger("co_scientist.llm")


def _failure_call_site(spec: CompletionSpec, opt: LLMCallOptions) -> str | None:
    """Names the call for a failure record, as specifically as it can.

    ``prompt_name`` is the better label where a node sets one -- it is
    already per-hypothesis or per-matchup, so it distinguishes items within
    a fan-out wave. The schema name is the fallback because every
    structured call has one, and it still identifies the prompt family,
    which is what separates the ten call sites sharing a budget constant.

    Args:
        spec: The spec the failed call was made with.
        opt: The options it was made with.

    Returns:
        A short label, or ``None`` for an unnamed free-text call.
    """
    if opt.prompt_name:
        return opt.prompt_name
    schema_name = (spec.json_schema or {}).get("name")
    return schema_name if isinstance(schema_name, str) else None


def _report_call_llm_failure(
    spec: CompletionSpec,
    opt: LLMCallOptions,
    error: Exception,
) -> None:
    """Annotates a failed call's context, and logs it if nobody above will.

    The annotation is unconditional: it records which call failed and the
    budget the request actually carried, so whichever layer ends up writing
    the record reports what went out. The thinking floor raises the budget
    before the request leaves, and printing the pre-floor number beside a
    reasoning-token count that exceeds it made a budget failure read as a
    provider one.

    The log is conditional (``opt.log_failures``), because the raw call this
    guards is not the layer that knows whether a retry follows. Both
    ``call_llm_json`` and ``call_llm`` run this raw call once per attempt
    under the one attempt loop (``llm.attempts.retry``), which says
    everything this warning would, plus the attempt number and whether the
    ladder gave up -- so both turn this off and log once per attempt in
    that loop (``llm.attempts.retry._log_failure``)
    instead of once here per raw call on top of that. As a result nothing
    in this codebase sets ``log_failures=True`` today, and the warning here
    fires only for a caller of the raw single-attempt primitive
    (``llm.attempts.single._call_llm_single_attempt``) that opts back into it
    directly.

    Warning, not error, for the same reason: a single recovered answerless
    completion put four ERROR rows in the diagnostics panel, and eight of
    one export's ten errors were this.

    Args:
        spec: The spec the failed call was made with.
        opt: The options it was made with; carries the thinking flag that
            decides the floor, and whether to log here at all.
        error: The failure being reported.
    """
    annotate_failure_context(
        error,
        spec.model_name,
        spec.max_tokens,
        opt.enable_thinking,
        _failure_call_site(spec, opt),
    )
    if not opt.log_failures:
        return
    _failure_logger.warning(
        "LLM call failed (model %s, max_tokens %s, call site asked for %s): %s",
        spec.model_name,
        effective_max_tokens(
            spec.model_name, spec.max_tokens, opt.enable_thinking
        ),
        spec.max_tokens,
        short_error_text(error),
    )


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

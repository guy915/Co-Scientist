"""The pre-call sequence every public LLM entry point runs.

Saves the prompt debug artifact (when named), clamps the temperature before
the cache key is built, and performs the cache lookup. ``call_llm`` and
``call_llm_json`` (through ``attempts.single`` and ``call``) and
``call_llm_with_tools`` (``tools.loop``) all start here, which is why it sits
below all three. Note for tests: caching is stubbed by patching ``get_cache``
on *this* module, which is where the lookup reads it.
"""

import logging
from dataclasses import replace
from typing import Any

from co_scientist.cache import (
    LLMCache,
    LLMCacheRequest,
    NullCache,
    cache_enabled_override,
    get_cache,
)
from co_scientist.llm.admission.free_policy import campaign_free_mode
from co_scientist.llm.request.completion import (
    _clamp_temperature,
    _save_prompt_if_named,
)
from co_scientist.llm.telemetry import record_cache_result
from co_scientist.llm.values import LLMCallOptions

logger = logging.getLogger(__name__)


def _resolve_cache(use_cache: bool) -> "LLMCache | NullCache":
    """Resolves the cache to use for a call, honoring the disable overrides.

    Campaign mode also bypasses cached completions so every evaluation
    request reaches current-price admission.

    NullCache when this call opted out, or the current task's generator was
    constructed with enable_cache=False (see cache.scoped_cache_override) --
    scoped to this task rather than the process-wide get_cache() singleton,
    so it never disables caching for any other concurrently-running
    generator.
    """
    cache_active = (
        use_cache
        and cache_enabled_override() is not False
        and not campaign_free_mode()
    )
    return get_cache() if cache_active else NullCache()


def _log_cache_lookup(
    prompt: str, cached_response: dict[str, Any] | None
) -> None:
    """Logs a cache miss for a lookup; a hit is logged by the call site."""
    if cached_response is None:
        logger.debug(
            "cache miss for prompt: %s%s",
            prompt[:200],
            "..." if len(prompt) > 200 else "",
        )


async def _prepare_llm_call(
    request: LLMCacheRequest, opts: LLMCallOptions
) -> tuple[LLMCacheRequest, "LLMCache | NullCache", dict[str, Any] | None]:
    """Runs the shared pre-call sequence for the public LLM entry points.

    Saves the prompt debug artifact (when named), clamps the temperature
    before the cache key is built so requested temperatures that execute
    identically share one cache entry, and performs the cache lookup.

    Args:
        request: The request as the caller asked for it; its response-shape
            fields (``json_schema``/``force_json``/``tools``) are what make
            the cache key caller-specific.
        opts: Cache and debug-artifact options for this call.

    Returns:
        A (clamped_request, cache, cached_response) tuple where the request
        carries the clamped temperature the call must actually use, and
        cached_response is None on a cache miss.
    """
    await _save_prompt_if_named(
        request.prompt, opts.run_id, opts.prompt_name, opts.prompt_metadata
    )

    request = replace(
        request,
        temperature=_clamp_temperature(request.model_name, request.temperature),
    )

    cache = _resolve_cache(opts.use_cache)
    cached_response = cache.get(request)
    _log_cache_lookup(request.prompt, cached_response)
    # Only a genuinely active cache is worth a hit/miss telemetry record.
    # ``call_llm_json``'s retry loop deliberately calls back into
    # ``call_llm`` with ``use_cache=False`` for every attempt (see that
    # module's docstring): a NullCache lookup there always "misses" by
    # construction, and counting it would double-count one logical request
    # as two cache attempts for no informative reason.
    if isinstance(cache, LLMCache):
        record_cache_result(request.model_name, hit=cached_response is not None)
    return request, cache, cached_response

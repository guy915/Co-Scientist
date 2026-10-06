"""Clamp temperature before cache lookup so equivalent requests share keys."""

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
)
from co_scientist.llm.telemetry import record_cache_result
from co_scientist.llm.values import LLMCallOptions

logger = logging.getLogger(__name__)


def _resolve_cache(use_cache: bool) -> "LLMCache | NullCache":
    """Campaigns bypass cached completions to reach current-price admission.
    Cache opt-outs stay task-local rather than altering concurrent
    generators.
    """
    cache_active = use_cache and cache_enabled_override() is not False and not campaign_free_mode()
    return get_cache() if cache_active else NullCache()


def _log_cache_lookup(prompt: str, cached_response: dict[str, Any] | None) -> None:
    if cached_response is None:
        logger.debug(
            "cache miss for prompt: %s%s",
            prompt[:200],
            "..." if len(prompt) > 200 else "",
        )


async def _prepare_llm_call(
    request: LLMCacheRequest, opts: LLMCallOptions
) -> tuple[LLMCacheRequest, "LLMCache | NullCache", dict[str, Any] | None]:
    request = replace(
        request,
        temperature=_clamp_temperature(request.model_name, request.temperature),
    )

    cache = _resolve_cache(opts.use_cache)
    cached_response = cache.get(request)
    _log_cache_lookup(request.prompt, cached_response)
    # NullCache retries are not logical cache misses; recording them double-
    # counts the request.
    if isinstance(cache, LLMCache):
        record_cache_result(request.model_name, hit=cached_response is not None)
    return request, cache, cached_response

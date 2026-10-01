"""Simple file-based cache for LLM responses.

This cache dramatically speeds up development and testing by avoiding
redundant LLM calls for identical requests.

The implementation is split across sibling modules by responsibility:
shared file-storage primitives (``cache_storage``), the LLM response cache
tier (``cache_llm``), and the whole-node output cache tier
(``cache_nodes``). This module hosts the process-wide singletons and their
accessors, and re-exports every name historically importable from
``co_scientist.cache``.
"""

import contextlib
import logging
import os
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from co_scientist.cache_llm import (
    LLMCache,
    LLMCacheRequest,
    NullCache,
)
from co_scientist.cache_nodes import NodeCache
from co_scientist.cache_storage import _cache_dir_stats as _cache_dir_stats
from co_scientist.cache_storage import (
    _clear_cache_files as _clear_cache_files,
)
from co_scientist.cache_storage import _hash_key as _hash_key
from co_scientist.cache_storage import (
    _read_llm_cache_entry as _read_llm_cache_entry,
)
from co_scientist.cache_storage import (
    _read_node_cache_entry as _read_node_cache_entry,
)
from co_scientist.cache_storage import (
    _write_cache_file_atomically as _write_cache_file_atomically,
)
from co_scientist.cache_storage import (
    _write_node_cache_file_atomically as _write_node_cache_file_atomically,
)
from co_scientist.config.env_vars import parse_timeout_env
from co_scientist.config.registry import parse_bool_env
from co_scientist.constants import DEFAULT_CACHE_DIR, DEFAULT_CACHE_ENABLED
from co_scientist.constants.cache import DEFAULT_CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)

__all__ = [
    "LLMCache",
    "LLMCacheRequest",
    "NodeCache",
    "NullCache",
    "cache_enabled_override",
    "clear_cache",
    "clear_node_cache",
    "get_cache",
    "get_cache_stats",
    "get_node_cache",
    "get_node_cache_stats",
    "scoped_cache_override",
]


def _resolve_cache_env() -> tuple[bool, str, float | None]:
    """Read the cache enabled flag, directory, and TTL from the environment.

    Each accessor calls this once, on the first call in the process, before it
    memoizes its singleton: whichever caller (a caller that has deliberately
    exported COSCIENTIST_CACHE_ENABLED/_DIR/_TTL_SECONDS into its own
    process, e.g. an ops deployment) runs first "wins" that setting for the
    rest of the process; later os.environ edits are ignored. A single
    generator's per-instance ``enable_cache`` preference does not take this
    path -- see ``scoped_cache_override`` for how that is scoped instead.

    Returns:
        A ``(cache_enabled, cache_dir, ttl_seconds)`` triple.
    """
    cache_enabled_str = os.getenv(
        "COSCIENTIST_CACHE_ENABLED", str(DEFAULT_CACHE_ENABLED).lower()
    )
    cache_dir = os.getenv("COSCIENTIST_CACHE_DIR", DEFAULT_CACHE_DIR)
    ttl_seconds = parse_timeout_env(
        "COSCIENTIST_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS
    )
    return parse_bool_env(cache_enabled_str), cache_dir, ttl_seconds


# Per-task override for whether the *current* asyncio task should treat
# caching as disabled, regardless of the process-wide default above. This
# is how HypothesisGenerator(enable_cache=False) takes effect (see
# generator/core.py): a context variable rather than an env-var mutation, so
# it never touches the memoized global singleton or any other
# concurrently-running generator's calls. asyncio.create_task/gather copy
# the active context at creation time, so this also reaches any child task
# spawned during the scoped generator's own execution (e.g. parallel
# review/debate calls within one run).
_cache_enabled_override: ContextVar[bool | None] = ContextVar(
    "cache_enabled_override", default=None
)


def cache_enabled_override() -> bool | None:
    """Return the current task's cache-enabled override, if one is scoped.

    Returns:
        ``True``/``False`` when a ``scoped_cache_override`` context is
        active, else ``None`` (defer to the process default in
        ``get_cache()``).
    """
    return _cache_enabled_override.get()


@contextlib.contextmanager
def scoped_cache_override(enable_cache: bool | None) -> Iterator[None]:
    """Scope a cache-enabled preference to the current asyncio task.

    Args:
        enable_cache: ``False`` forces every cache lookup made within this
            context to miss (see ``llm._prepare_llm_call``), ``True`` defers
            to the process default (per-instance force-enable is not
            supported -- see the module docstring), and ``None`` is a no-op
            so callers can pass a generator's optional constructor argument
            straight through.

    Yields:
        None.
    """
    if enable_cache is None:
        yield
        return
    token = _cache_enabled_override.set(enable_cache)
    try:
        yield
    finally:
        _cache_enabled_override.reset(token)


# Global cache instance (can be configured via environment variable)
_global_cache: LLMCache | None = None


def get_cache() -> LLMCache:
    """Get or create the global cache instance."""
    global _global_cache

    if _global_cache is None:
        cache_enabled, cache_dir, ttl_seconds = _resolve_cache_env()
        _global_cache = LLMCache(
            cache_dir=cache_dir,
            enabled=cache_enabled,
            ttl_seconds=ttl_seconds,
        )

        if cache_enabled:
            logger.info("LLM caching enabled (dir: %s)", cache_dir)
        else:
            logger.info("LLM caching disabled")

    return _global_cache


def clear_cache() -> int:
    """Clear the global cache."""
    return get_cache().clear()


def get_cache_stats() -> dict[str, Any]:
    """Get global cache statistics."""
    return get_cache().get_stats()


# Global node cache instance
_global_node_cache: NodeCache | None = None


def get_node_cache() -> NodeCache:
    """Get or create the global node cache instance."""
    global _global_node_cache

    if _global_node_cache is None:
        cache_enabled, cache_dir, ttl_seconds = _resolve_cache_env()
        _global_node_cache = NodeCache(
            cache_dir=cache_dir,
            enabled=cache_enabled,
            ttl_seconds=ttl_seconds,
        )

        if cache_enabled:
            logger.info("Node caching enabled (dir: %s/nodes)", cache_dir)
        else:
            logger.info("Node caching disabled")

    return _global_node_cache


def clear_node_cache() -> int:
    """Clear the global node cache."""
    return get_node_cache().clear()


def get_node_cache_stats() -> dict[str, Any]:
    """Get global node cache statistics."""
    return get_node_cache().get_stats()

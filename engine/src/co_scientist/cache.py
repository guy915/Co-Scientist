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

import logging
import os
from typing import Any

from co_scientist.cache_llm import LLMCache, NullCache
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
from co_scientist.config.registry import parse_bool_env
from co_scientist.constants import DEFAULT_CACHE_DIR, DEFAULT_CACHE_ENABLED

logger = logging.getLogger(__name__)

__all__ = [
    "LLMCache",
    "NodeCache",
    "NullCache",
    "clear_cache",
    "clear_node_cache",
    "get_cache",
    "get_cache_stats",
    "get_node_cache",
    "get_node_cache_stats",
]


def _resolve_cache_env() -> tuple[bool, str]:
    """Read the cache enabled flag and directory from the environment.

    Each accessor calls this once, on the first call in the process, before it
    memoizes its singleton: HypothesisGenerator must set
    COSCIENTIST_CACHE_ENABLED/_DIR (see its __init__) before the first LLM
    call; later os.environ edits are ignored.

    Returns:
        A ``(cache_enabled, cache_dir)`` pair.
    """
    cache_enabled_str = os.getenv(
        "COSCIENTIST_CACHE_ENABLED", str(DEFAULT_CACHE_ENABLED).lower()
    )
    cache_dir = os.getenv("COSCIENTIST_CACHE_DIR", DEFAULT_CACHE_DIR)
    return parse_bool_env(cache_enabled_str), cache_dir


# Global cache instance (can be configured via environment variable)
_global_cache: LLMCache | None = None


def get_cache() -> LLMCache:
    """Get or create the global cache instance."""
    global _global_cache

    if _global_cache is None:
        cache_enabled, cache_dir = _resolve_cache_env()
        _global_cache = LLMCache(cache_dir=cache_dir, enabled=cache_enabled)

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
        cache_enabled, cache_dir = _resolve_cache_env()
        _global_node_cache = NodeCache(
            cache_dir=cache_dir, enabled=cache_enabled
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

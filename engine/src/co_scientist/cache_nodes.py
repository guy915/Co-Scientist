"""File-based cache tier for whole node outputs.

Defines ``NodeCache``, which pickles the full output of heavy workflow
nodes (e.g., literature review) into a ``nodes`` subdirectory of the cache
so repeated runs with identical inputs skip the redundant work.
"""

import logging
from pathlib import Path
from typing import Any

from co_scientist.cache_storage import (
    _cache_dir_stats,
    _clear_cache_files,
    _evict_stale_entry,
    _hash_key,
    _is_cache_entry_stale,
    _read_node_cache_entry,
    _write_node_cache_file_atomically,
)
from co_scientist.constants import DEFAULT_CACHE_DIR
from co_scientist.constants_cache import DEFAULT_CACHE_TTL_SECONDS
from co_scientist.llm_credentials import current_api_key
from co_scientist.llm_free_policy import campaign_free_mode

logger = logging.getLogger(__name__)


class NodeCache:
    """Cache for entire node outputs (e.g., literature review).

    This caches the full output of heavy nodes to avoid redundant
    work when the same inputs are provided again.

    Controlled by the same COSCIENTIST_CACHE_ENABLED flag as LLM caching.
    """

    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        enabled: bool = True,
        ttl_seconds: float | None = DEFAULT_CACHE_TTL_SECONDS,
    ):
        """Initialize the node cache.

        Args:
            cache_dir: Base directory to store cache files
            enabled: Whether caching is enabled
            ttl_seconds: Age after which an entry is treated as a miss, or
                None to disable expiry.
        """
        self.cache_dir = Path(cache_dir) / "nodes"
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds

        if self.enabled:
            self.cache_dir.mkdir(exist_ok=True, parents=True)
            logger.debug("node cache initialized at %s", self.cache_dir)

    def _generate_cache_key(self, node_name: str, **key_params: Any) -> str:
        """Generate a unique cache key for the node with given parameters.

        Args:
            node_name: Name of the node (e.g., "literature_review")
            **key_params: Parameters that affect the node output (e.g.,
            research_goal)

        Returns:
            SHA256 hash of the node name and parameters
        """
        key_data = {"node": node_name, **key_params}
        return _hash_key(key_data)

    def get(
        self, node_name: str, force: bool = False, **key_params: Any
    ) -> dict[str, Any] | None:
        """Get cached node output if available.

        Args:
            node_name: Name of the node
            force: If True, check cache even if globally disabled
                (for dev/testing)
            **key_params: Parameters to match (e.g., research_goal="...")

        Returns:
            Cached node output dict or None if not found
        """
        # Shared node outputs have neither credential nor experiment provenance.
        if campaign_free_mode() or current_api_key():
            return None

        if not self.enabled and not force:
            return None

        cache_key = self._generate_cache_key(node_name, **key_params)
        cache_file = self.cache_dir / f"{cache_key}.pkl"

        if not cache_file.exists():
            logger.debug(
                "node cache MISS for %s (key %s...)", node_name, cache_key[:8]
            )
            return None

        # force bypasses expiry too: it exists to make a dev/test entry
        # always trusted regardless of the ambient cache settings.
        if not force and _is_cache_entry_stale(cache_file, self.ttl_seconds):
            logger.debug(
                "node cache EXPIRED (ttl) for %s (key %s...)",
                node_name,
                cache_key[:8],
            )
            _evict_stale_entry(cache_file)
            return None

        return _read_node_cache_entry(cache_file, node_name, cache_key)

    def set(
        self,
        node_name: str,
        output: dict[str, Any],
        force: bool = False,
        **key_params: Any,
    ) -> None:
        """Store node output in cache.

        Args:
            node_name: Name of the node
            output: The node output dictionary to cache
            force: If True, cache even if globally disabled (for dev/testing)
            **key_params: Parameters that affect the output
                (e.g., research_goal="...")
        """
        if campaign_free_mode() or current_api_key():
            return

        if not self.enabled and not force:
            return

        # Ensure cache dir exists if forcing (may not exist if globally
        # disabled)
        if force and not self.cache_dir.exists():
            self.cache_dir.mkdir(exist_ok=True, parents=True)

        cache_key = self._generate_cache_key(node_name, **key_params)
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        _write_node_cache_file_atomically(
            cache_file, node_name, cache_key, output
        )

    def clear(self) -> int:
        """Clear all cached node outputs.

        Returns:
            Number of cache files deleted
        """
        return _clear_cache_files(
            self.cache_dir, self.enabled, "*.pkl", "cached node outputs"
        )

    def get_stats(self) -> dict[str, Any]:
        """Get node cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        return _cache_dir_stats(self.cache_dir, self.enabled, "*.pkl")

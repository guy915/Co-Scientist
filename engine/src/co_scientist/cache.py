"""Simple file-based cache for LLM responses.

This cache dramatically speeds up development and testing by avoiding
redundant LLM calls for identical requests.
"""

import hashlib
import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any

from co_scientist.config.registry import parse_bool_env
from co_scientist.constants import (
    DEFAULT_CACHE_DIR,
    DEFAULT_CACHE_ENABLED,
    truncate,
)

logger = logging.getLogger(__name__)


def _hash_key(key_data: dict[str, Any]) -> str:
    """Return the SHA256 hex digest of a canonical-JSON key payload."""
    key_string = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(key_string.encode()).hexdigest()


# Shared by LLMCache.clear() and NodeCache.clear() so the glob-and-delete
# logic is not duplicated across the two cache tiers.
def _clear_cache_files(cache_dir: Path, enabled: bool, pattern: str,
                       label: str) -> int:
    """Delete every cache file matching pattern; return the count deleted."""
    if not enabled or not cache_dir.exists():
        return 0

    count = 0
    for cache_file in cache_dir.glob(pattern):
        cache_file.unlink()
        count += 1

    logger.info("Cleared %s %s", count, label)
    return count


# Shared by LLMCache.get_stats() and NodeCache.get_stats(); each caller
# supplies its own directory and glob pattern (".json" vs ".pkl").
def _cache_dir_stats(cache_dir: Path, enabled: bool,
                     pattern: str) -> dict[str, Any]:
    """Summarize a cache directory's file count and total size in MB."""
    if not enabled or not cache_dir.exists():
        return {"enabled": False, "cache_files": 0, "total_size_mb": 0.0}

    cache_files = list(cache_dir.glob(pattern))
    total_size = sum(f.stat().st_size for f in cache_files)

    return {
        "enabled": True,
        "cache_files": len(cache_files),
        "total_size_mb": total_size / (1024 * 1024),
        "cache_dir": str(cache_dir),
    }


def _read_llm_cache_entry(cache_file: Path,
                          cache_key: str) -> dict[str, Any] | None:
    """Read a single cached LLM response, self-healing on corruption.

    Args:
        cache_file: Path to the ``.json`` cache entry to read.
        cache_key: The entry's cache key, used only for log messages.

    Returns:
        The cached response dict on a clean read, otherwise None.
    """
    try:
        # Use atomic read: if file is being written, this will either
        # read the old complete file or fail gracefully
        with open(cache_file, encoding="utf-8") as f:
            cached_data = json.load(f)
        logger.debug("cache HIT for key %s...", cache_key[:8])
        response: dict[str, Any] = cached_data["response"]
        return response
    except (json.JSONDecodeError, KeyError, OSError) as e:
        # Handle race conditions: file might be partially written or locked
        logger.debug(
            "cache read failed for %s... (may be concurrent write): %s",
            cache_key[:8], e)
        # Don't remove file on IOError - it might just be locked by another
        # process
        if isinstance(e, (json.JSONDecodeError, KeyError)):
            # Only remove on actual corruption, not on I/O errors
            try:
                cache_file.unlink()
            except OSError:
                pass  # File might have been removed by another process
        return None


def _write_cache_file_atomically(cache_file: Path, cache_key: str,
                                 cache_data: dict[str, Any]) -> None:
    """Write cache_data to cache_file via a temp-file-then-rename swap.

    Args:
        cache_file: Destination path for the cache entry.
        cache_key: The entry's cache key, used only for log messages.
        cache_data: JSON-serializable payload to write.
    """
    # Use atomic write: write to temp file, then rename (atomic on most
    # filesystems) This prevents race conditions when multiple processes
    # write the same cache file
    temp_file = cache_file.with_suffix(".tmp")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        # Atomic rename - if this fails, temp file will be cleaned up on
        # next access
        temp_file.replace(cache_file)
        logger.debug("cached response for key %s...", cache_key[:8])
    except OSError as e:
        # If rename fails (e.g., file locked), remove temp file and continue
        try:
            temp_file.unlink()
        except OSError:
            pass
        logger.debug("cache write conflict for %s... (concurrent write): %s",
                     cache_key[:8], e)


class LLMCache:
    """Simple file-based cache for LLM responses."""

    def __init__(self,
                 cache_dir: str = DEFAULT_CACHE_DIR,
                 enabled: bool = DEFAULT_CACHE_ENABLED):
        """Initialize the LLM cache.

        Args:
            cache_dir: Directory to store cache files
            enabled: Whether caching is enabled
        """
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled

        # Directory is only created when caching is enabled, so a disabled
        # cache leaves no stray directory on disk.
        if self.enabled:
            self.cache_dir.mkdir(exist_ok=True, parents=True)
            logger.debug("LLM cache initialized at %s", self.cache_dir)

    def _generate_cache_key(
        self,
        prompt: str,
        model_name: str,
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
        json_schema: dict[str, Any] | None = None,
        force_json: bool | None = None,
    ) -> str:
        """Generate a unique cache key for the request.

        Args:
            prompt: The prompt text
            model_name: Model name
            temperature: Temperature parameter
            max_tokens: Max tokens parameter
            tools: Optional list of tool definitions (for tool-calling LLMs)
            json_schema: Optional JSON schema for structured output
            force_json: Optional flag to force JSON output

        Returns:
            SHA256 hash of the request parameters
        """
        # Create deterministic string representation
        key_data = {
            "prompt": prompt,
            "model": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Folding tools/json_schema/force_json into the key means a call that
        # differs only in response-format shape gets its own cache entry, so
        # a JSON-schema call can never be served a cached freeform response
        # (or vice versa) for the same prompt/model/temperature/max_tokens.
        # Add optional parameters if provided
        if tools is not None:
            key_data["tools"] = json.dumps(tools, sort_keys=True)
        if json_schema is not None:
            key_data["json_schema"] = json.dumps(json_schema, sort_keys=True)
        if force_json is not None:
            key_data["force_json"] = force_json

        return _hash_key(key_data)

    def get(
        self,
        prompt: str,
        model_name: str,
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
        json_schema: dict[str, Any] | None = None,
        force_json: bool | None = None,
    ) -> dict[str, Any] | None:
        """Get cached response if available.

        Args:
            prompt: The prompt text
            model_name: Model name
            temperature: Temperature parameter
            max_tokens: Max tokens parameter
            tools: Optional list of tool definitions (for tool-calling LLMs)
            json_schema: Optional JSON schema for structured output
            force_json: Optional flag to force JSON output

        Returns:
            Cached response dict or None if not found
        """
        if not self.enabled:
            return None

        cache_key = self._generate_cache_key(prompt, model_name, temperature,
                                             max_tokens, tools, json_schema,
                                             force_json)
        cache_file = self.cache_dir / f"{cache_key}.json"

        if cache_file.exists():
            return _read_llm_cache_entry(cache_file, cache_key)

        logger.debug("cache MISS for key %s...", cache_key[:8])
        return None

    def set(
        self,
        prompt: str,
        model_name: str,
        temperature: float,
        max_tokens: int,
        response: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
        json_schema: dict[str, Any] | None = None,
        force_json: bool | None = None,
    ) -> None:
        """Store response in cache.

        Args:
            prompt: The prompt text
            model_name: Model name
            temperature: Temperature parameter
            max_tokens: Max tokens parameter
            response: The LLM response to cache
            tools: Optional list of tool definitions (for tool-calling LLMs)
            json_schema: Optional JSON schema for structured output
            force_json: Optional flag to force JSON output
        """
        if not self.enabled:
            return

        cache_key = self._generate_cache_key(prompt, model_name, temperature,
                                             max_tokens, tools, json_schema,
                                             force_json)
        cache_file = self.cache_dir / f"{cache_key}.json"

        try:
            cache_data = {
                "request": {
                    "model": model_name,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "prompt_preview": truncate(prompt),
                },
                "response": response,
            }
            _write_cache_file_atomically(cache_file, cache_key, cache_data)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to cache response: %s", e)

    def clear(self) -> int:
        """Clear all cached responses.

        Returns:
            Number of cache files deleted
        """
        return _clear_cache_files(self.cache_dir, self.enabled, "*.json",
                                  "cached responses")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        return _cache_dir_stats(self.cache_dir, self.enabled, "*.json")


class NullCache:
    """A no-op cache: never returns a hit and never stores.

    Used to force a fresh LLM call regardless of the global cache state. This
    matters for stochastic, diversity-critical calls (hypothesis generation):
    caching them would freeze the sampled output, so a warm cache returns the
    same hypothesis on every call -- which the deduplicate reducer then
    collapses to one. Bypassing the cache keeps generation diverse regardless
    of cache state, while caching stays on for deterministic nodes.
    """

    def get(self, *_args: Any, **_kwargs: Any) -> dict[str, Any] | None:
        """Always report a cache miss, regardless of the arguments given."""
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        """No-op: never persists a response."""
        return None


# Global cache instance (can be configured via environment variable)
_global_cache: LLMCache | None = None


def get_cache() -> LLMCache:
    """Get or create the global cache instance."""
    global _global_cache

    if _global_cache is None:
        # First call in the process wins: the env vars are read once and the
        # resulting LLMCache is memoized below, so HypothesisGenerator must
        # set COSCIENTIST_CACHE_ENABLED/_DIR (see its __init__) before the
        # first LLM call in the process; later os.environ edits are ignored.
        # Check environment variable for cache configuration
        cache_enabled_str = os.getenv("COSCIENTIST_CACHE_ENABLED",
                                      str(DEFAULT_CACHE_ENABLED).lower())
        cache_enabled = parse_bool_env(cache_enabled_str)
        cache_dir = os.getenv("COSCIENTIST_CACHE_DIR", DEFAULT_CACHE_DIR)

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


def _read_node_cache_entry(cache_file: Path, node_name: str,
                           cache_key: str) -> dict[str, Any] | None:
    """Read a single cached node output, self-healing on corruption.

    Args:
        cache_file: Path to the ``.pkl`` cache entry to read.
        node_name: Name of the node the entry belongs to, for log messages.
        cache_key: The entry's cache key, used only for log messages.

    Returns:
        The cached node output dict on a clean read, otherwise None.
    """
    try:
        with open(cache_file, "rb") as f:
            cached_data: dict[str, Any] = pickle.load(f)
        logger.debug("node cache HIT for %s (key %s...)", node_name,
                     cache_key[:8])
        return cached_data
    except (pickle.PickleError, OSError) as e:
        logger.debug("node cache read failed for %s...: %s", cache_key[:8], e)
        try:
            cache_file.unlink()
        except OSError:
            pass  # File might have been removed by another process
        return None


def _write_node_cache_file_atomically(cache_file: Path, node_name: str,
                                      cache_key: str,
                                      output: dict[str, Any]) -> None:
    """Write output to cache_file via a temp-file-then-rename swap.

    Args:
        cache_file: Destination path for the cache entry.
        node_name: Name of the node the entry belongs to, for log messages.
        cache_key: The entry's cache key, used only for log messages.
        output: The node output dictionary to pickle.
    """
    try:
        temp_file = cache_file.with_suffix(".tmp")
        with open(temp_file, "wb") as f:
            pickle.dump(output, f)
        temp_file.replace(cache_file)
        logger.debug("cached node output for %s (key %s...)", node_name,
                     cache_key[:8])
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to cache node output for %s: %s", node_name, e)


class NodeCache:
    """Cache for entire node outputs (e.g., literature review).

    This caches the full output of heavy nodes to avoid redundant
    work when the same inputs are provided again.

    Controlled by the same COSCIENTIST_CACHE_ENABLED flag as LLM caching.
    """

    def __init__(self,
                 cache_dir: str = DEFAULT_CACHE_DIR,
                 enabled: bool = True):
        """Initialize the node cache.

        Args:
            cache_dir: Base directory to store cache files
            enabled: Whether caching is enabled
        """
        self.cache_dir = Path(cache_dir) / "nodes"
        self.enabled = enabled

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

    def get(self,
            node_name: str,
            force: bool = False,
            **key_params: Any) -> dict[str, Any] | None:
        """Get cached node output if available.

        Args:
            node_name: Name of the node
            force: If True, check cache even if globally disabled
                (for dev/testing)
            **key_params: Parameters to match (e.g., research_goal="...")

        Returns:
            Cached node output dict or None if not found
        """
        if not self.enabled and not force:
            return None

        cache_key = self._generate_cache_key(node_name, **key_params)
        cache_file = self.cache_dir / f"{cache_key}.pkl"

        if cache_file.exists():
            return _read_node_cache_entry(cache_file, node_name, cache_key)

        logger.debug("node cache MISS for %s (key %s...)", node_name,
                     cache_key[:8])
        return None

    def set(self,
            node_name: str,
            output: dict[str, Any],
            force: bool = False,
            **key_params: Any) -> None:
        """Store node output in cache.

        Args:
            node_name: Name of the node
            output: The node output dictionary to cache
            force: If True, cache even if globally disabled (for dev/testing)
            **key_params: Parameters that affect the output
                (e.g., research_goal="...")
        """
        if not self.enabled and not force:
            return

        # Ensure cache dir exists if forcing (may not exist if globally
        # disabled)
        if force and not self.cache_dir.exists():
            self.cache_dir.mkdir(exist_ok=True, parents=True)

        cache_key = self._generate_cache_key(node_name, **key_params)
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        _write_node_cache_file_atomically(cache_file, node_name, cache_key,
                                          output)

    def clear(self) -> int:
        """Clear all cached node outputs.

        Returns:
            Number of cache files deleted
        """
        return _clear_cache_files(self.cache_dir, self.enabled, "*.pkl",
                                  "cached node outputs")

    def get_stats(self) -> dict[str, Any]:
        """Get node cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        return _cache_dir_stats(self.cache_dir, self.enabled, "*.pkl")


# Global node cache instance
_global_node_cache: NodeCache | None = None


def get_node_cache() -> NodeCache:
    """Get or create the global node cache instance."""
    global _global_node_cache

    if _global_node_cache is None:
        # Same one-shot env-var-read-then-memoize pattern as get_cache().
        # Reuse same cache enabled flag as LLM cache
        cache_enabled_str = os.getenv("COSCIENTIST_CACHE_ENABLED",
                                      str(DEFAULT_CACHE_ENABLED).lower())
        cache_enabled = parse_bool_env(cache_enabled_str)
        cache_dir = os.getenv("COSCIENTIST_CACHE_DIR", DEFAULT_CACHE_DIR)

        _global_node_cache = NodeCache(cache_dir=cache_dir,
                                       enabled=cache_enabled)

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

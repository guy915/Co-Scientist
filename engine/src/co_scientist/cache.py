"""Simple file-based cache for LLM responses.

This cache dramatically speeds up development and testing by avoiding
redundant LLM calls for identical requests.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import pickle

from co_scientist.constants import DEFAULT_CACHE_DIR, DEFAULT_CACHE_ENABLED

logger = logging.getLogger(__name__)


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

        # Add optional parameters if provided
        if tools is not None:
            key_data["tools"] = json.dumps(tools, sort_keys=True)
        if json_schema is not None:
            key_data["json_schema"] = json.dumps(json_schema, sort_keys=True)
        if force_json is not None:
            key_data["force_json"] = force_json

        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_string.encode()).hexdigest()

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
            try:
                # Use atomic read: if file is being written, this will either
                # read the old complete file or fail gracefully
                with open(cache_file, encoding="utf-8") as f:
                    cached_data = json.load(f)
                logger.debug("cache HIT for key %s...", cache_key[:8])
                response: dict[str, Any] = cached_data["response"]
                return response
            except (json.JSONDecodeError, KeyError, OSError) as e:
                # Handle race conditions: file might be partially written or
                # locked
                logger.debug(
                    "cache read failed for %s... (may be concurrent write): %s",
                    cache_key[:8], e)
                # Don't remove file on IOError - it might just be locked by
                # another process
                if isinstance(e, (json.JSONDecodeError, KeyError)):
                    # Only remove on actual corruption, not on I/O errors
                    try:
                        cache_file.unlink()
                    except OSError:
                        pass  # File might have been removed by another process
                return None

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
                    "model":
                        model_name,
                    "temperature":
                        temperature,
                    "max_tokens":
                        max_tokens,
                    "prompt_preview":
                        prompt[:200] + "..." if len(prompt) > 200 else prompt,
                },
                "response": response,
            }

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
                # If rename fails (e.g., file locked), remove temp file and
                # continue
                try:
                    temp_file.unlink()
                except OSError:
                    pass
                logger.debug(
                    "cache write conflict for %s... (concurrent write): %s",
                    cache_key[:8], e)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to cache response: %s", e)

    def clear(self) -> int:
        """Clear all cached responses.

        Returns:
            Number of cache files deleted
        """
        if not self.enabled or not self.cache_dir.exists():
            return 0

        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
            count += 1

        logger.info("Cleared %s cached responses", count)
        return count

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        if not self.enabled or not self.cache_dir.exists():
            return {"enabled": False, "cache_files": 0, "total_size_mb": 0.0}

        cache_files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)

        return {
            "enabled": True,
            "cache_files": len(cache_files),
            "total_size_mb": total_size / (1024 * 1024),
            "cache_dir": str(self.cache_dir),
        }


# Global cache instance (can be configured via environment variable)
_global_cache: LLMCache | None = None


def get_cache() -> LLMCache:
    """Get or create the global cache instance."""
    global _global_cache

    if _global_cache is None:
        # Check environment variable for cache configuration
        cache_enabled_str = os.getenv("COSCIENTIST_CACHE_ENABLED",
                                      str(DEFAULT_CACHE_ENABLED).lower())
        cache_enabled = cache_enabled_str.lower() in ("true", "1", "yes")
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
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_string.encode()).hexdigest()

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
            try:
                with open(cache_file, "rb") as f:
                    cached_data: dict[str, Any] = pickle.load(f)
                logger.debug("node cache HIT for %s (key %s...)", node_name,
                             cache_key[:8])
                return cached_data
            except (pickle.PickleError, OSError) as e:
                logger.debug("node cache read failed for %s...: %s",
                             cache_key[:8], e)
                try:
                    cache_file.unlink()
                except OSError:
                    pass
                return None

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

        try:
            temp_file = cache_file.with_suffix(".tmp")
            with open(temp_file, "wb") as f:
                pickle.dump(output, f)
            temp_file.replace(cache_file)
            logger.debug("cached node output for %s (key %s...)", node_name,
                         cache_key[:8])
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to cache node output for %s: %s", node_name,
                           e)

    def clear(self) -> int:
        """Clear all cached node outputs.

        Returns:
            Number of cache files deleted
        """
        if not self.enabled or not self.cache_dir.exists():
            return 0

        count = 0
        for cache_file in self.cache_dir.glob("*.pkl"):
            cache_file.unlink()
            count += 1

        logger.info("Cleared %s cached node outputs", count)
        return count

    def get_stats(self) -> dict[str, Any]:
        """Get node cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        if not self.enabled or not self.cache_dir.exists():
            return {"enabled": False, "cache_files": 0, "total_size_mb": 0.0}

        cache_files = list(self.cache_dir.glob("*.pkl"))
        total_size = sum(f.stat().st_size for f in cache_files)

        return {
            "enabled": True,
            "cache_files": len(cache_files),
            "total_size_mb": total_size / (1024 * 1024),
            "cache_dir": str(self.cache_dir),
        }


# Global node cache instance
_global_node_cache: NodeCache | None = None


def get_node_cache() -> NodeCache:
    """Get or create the global node cache instance."""
    global _global_node_cache

    if _global_node_cache is None:
        # Reuse same cache enabled flag as LLM cache
        cache_enabled_str = os.getenv("COSCIENTIST_CACHE_ENABLED",
                                      str(DEFAULT_CACHE_ENABLED).lower())
        cache_enabled = cache_enabled_str.lower() in ("true", "1", "yes")
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

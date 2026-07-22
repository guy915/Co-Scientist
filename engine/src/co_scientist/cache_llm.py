"""File-based cache tier for LLM responses.

Defines ``LLMCache``, which persists LLM responses as JSON files keyed by
the full request parameters, and ``NullCache``, a no-op stand-in used to
force fresh LLM calls for diversity-critical generation.
"""

import json
import logging
from pathlib import Path
from typing import Any

from co_scientist.cache_storage import (
    _cache_dir_stats,
    _clear_cache_files,
    _hash_key,
    _read_llm_cache_entry,
    _write_cache_file_atomically,
)
from co_scientist.constants import (
    DEFAULT_CACHE_DIR,
    DEFAULT_CACHE_ENABLED,
    truncate,
)

logger = logging.getLogger(__name__)


class LLMCache:
    """Simple file-based cache for LLM responses."""

    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        enabled: bool = DEFAULT_CACHE_ENABLED,
    ):
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

    def _fold_optional_key_params(
        self,
        key_data: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        json_schema: dict[str, Any] | None,
        force_json: bool | None,
    ) -> None:
        """Fold optional response-shape params into key_data, in place.

        Folding tools/json_schema/force_json into the key means a call that
        differs only in response-format shape gets its own cache entry, so a
        JSON-schema call can never be served a cached freeform response (or
        vice versa) for the same prompt/model/temperature/max_tokens.
        """
        if tools is not None:
            key_data["tools"] = json.dumps(tools, sort_keys=True)
        if json_schema is not None:
            key_data["json_schema"] = json.dumps(json_schema, sort_keys=True)
        if force_json is not None:
            key_data["force_json"] = force_json

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
        self._fold_optional_key_params(key_data, tools, json_schema, force_json)
        return _hash_key(key_data)

    def _cache_location(
        self,
        prompt: str,
        model_name: str,
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None,
        json_schema: dict[str, Any] | None,
        force_json: bool | None,
    ) -> tuple[str, Path]:
        """Compute the cache key and its backing file for this request."""
        cache_key = self._generate_cache_key(
            prompt,
            model_name,
            temperature,
            max_tokens,
            tools,
            json_schema,
            force_json,
        )
        return cache_key, self.cache_dir / f"{cache_key}.json"

    def _read_or_miss(
        self, cache_key: str, cache_file: Path
    ) -> dict[str, Any] | None:
        """Return the cached entry for cache_file, or log and return None."""
        if cache_file.exists():
            return _read_llm_cache_entry(cache_file, cache_key)

        logger.debug("cache MISS for key %s...", cache_key[:8])
        return None

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

        cache_key, cache_file = self._cache_location(
            prompt,
            model_name,
            temperature,
            max_tokens,
            tools,
            json_schema,
            force_json,
        )
        return self._read_or_miss(cache_key, cache_file)

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
            tools: Optional tool definitions (for tool-calling LLMs)
            json_schema: Optional JSON schema for structured output
            force_json: Optional flag to force JSON output
        """
        if not self.enabled:
            return

        self._write_entry(
            prompt,
            model_name,
            temperature,
            max_tokens,
            response,
            tools,
            json_schema,
            force_json,
        )

    def _write_entry(
        self,
        prompt: str,
        model_name: str,
        temperature: float,
        max_tokens: int,
        response: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        json_schema: dict[str, Any] | None,
        force_json: bool | None,
    ) -> None:
        """Compute the cache location and persist response there."""
        cache_key, cache_file = self._cache_location(
            prompt,
            model_name,
            temperature,
            max_tokens,
            tools,
            json_schema,
            force_json,
        )
        request_meta = {
            "model": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "prompt_preview": truncate(prompt),
        }
        try:
            cache_data = {"request": request_meta, "response": response}
            _write_cache_file_atomically(cache_file, cache_key, cache_data)
        except Exception as e:
            logger.warning("Failed to cache response: %s", e)

    def clear(self) -> int:
        """Clear all cached responses.

        Returns:
            Number of cache files deleted
        """
        return _clear_cache_files(
            self.cache_dir, self.enabled, "*.json", "cached responses"
        )

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

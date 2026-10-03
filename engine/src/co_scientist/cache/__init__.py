"""File-based LLM and node caches with scoped overrides and shared accessors."""

import contextlib
import hashlib
import json
import logging
import os
import pickle
import time
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from co_scientist.config.env_vars import parse_timeout_env
from co_scientist.config.registry import parse_bool_env
from co_scientist.constants import (
    DEFAULT_CACHE_DIR,
    DEFAULT_CACHE_ENABLED,
    DEFAULT_CACHE_TTL_SECONDS,
    LLM_CACHE_SCHEMA_VERSION,
    truncate,
)
from co_scientist.llm import campaign_free_mode, current_api_key

logger = logging.getLogger(__name__)


def _hash_key(key_data: dict[str, Any]) -> str:
    """Return the SHA256 hex digest of a canonical-JSON key payload."""
    key_string = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(key_string.encode()).hexdigest()


def _is_cache_entry_stale(cache_file: Path, ttl_seconds: float | None) -> bool:
    """Return whether a cache entry is older than its TTL.

    Uses the file's own mtime rather than a timestamp stored inside the
    entry, so neither cache tier's on-disk format has to change to gain
    expiry, and entries written before TTL support was added age out
    exactly like any other entry instead of being treated as ageless.

    Args:
        cache_file: The cache entry file whose age to check.
        ttl_seconds: The expiry ceiling, or None to disable expiry (every
            entry is considered fresh).

    Returns:
        True when the entry's age exceeds ``ttl_seconds``. A file that
        vanished or cannot be stat'd (e.g. a concurrent clear) is reported
        fresh -- the read that follows resolves the real outcome.
    """
    if ttl_seconds is None:
        return False
    try:
        age_seconds = time.time() - cache_file.stat().st_mtime
    except OSError:
        return False
    return age_seconds > ttl_seconds


def _evict_stale_entry(cache_file: Path) -> None:
    """Delete an expired cache entry, ignoring a concurrent removal."""
    with contextlib.suppress(OSError):
        cache_file.unlink()


# Shared by LLMCache.clear() and NodeCache.clear() so the glob-and-delete
# logic is not duplicated across the two cache tiers.
def _clear_cache_files(
    cache_dir: Path, enabled: bool, pattern: str, label: str
) -> int:
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
def _cache_dir_stats(
    cache_dir: Path, enabled: bool, pattern: str
) -> dict[str, Any]:
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


def _read_llm_cache_entry(
    cache_file: Path, cache_key: str
) -> dict[str, Any] | None:
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
            cache_key[:8],
            e,
        )
        # Don't remove file on IOError - it might just be locked by another
        # process
        if isinstance(e, (json.JSONDecodeError, KeyError)):
            # Only remove on actual corruption, not on I/O errors. The file
            # might have been removed by another process, so suppress OSError.
            with contextlib.suppress(OSError):
                cache_file.unlink()
        return None


def _write_cache_file_atomically(
    cache_file: Path, cache_key: str, cache_data: dict[str, Any]
) -> None:
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
        with contextlib.suppress(OSError):
            temp_file.unlink()
        logger.debug(
            "cache write conflict for %s... (concurrent write): %s",
            cache_key[:8],
            e,
        )


def _read_node_cache_entry(
    cache_file: Path, node_name: str, cache_key: str
) -> dict[str, Any] | None:
    """Read a single cached node output, self-healing on corruption.

    Args:
        cache_file: Path to the ``.pkl`` cache entry to read.
        node_name: Name of the node the entry belongs to, for log messages.
        cache_key: The entry's cache key, used only for log messages.

    Returns:
        The cached node output dict on a clean read, otherwise None.
    """
    try:
        # Pickle is safe here: entries are written locally by
        # _write_node_cache_file_atomically below into this package's own
        # cache directory, so the data is trusted (not user-supplied).
        with open(cache_file, "rb") as f:
            cached_data: dict[str, Any] = pickle.load(f)
        logger.debug(
            "node cache HIT for %s (key %s...)", node_name, cache_key[:8]
        )
        return cached_data
    except (pickle.PickleError, OSError) as e:
        logger.debug("node cache read failed for %s...: %s", cache_key[:8], e)
        # The file might have been removed by another process, so suppress
        # OSError.
        with contextlib.suppress(OSError):
            cache_file.unlink()
        return None


def _write_node_cache_file_atomically(
    cache_file: Path, node_name: str, cache_key: str, output: dict[str, Any]
) -> None:
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
        logger.debug(
            "cached node output for %s (key %s...)", node_name, cache_key[:8]
        )
    except Exception as e:
        logger.warning("Failed to cache node output for %s: %s", node_name, e)


@dataclass(frozen=True)
class LLMCacheRequest:
    """The request parameters identifying one cached LLM response.

    Attributes:
        prompt: The prompt text.
        model_name: Model name in litellm format.
        temperature: Temperature parameter, already clamped.
        max_tokens: Max tokens parameter.
        tools: Optional list of tool definitions (for tool-calling LLMs).
        json_schema: Optional JSON schema for structured output.
        force_json: Optional flag to force JSON output.
        tool_contract: Optional resolved configuration of whatever the
            prompt's tools (or other external source data) actually do at
            call time -- as opposed to ``tools``, which is only the schema
            *advertised* to the model. Two calls can offer an identical
            tool schema while the tool itself behaves differently (a data
            source disabled, an endpoint changed), in which case a cached
            transcript from the old configuration must not replay. Mirrors
            the node-cache tier's ``tool_contract``
            (``agents/generation/literature_review/node.py``); folded into
            the key only when a caller supplies one; keeping every call
            site that has no notion of an external tool contract unaffected.
        cache_schema_version: Schema version this entry was cached under.
            Defaults to the current ``LLM_CACHE_SCHEMA_VERSION`` so every
            caller is versioned without having to set this explicitly;
            bumping the constant invalidates the whole cache at once.
    """

    prompt: str
    model_name: str
    temperature: float
    max_tokens: int
    tools: list[dict[str, Any]] | None = None
    json_schema: dict[str, Any] | None = None
    force_json: bool | None = None
    tool_contract: dict[str, Any] | None = None
    cache_schema_version: int = LLM_CACHE_SCHEMA_VERSION


class LLMCache:
    """Simple file-based cache for LLM responses."""

    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        enabled: bool = DEFAULT_CACHE_ENABLED,
        ttl_seconds: float | None = DEFAULT_CACHE_TTL_SECONDS,
    ):
        """Initialize the LLM cache.

        Args:
            cache_dir: Directory to store cache files
            enabled: Whether caching is enabled
            ttl_seconds: Age after which an entry is treated as a miss, or
                None to disable expiry.
        """
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds

        # Directory is only created when caching is enabled, so a disabled
        # cache leaves no stray directory on disk.
        if self.enabled:
            self.cache_dir.mkdir(exist_ok=True, parents=True)
            logger.debug("LLM cache initialized at %s", self.cache_dir)

    def _fold_optional_key_params(
        self, key_data: dict[str, Any], request: LLMCacheRequest
    ) -> None:
        """Fold optional response-shape params into key_data, in place.

        Folding tools/json_schema/force_json into the key means a call that
        differs only in response-format shape gets its own cache entry, so a
        JSON-schema call can never be served a cached freeform response (or
        vice versa) for the same prompt/model/temperature/max_tokens.

        Args:
            key_data: The in-progress key payload; mutated in place.
            request: The request whose optional fields are folded in.
        """
        if request.tools is not None:
            key_data["tools"] = json.dumps(request.tools, sort_keys=True)
        if request.json_schema is not None:
            key_data["json_schema"] = json.dumps(
                request.json_schema, sort_keys=True
            )
        if request.force_json is not None:
            key_data["force_json"] = request.force_json
        if request.tool_contract is not None:
            key_data["tool_contract"] = json.dumps(
                request.tool_contract, sort_keys=True
            )

    def _generate_cache_key(self, request: LLMCacheRequest) -> str:
        """Generate a unique cache key for the request.

        Args:
            request: The parameters identifying the cached response.

        Returns:
            SHA256 hash of the request parameters
        """
        # Create deterministic string representation
        key_data = {
            "prompt": request.prompt,
            "model": request.model_name,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "cache_schema_version": request.cache_schema_version,
        }
        self._fold_optional_key_params(key_data, request)
        return _hash_key(key_data)

    def _cache_location(self, request: LLMCacheRequest) -> tuple[str, Path]:
        """Compute the cache key and its backing file for this request.

        Args:
            request: The parameters identifying the cached response.

        Returns:
            The cache key and the file it is stored in.
        """
        cache_key = self._generate_cache_key(request)
        return cache_key, self.cache_dir / f"{cache_key}.json"

    def _read_or_miss(
        self, cache_key: str, cache_file: Path
    ) -> dict[str, Any] | None:
        """Return the cached entry for cache_file, or log and return None."""
        if not cache_file.exists():
            logger.debug("cache MISS for key %s...", cache_key[:8])
            return None

        if _is_cache_entry_stale(cache_file, self.ttl_seconds):
            logger.debug("cache EXPIRED (ttl) for key %s...", cache_key[:8])
            _evict_stale_entry(cache_file)
            return None

        return _read_llm_cache_entry(cache_file, cache_key)

    def get(self, request: LLMCacheRequest) -> dict[str, Any] | None:
        """Get cached response if available.

        Args:
            request: The parameters identifying the cached response.

        Returns:
            Cached response dict or None if not found
        """
        if not self.enabled:
            return None

        cache_key, cache_file = self._cache_location(request)
        return self._read_or_miss(cache_key, cache_file)

    def set(self, request: LLMCacheRequest, response: dict[str, Any]) -> None:
        """Store response in cache.

        Args:
            request: The parameters identifying the cached response.
            response: The LLM response to cache
        """
        if not self.enabled:
            return

        self._write_entry(request, response)

    def _write_entry(
        self, request: LLMCacheRequest, response: dict[str, Any]
    ) -> None:
        """Compute the cache location and persist response there.

        Args:
            request: The parameters identifying the cached response.
            response: The LLM response to cache.
        """
        cache_key, cache_file = self._cache_location(request)
        request_meta = {
            "model": request.model_name,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "prompt_preview": truncate(request.prompt),
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

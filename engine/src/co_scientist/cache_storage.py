"""Shared file-storage primitives for the cache tiers.

Provides the key hashing, atomic read/write, clearing, and statistics
helpers shared by the LLM response cache (JSON entries) and the node
output cache (pickle entries).
"""

import contextlib
import hashlib
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Any

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

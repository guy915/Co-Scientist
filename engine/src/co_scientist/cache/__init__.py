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

from co_scientist._context import _bind_contextvar
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
    key_string = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(key_string.encode()).hexdigest()


def _is_cache_entry_stale(cache_file: Path, ttl_seconds: float | None) -> bool:
    """File mtime expires legacy entries without migrating either cache
    format.
    """
    if ttl_seconds is None:
        return False
    try:
        age_seconds = time.time() - cache_file.stat().st_mtime
    except OSError:
        return False
    return age_seconds > ttl_seconds


def _evict_stale_entry(cache_file: Path) -> None:
    with contextlib.suppress(OSError):
        cache_file.unlink()


def _clear_cache_files(cache_dir: Path, enabled: bool, pattern: str, label: str) -> int:
    if not enabled or not cache_dir.exists():
        return 0

    count = 0
    for cache_file in cache_dir.glob(pattern):
        cache_file.unlink()
        count += 1

    logger.info("Cleared %s %s", count, label)
    return count


def _cache_dir_stats(cache_dir: Path, enabled: bool, pattern: str) -> dict[str, Any]:
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


def _read_llm_cache_entry(cache_file: Path, cache_key: str) -> dict[str, Any] | None:
    try:
        # Atomic replacement exposes a complete prior entry or a recoverable
        # read failure.
        with open(cache_file, encoding="utf-8") as f:
            cached_data = json.load(f)
        logger.debug("cache HIT for key %s...", cache_key[:8])
        response: dict[str, Any] = cached_data["response"]
        return response
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.debug(
            "cache read failed for %s... (may be concurrent write): %s",
            cache_key[:8],
            e,
        )
        # I/O failure is not corruption: another process may hold or remove the
        # file.
        if isinstance(e, (json.JSONDecodeError, KeyError)):
            # Remove only corrupt entries; tolerate concurrent deletion.
            with contextlib.suppress(OSError):
                cache_file.unlink()
        return None


def _write_cache_file_atomically(
    cache_file: Path, cache_key: str, cache_data: dict[str, Any]
) -> None:
    # Temp-file rename keeps concurrent cache writers from publishing partial
    # JSON.
    temp_file = cache_file.with_suffix(".tmp")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        temp_file.replace(cache_file)
        logger.debug("cached response for key %s...", cache_key[:8])
    except OSError as e:
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
    try:
        # Pickle entries are trusted local cache files, never user-supplied
        # payloads.
        with open(cache_file, "rb") as f:
            cached_data: dict[str, Any] = pickle.load(f)
        logger.debug("node cache HIT for %s (key %s...)", node_name, cache_key[:8])
        return cached_data
    except (pickle.PickleError, OSError) as e:
        logger.debug("node cache read failed for %s...: %s", cache_key[:8], e)
        with contextlib.suppress(OSError):
            cache_file.unlink()
        return None


def _write_node_cache_file_atomically(
    cache_file: Path, node_name: str, cache_key: str, output: dict[str, Any]
) -> None:
    try:
        temp_file = cache_file.with_suffix(".tmp")
        with open(temp_file, "wb") as f:
            pickle.dump(output, f)
        temp_file.replace(cache_file)
        logger.debug("cached node output for %s (key %s...)", node_name, cache_key[:8])
    except Exception as e:
        logger.warning("Failed to cache node output for %s: %s", node_name, e)


@dataclass(frozen=True)
class LLMCacheRequest:
    """Advertised tool schemas do not identify external tool behavior;
    optional tool_contract does.
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
    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        enabled: bool = DEFAULT_CACHE_ENABLED,
        ttl_seconds: float | None = DEFAULT_CACHE_TTL_SECONDS,
    ):
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds

        if self.enabled:
            self.cache_dir.mkdir(exist_ok=True, parents=True)
            logger.debug("LLM cache initialized at %s", self.cache_dir)

    def _fold_optional_key_params(self, key_data: dict[str, Any], request: LLMCacheRequest) -> None:
        """Response-format and tool behavior belong in cache identity;
        freeform and JSON cannot share entries.
        """
        if request.tools is not None:
            key_data["tools"] = json.dumps(request.tools, sort_keys=True)
        if request.json_schema is not None:
            key_data["json_schema"] = json.dumps(request.json_schema, sort_keys=True)
        if request.force_json is not None:
            key_data["force_json"] = request.force_json
        if request.tool_contract is not None:
            key_data["tool_contract"] = json.dumps(request.tool_contract, sort_keys=True)

    def _generate_cache_key(self, request: LLMCacheRequest) -> str:
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
        cache_key = self._generate_cache_key(request)
        return cache_key, self.cache_dir / f"{cache_key}.json"

    def _read_or_miss(self, cache_key: str, cache_file: Path) -> dict[str, Any] | None:
        if not cache_file.exists():
            logger.debug("cache MISS for key %s...", cache_key[:8])
            return None

        if _is_cache_entry_stale(cache_file, self.ttl_seconds):
            logger.debug("cache EXPIRED (ttl) for key %s...", cache_key[:8])
            _evict_stale_entry(cache_file)
            return None

        return _read_llm_cache_entry(cache_file, cache_key)

    def get(self, request: LLMCacheRequest) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        cache_key, cache_file = self._cache_location(request)
        return self._read_or_miss(cache_key, cache_file)

    def set(self, request: LLMCacheRequest, response: dict[str, Any]) -> None:
        if not self.enabled:
            return

        self._write_entry(request, response)

    def _write_entry(self, request: LLMCacheRequest, response: dict[str, Any]) -> None:
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
        return _clear_cache_files(self.cache_dir, self.enabled, "*.json", "cached responses")

    def get_stats(self) -> dict[str, Any]:
        return _cache_dir_stats(self.cache_dir, self.enabled, "*.json")


class NullCache:
    """Stochastic generation must bypass cache or repeated samples
    deduplicate into one hypothesis.
    """

    def get(self, *_args: Any, **_kwargs: Any) -> dict[str, Any] | None:
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class NodeCache:
    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        enabled: bool = True,
        ttl_seconds: float | None = DEFAULT_CACHE_TTL_SECONDS,
    ):
        self.cache_dir = Path(cache_dir) / "nodes"
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds

        if self.enabled:
            self.cache_dir.mkdir(exist_ok=True, parents=True)
            logger.debug("node cache initialized at %s", self.cache_dir)

    def _generate_cache_key(self, node_name: str, **key_params: Any) -> str:
        key_data = {"node": node_name, **key_params}
        return _hash_key(key_data)

    def get(self, node_name: str, force: bool = False, **key_params: Any) -> dict[str, Any] | None:
        # Shared node outputs have neither credential nor experiment provenance.
        if campaign_free_mode() or current_api_key():
            return None

        if not self.enabled and not force:
            return None

        cache_key = self._generate_cache_key(node_name, **key_params)
        cache_file = self.cache_dir / f"{cache_key}.pkl"

        if not cache_file.exists():
            logger.debug("node cache MISS for %s (key %s...)", node_name, cache_key[:8])
            return None

        # Dev/test force bypasses expiry as well as disabled caching.
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
        if campaign_free_mode() or current_api_key():
            return

        if not self.enabled and not force:
            return

        if force and not self.cache_dir.exists():
            self.cache_dir.mkdir(exist_ok=True, parents=True)

        cache_key = self._generate_cache_key(node_name, **key_params)
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        _write_node_cache_file_atomically(cache_file, node_name, cache_key, output)

    def clear(self) -> int:
        return _clear_cache_files(self.cache_dir, self.enabled, "*.pkl", "cached node outputs")

    def get_stats(self) -> dict[str, Any]:
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
    """The first accessor memoizes process defaults; per-generator
    preferences use task-local overrides.
    """
    cache_enabled_str = os.getenv("COSCIENTIST_CACHE_ENABLED", str(DEFAULT_CACHE_ENABLED).lower())
    cache_dir = os.getenv("COSCIENTIST_CACHE_DIR", DEFAULT_CACHE_DIR)
    ttl_seconds = parse_timeout_env("COSCIENTIST_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS)
    return parse_bool_env(cache_enabled_str), cache_dir, ttl_seconds


# Task-local overrides reach spawned children without changing concurrent runs
# or process defaults.
_cache_enabled_override: ContextVar[bool | None] = ContextVar(
    "cache_enabled_override", default=None
)


def cache_enabled_override() -> bool | None:
    return _cache_enabled_override.get()


@contextlib.contextmanager
def scoped_cache_override(enable_cache: bool | None) -> Iterator[None]:
    """Child tasks inherit isolation; False bypasses caching, True cannot
    override a disabled process default.
    """
    if enable_cache is None:
        yield
        return
    with _bind_contextvar(_cache_enabled_override, enable_cache):
        yield


_global_cache: LLMCache | None = None


def get_cache() -> LLMCache:
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
    return get_cache().clear()


def get_cache_stats() -> dict[str, Any]:
    return get_cache().get_stats()


_global_node_cache: NodeCache | None = None


def get_node_cache() -> NodeCache:
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
    return get_node_cache().clear()


def get_node_cache_stats() -> dict[str, Any]:
    return get_node_cache().get_stats()

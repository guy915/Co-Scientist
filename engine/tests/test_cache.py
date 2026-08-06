"""Tests for the file-based LLM and node caches in ``co_scientist.cache``.

These tests exercise the real on-disk behavior of ``LLMCache`` and
``NodeCache``: key derivation, get/set roundtrips, the enabled/disabled gate,
and the ``clear``/``get_stats`` helpers (both directly and through the global
factories ``get_cache``/``get_node_cache``).

All disk writes are isolated to pytest's ``tmp_path``. An autouse fixture both
redirects the ``COSCIENTIST_CACHE_DIR`` env var and resets the module-level
global singletons, so the global factories never touch the repo's real
``.coscientist_cache`` directory.
"""

import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from co_scientist import cache
from co_scientist.cache import LLMCache, LLMCacheRequest, NodeCache


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every cache to ``tmp_path`` and reset the global singletons.

    ``get_cache``/``get_node_cache`` only read the environment when their
    module-level singleton is ``None``, so the globals must be reset between
    tests to keep each test's env settings effective and to avoid reusing (or
    creating) the repo's real cache directory.

    Args:
        tmp_path: Per-test temporary directory provided by pytest.
        monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setenv("COSCIENTIST_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    monkeypatch.setattr(cache, "_global_cache", None)
    monkeypatch.setattr(cache, "_global_node_cache", None)


# A reusable request/response pair for the LLM cache.
_REQUEST = LLMCacheRequest(
    prompt="explain mitochondria",
    model_name="test-model",
    temperature=0.3,
    max_tokens=100,
)
_RESPONSE: dict[str, Any] = {"content": "the powerhouse of the cell"}

# --- LLMCache: key derivation ----------------------------------------------


def test_key_stable_for_same_inputs(tmp_path: Path) -> None:
    """The same request parameters always derive the same cache key."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    key_a = cache_obj._generate_cache_key(_REQUEST)
    key_b = cache_obj._generate_cache_key(_REQUEST)
    assert key_a == key_b
    # SHA256 hex digest.
    assert len(key_a) == 64


def test_key_differs_for_different_inputs(tmp_path: Path) -> None:
    """Changing any request parameter changes the derived cache key."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    base = cache_obj._generate_cache_key(_REQUEST)
    other_prompt = cache_obj._generate_cache_key(
        replace(_REQUEST, prompt="different prompt")
    )
    other_temp = cache_obj._generate_cache_key(
        replace(_REQUEST, temperature=0.9)
    )
    assert base != other_prompt
    assert base != other_temp
    assert other_prompt != other_temp


def test_key_changes_with_optional_params(tmp_path: Path) -> None:
    """Optional params (tools/json_schema/force_json) participate in the key."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    base = cache_obj._generate_cache_key(_REQUEST)
    with_tools = cache_obj._generate_cache_key(
        replace(_REQUEST, tools=[{"name": "search"}])
    )
    with_force_json = cache_obj._generate_cache_key(
        replace(_REQUEST, force_json=True)
    )
    assert base != with_tools
    assert base != with_force_json


def test_key_changes_with_tool_contract(tmp_path: Path) -> None:
    """The resolved tool contract, not just its schema, is part of the key.

    A source config change invalidates a cached tool-call transcript even
    when the tool schema offered to the model is unchanged (I4).
    """
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    base = cache_obj._generate_cache_key(_REQUEST)
    enabled = cache_obj._generate_cache_key(
        replace(_REQUEST, tool_contract={"pubmed": {"enabled": True}})
    )
    disabled = cache_obj._generate_cache_key(
        replace(_REQUEST, tool_contract={"pubmed": {"enabled": False}})
    )
    assert base != enabled
    assert enabled != disabled


def test_key_changes_with_cache_schema_version(tmp_path: Path) -> None:
    """Bumping cache_schema_version invalidates the whole cache at once."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    base = cache_obj._generate_cache_key(_REQUEST)
    next_version = _REQUEST.cache_schema_version + 1
    bumped = cache_obj._generate_cache_key(
        replace(_REQUEST, cache_schema_version=next_version)
    )
    assert base != bumped


# --- LLMCache: get/set roundtrip -------------------------------------------


def test_roundtrip_hit(tmp_path: Path) -> None:
    """A value that was set is returned on a subsequent get (cache hit)."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    assert cache_obj.get(_REQUEST) is None  # cold: miss
    cache_obj.set(_REQUEST, _RESPONSE)
    assert cache_obj.get(_REQUEST) == _RESPONSE


def test_different_key_is_a_miss(tmp_path: Path) -> None:
    """A request with different parameters misses even after a set."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    cache_obj.set(_REQUEST, _RESPONSE)
    assert cache_obj.get(replace(_REQUEST, prompt="unrelated")) is None


def test_tool_contract_change_is_a_miss_end_to_end(tmp_path: Path) -> None:
    """A get/set roundtrip misses when only ``tool_contract`` changed (I4)."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    original = replace(_REQUEST, tool_contract={"pubmed": {"enabled": True}})
    changed = replace(_REQUEST, tool_contract={"pubmed": {"enabled": False}})
    cache_obj.set(original, _RESPONSE)
    assert cache_obj.get(original) == _RESPONSE
    assert cache_obj.get(changed) is None


# --- LLMCache: TTL expiry ---------------------------------------------------


def test_ttl_expired_entry_is_a_miss_and_is_evicted(tmp_path: Path) -> None:
    """An entry older than the TTL misses and its file is removed."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True, ttl_seconds=60)
    cache_obj.set(_REQUEST, _RESPONSE)
    _, cache_file = cache_obj._cache_location(_REQUEST)
    stale = time.time() - 120
    os.utime(cache_file, (stale, stale))

    assert cache_obj.get(_REQUEST) is None
    assert not cache_file.exists()


def test_ttl_fresh_entry_is_still_a_hit(tmp_path: Path) -> None:
    """An entry inside the TTL window is served normally."""
    cache_obj = LLMCache(
        cache_dir=str(tmp_path), enabled=True, ttl_seconds=3600
    )
    cache_obj.set(_REQUEST, _RESPONSE)
    assert cache_obj.get(_REQUEST) == _RESPONSE


def test_ttl_none_disables_expiry(tmp_path: Path) -> None:
    """``ttl_seconds=None`` never expires an entry, however old."""
    cache_obj = LLMCache(
        cache_dir=str(tmp_path), enabled=True, ttl_seconds=None
    )
    cache_obj.set(_REQUEST, _RESPONSE)
    _, cache_file = cache_obj._cache_location(_REQUEST)
    ancient = time.time() - 10_000_000
    os.utime(cache_file, (ancient, ancient))

    assert cache_obj.get(_REQUEST) == _RESPONSE


def test_set_writes_file_under_cache_dir(tmp_path: Path) -> None:
    """``set`` persists exactly one ``.json`` file inside the cache dir."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    cache_obj.set(_REQUEST, _RESPONSE)
    json_files = list(tmp_path.glob("*.json"))
    assert len(json_files) == 1


# --- LLMCache: disabled gate -----------------------------------------------


def test_disabled_get_always_misses(tmp_path: Path) -> None:
    """When disabled, ``set`` is a no-op and ``get`` always misses."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=False)
    cache_obj.set(_REQUEST, _RESPONSE)
    assert cache_obj.get(_REQUEST) is None
    # No files written, and the dir is not even created when disabled.
    assert not tmp_path.exists() or list(tmp_path.glob("*.json")) == []


def test_disabled_does_not_create_dir(tmp_path: Path) -> None:
    """A disabled cache does not create its directory on construction."""
    target = tmp_path / "nonexistent"
    LLMCache(cache_dir=str(target), enabled=False)
    assert not target.exists()


# --- LLMCache: stats and clear ---------------------------------------------


def test_stats_reflect_entries_and_clear_empties(tmp_path: Path) -> None:
    """``get_stats`` counts entries; ``clear`` deletes them, returns count."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    assert cache_obj.get_stats()["cache_files"] == 0

    cache_obj.set(_REQUEST, _RESPONSE)
    cache_obj.set(replace(_REQUEST, prompt="second"), _RESPONSE)

    stats = cache_obj.get_stats()
    assert stats["enabled"] is True
    assert stats["cache_files"] == 2
    assert stats["total_size_mb"] > 0.0
    assert stats["cache_dir"] == str(tmp_path)

    deleted = cache_obj.clear()
    assert deleted == 2
    assert cache_obj.get_stats()["cache_files"] == 0


def test_disabled_stats_shape(tmp_path: Path) -> None:
    """Disabled ``get_stats`` reports disabled shape with no ``cache_dir``."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=False)
    stats = cache_obj.get_stats()
    assert stats == {"enabled": False, "cache_files": 0, "total_size_mb": 0.0}
    assert "cache_dir" not in stats


def test_disabled_clear_returns_zero(tmp_path: Path) -> None:
    """``clear`` on a disabled cache deletes nothing and returns zero."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=False)
    assert cache_obj.clear() == 0


# --- Global LLM cache factory (env-driven) ---------------------------------


def test_get_cache_is_singleton(tmp_path: Path) -> None:
    """``get_cache`` returns the same instance across calls within a test."""
    first = cache.get_cache()
    second = cache.get_cache()
    assert first is second
    # Honors the env var redirection from the autouse fixture.
    assert first.enabled is True
    assert first.cache_dir == tmp_path


def test_get_cache_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``COSCIENTIST_CACHE_ENABLED=false`` disables the global LLM cache."""
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "false")
    monkeypatch.setattr(cache, "_global_cache", None)
    assert cache.get_cache().enabled is False


def test_get_cache_reads_ttl_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``COSCIENTIST_CACHE_TTL_SECONDS`` sets the global LLM cache's TTL."""
    monkeypatch.setenv("COSCIENTIST_CACHE_TTL_SECONDS", "42")
    monkeypatch.setattr(cache, "_global_cache", None)
    assert cache.get_cache().ttl_seconds == 42.0


def test_get_cache_ttl_zero_disables_expiry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``COSCIENTIST_CACHE_TTL_SECONDS=0`` disables expiry.

    Matches every other wall-clock ceiling in this codebase.
    """
    monkeypatch.setenv("COSCIENTIST_CACHE_TTL_SECONDS", "0")
    monkeypatch.setattr(cache, "_global_cache", None)
    assert cache.get_cache().ttl_seconds is None


def test_get_node_cache_reads_ttl_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``COSCIENTIST_CACHE_TTL_SECONDS`` sets the global node cache's TTL."""
    monkeypatch.setenv("COSCIENTIST_CACHE_TTL_SECONDS", "99")
    monkeypatch.setattr(cache, "_global_node_cache", None)
    assert cache.get_node_cache().ttl_seconds == 99.0


# --- scoped_cache_override / cache_enabled_override --------------------


def test_cache_enabled_override_defaults_to_none() -> None:
    """With no active scope, there is no per-task override."""
    assert cache.cache_enabled_override() is None


def test_scoped_cache_override_none_is_a_noop() -> None:
    """Passing None (a generator's unset enable_cache) sets no override."""
    with cache.scoped_cache_override(None):
        assert cache.cache_enabled_override() is None
    assert cache.cache_enabled_override() is None


def test_scoped_cache_override_sets_and_resets() -> None:
    """The override is visible inside the scope and cleared on exit."""
    with cache.scoped_cache_override(False):
        assert cache.cache_enabled_override() is False
    assert cache.cache_enabled_override() is None


def test_scoped_cache_override_restores_prior_value_when_nested() -> None:
    """Exiting an inner scope restores the outer scope's override."""
    with cache.scoped_cache_override(True):
        with cache.scoped_cache_override(False):
            assert cache.cache_enabled_override() is False
        assert cache.cache_enabled_override() is True
    assert cache.cache_enabled_override() is None


def test_scoped_cache_override_resets_even_on_exception() -> None:
    """A raised exception inside the scope still clears the override."""
    with pytest.raises(ValueError), cache.scoped_cache_override(False):
        raise ValueError("boom")
    assert cache.cache_enabled_override() is None


def test_module_level_stats_and_clear(tmp_path: Path) -> None:
    """``get_cache_stats``/``clear_cache`` operate on the global LLM cache."""
    cache_obj = cache.get_cache()
    cache_obj.set(_REQUEST, _RESPONSE)

    stats = cache.get_cache_stats()
    assert stats["cache_files"] == 1
    assert stats["cache_dir"] == str(tmp_path)

    assert cache.clear_cache() == 1
    assert cache.get_cache_stats()["cache_files"] == 0


# --- NodeCache -------------------------------------------------------------

_NODE_OUTPUT: dict[str, Any] = {"papers": ["a", "b"], "summary": "found 2"}


def test_node_cache_roundtrip(tmp_path: Path) -> None:
    """A node output stored under given params is returned on matching get."""
    node = NodeCache(cache_dir=str(tmp_path), enabled=True)
    assert node.get("literature_review", research_goal="cancer") is None
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    assert node.get("literature_review", research_goal="cancer") == _NODE_OUTPUT


def test_node_cache_ttl_expired_entry_is_a_miss_and_is_evicted(
    tmp_path: Path,
) -> None:
    """A node-cache entry older than the TTL misses and is evicted (I4)."""
    node = NodeCache(cache_dir=str(tmp_path), enabled=True, ttl_seconds=60)
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    cache_key = node._generate_cache_key(
        "literature_review", research_goal="cancer"
    )
    cache_file = node.cache_dir / f"{cache_key}.pkl"
    stale = time.time() - 120
    os.utime(cache_file, (stale, stale))

    assert node.get("literature_review", research_goal="cancer") is None
    assert not cache_file.exists()


def test_node_cache_ttl_none_disables_expiry(tmp_path: Path) -> None:
    """A node cache with no TTL never expires an entry."""
    node = NodeCache(cache_dir=str(tmp_path), enabled=True, ttl_seconds=None)
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    cache_key = node._generate_cache_key(
        "literature_review", research_goal="cancer"
    )
    cache_file = node.cache_dir / f"{cache_key}.pkl"
    ancient = time.time() - 10_000_000
    os.utime(cache_file, (ancient, ancient))

    assert node.get("literature_review", research_goal="cancer") == _NODE_OUTPUT


def test_node_cache_force_bypasses_ttl(tmp_path: Path) -> None:
    """``force=True`` serves an expired entry too, like the disabled gate."""
    node = NodeCache(cache_dir=str(tmp_path), enabled=True, ttl_seconds=60)
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    cache_key = node._generate_cache_key(
        "literature_review", research_goal="cancer"
    )
    cache_file = node.cache_dir / f"{cache_key}.pkl"
    stale = time.time() - 120
    os.utime(cache_file, (stale, stale))

    assert (
        node.get("literature_review", force=True, research_goal="cancer")
        == _NODE_OUTPUT
    )


def test_node_cache_param_mismatch_is_miss(tmp_path: Path) -> None:
    """Different key params (or node name) miss the stored entry."""
    node = NodeCache(cache_dir=str(tmp_path), enabled=True)
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    assert node.get("literature_review", research_goal="diabetes") is None
    assert node.get("other_node", research_goal="cancer") is None


def test_node_cache_writes_pkl_under_nodes_subdir(tmp_path: Path) -> None:
    """Node outputs are pickled into a ``nodes`` subdirectory of the cache."""
    node = NodeCache(cache_dir=str(tmp_path), enabled=True)
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    pkl_files = list((tmp_path / "nodes").glob("*.pkl"))
    assert len(pkl_files) == 1


def test_node_cache_disabled_is_noop(tmp_path: Path) -> None:
    """A disabled node cache stores nothing and always misses."""
    node = NodeCache(cache_dir=str(tmp_path), enabled=False)
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    assert node.get("literature_review", research_goal="cancer") is None


def test_node_cache_force_bypasses_disabled_gate(tmp_path: Path) -> None:
    """``force=True`` writes and reads even when the cache is disabled."""
    node = NodeCache(cache_dir=str(tmp_path), enabled=False)
    node.set("literature_review", _NODE_OUTPUT, force=True, research_goal="x")
    # Without force, the disabled gate still hides the entry.
    assert node.get("literature_review", research_goal="x") is None
    # With force, the forced entry is retrievable.
    assert (
        node.get("literature_review", force=True, research_goal="x")
        == _NODE_OUTPUT
    )


def test_node_cache_stats_and_clear(tmp_path: Path) -> None:
    """``get_stats`` counts node entries and ``clear`` removes them."""
    node = NodeCache(cache_dir=str(tmp_path), enabled=True)
    assert node.get_stats()["cache_files"] == 0
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    node.set("literature_review", _NODE_OUTPUT, research_goal="diabetes")

    stats = node.get_stats()
    assert stats["enabled"] is True
    assert stats["cache_files"] == 2
    assert stats["cache_dir"] == str(tmp_path / "nodes")

    assert node.clear() == 2
    assert node.get_stats()["cache_files"] == 0


# --- Global node cache factory (env-driven) --------------------------------


def test_get_node_cache_is_singleton(tmp_path: Path) -> None:
    """``get_node_cache`` returns one env-configured singleton per reset."""
    first = cache.get_node_cache()
    second = cache.get_node_cache()
    assert first is second
    assert first.enabled is True
    assert first.cache_dir == tmp_path / "nodes"


def test_module_level_node_stats_and_clear(tmp_path: Path) -> None:
    """``get_node_cache_stats``/``clear_node_cache`` hit global node cache."""
    node = cache.get_node_cache()
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")

    assert cache.get_node_cache_stats()["cache_files"] == 1
    assert cache.clear_node_cache() == 1
    assert cache.get_node_cache_stats()["cache_files"] == 0

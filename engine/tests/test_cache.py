# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
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

from pathlib import Path
from typing import Any

import pytest

from co_scientist import cache
from co_scientist.cache import LLMCache
from co_scientist.cache import NodeCache


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
_REQUEST: dict[str, Any] = {
    "prompt": "explain mitochondria",
    "model_name": "test-model",
    "temperature": 0.3,
    "max_tokens": 100,
}
_RESPONSE: dict[str, Any] = {"content": "the powerhouse of the cell"}


# --- LLMCache: key derivation ----------------------------------------------


def test_key_stable_for_same_inputs(tmp_path: Path) -> None:
    """The same request parameters always derive the same cache key."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    key_a = cache_obj._generate_cache_key(**_REQUEST)  # pylint: disable=protected-access
    key_b = cache_obj._generate_cache_key(**_REQUEST)  # pylint: disable=protected-access
    assert key_a == key_b
    # SHA256 hex digest.
    assert len(key_a) == 64


def test_key_differs_for_different_inputs(tmp_path: Path) -> None:
    """Changing any request parameter changes the derived cache key."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    base = cache_obj._generate_cache_key(**_REQUEST)  # pylint: disable=protected-access
    other_prompt = cache_obj._generate_cache_key(  # pylint: disable=protected-access
        **{**_REQUEST, "prompt": "different prompt"})
    other_temp = cache_obj._generate_cache_key(  # pylint: disable=protected-access
        **{**_REQUEST, "temperature": 0.9})
    assert base != other_prompt
    assert base != other_temp
    assert other_prompt != other_temp


def test_key_changes_with_optional_params(tmp_path: Path) -> None:
    """Optional params (tools/json_schema/force_json) participate in the key."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    base = cache_obj._generate_cache_key(**_REQUEST)  # pylint: disable=protected-access
    with_tools = cache_obj._generate_cache_key(  # pylint: disable=protected-access
        **_REQUEST, tools=[{"name": "search"}])
    with_force_json = cache_obj._generate_cache_key(  # pylint: disable=protected-access
        **_REQUEST, force_json=True)
    assert base != with_tools
    assert base != with_force_json


# --- LLMCache: get/set roundtrip -------------------------------------------


def test_roundtrip_hit(tmp_path: Path) -> None:
    """A value that was set is returned on a subsequent get (cache hit)."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    assert cache_obj.get(**_REQUEST) is None  # cold: miss
    cache_obj.set(**_REQUEST, response=_RESPONSE)
    assert cache_obj.get(**_REQUEST) == _RESPONSE


def test_different_key_is_a_miss(tmp_path: Path) -> None:
    """A request with different parameters misses even after a set."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    cache_obj.set(**_REQUEST, response=_RESPONSE)
    assert cache_obj.get(**{**_REQUEST, "prompt": "unrelated"}) is None


def test_set_writes_file_under_cache_dir(tmp_path: Path) -> None:
    """``set`` persists exactly one ``.json`` file inside the cache dir."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    cache_obj.set(**_REQUEST, response=_RESPONSE)
    json_files = list(tmp_path.glob("*.json"))
    assert len(json_files) == 1


# --- LLMCache: disabled gate -----------------------------------------------


def test_disabled_get_always_misses(tmp_path: Path) -> None:
    """When disabled, ``set`` is a no-op and ``get`` always misses."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=False)
    cache_obj.set(**_REQUEST, response=_RESPONSE)
    assert cache_obj.get(**_REQUEST) is None
    # No files written, and the dir is not even created when disabled.
    assert not tmp_path.exists() or list(tmp_path.glob("*.json")) == []


def test_disabled_does_not_create_dir(tmp_path: Path) -> None:
    """A disabled cache does not create its directory on construction."""
    target = tmp_path / "nonexistent"
    LLMCache(cache_dir=str(target), enabled=False)
    assert not target.exists()


# --- LLMCache: stats and clear ---------------------------------------------


def test_stats_reflect_entries_and_clear_empties(tmp_path: Path) -> None:
    """``get_stats`` counts entries; ``clear`` deletes them and returns count."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    assert cache_obj.get_stats()["cache_files"] == 0

    cache_obj.set(**_REQUEST, response=_RESPONSE)
    cache_obj.set(**{**_REQUEST, "prompt": "second"}, response=_RESPONSE)

    stats = cache_obj.get_stats()
    assert stats["enabled"] is True
    assert stats["cache_files"] == 2
    assert stats["total_size_mb"] > 0.0
    assert stats["cache_dir"] == str(tmp_path)

    deleted = cache_obj.clear()
    assert deleted == 2
    assert cache_obj.get_stats()["cache_files"] == 0


def test_disabled_stats_shape(tmp_path: Path) -> None:
    """Disabled ``get_stats`` reports the disabled shape with no ``cache_dir``."""
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


def test_get_cache_disabled_via_env(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``COSCIENTIST_CACHE_ENABLED=false`` disables the global LLM cache."""
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "false")
    monkeypatch.setattr(cache, "_global_cache", None)
    assert cache.get_cache().enabled is False


def test_module_level_stats_and_clear(tmp_path: Path) -> None:
    """``get_cache_stats``/``clear_cache`` operate on the global LLM cache."""
    cache_obj = cache.get_cache()
    cache_obj.set(**_REQUEST, response=_RESPONSE)

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
    assert node.get("literature_review", force=True,
                    research_goal="x") == _NODE_OUTPUT


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
    """``get_node_cache_stats``/``clear_node_cache`` hit the global node cache."""
    node = cache.get_node_cache()
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")

    assert cache.get_node_cache_stats()["cache_files"] == 1
    assert cache.clear_node_cache() == 1
    assert cache.get_node_cache_stats()["cache_files"] == 0

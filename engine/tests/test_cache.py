"""Offline contracts for cache."""

from __future__ import annotations

import os
import pickle
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from co_scientist import cache
from co_scientist.cache import (
    LLMCache,
    LLMCacheRequest,
    NodeCache,
    _read_llm_cache_entry,
    _read_node_cache_entry,
    _write_cache_file_atomically,
    _write_node_cache_file_atomically,
)
from co_scientist.llm import scoped_api_key


@pytest.fixture
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


# --- LLMCache: get/set roundtrip -------------------------------------------


# --- LLMCache: TTL expiry ---------------------------------------------------


# --- LLMCache: disabled gate -----------------------------------------------


# --- LLMCache: stats and clear ---------------------------------------------


# --- Global LLM cache factory (env-driven) ---------------------------------


# --- scoped_cache_override / cache_enabled_override --------------------


# --- NodeCache -------------------------------------------------------------

_NODE_OUTPUT: dict[str, Any] = {"papers": ["a", "b"], "summary": "found 2"}


# --- Global node cache factory (env-driven) --------------------------------


@pytest.mark.usefixtures("_isolate_cache")
class TestCache:
    def test_key_stable_for_same_inputs(self, tmp_path: Path) -> None:
        """The same request parameters always derive the same cache key."""
        cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
        key_a = cache_obj._generate_cache_key(_REQUEST)
        key_b = cache_obj._generate_cache_key(_REQUEST)
        assert key_a == key_b
        # SHA256 hex digest.
        assert len(key_a) == 64

    def test_key_differs_for_different_inputs(self, tmp_path: Path) -> None:
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

    def test_key_changes_with_optional_params(self, tmp_path: Path) -> None:
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

    def test_key_changes_with_tool_contract(self, tmp_path: Path) -> None:
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

    def test_key_changes_with_cache_schema_version(
        self, tmp_path: Path
    ) -> None:
        """Bumping cache_schema_version invalidates the whole cache at once."""
        cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
        base = cache_obj._generate_cache_key(_REQUEST)
        next_version = _REQUEST.cache_schema_version + 1
        bumped = cache_obj._generate_cache_key(
            replace(_REQUEST, cache_schema_version=next_version)
        )
        assert base != bumped

    def test_roundtrip_hit(self, tmp_path: Path) -> None:
        """A value that was set is returned on a subsequent get (cache hit)."""
        cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
        assert cache_obj.get(_REQUEST) is None  # cold: miss
        cache_obj.set(_REQUEST, _RESPONSE)
        assert cache_obj.get(_REQUEST) == _RESPONSE

    def test_different_key_is_a_miss(self, tmp_path: Path) -> None:
        """A request with different parameters misses even after a set."""
        cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
        cache_obj.set(_REQUEST, _RESPONSE)
        assert cache_obj.get(replace(_REQUEST, prompt="unrelated")) is None

    def test_tool_contract_change_is_a_miss_end_to_end(
        self, tmp_path: Path
    ) -> None:
        cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
        original = replace(
            _REQUEST, tool_contract={"pubmed": {"enabled": True}}
        )
        changed = replace(
            _REQUEST, tool_contract={"pubmed": {"enabled": False}}
        )
        cache_obj.set(original, _RESPONSE)
        assert cache_obj.get(original) == _RESPONSE
        assert cache_obj.get(changed) is None

    def test_ttl_expired_entry_is_a_miss_and_is_evicted(
        self, tmp_path: Path
    ) -> None:
        """An entry older than the TTL misses and its file is removed."""
        cache_obj = LLMCache(
            cache_dir=str(tmp_path), enabled=True, ttl_seconds=60
        )
        cache_obj.set(_REQUEST, _RESPONSE)
        _, cache_file = cache_obj._cache_location(_REQUEST)
        stale = time.time() - 120
        os.utime(cache_file, (stale, stale))

        assert cache_obj.get(_REQUEST) is None
        assert not cache_file.exists()

    def test_ttl_fresh_entry_is_still_a_hit(self, tmp_path: Path) -> None:
        """An entry inside the TTL window is served normally."""
        cache_obj = LLMCache(
            cache_dir=str(tmp_path), enabled=True, ttl_seconds=3600
        )
        cache_obj.set(_REQUEST, _RESPONSE)
        assert cache_obj.get(_REQUEST) == _RESPONSE

    def test_ttl_none_disables_expiry(self, tmp_path: Path) -> None:
        """``ttl_seconds=None`` never expires an entry, however old."""
        cache_obj = LLMCache(
            cache_dir=str(tmp_path), enabled=True, ttl_seconds=None
        )
        cache_obj.set(_REQUEST, _RESPONSE)
        _, cache_file = cache_obj._cache_location(_REQUEST)
        ancient = time.time() - 10_000_000
        os.utime(cache_file, (ancient, ancient))

        assert cache_obj.get(_REQUEST) == _RESPONSE

    def test_set_writes_file_under_cache_dir(self, tmp_path: Path) -> None:
        """``set`` persists exactly one ``.json`` file inside the cache dir."""
        cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
        cache_obj.set(_REQUEST, _RESPONSE)
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1

    def test_disabled_get_always_misses(self, tmp_path: Path) -> None:
        """When disabled, ``set`` is a no-op and ``get`` always misses."""
        cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=False)
        cache_obj.set(_REQUEST, _RESPONSE)
        assert cache_obj.get(_REQUEST) is None
        # No files written, and the dir is not even created when disabled.
        assert not tmp_path.exists() or list(tmp_path.glob("*.json")) == []

    def test_disabled_does_not_create_dir(self, tmp_path: Path) -> None:
        """A disabled cache does not create its directory on construction."""
        target = tmp_path / "nonexistent"
        LLMCache(cache_dir=str(target), enabled=False)
        assert not target.exists()

    def test_stats_reflect_entries_and_clear_empties(
        self, tmp_path: Path
    ) -> None:
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

    def test_disabled_stats_shape(self, tmp_path: Path) -> None:
        cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=False)
        stats = cache_obj.get_stats()
        assert stats == {
            "enabled": False,
            "cache_files": 0,
            "total_size_mb": 0.0,
        }
        assert "cache_dir" not in stats

    def test_disabled_clear_returns_zero(self, tmp_path: Path) -> None:
        """``clear`` on a disabled cache deletes nothing and returns zero."""
        cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=False)
        assert cache_obj.clear() == 0

    def test_get_cache_is_singleton(self, tmp_path: Path) -> None:
        first = cache.get_cache()
        second = cache.get_cache()
        assert first is second
        # Honors the env var redirection from the autouse fixture.
        assert first.enabled is True
        assert first.cache_dir == tmp_path

    def test_get_cache_disabled_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``COSCIENTIST_CACHE_ENABLED=false`` disables the global LLM cache."""
        monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "false")
        monkeypatch.setattr(cache, "_global_cache", None)
        assert cache.get_cache().enabled is False

    def test_get_cache_reads_ttl_from_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``COSCIENTIST_CACHE_TTL_SECONDS`` sets the global LLM cache's TTL."""
        monkeypatch.setenv("COSCIENTIST_CACHE_TTL_SECONDS", "42")
        monkeypatch.setattr(cache, "_global_cache", None)
        assert cache.get_cache().ttl_seconds == 42.0

    def test_get_cache_ttl_zero_disables_expiry(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``COSCIENTIST_CACHE_TTL_SECONDS=0`` disables expiry.

        Matches every other wall-clock ceiling in this codebase.
        """
        monkeypatch.setenv("COSCIENTIST_CACHE_TTL_SECONDS", "0")
        monkeypatch.setattr(cache, "_global_cache", None)
        assert cache.get_cache().ttl_seconds is None

    def test_get_node_cache_reads_ttl_from_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("COSCIENTIST_CACHE_TTL_SECONDS", "99")
        monkeypatch.setattr(cache, "_global_node_cache", None)
        assert cache.get_node_cache().ttl_seconds == 99.0

    def test_cache_enabled_override_defaults_to_none(self) -> None:
        """With no active scope, there is no per-task override."""
        assert cache.cache_enabled_override() is None

    def test_scoped_cache_override_none_is_a_noop(self) -> None:
        """Passing None (a generator's unset enable_cache) sets no override."""
        with cache.scoped_cache_override(None):
            assert cache.cache_enabled_override() is None
        assert cache.cache_enabled_override() is None

    def test_scoped_cache_override_sets_and_resets(self) -> None:
        """The override is visible inside the scope and cleared on exit."""
        with cache.scoped_cache_override(False):
            assert cache.cache_enabled_override() is False
        assert cache.cache_enabled_override() is None

    def test_scoped_cache_override_restores_prior_value_when_nested(
        self,
    ) -> None:
        """Exiting an inner scope restores the outer scope's override."""
        with cache.scoped_cache_override(True):
            with cache.scoped_cache_override(False):
                assert cache.cache_enabled_override() is False
            assert cache.cache_enabled_override() is True
        assert cache.cache_enabled_override() is None

    def test_scoped_cache_override_resets_even_on_exception(self) -> None:
        """A raised exception inside the scope still clears the override."""
        with pytest.raises(ValueError), cache.scoped_cache_override(False):
            raise ValueError("boom")
        assert cache.cache_enabled_override() is None

    def test_module_level_stats_and_clear(self, tmp_path: Path) -> None:
        cache_obj = cache.get_cache()
        cache_obj.set(_REQUEST, _RESPONSE)

        stats = cache.get_cache_stats()
        assert stats["cache_files"] == 1
        assert stats["cache_dir"] == str(tmp_path)

        assert cache.clear_cache() == 1
        assert cache.get_cache_stats()["cache_files"] == 0

    def test_node_cache_roundtrip(self, tmp_path: Path) -> None:
        node = NodeCache(cache_dir=str(tmp_path), enabled=True)
        assert node.get("literature_review", research_goal="cancer") is None
        node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
        assert (
            node.get("literature_review", research_goal="cancer")
            == _NODE_OUTPUT
        )

    def test_node_cache_ttl_expired_entry_is_a_miss_and_is_evicted(
        self,
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

    def test_node_cache_ttl_none_disables_expiry(self, tmp_path: Path) -> None:
        """A node cache with no TTL never expires an entry."""
        node = NodeCache(
            cache_dir=str(tmp_path), enabled=True, ttl_seconds=None
        )
        node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
        cache_key = node._generate_cache_key(
            "literature_review", research_goal="cancer"
        )
        cache_file = node.cache_dir / f"{cache_key}.pkl"
        ancient = time.time() - 10_000_000
        os.utime(cache_file, (ancient, ancient))

        assert (
            node.get("literature_review", research_goal="cancer")
            == _NODE_OUTPUT
        )

    def test_node_cache_force_bypasses_ttl(self, tmp_path: Path) -> None:
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

    def test_node_cache_param_mismatch_is_miss(self, tmp_path: Path) -> None:
        """Different key params (or node name) miss the stored entry."""
        node = NodeCache(cache_dir=str(tmp_path), enabled=True)
        node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
        assert node.get("literature_review", research_goal="diabetes") is None
        assert node.get("other_node", research_goal="cancer") is None

    def test_node_cache_writes_pkl_under_nodes_subdir(
        self, tmp_path: Path
    ) -> None:
        node = NodeCache(cache_dir=str(tmp_path), enabled=True)
        node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
        pkl_files = list((tmp_path / "nodes").glob("*.pkl"))
        assert len(pkl_files) == 1

    def test_node_cache_disabled_is_noop(self, tmp_path: Path) -> None:
        """A disabled node cache stores nothing and always misses."""
        node = NodeCache(cache_dir=str(tmp_path), enabled=False)
        node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
        assert node.get("literature_review", research_goal="cancer") is None

    def test_node_cache_force_bypasses_disabled_gate(
        self, tmp_path: Path
    ) -> None:
        """``force=True`` writes and reads even when the cache is disabled."""
        node = NodeCache(cache_dir=str(tmp_path), enabled=False)
        node.set(
            "literature_review", _NODE_OUTPUT, force=True, research_goal="x"
        )
        # Without force, the disabled gate still hides the entry.
        assert node.get("literature_review", research_goal="x") is None
        # With force, the forced entry is retrievable.
        assert (
            node.get("literature_review", force=True, research_goal="x")
            == _NODE_OUTPUT
        )

    def test_node_cache_stats_and_clear(self, tmp_path: Path) -> None:
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

    def test_get_node_cache_is_singleton(self, tmp_path: Path) -> None:
        """``get_node_cache`` returns one env-configured singleton per reset."""
        first = cache.get_node_cache()
        second = cache.get_node_cache()
        assert first is second
        assert first.enabled is True
        assert first.cache_dir == tmp_path / "nodes"

    def test_module_level_node_stats_and_clear(self, tmp_path: Path) -> None:
        node = cache.get_node_cache()
        node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")

        assert cache.get_node_cache_stats()["cache_files"] == 1
        assert cache.clear_node_cache() == 1
        assert cache.get_node_cache_stats()["cache_files"] == 0


# --- _read_llm_cache_entry: corruption self-healing -------------------------


def test_read_llm_cache_entry_corrupt_json_removes_file(tmp_path: Path) -> None:
    """Invalid JSON is treated as a miss and the corrupt file is removed."""
    cache_file = tmp_path / "entry.json"
    cache_file.write_text("not valid json{{{", encoding="utf-8")

    result = _read_llm_cache_entry(cache_file, "deadbeef")

    assert result is None
    assert not cache_file.exists()


def test_read_llm_cache_entry_missing_response_key_removes_file(
    tmp_path: Path,
) -> None:
    """Valid JSON missing the "response" key is a miss; file is removed."""
    cache_file = tmp_path / "entry.json"
    cache_file.write_text('{"unexpected": "shape"}', encoding="utf-8")

    result = _read_llm_cache_entry(cache_file, "deadbeef")

    assert result is None
    assert not cache_file.exists()


def test_read_llm_cache_entry_os_error_is_a_miss_without_removal(
    tmp_path: Path,
) -> None:
    """An OSError while opening leaves the entry alone (may be concurrent).

    A directory in place of the expected file makes ``open()`` raise
    ``IsADirectoryError``, an ``OSError`` subclass, without ever producing
    JSON to decode.
    """
    cache_file = tmp_path / "entry.json"
    cache_file.mkdir()

    result = _read_llm_cache_entry(cache_file, "deadbeef")

    assert result is None
    # OSError is not corruption, so the entry is left in place.
    assert cache_file.exists()


def test_read_llm_cache_entry_success_returns_response(tmp_path: Path) -> None:
    """A clean read returns the stored "response" payload."""
    cache_file = tmp_path / "entry.json"
    cache_file.write_text('{"response": {"content": "hi"}}', encoding="utf-8")

    result = _read_llm_cache_entry(cache_file, "deadbeef")

    assert result == {"content": "hi"}


# --- _write_cache_file_atomically: write failures ---------------------------


def test_write_cache_file_atomically_os_error_is_swallowed(
    tmp_path: Path,
) -> None:
    """A write failure (missing parent dir) is logged, not raised."""
    cache_file = tmp_path / "missing_parent" / "entry.json"

    # Should not raise even though the parent directory does not exist.
    _write_cache_file_atomically(cache_file, "deadbeef", {"response": {}})

    assert not cache_file.exists()


def test_write_cache_file_atomically_success_writes_file(
    tmp_path: Path,
) -> None:
    """A normal write leaves the destination file in place, no temp file."""
    cache_file = tmp_path / "entry.json"

    _write_cache_file_atomically(cache_file, "deadbeef", {"response": {"a": 1}})

    assert cache_file.exists()
    assert not cache_file.with_suffix(".tmp").exists()


# --- _read_node_cache_entry: corruption self-healing ------------------------
#
# Pickle here mirrors production usage: cache/storage.py documents that
# node-cache entries are written locally by this package's own atomic
# writer into its own cache directory, so reading them back is trusted,
# not user-supplied, data. These tests write the fixtures themselves.


def test_read_node_cache_entry_corrupt_pickle_removes_file(
    tmp_path: Path,
) -> None:
    """Invalid pickle bytes are treated as a miss and the file is removed."""
    cache_file = tmp_path / "entry.pkl"
    cache_file.write_bytes(b"not a pickle stream")

    result = _read_node_cache_entry(cache_file, "literature_review", "deadbeef")

    assert result is None
    assert not cache_file.exists()


def test_read_node_cache_entry_os_error_is_a_miss(tmp_path: Path) -> None:
    """An OSError while opening (e.g. a directory) is a miss.

    ``Path.unlink()`` on a directory itself raises ``OSError``, which the
    handler suppresses, so the directory is left behind.
    """
    cache_file = tmp_path / "entry.pkl"
    cache_file.mkdir()

    result = _read_node_cache_entry(cache_file, "literature_review", "deadbeef")

    assert result is None
    assert cache_file.exists()


def test_read_node_cache_entry_success_returns_output(tmp_path: Path) -> None:
    """A clean read returns the unpickled node output."""
    cache_file = tmp_path / "entry.pkl"
    with open(cache_file, "wb") as f:
        pickle.dump({"papers": ["a"]}, f)

    result = _read_node_cache_entry(cache_file, "literature_review", "deadbeef")

    assert result == {"papers": ["a"]}


# --- _write_node_cache_file_atomically: write failures ----------------------


def test_write_node_cache_file_atomically_failure_is_swallowed(
    tmp_path: Path,
) -> None:
    """Any failure during the pickle write is logged, never raised."""
    cache_file = tmp_path / "missing_parent" / "entry.pkl"

    # Should not raise even though the parent directory does not exist.
    _write_node_cache_file_atomically(
        cache_file, "literature_review", "deadbeef", {"papers": []}
    )

    assert not cache_file.exists()


def test_write_node_cache_file_atomically_success_writes_file(
    tmp_path: Path,
) -> None:
    """A normal write leaves the destination file in place."""
    cache_file = tmp_path / "entry.pkl"

    _write_node_cache_file_atomically(
        cache_file, "literature_review", "deadbeef", {"papers": ["x"]}
    )

    assert cache_file.exists()
    with open(cache_file, "rb") as f:
        assert pickle.load(f) == {"papers": ["x"]}


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("scope", ["campaign", "byok"])
def test_isolated_execution_cannot_read_or_replace_shared_node_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, force: bool, scope: str
) -> None:
    cache = NodeCache(cache_dir=str(tmp_path))
    params = {"research_goal": "public goal", "model_name": "same-model"}
    cache.set(
        "literature_review", {"text": "previous run"}, force=False, **params
    )
    with monkeypatch.context() as patch:
        if scope == "campaign":
            patch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        with scoped_api_key("user-key" if scope == "byok" else None):
            assert cache.get("literature_review", force=force, **params) is None
            cache.set(
                "literature_review",
                {"text": "isolated run"},
                force=force,
                **params,
            )
    assert cache.get("literature_review", force=False, **params) == {
        "text": "previous run"
    }


async def test_campaign_literature_node_does_not_replay_previous_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from co_scientist.agents.generation.literature_review import node as lr
    from co_scientist.constants import LITERATURE_REVIEW_FAILED
    from tests._research_fakes import _stub_node
    from tests._state import make_state

    _stub_node(monkeypatch, server_available=False)
    cache = NodeCache(cache_dir=str(tmp_path))
    monkeypatch.setattr(lr, "get_node_cache", lambda: cache)
    state = make_state(research_goal="public research")
    state["dev_test_lit_tools_isolation"] = True
    cache.set(
        "literature_review",
        {"articles_with_reasoning": "previous paid review"},
        **lr._literature_cache_params(state, lr.search_config_for(state)),
    )
    previous = await lr.literature_review_node(state)
    assert previous["articles_with_reasoning"] == "previous paid review"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    fresh = await lr.literature_review_node(state)
    assert fresh["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    assert fresh["retrieval_degradation"]["reason"] == "mcp_unreachable"

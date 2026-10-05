from __future__ import annotations

import os
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
)
from co_scientist.llm import scoped_api_key

_REQUEST = LLMCacheRequest(
    prompt="explain mitochondria",
    model_name="test-model",
    temperature=0.3,
    max_tokens=100,
)
_RESPONSE: dict[str, Any] = {"content": "the powerhouse of the cell"}
_NODE_OUTPUT: dict[str, Any] = {"papers": ["a", "b"], "summary": "found 2"}


def _age(path: Path, seconds: float) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


@pytest.mark.parametrize(
    "changed",
    [
        {"prompt": "different prompt"},
        {"temperature": 0.9},
        {"tools": [{"name": "search"}]},
        {"force_json": True},
        # Tool configuration changes invalidate transcripts even with equal
        # schemas.
        {"tool_contract": {"pubmed": {"enabled": True}}},
        {"cache_schema_version": _REQUEST.cache_schema_version + 1},
    ],
    ids=lambda changed: next(iter(changed)),
)
def test_a_changed_request_is_a_cache_miss(
    tmp_path: Path, changed: dict[str, Any]
) -> None:
    llm_cache = LLMCache(cache_dir=str(tmp_path), enabled=True)
    assert llm_cache.get(_REQUEST) is None
    llm_cache.set(_REQUEST, _RESPONSE)
    assert llm_cache.get(_REQUEST) == _RESPONSE
    assert llm_cache.get(replace(_REQUEST, **changed)) is None


def test_a_disabled_cache_neither_stores_nor_creates_its_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "nonexistent"
    llm_cache = LLMCache(cache_dir=str(target), enabled=False)
    llm_cache.set(_REQUEST, _RESPONSE)
    assert llm_cache.get(_REQUEST) is None
    assert not target.exists()


@pytest.mark.parametrize(
    ("ttl", "age", "hit"),
    [(60, 120, False), (3600, 120, True), (None, 10_000_000, True)],
)
def test_llm_entries_expire_by_ttl_and_are_evicted(
    tmp_path: Path, ttl: float | None, age: float, hit: bool
) -> None:
    llm_cache = LLMCache(cache_dir=str(tmp_path), enabled=True, ttl_seconds=ttl)
    llm_cache.set(_REQUEST, _RESPONSE)
    (entry,) = tmp_path.glob("*.json")
    _age(entry, age)

    assert (llm_cache.get(_REQUEST) == _RESPONSE) is hit
    assert entry.exists() is hit


@pytest.mark.parametrize(
    "content", ["not valid json{{{", '{"unexpected": "shape"}']
)
def test_a_corrupt_llm_entry_is_a_miss_and_is_removed(
    tmp_path: Path, content: str
) -> None:
    llm_cache = LLMCache(cache_dir=str(tmp_path), enabled=True)
    llm_cache.set(_REQUEST, _RESPONSE)
    (entry,) = tmp_path.glob("*.json")
    entry.write_text(content, encoding="utf-8")

    assert llm_cache.get(_REQUEST) is None
    assert not entry.exists()


def test_stats_count_entries_and_clear_empties(tmp_path: Path) -> None:
    llm_cache = LLMCache(cache_dir=str(tmp_path), enabled=True)
    llm_cache.set(_REQUEST, _RESPONSE)
    llm_cache.set(replace(_REQUEST, prompt="second"), _RESPONSE)
    assert llm_cache.get_stats()["cache_files"] == 2
    assert llm_cache.clear() == 2
    assert llm_cache.get_stats()["cache_files"] == 0


def test_the_global_cache_reads_enablement_and_ttl_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COSCIENTIST_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    monkeypatch.setenv("COSCIENTIST_CACHE_TTL_SECONDS", "42")
    monkeypatch.setattr(cache, "_global_cache", None)
    assert cache.get_cache().enabled is True
    assert cache.get_cache().ttl_seconds == 42.0
    monkeypatch.setenv("COSCIENTIST_CACHE_TTL_SECONDS", "0")
    monkeypatch.setattr(cache, "_global_cache", None)
    assert cache.get_cache().ttl_seconds is None


def test_scoped_cache_override_nests_and_resets_even_on_error() -> None:
    assert cache.cache_enabled_override() is None
    with cache.scoped_cache_override(True):
        with cache.scoped_cache_override(False):
            assert cache.cache_enabled_override() is False
        assert cache.cache_enabled_override() is True
    with pytest.raises(ValueError), cache.scoped_cache_override(False):
        raise ValueError("boom")
    assert cache.cache_enabled_override() is None


def test_node_cache_keys_on_node_and_params(tmp_path: Path) -> None:
    node = NodeCache(cache_dir=str(tmp_path), enabled=True)
    assert node.get("literature_review", research_goal="cancer") is None
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    assert node.get("literature_review", research_goal="cancer") == _NODE_OUTPUT
    assert node.get("literature_review", research_goal="diabetes") is None
    assert node.get("other_node", research_goal="cancer") is None


@pytest.mark.parametrize(
    ("ttl", "force", "hit"),
    [(60, False, False), (60, True, True), (None, False, True)],
)
def test_node_entries_expire_by_ttl_unless_forced(
    tmp_path: Path, ttl: float | None, force: bool, hit: bool
) -> None:
    node = NodeCache(cache_dir=str(tmp_path), enabled=True, ttl_seconds=ttl)
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    (entry,) = (tmp_path / "nodes").glob("*.pkl")
    _age(entry, 10_000_000)

    got = node.get("literature_review", force=force, research_goal="cancer")
    assert (got == _NODE_OUTPUT) is hit


def test_a_corrupt_node_entry_is_a_miss_and_is_removed(
    tmp_path: Path,
) -> None:
    node = NodeCache(cache_dir=str(tmp_path), enabled=True)
    node.set("literature_review", _NODE_OUTPUT, research_goal="cancer")
    (entry,) = (tmp_path / "nodes").glob("*.pkl")
    entry.write_bytes(b"not a pickle stream")

    assert node.get("literature_review", research_goal="cancer") is None
    assert not entry.exists()


def test_node_cache_force_bypasses_the_disabled_gate(tmp_path: Path) -> None:
    node = NodeCache(cache_dir=str(tmp_path), enabled=False)
    node.set("literature_review", _NODE_OUTPUT, force=True, research_goal="x")
    assert node.get("literature_review", research_goal="x") is None
    assert (
        node.get("literature_review", force=True, research_goal="x")
        == _NODE_OUTPUT
    )


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

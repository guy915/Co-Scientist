from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

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


def test_a_failed_cache_write_never_breaks_the_run(tmp_path: Path) -> None:
    llm_cache = LLMCache(cache_dir=str(tmp_path / "gone"), enabled=True)
    (tmp_path / "gone").rmdir()
    llm_cache.set(_REQUEST, _RESPONSE)
    (tmp_path / "gone").mkdir()
    llm_cache.set(_REQUEST, {"content": object()})
    assert llm_cache.get(_REQUEST) is None

    node = NodeCache(cache_dir=str(tmp_path), enabled=True)
    node.set("node", {"unpicklable": lambda: None}, research_goal="x")
    assert node.get("node", research_goal="x") is None


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

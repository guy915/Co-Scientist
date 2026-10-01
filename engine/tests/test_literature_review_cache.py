"""Cache replay must preserve literature-review research provenance."""

from pathlib import Path
from typing import Any

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.cache import NodeCache
from co_scientist.cache import nodes as cache_nodes
from co_scientist.evidence import search as lr_search
from co_scientist.models import Article
from tests._literature_node import _TWO_PAPERS, _stub_node, _stub_research
from tests._state import make_state


async def test_cached_research_keeps_ledger_and_article_call_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A hit reuses both the search result and its research ledger."""
    cache = NodeCache(str(tmp_path), enabled=True, ttl_seconds=None)
    monkeypatch.setattr(cache_nodes, "campaign_free_mode", lambda: False)
    monkeypatch.setattr(cache_nodes, "current_api_key", lambda: None)
    client = _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=_TWO_PAPERS,
        queries=["query alpha"],
        synthesis="SYNTHESIZED REVIEW",
    )

    async def keep_lexical_order(
        ranked: dict[str, dict[str, Any]], _config: Any
    ) -> dict[str, dict[str, Any]]:
        return ranked

    monkeypatch.setattr(
        lr_search, "_apply_semantic_relevance_if_enabled", keep_lexical_order
    )
    monkeypatch.setattr(lr, "get_node_cache", lambda: cache)
    _stub_research(monkeypatch)
    state = make_state(research_goal="goal", research_tier="extended")

    first = await literature_review_node(state)
    first_search_count = len(client.calls)
    cached = await literature_review_node(state)

    assert first["research_ledgers"] == cached["research_ledgers"]
    researched = [a for a in cached["articles"] if a.source_id == "PMID7"]
    assert len(researched) == 1
    assert researched[0].retrieval_call_id == "call-7"
    assert len(client.calls) == first_search_count


async def test_legacy_research_cache_entry_is_refreshed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An article call ID without its ledger makes the cache entry stale."""
    cache = NodeCache(str(tmp_path), enabled=True, ttl_seconds=None)
    monkeypatch.setattr(cache_nodes, "campaign_free_mode", lambda: False)
    monkeypatch.setattr(cache_nodes, "current_api_key", lambda: None)
    client = _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=_TWO_PAPERS,
        queries=["query alpha"],
        synthesis="REFRESHED REVIEW",
    )

    async def keep_lexical_order(
        ranked: dict[str, dict[str, Any]], _config: Any
    ) -> dict[str, dict[str, Any]]:
        return ranked

    monkeypatch.setattr(
        lr_search, "_apply_semantic_relevance_if_enabled", keep_lexical_order
    )
    monkeypatch.setattr(lr, "get_node_cache", lambda: cache)
    _stub_research(monkeypatch)
    state = make_state(research_goal="goal", research_tier="extended")
    config = lr.search_config_for(state)
    cache.set(
        "literature_review",
        {
            "articles": [
                Article(
                    title="Legacy researched paper",
                    retrieval_call_id="call-legacy",
                )
            ],
            "articles_with_reasoning": "LEGACY CACHE",
        },
        **lr._literature_cache_params(state, config),
    )

    result = await literature_review_node(state)

    assert (
        result["articles_with_reasoning"]
        == "REFRESHED REVIEW\n\n## Research\nfound"
    )
    assert result["research_ledgers"]
    assert client.calls


@pytest.mark.parametrize(
    ("cache_enabled", "force_cache"), [(True, False), (False, True)]
)
async def test_ordinary_cache_hit_without_research_provenance_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cache_enabled: bool,
    force_cache: bool,
) -> None:
    """Ordinary Phase 2 articles have no ledger and remain cacheable."""
    cache = NodeCache(str(tmp_path), enabled=cache_enabled, ttl_seconds=None)
    monkeypatch.setattr(cache_nodes, "campaign_free_mode", lambda: False)
    monkeypatch.setattr(cache_nodes, "current_api_key", lambda: None)
    client = _stub_node(monkeypatch, server_available=False)
    monkeypatch.setattr(lr, "get_node_cache", lambda: cache)
    state = make_state(
        research_goal="ordinary goal",
        dev_test_lit_tools_isolation=force_cache,
    )
    config = lr.search_config_for(state)
    cache.set(
        "literature_review",
        {
            "articles": [Article(title="Ordinary Phase 2 paper")],
            "articles_with_reasoning": "ORDINARY CACHED REVIEW",
        },
        force=force_cache,
        **lr._literature_cache_params(state, config),
    )

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == "ORDINARY CACHED REVIEW"
    assert client.calls == []

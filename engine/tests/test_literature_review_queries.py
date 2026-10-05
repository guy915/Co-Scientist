from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import co_scientist.cache as cache_nodes
from co_scientist.agents.generation.literature_review import (
    literature_review_node,
    queries,
    synthesis,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.generation.literature_review import (
    orchestration as lr_orchestration,
)
from co_scientist.cache import NodeCache
from co_scientist.config import (
    SearchSourceConfig,
    ToolConfig,
    ToolRegistry,
    WorkflowConfig,
)
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS,
)
from co_scientist.evidence import search as lr_search
from co_scientist.evidence.search_query import broadened_queries
from co_scientist.models import Article
from tests._llm_fake import install_fake_llm
from tests._mcp import make_tool_results_client
from tests._research_fakes import (
    _TWO_PAPERS,
    _stub_node,
    _stub_research,
    make_search_config,
)
from tests._state import make_state


@pytest.mark.parametrize(
    ("response", "query_format", "expected"),
    [
        (["one", "two"], "boolean", ["one", "two"]),
        ('["one", "two"]', "", ["one", "two"]),
        ('{"queries": ["one", "two"]}', "natural_language", ["one", "two"]),
        ('{"x": 1}', "boolean", ["llm fallback"]),
        ("not JSON", "boolean", ["llm fallback"]),
        ({"queries": ["ignored"]}, "boolean", ["llm fallback"]),
        (None, "boolean", ["llm fallback"]),
    ],
)
async def test_review_recovers_empty_results_from_configured_query_generation(
    monkeypatch: pytest.MonkeyPatch,
    response: Any,
    query_format: str,
    expected: list[str],
) -> None:
    _stub_node(monkeypatch, server_available=True, queries=["llm fallback"])
    registry = ToolRegistry(skip_user_config=True)
    registry.config.workflows = {
        "literature_review": WorkflowConfig(
            primary_search="search",
            query_generation_tool="query_generator",
            query_format=query_format,
        )
    }
    registry.config.tools = {
        "tools": {
            name: ToolConfig(server="s", mcp_tool_name=name)
            for name in ("search", "query_generator")
        }
    }
    client = make_tool_results_client(
        {"query_generator": response, "search": {}}
    )

    async def get_client(**_: Any) -> Any:
        return client

    monkeypatch.setattr(lr, "get_mcp_client", get_client)
    result = await literature_review_node(
        make_state(tool_registry=registry, research_goal="goal")
    )
    assert result["literature_review_queries"] == expected
    assert result["metrics"].llm_calls == (0 if expected[0] == "one" else 1)
    assert client.calls[0] == (
        "query_generator",
        {"research_goal": "goal", "query_format": query_format or "boolean"},
    )


@pytest.mark.parametrize("failure", ["missing-tool", "mcp-error", "llm-error"])
async def test_review_still_searches_when_a_query_generator_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    _stub_node(monkeypatch, server_available=True, queries=["llm fallback"])
    registry = ToolRegistry(skip_user_config=True)
    registry.config.workflows = {
        "literature_review": WorkflowConfig(
            primary_search="search", query_generation_tool="generate"
        )
    }
    registry.config.tools = {
        "tools": {"search": ToolConfig(server="s", mcp_tool_name="search")}
    }
    if failure != "missing-tool":
        registry.config.tools["tools"]["generate"] = ToolConfig(
            server="s", mcp_tool_name="generate"
        )
    client = make_tool_results_client({"search": {}}, error_tools={"generate"})

    async def get_client(**_: Any) -> Any:
        return client

    async def failed_llm(**_: Any) -> Any:
        raise RuntimeError("llm down")

    monkeypatch.setattr(lr, "get_mcp_client", get_client)
    if failure == "llm-error":
        monkeypatch.setattr(queries, "call_llm_json", failed_llm)
    goal = (
        "How does mifepristone affect the glucocorticoid receptor "
        "in glioblastoma?"
    )
    result = await literature_review_node(
        make_state(tool_registry=registry, research_goal=goal)
    )
    query = result["literature_review_queries"][0]
    if failure == "llm-error":
        assert "?" not in query
        assert all(
            word not in query.lower().split()
            for word in ("how", "does", "the", "in")
        )
        assert all(
            word in query.lower()
            for word in (
                "mifepristone",
                "glucocorticoid",
                "receptor",
                "glioblastoma",
            )
        )
    else:
        assert query == "llm fallback"
    assert result["metrics"].llm_calls == 1


_NINE_TERMS = (
    "mifepristone glucocorticoid receptor antagonist glioblastoma "
    "blood brain barrier PD-L1"
)


class _QueryScriptedClient:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.queries: list[str] = []

    async def call_tool(self, _tool_name: str, **kwargs: Any) -> Any:
        query = str(kwargs["query"])
        self.queries.append(query)
        outcome = self.responses[query]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def has_tool(self, _name: str) -> bool:
        return False


@pytest.mark.parametrize("multi_source", [False, True])
@pytest.mark.parametrize("success_level", [0, 1, 2, None])
async def test_review_broadens_empty_searches_and_diagnoses_failed_transports(
    monkeypatch: pytest.MonkeyPatch,
    multi_source: bool,
    success_level: int | None,
) -> None:
    _stub_node(monkeypatch, server_available=True, queries=[_NINE_TERMS])
    ladder = broadened_queries(_NINE_TERMS)
    assert ladder == [
        _NINE_TERMS,
        "mifepristone glucocorticoid receptor antagonist glioblastoma",
        "mifepristone glucocorticoid",
    ]
    responses: dict[str, Any] = {query: {} for query in ladder}
    if success_level is None:
        responses[ladder[0]] = RuntimeError("backend down")
    else:
        responses[ladder[success_level]] = {
            "paper": {"title": "Evidence", "abstract": "Measured result"}
        }
    client = _QueryScriptedClient(responses)

    async def get_client(**_: Any) -> Any:
        return client

    async def no_sleep(_delay: float) -> None:
        pass

    events: list[tuple[str, dict[str, Any]]] = []

    async def progress(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    monkeypatch.setattr(lr, "get_mcp_client", get_client)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    registry = ToolRegistry(skip_user_config=True)
    registry.config.tools = {
        "tools": {"search": ToolConfig(server="s", mcp_tool_name="search")}
    }
    registry.config.workflows = {
        "literature_review": WorkflowConfig(
            primary_search="search",
            search_sources=[SearchSourceConfig(tool="search")]
            if multi_source
            else [],
        )
    }
    result = await literature_review_node(
        make_state(tool_registry=registry, progress_callback=progress)
    )
    if success_level is None:
        assert result["articles"] == []
        assert set(client.queries) == {ladder[0]}
        assert any(
            "backend down" in str(payload)
            for event, payload in events
            if event == "literature_review_error"
        )
    else:
        assert result["articles"][0].title == "Evidence"
        assert client.queries == ladder[: success_level + 1]


@pytest.mark.parametrize("paper_count", [1, 50])
async def test_review_synthesis_failure_preserves_a_bounded_analysis_rollup(
    monkeypatch: pytest.MonkeyPatch,
    paper_count: int,
) -> None:
    papers = {
        f"P{i}": {
            "title": f"Paper number {i}",
            "abstract": "Retrieved evidence",
        }
        for i in range(paper_count)
    }
    _stub_node(monkeypatch, server_available=True, search_payload=papers)

    async def analyze(**_: Any) -> dict[str, Any]:
        return {
            "key_findings": "Finding text. " * 50,
            "gaps_identified": "Gap text. " * 50,
            "unexplored_areas": "Unexplored text. " * 50,
        }

    async def fail(**_: Any) -> Any:
        raise RuntimeError("synthesis unavailable")

    monkeypatch.setattr(synthesis, "call_llm_json", analyze)
    monkeypatch.setattr(synthesis, "call_llm", fail)
    result = await literature_review_node(
        make_state(literature_review_papers_count=paper_count)
    )
    text = result["articles_with_reasoning"]
    assert text != LITERATURE_REVIEW_FAILED
    assert "not an LLM synthesis" in text
    assert all(
        fragment in text
        for fragment in ("Finding text.", "Gap text.", "Unexplored text.")
    )
    assert len(text) <= LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS + 10
    assert f"Paper number {20 if paper_count > 1 else 0}" in text


async def test_cached_research_keeps_ledger_and_article_call_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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


async def _boom(*_: Any, **__: Any) -> Any:
    raise RuntimeError("external dependency refused the call")


async def _enrichment_ok(*_: Any, **__: Any) -> tuple[str, list[Any]]:
    return "KRAS activates MAPK", [{"id": "kg:1"}]


async def _fetch_content_and_enrichment() -> tuple[str, list[Any]]:
    return await lr_orchestration._fetch_content_and_enrichment(
        {},
        {},
        make_search_config(),
        make_tool_results_client(),
        make_state(research_goal="Study of KRAS in cancer"),
    )


async def test_failed_retrieval_keeps_the_enrichment_it_ran_beside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lr_orchestration, "_discover_then_fetch_content", _boom)
    monkeypatch.setattr(
        lr_orchestration, "_phase2_6_fetch_context_enrichment", _enrichment_ok
    )

    context, sources = await _fetch_content_and_enrichment()

    assert context == "KRAS activates MAPK"
    assert sources == [{"id": "kg:1"}]


async def test_failed_enrichment_degrades_to_empty_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrieved: list[str] = []

    async def _retrieval_ok(*_: Any, **__: Any) -> None:
        retrieved.append("papers")

    monkeypatch.setattr(
        lr_orchestration, "_discover_then_fetch_content", _retrieval_ok
    )
    monkeypatch.setattr(
        lr_orchestration, "_phase2_6_fetch_context_enrichment", _boom
    )

    context, sources = await _fetch_content_and_enrichment()

    assert retrieved == ["papers"]
    assert (context, sources) == ("", [])


@pytest.fixture(autouse=True)
def _hermetic_node_model(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_llm(monkeypatch)

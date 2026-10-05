from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
    queries,
    synthesis,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.generation.literature_review import (
    orchestration as lr_orchestration,
)
from co_scientist.config import (
    SearchSourceConfig,
    WorkflowConfig,
)
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS,
)
from co_scientist.evidence.search_query import broadened_queries
from co_scientist.models import Article
from tests._llm_fake import install_fake_llm
from tests._mcp import make_tool_results_client
from tests._research_fakes import (
    _TWO_PAPERS,
    _stub_node,
    _stub_research,
    enable_node_cache,
    install_mcp_client,
    keep_lexical_order,
    make_search_config,
    review_registry,
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
    registry = review_registry(
        WorkflowConfig(
            primary_search="search",
            query_generation_tool="query_generator",
            query_format=query_format,
        ),
        "search",
        "query_generator",
    )
    client = install_mcp_client(
        monkeypatch,
        make_tool_results_client({"query_generator": response, "search": {}}),
    )
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
    registry = review_registry(
        WorkflowConfig(
            primary_search="search", query_generation_tool="generate"
        ),
        "search",
        *(() if failure == "missing-tool" else ("generate",)),
    )
    install_mcp_client(
        monkeypatch,
        make_tool_results_client({"search": {}}, error_tools={"generate"}),
    )

    async def failed_llm(**_: Any) -> Any:
        raise RuntimeError("llm down")

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
    client = install_mcp_client(monkeypatch, _QueryScriptedClient(responses))

    async def no_sleep(_delay: float) -> None:
        pass

    events: list[tuple[str, dict[str, Any]]] = []

    async def progress(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    registry = review_registry(
        WorkflowConfig(
            primary_search="search",
            search_sources=[SearchSourceConfig(tool="search")]
            if multi_source
            else [],
        ),
        "search",
    )
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
    client = _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=_TWO_PAPERS,
        queries=["query alpha"],
        synthesis="SYNTHESIZED REVIEW",
    )
    enable_node_cache(monkeypatch, tmp_path)
    keep_lexical_order(monkeypatch)
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
    client = _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=_TWO_PAPERS,
        queries=["query alpha"],
        synthesis="REFRESHED REVIEW",
    )
    cache = enable_node_cache(monkeypatch, tmp_path)
    keep_lexical_order(monkeypatch)
    _stub_research(monkeypatch)
    state = make_state(research_goal="goal", research_tier="extended")
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
        **lr._literature_cache_params(state, lr.search_config_for(state)),
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
    client = _stub_node(monkeypatch, server_available=False)
    cache = enable_node_cache(monkeypatch, tmp_path)
    cache.enabled = cache_enabled
    state = make_state(
        research_goal="ordinary goal",
        dev_test_lit_tools_isolation=force_cache,
    )
    cache.set(
        "literature_review",
        {
            "articles": [Article(title="Ordinary Phase 2 paper")],
            "articles_with_reasoning": "ORDINARY CACHED REVIEW",
        },
        force=force_cache,
        **lr._literature_cache_params(state, lr.search_config_for(state)),
    )

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == "ORDINARY CACHED REVIEW"
    assert client.calls == []


async def _boom(*_: Any, **__: Any) -> Any:
    raise RuntimeError("external dependency refused the call")


async def _enrichment_ok(*_: Any, **__: Any) -> tuple[str, list[Any]]:
    return "KRAS activates MAPK", [{"id": "kg:1"}]


async def _retrieval_ok(*_: Any, **__: Any) -> None:
    return None


@pytest.mark.parametrize(
    ("retrieval", "enrichment", "expected"),
    [
        (_boom, _enrichment_ok, ("KRAS activates MAPK", [{"id": "kg:1"}])),
        (_retrieval_ok, _boom, ("", [])),
    ],
    ids=["failed-retrieval-keeps-enrichment", "failed-enrichment-is-empty"],
)
async def test_one_failed_phase_never_costs_the_other(
    monkeypatch: pytest.MonkeyPatch,
    retrieval: Any,
    enrichment: Any,
    expected: tuple[str, list[Any]],
) -> None:
    monkeypatch.setattr(
        lr_orchestration, "_discover_then_fetch_content", retrieval
    )
    monkeypatch.setattr(
        lr_orchestration, "_phase2_6_fetch_context_enrichment", enrichment
    )

    result = await lr_orchestration._fetch_content_and_enrichment(
        {},
        {},
        make_search_config(),
        make_tool_results_client(),
        make_state(research_goal="Study of KRAS in cancer"),
    )

    assert result == expected


@pytest.fixture(autouse=True)
def _hermetic_node_model(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_llm(monkeypatch)

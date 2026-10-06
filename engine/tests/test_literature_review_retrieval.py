from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

import co_scientist.evidence as evidence
from co_scientist.agents.generation.literature_review import (
    literature_review_node,
    queries,
    synthesis,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.generation.literature_review import (
    orchestration as lr_orchestration,
)
from co_scientist.agents.reflection import deep_verification_evidence as probes
from co_scientist.config import SearchSourceConfig, ToolRegistry, WorkflowConfig
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS,
)
from co_scientist.evidence import search
from co_scientist.evidence.search_query import broadened_queries
from co_scientist.generator.initial_state import (
    RunCapabilities,
    RunIdentity,
    _build_initial_state,
)
from co_scientist.llm import scoped_campaign_mode
from co_scientist.models import Article
from co_scientist.retrieval_degradation import (
    CAPABILITIES_LOST_WITHOUT_MCP,
    FLOOR_NONE,
    FLOOR_RUN_ATTACHMENTS,
    MCP_UNREACHABLE,
)
from tests._llm_fake import install_fake_llm
from tests._mcp import make_tool_lookup_registry, make_tool_results_client
from tests._research_fakes import (
    _TWO_PAPERS,
    _stub_node,
    _stub_research,
    enable_node_cache,
    install_mcp_client,
    keep_lexical_order,
    make_search_config,
    make_search_run_ctx,
    make_tool_config,
    make_two_source_workflow,
    review_registry,
)
from tests._state import make_state


async def test_probe_search_preserves_sources_and_excludes_retractions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = {
        "W123": {
            "title": "Current evidence",
            "abstract": "A measured result.",
            "_source_name": "openalex",
        },
        "retracted": {
            "title": "Retracted evidence",
            "abstract": "A withdrawn result.",
            "is_retracted": True,
        },
    }

    async def collect(*args: Any) -> tuple[Any, Any]:
        assert args[2].semantic_relevance_enabled is False
        assert args[2].papers_to_read_count == 6
        args[4].append("One source unavailable")
        return records, {}

    monkeypatch.setattr(
        "co_scientist.evidence.search.collect_papers",
        collect,
    )
    monkeypatch.setattr(
        "co_scientist.mcp_client.get_mcp_client",
        AsyncMock(return_value=object()),
    )
    articles, errors = await probes._retrieve_probe_evidence(
        make_state(mcp_available=True), ["measured result"]
    )
    assert [(a.source, a.source_id) for a in articles] == [("openalex", "W123")]
    assert errors == ["One source unavailable"]


def test_shared_evidence_modules_do_not_import_agents() -> None:
    for path in Path(evidence.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text())
        modules = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        modules += [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(
            module.startswith("co_scientist.agents") for module in modules
        ), path


def _state(*, mcp_available: bool, opts: dict[str, Any] | None = None) -> Any:
    return _build_initial_state(
        config_fields={},
        identity=RunIdentity(
            research_goal="reverse fibrosis", start_time=0.0, run_id="run-1"
        ),
        capabilities=RunCapabilities(mcp_available=mcp_available),
        opts=opts or {},
        user_inputs={},
    )


@pytest.mark.parametrize(
    ("mcp_available", "opts", "floor"),
    [
        (False, None, FLOOR_NONE),
        (
            False,
            {"context_enrichment_sources": [{"title": "a memo"}]},
            FLOOR_RUN_ATTACHMENTS,
        ),
    ],
    ids=["no-documents-of-its-own", "run-attachments"],
)
def test_a_run_that_cannot_retrieve_names_what_it_lost(
    mcp_available: bool, opts: dict[str, Any] | None, floor: str
) -> None:
    """Ideas and reviews can look healthy without retrieval; the loss must
    reach the report."""
    degradation = _state(mcp_available=mcp_available, opts=opts)[
        "retrieval_degradation"
    ]

    assert _state(mcp_available=True)["retrieval_degradation"] is None
    assert degradation is not None
    assert degradation["reason"] == MCP_UNREACHABLE
    assert degradation["lost"] == list(CAPABILITIES_LOST_WITHOUT_MCP)
    assert "literature_review" in degradation["lost"]
    assert "deep_research" in degradation["lost"]
    assert degradation["floor"] == floor
    assert json.loads(json.dumps(degradation)) == degradation


@pytest.mark.parametrize(
    ("discovered", "expected"),
    [
        ('["http://paper.pdf", "http://ignored.pdf"]', "http://paper.pdf"),
        ('{"pdf_links": ["http://paper.pdf"]}', "http://paper.pdf"),
        ("http://paper.pdf", "http://paper.pdf"),
        (["http://paper.pdf"], "http://paper.pdf"),
        ("not a URL", None),
        ("[]", None),
        ('{"other": "value"}', None),
        (None, None),
    ],
)
async def test_review_discovers_pdf_urls_without_losing_abstract_evidence(
    monkeypatch: pytest.MonkeyPatch,
    discovered: Any,
    expected: str | None,
) -> None:
    _stub_node(monkeypatch, server_available=True)
    registry = review_registry(
        WorkflowConfig(
            primary_search="search",
            pdf_discovery_tool="discover",
            pdf_discovery_url_field="url",
            content_tool="read",
        ),
        "search",
        "discover",
        "read",
    )
    client = install_mcp_client(
        monkeypatch,
        make_tool_results_client(
            {
                "search": {
                    "paper": {
                        "title": "A",
                        "url": "http://landing",
                        "abstract": "Abstract evidence",
                    }
                },
                "discover": discovered,
                "read": "Retrieved fulltext",
            }
        ),
    )
    result = await literature_review_node(make_state(tool_registry=registry))
    article = result["articles"][0]
    assert article.used_in_analysis
    assert article.content == ("Retrieved fulltext" if expected else None)
    assert [args["url"] for name, args in client.calls if name == "read"] == (
        [expected] if expected else []
    )


@pytest.fixture(autouse=True)
def _hermetic_node_model(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_llm(monkeypatch)


@pytest.mark.parametrize(
    ("ids", "reserved", "budget", "retracted", "expected"),
    [
        (("pm1", "pm2", "c1", "c2"), 0, 2, set(), ["pm1", "pm2"]),
        (
            ("pm1", "pm2", "oa1", "c1", "c2", "c3"),
            2,
            4,
            set(),
            ["c1", "c2", "pm1", "pm2"],
        ),
        (("pm1", "pm2", "pm3", "c1"), 2, 3, set(), ["c1", "pm1", "pm2"]),
        (("c1", "c2", "c3", "pm1"), 3, 2, set(), ["c1", "c2"]),
        (("c1", "c2", "c3"), 2, 3, {"c1", "c2"}, ["c3"]),
        (("pm1", "pm2"), 0, 5, {"pm2"}, ["pm1"]),
        (("c1", "pm1"), 1, -1, set(), []),
        (("c1", "c2", "pm1"), 2, 3, {"c2"}, ["c1", "pm1"]),
    ],
    ids=[
        "unreserved",
        "reserved",
        "underfilled-source",
        "cap",
        "retracted-reservation",
        "retracted-underfilled",
        "nonpositive-budget",
        "no-padding",
    ],
)
async def test_review_respects_reservations_and_excludes_retracted_evidence(
    monkeypatch: pytest.MonkeyPatch,
    ids: tuple[str, ...],
    reserved: int,
    budget: int,
    retracted: set[str],
    expected: list[str],
) -> None:
    ranked = {
        paper_id: {"title": paper_id, "is_retracted": paper_id in retracted}
        for paper_id in ids
    }
    source_map = {
        paper_id: "corpus" if paper_id.startswith("c") else "pubmed"
        for paper_id in ids
    }
    _stub_node(monkeypatch, server_available=True, search_payload=ranked)
    monkeypatch.setattr(
        search,
        "merge_search_results",
        lambda *args, **kwargs: (ranked, source_map),
    )
    registry = ToolRegistry(skip_user_config=True)
    registry.config.workflows = {
        "literature_review": WorkflowConfig(
            search_sources=[
                SearchSourceConfig(tool="corpus", reserved_slots=reserved),
                SearchSourceConfig(tool="pubmed"),
            ]
        )
    }
    registry.config.tools = {
        "tools": {name: make_tool_config(name) for name in ("corpus", "pubmed")}
    }
    result = await literature_review_node(
        make_state(
            research_goal="",
            tool_registry=registry,
            literature_review_papers_count=budget,
        )
    )
    assert [article.source_id for article in result["articles"]] == expected


class _SequencedMCPClient:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        self.calls.append((tool_name, kwargs))
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def _collect_multi_source(
    registry: Any,
    client: Any,
    errors: list[str],
    *,
    papers_per_query: int,
    semantic: bool = True,
) -> tuple[dict[str, Any], dict[str, str]]:
    config = make_search_config(
        tool_registry=cast(ToolRegistry, registry),
        workflow=make_two_source_workflow(papers_per_query),
        is_multi_source=True,
        search_tool_name="unused",
        source_name="mixed",
        papers_to_read_count=10,
    )
    config.semantic_relevance_enabled = semantic
    return await search._phase2_collect_papers_multi_source(
        ["q1"], config, make_search_run_ctx(client, errors, run_id="run-1")
    )


async def test_a_failing_source_keeps_its_healthy_sibling_and_diagnostics() -> (
    None
):
    registry = make_tool_lookup_registry(
        {
            "src_a": make_tool_config(mcp_tool_name="search_europepmc"),
            "src_b": make_tool_config(mcp_tool_name="search_pubmed"),
        }
    )

    class Client:
        async def call_tool(self, name: str, **_: Any) -> Any:
            if name == "search_europepmc":
                return (
                    "Error calling tool 'search_europepmc': "
                    "Europe PMC unavailable: HTTP 503"
                )
            return {"P1": {"title": "Healthy source paper"}}

    errors: list[str] = []

    papers, sources = await _collect_multi_source(
        registry, Client(), errors, papers_per_query=1, semantic=False
    )

    assert set(papers) == {"P1"}
    assert sources == {"P1": "src_b"}
    assert len(errors) == 1
    assert "search_europepmc" in errors[0] and "Europe PMC" in errors[0]
    assert "HTTP 503" in errors[0]


async def test_campaign_scope_skips_a_source_its_policy_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry predates campaign scope; refused sources must be filtered
    before spending retries."""
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    registry = make_tool_lookup_registry(
        {
            "src_a": make_tool_config(mcp_tool_name="search_pubmed"),
            "src_b": make_tool_config(mcp_tool_name="search_web"),
        }
    )
    client = _SequencedMCPClient([{"P1": {"title": "Only PubMed"}}])
    errors: list[str] = []

    with scoped_campaign_mode(True):
        metadata, _ = await _collect_multi_source(
            registry, client, errors, papers_per_query=2, semantic=False
        )

    assert [name for name, _ in client.calls] == ["search_pubmed"]
    assert set(metadata) == {"P1"}
    assert errors == []


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


@pytest.mark.parametrize(
    ("multi_source", "success_level"),
    [(False, 0), (False, 2), (True, 1), (True, None)],
)
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

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.generation.literature_review.research_phase import (
    run_research_phase,
)
from co_scientist.config.schema import (
    ResponseFormat,
    ToolConfig,
    WorkflowConfig,
)
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    LITERATURE_REVIEW_PAPERS_COUNT_DEV,
)
from co_scientist.evidence import (
    article_support,
    relevance,
    search,
    search_support,
)
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.generator.core import HypothesisGenerator
from co_scientist.mcp_client import MCPToolClient
from co_scientist.offline import llm as offline_llm
from tests._llm_fake import install_fake_llm, mock_call_llm_json
from tests._mcp import make_tool_results_client, stub_mcp_availability
from tests._research_fakes import (
    _PAPERS,
    FakeResearchClient,
    _make_event_recorder,
    _ScriptedModel,
    _stub_node,
    install_mcp_client,
    make_search_config,
    provider_registry,
    research_registry,
    research_workflow,
    review_registry,
)
from tests._state import make_state


@pytest.mark.parametrize(
    ("response_format", "payload", "ids"),
    [
        (ResponseFormat(), {"p1": {"title": "A"}}, ["p1"]),
        (ResponseFormat(is_dict=True), {"p1": {"title": "A"}}, ["p1"]),
        (
            ResponseFormat(results_path="results", is_dict=True),
            {"results": {"p1": {"title": "A"}}},
            ["p1"],
        ),
        (
            ResponseFormat(field_mapping={"source_id": "pmid"}),
            [{"pmid": "111", "title": "A"}, {"pmid": "222", "title": "B"}],
            ["111", "222"],
        ),
        (
            ResponseFormat(field_mapping={"source_id": "@id"}),
            [{"arxiv_id": "2401.0001", "title": "A"}],
            ["2401.0001"],
        ),
        (ResponseFormat(), [{"title": "A"}, {"title": "B"}], ["0", "1"]),
    ],
    ids=[
        "keyed",
        "declared-dict",
        "nested",
        "pubmed-list",
        "arxiv-list",
        "positional",
    ],
)
async def test_review_preserves_provider_identifiers(
    monkeypatch: pytest.MonkeyPatch,
    response_format: ResponseFormat,
    payload: Any,
    ids: list[str],
) -> None:
    _stub_node(monkeypatch, server_available=True, search_payload=payload)
    registry = provider_registry(response_format=response_format)
    result = await literature_review_node(make_state(tool_registry=registry))
    assert sorted(article.source_id for article in result["articles"]) == ids
    assert all(not article.used_in_analysis for article in result["articles"])


@pytest.mark.parametrize("payload", ["not a collection", 42, [{"title": "A"}]])
async def test_a_legacy_response_that_is_no_paper_collection_yields_no_papers(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    _stub_node(monkeypatch, server_available=True, search_payload=payload)

    result = await literature_review_node(make_state())

    assert result["articles"] == []
    assert result["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED


def test_published_retraction_metadata_is_explicit_even_outside_search() -> (
    None
):
    # Search excludes withdrawn records; attachments and probes also project
    # articles through this shared publishing boundary.
    articles = article_support.build_articles_from_metadata(
        {
            "flag": {"is_retracted": True, "correction_status": "retracted"},
            "type": {
                "publication_types": [
                    "Journal Article",
                    "Retracted Publication",
                ]
            },
        },
        "pubmed",
    )
    assert all(
        article.is_retracted and article.correction_status == "retracted"
        for article in articles
    )


def test_merge_search_results_ranks_quality_and_flags_retractions() -> None:
    """Retraction overrides source rank even when a source ranks it first."""
    source_results = [
        (
            "openalex",
            {
                "weak": {
                    "title": "Weak",
                    "source": "openalex",
                    "year": 2000,
                },
                "strong": {
                    "title": "Strong",
                    "source": "pubmed",
                    "year": 2026,
                    "cited_by_count": 1000,
                },
                "retracted": {
                    "title": "Retracted",
                    "source": "pubmed",
                    "is_retracted": True,
                },
            },
        )
    ]

    merged, _ = search_support.merge_search_results(source_results)

    assert list(merged) == ["weak", "strong", "retracted"]
    assert merged["retracted"]["correction_status"] == "retracted"


@pytest.mark.parametrize(
    ("state", "env_dev_mode", "dev_mode", "papers"),
    [
        ({"literature_review_papers_count": 12}, None, False, 12),
        (
            {"dev_mode": True, "literature_review_papers_count": 12},
            None,
            True,
            LITERATURE_REVIEW_PAPERS_COUNT_DEV,
        ),
        # The run boundary resolves dev mode; rereading process env changes its
        # budget.
        ({"literature_review_papers_count": 12}, "true", False, 12),
    ],
    ids=["run-count", "dev-mode-from-state", "ambient-env-ignored"],
)
def test_the_run_decides_the_paper_budget_and_dev_mode(
    monkeypatch: pytest.MonkeyPatch,
    state: dict[str, Any],
    env_dev_mode: str | None,
    dev_mode: bool,
    papers: int,
) -> None:
    if env_dev_mode is not None:
        monkeypatch.setenv("COSCIENTIST_DEV_MODE", env_dev_mode)

    config = lr.search_config_for(make_state(**state))

    assert config.is_dev_mode is dev_mode
    assert config.papers_to_read_count == papers


async def test_review_publishes_private_context_with_a_missing_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Initial task options accept plain enrichment records, including private
    # catalog entries whose label has not been supplied.
    stub_mcp_availability(monkeypatch, available=True)
    state = await HypothesisGenerator(
        model_name="test-model"
    ).prepare_task_state(
        "Private evidence",
        opts={
            "context_enrichment_sources": [{}, {"display": "Private finding"}],
        },
    )
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload={
            "paper": {"title": "A", "abstract": "Evidence"},
        },
    )
    result = await literature_review_node(state)
    assert "[C2] External source" in result["articles_with_reasoning"]
    assert "[C3] Private finding" in result["articles_with_reasoning"]
    assert result["context_enrichment_sources"][:2] == [
        {},
        {"display": "Private finding"},
    ]


@pytest.fixture(autouse=True)
def _hermetic_node_model(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_llm(monkeypatch)


async def test_an_unreachable_server_fails_the_review_and_records_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A setup-time outage routes around this node; an outage here must mark
    report degradation."""
    fake_client = _stub_node(monkeypatch, server_available=False)
    state = make_state(research_goal="cancer immunotherapy resistance")
    state["context_enrichment_sources"] = [{"title": "an attachment"}]

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    assert result["literature_review_queries"] == []
    assert result["articles"] == []
    assert result["messages"][0]["metadata"]["error"] is True
    assert fake_client.calls == []
    degradation = result["retrieval_degradation"]
    assert degradation["reason"] == "mcp_unreachable"
    assert degradation["floor"] == "run_attachments"


async def test_abstract_only_papers_are_analyzed_with_bounded_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    papers = {
        "PMID5": {
            "title": "Abstract-only paper",
            "abstract": "Just an abstract, no body.",
        },
    }
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=papers,
        queries=["q"],
    )
    state = make_state(research_goal="abstract only goal")

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == "SYNTHESIZED REVIEW"
    assert result["literature_review_queries"] == ["q"]
    assert len(result["articles"]) == 1
    assert result["articles"][0].source_id == "PMID5"
    assert result["articles"][0].content is None
    assert result["articles"][0].abstract == "Just an abstract, no body."
    assert result["articles"][0].used_in_analysis is True
    assert result["messages"][0]["metadata"]["articles_analyzed"] == 1


async def test_tool_error_envelope_reaches_source_failure_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, callback = _make_event_recorder()
    _stub_node(monkeypatch, server_available=True, queries=["q"])

    class Client:
        async def call_tool(self, _name: str, **_params: Any) -> str:
            return (
                "Error calling tool 'search_europepmc': "
                "Europe PMC unavailable: HTTP 429; Retry-After=60"
            )

    async def get_client(**_: Any) -> Client:
        return Client()

    monkeypatch.setattr(lr, "get_mcp_client", get_client)
    await literature_review_node(
        make_state(research_goal="public evidence", progress_callback=callback)
    )
    errors = [p for e, p in events if e == "literature_review_error"]
    assert errors and errors[0]["search_errors_count"] > 0
    assert any(
        "Europe PMC" in s and "Retry-After=60" in s
        for s in errors[0]["search_error_sample"]
    )
    assert not any(e == "literature_review_empty" for e, _ in events)


@pytest.mark.parametrize(
    ("payload", "display", "count"),
    [
        (
            {
                "statements": [
                    {"subj": {}, "obj": {"name": "MAPK1"}},
                    {"subj": "KRAS", "obj": {"name": "MAPK1"}},
                    {
                        "subj": {"name": "EGFR"},
                        "obj": {"name": "MAPK1"},
                        "type": "Activation",
                        "belief": 0.9,
                    },
                ]
            },
            "EGFR",
            1,
        ),
        (
            {
                "statements": [
                    {
                        "members": [{"name": "BRCA1"}, {"name": "BARD1"}],
                        "type": "Complex",
                        "belief": 0.87,
                    }
                ]
            },
            "Complex(BRCA1, BARD1) [Complex] (belief: 0.87)",
            1,
        ),
        ({"statements": []}, None, 0),
        ({"results": [{"n": i} for i in range(10)]}, "{'n': 0}", 4),
        ({"other": "value"}, "{'other': 'value'}", 1),
        ([{"n": 1}, {"n": 2}], "{'n': 1}", 2),
        (42, "42", 1),
    ],
    ids=[
        "malformed-siblings",
        "complex",
        "empty-statements",
        "capped-results",
        "dict",
        "list",
        "scalar",
    ],
)
async def test_review_appends_enrichment_after_the_paper_citation_namespace(
    monkeypatch: pytest.MonkeyPatch,
    payload: Any,
    display: str | None,
    count: int,
) -> None:
    _stub_node(monkeypatch, server_available=True)
    registry = review_registry(
        WorkflowConfig(
            primary_search="search", context_enrichment_tools=["kg"]
        ),
        "search",
        configs={
            "kg": ToolConfig(
                server="s",
                mcp_tool_name="mcp_kg",
                display_name="Knowledge Graph",
            )
        },
    )
    install_mcp_client(
        monkeypatch,
        make_tool_results_client(
            {
                "search": {"paper": {"title": "A", "abstract": "Evidence"}},
                "mcp_kg": json.dumps(payload)
                if isinstance(payload, (dict, list))
                else payload,
            }
        ),
    )
    result = await literature_review_node(
        make_state(research_goal="Study KRAS in cancer", tool_registry=registry)
    )
    sources = result.get("context_enrichment_sources", [])
    assert len(sources) == count
    if display is None:
        assert (
            "Knowledge Graph Evidence" not in result["articles_with_reasoning"]
        )
    else:
        assert display in result["articles_with_reasoning"]
        assert "[C2]" in result["articles_with_reasoning"]
        assert all(
            source["tool_id"] == "kg" and source["entity"] == "KRAS"
            for source in sources
        )


def _config(tmp_path: Path) -> SearchConfig:
    registry = research_registry(tmp_path)
    return make_search_config(
        tool_registry=registry,
        workflow=research_workflow(registry),
        is_multi_source=True,
        search_tool_name="search_alpha",
        search_tool_config=registry.get_tool("alpha"),
        source_name="alpha",
        papers_to_read_count=4,
        research_goal="reverse fibrosis",
        model_name="offline/test",
    )


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> _ScriptedModel:
    model = _ScriptedModel()
    monkeypatch.setattr("co_scientist.research_adapter.call_llm_json", model)
    return model


def _client() -> MCPToolClient:
    return cast(
        MCPToolClient,
        FakeResearchClient(
            {
                "search_alpha": _PAPERS,
                "read_pdf": {"content": _PAPERS["doc-a"]["abstract"]},
            }
        ),
    )


async def test_research_seeds_are_unique_and_bounded_by_first_level_breadth(
    tmp_path: Path,
    scripted: _ScriptedModel,
) -> None:
    analyses = [
        {"analysis": {"gaps_identified": "No human data"}},
        {"analysis": {"gaps_identified": "no human data  "}},
        *[{"analysis": {"unexplored_areas": f"Gap {i}"}} for i in range(10)],
    ]
    outcome = await run_research_phase(
        make_state(research_tier="extended"),
        _config(tmp_path),
        _client(),
        analyses,
    )
    assert outcome is not None
    asked = [thread["question"]["text"] for thread in outcome.ledger["threads"]]
    assert asked.count("No human data") == 1
    assert "no human data  " not in asked
    assert len(asked) <= 8
    assert asked[0] == "No human data"


def _candidate(title: str, lexical_score: float) -> dict[str, object]:
    return {
        "title": title,
        "abstract": f"Abstract for {title}.",
        "retrieval_score": lexical_score,
    }


def _pool(n: int) -> dict[str, dict[str, object]]:
    return {
        f"p{i}": _candidate(f"Paper {i}", 1.0 - i / (n + 1))
        for i in range(1, n + 1)
    }


async def _ranked_review(
    monkeypatch: pytest.MonkeyPatch,
    pool: dict[str, Any],
    *,
    goal: str = "goal",
    count: int | None = None,
) -> dict[str, Any]:
    _stub_node(monkeypatch, server_available=True, search_payload=pool)
    monkeypatch.setattr(
        search, "merge_search_results", lambda *args, **kwargs: (pool, {})
    )
    result = await literature_review_node(
        make_state(
            research_goal=goal,
            model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
            literature_review_papers_count=len(pool)
            if count is None
            else count,
        )
    )
    return {article.source_id: article for article in result["articles"]}


async def test_review_semantic_failure_preserves_lexical_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_call_llm_json(
        monkeypatch, relevance, side_effect=RuntimeError("provider exploded")
    )
    papers = await _ranked_review(monkeypatch, _pool(2))
    assert len(papers) == 2
    assert all(
        article.retrieval_rationale == relevance._FAILED_JUDGMENT_RATIONALE
        for article in papers.values()
    )


async def test_review_with_negative_budget_keeps_only_lexical_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_judgment(**_: Any) -> Any:
        pytest.fail("A nonpositive budget must not purchase semantic judgments")

    monkeypatch.setattr(relevance, "call_llm_json", unexpected_judgment)
    result = await _ranked_review(
        monkeypatch,
        {
            "low": _candidate("Low", -0.2),
            "high": _candidate("High", 1.5),
            "spare": _candidate("Spare", 0.5),
        },
        count=-1,
    )
    assert result["low"].retrieval_score == 0.0
    assert result["high"].retrieval_score == 1.0
    assert all(
        article.retriever_version == relevance._LEXICAL_ONLY_VERSION
        for article in result.values()
    )

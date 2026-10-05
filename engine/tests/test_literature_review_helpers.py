from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
    synthesis,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.config import ToolRegistry
from co_scientist.config.schema import ResponseFormat
from co_scientist.constants import LITERATURE_REVIEW_PAPERS_COUNT_DEV
from co_scientist.evidence import article_support, search_support
from co_scientist.evidence import retrieval_support as errors
from co_scientist.generator.core import HypothesisGenerator
from tests._llm_fake import install_fake_llm
from tests._mcp import stub_mcp_availability
from tests._research_fakes import _stub_node, make_tool_config
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
    registry = ToolRegistry(skip_user_config=True)
    registry.config.workflows["literature_review"].search_sources = []
    registry.config.workflows["literature_review"].primary_search = "provider"
    registry.config.tools = {
        "search": {
            "provider": make_tool_config(
                "provider", response_format=response_format
            )
        }
    }
    result = await literature_review_node(make_state(tool_registry=registry))
    assert sorted(article.source_id for article in result["articles"]) == ids
    assert all(not article.used_in_analysis for article in result["articles"])


@pytest.mark.parametrize(
    ("mapping", "source_type", "expected"),
    [
        ({"source": "'pubmed'"}, "academic", "pubmed"),
        ({"source": "paper.source"}, "preprint", "preprint"),
        ({}, "arxiv", "arxiv"),
    ],
)
async def test_review_retains_the_configured_source_label(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, str],
    source_type: str,
    expected: str,
) -> None:
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload={"p1": {"title": "A"}},
    )
    registry = ToolRegistry(skip_user_config=True)
    registry.config.workflows["literature_review"].search_sources = []
    registry.config.workflows["literature_review"].primary_search = "provider"
    registry.config.tools = {
        "search": {
            "provider": make_tool_config(
                "provider",
                source_type=source_type,
                response_format=ResponseFormat(field_mapping=mapping),
            )
        }
    }
    result = await literature_review_node(make_state(tool_registry=registry))
    assert result["articles"][0].source == expected


@pytest.mark.parametrize("payload", ["not a collection", 42, [{"title": "A"}]])
def test_legacy_unconfigured_response_cannot_invent_paper_records(
    payload: Any,
) -> None:
    assert search_support.normalize_search_response(payload, None) == {}
    assert search_support.extract_source_name(None) == "unknown"


async def test_review_publishes_metadata_and_keeps_metadata_only_papers_unused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    papers = {
        "PMID42": {
            "title": "Cancer signaling",
            "authors": ["Smith J", "Doe A"],
            "year": "2020",
            "publication": "Nature",
            "abstract": "An abstract.",
            "fulltext": "Full body text.",
            "url": "https://example.com/article",
            "doi": "10.1000/example",
        },
        "metadata": {},
        "preprint": {"publication_types": ["Preprint"], "venue": "JMLR"},
        "explicit": {
            "publication_type": "Journal Article",
            "publication_types": ["x"],
        },
    }
    _stub_node(monkeypatch, server_available=True, search_payload=papers)
    result = await literature_review_node(make_state())
    articles = {article.source_id: article for article in result["articles"]}
    published = articles["PMID42"]
    assert (
        published.title,
        published.url,
        published.authors,
        published.year,
        published.venue,
    ) == (
        "Cancer signaling",
        "https://example.com/article",
        ["Smith J", "Doe A"],
        2020,
        "Nature",
    )
    assert (
        published.abstract,
        published.content,
        published.source,
        published.doi,
        published.used_in_analysis,
    ) == (
        "An abstract.",
        "Full body text.",
        "pubmed",
        "10.1000/example",
        True,
    )
    empty = articles["metadata"]
    assert (
        empty.title,
        empty.authors,
        empty.year,
        empty.venue,
        empty.abstract,
        empty.content,
        empty.used_in_analysis,
    ) == (
        "unknown",
        [],
        None,
        None,
        None,
        None,
        False,
    )
    assert articles["preprint"].publication_type == "Preprint"
    assert articles["preprint"].venue == "JMLR"
    assert articles["explicit"].publication_type == "Journal Article"
    assert empty.publication_type is None


@pytest.mark.parametrize(
    ("paper_id", "source", "metadata", "url", "year"),
    [
        (
            "999",
            "pubmed",
            {"url": "https://custom.example/x", "year": "2019"},
            "https://custom.example/x",
            2019,
        ),
        (
            "12345",
            "pubmed",
            {"year": 2007},
            "https://pubmed.ncbi.nlm.nih.gov/12345/",
            2007,
        ),
        (
            "10.1000/xyz123",
            "crossref",
            {"date_revised": "2021/03/01"},
            "https://doi.org/10.1000/xyz123",
            2021,
        ),
        (
            "arxiv:2401.0001",
            "arxiv",
            {"year": "not-a-year"},
            "arxiv:2401.0001",
            None,
        ),
        ("empty", "arxiv", {}, "empty", None),
        (
            "date",
            "arxiv",
            {"year": "", "date_revised": "1998/12/31"},
            "date",
            1998,
        ),
    ],
)
async def test_review_publishes_source_locators_and_dates(
    monkeypatch: pytest.MonkeyPatch,
    paper_id: str,
    source: str,
    metadata: dict[str, Any],
    url: str,
    year: int | None,
) -> None:
    _stub_node(
        monkeypatch, server_available=True, search_payload={paper_id: metadata}
    )
    registry = ToolRegistry(skip_user_config=True)
    registry.config.workflows["literature_review"].search_sources = []
    registry.config.workflows["literature_review"].primary_search = "provider"
    registry.config.tools = {
        "search": {"provider": make_tool_config("provider", source_type=source)}
    }
    result = await literature_review_node(make_state(tool_registry=registry))
    article = result["articles"][0]
    assert (article.source_id, article.url, article.year) == (
        paper_id,
        url,
        year,
    )


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


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"fulltext": "full", "abstract": "abs"}, "full"),
        ({"abstract": "abs"}, "abs"),
        (
            {"fulltext": "This was shown before (Smith et al. 2019) [12]."},
            "This was shown before  .",
        ),
    ],
)
async def test_review_analyzes_a_sanitized_copy_of_available_evidence(
    monkeypatch: pytest.MonkeyPatch,
    metadata: dict[str, Any],
    expected: str,
) -> None:
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload={"paper": {"title": "A", **metadata}},
    )
    prompts: list[str] = []

    async def analyze(*, prompt: str, **_: Any) -> dict[str, Any]:
        prompts.append(prompt)
        return {"key_findings": "Evidence"}

    monkeypatch.setattr(synthesis, "call_llm_json", analyze)
    result = await literature_review_node(make_state())
    assert expected in prompts[0]
    assert "(Smith et al. 2019)" not in prompts[0]
    assert "[12]" not in prompts[0]
    if "fulltext" in metadata:
        assert result["articles"][0].content == str(metadata["fulltext"])


def test_analysis_copy_obeys_the_callers_text_limit() -> None:
    # The node uses the default cap; other evidence callers supply shorter
    # budgets through this shared interface.
    assert article_support.get_paper_content_for_analysis({}) == ""
    assert (
        article_support.get_paper_content_for_analysis({"fulltext": 12345})
        == "12345"
    )
    assert (
        article_support.get_paper_content_for_analysis(
            {"fulltext": "short"}, max_chars=100
        )
        == "short"
    )
    out = article_support.get_paper_content_for_analysis(
        {"fulltext": "x" * 500}, max_chars=100
    )
    assert out == "x" * 100 + "\n\n[... truncated for length ...]"


def test_merge_search_results_combines_and_maps_sources() -> None:
    source_results = [
        ("pubmed", {"p1": {"title": "Alpha"}}),
        ("arxiv", {"a1": {"title": "Beta"}}),
    ]
    merged, source_map = search_support.merge_search_results(source_results)
    assert set(merged) == {"p1", "a1"}
    assert source_map == {"p1": "pubmed", "a1": "arxiv"}


def test_merge_search_results_deduplicates_by_title() -> None:
    source_results = [
        ("pubmed", {"p1": {"title": "Shared Title"}}),
        ("arxiv", {"a1": {"title": "  shared title  "}}),
    ]
    merged, source_map = search_support.merge_search_results(source_results)
    assert set(merged) == {"p1"}
    assert source_map == {"p1": "pubmed"}


def test_merge_search_results_no_dedup_keeps_duplicates() -> None:
    source_results = [
        ("pubmed", {"p1": {"title": "Same"}}),
        ("arxiv", {"a1": {"title": "Same"}}),
    ]
    merged, _ = search_support.merge_search_results(
        source_results, deduplicate=False
    )
    assert set(merged) == {"p1", "a1"}


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


def test_merge_search_results_lets_a_metadata_poor_source_compete() -> None:
    """Source-rank fusion avoids penalizing sources without citation/year
    metadata."""
    rich_source: dict[str, dict[str, Any]] = {
        f"op{i}": {
            "title": f"Openalex paper {i}",
            "source": "openalex",
            "cited_by_count": 500,
            "year": 2020,
        }
        for i in range(1, 7)
    }
    source_results = [
        ("openalex_tool", rich_source),
        ("web_tool", {"web1": {"title": "Web paper", "source": "web"}}),
    ]

    merged, _ = search_support.merge_search_results(source_results)

    assert list(merged).index("web1") <= 2


def test_merge_search_results_accumulates_cross_source_agreement() -> None:
    """Title dedup must keep both source rank contributions without
    overwrites."""
    source_results = [
        (
            "source_a_tool",
            {
                "solo": {"title": "Solo Paper"},
                "shared_a": {"title": "Shared Paper", "note": "from A"},
                "filler_a": {"title": "Filler A"},
            },
        ),
        (
            "source_b_tool",
            {
                "other_b": {"title": "Other B"},
                "shared_b": {"title": "Shared Paper", "note": "from B"},
                "filler_b": {"title": "Filler B"},
            },
        ),
    ]

    merged, source_map = search_support.merge_search_results(source_results)

    assert list(merged).index("shared_a") < list(merged).index("solo")
    # Dedup accumulates rank while preserving first-source metadata/provenance.
    assert "shared_b" not in merged
    assert merged["shared_a"]["note"] == "from A"
    assert source_map["shared_a"] == "source_a_tool"


class _FakeExceptionGroupError(Exception):
    """Duck-typed stand-in for ``ExceptionGroup`` (portable to Python 3.10).

    Exposes the ``exceptions`` tuple that ``describe_exception`` unwraps,
    mirroring the real ``ExceptionGroup`` the anyio-based MCP transport raises.
    """

    def __init__(self, message: str, exceptions: list[BaseException]) -> None:
        super().__init__(message)
        self.exceptions = tuple(exceptions)


def test_describe_exc_plain_exception() -> None:
    assert (
        errors.describe_exception(ValueError("bad input"))
        == "ValueError: bad input"
    )


def test_describe_exc_unwraps_exception_group() -> None:
    leaf = ConnectionError("All connection attempts failed")
    group = _FakeExceptionGroupError("unhandled errors in a TaskGroup", [leaf])
    assert (
        errors.describe_exception(group)
        == "ConnectionError: All connection attempts failed"
    )


def test_get_search_config_defaults_single_source() -> None:
    config = lr.search_config_for(make_state())
    assert config.is_multi_source is False
    assert config.source_name == "pubmed"
    assert config.search_tool_name == "pubmed_search_with_fulltext"
    assert config.search_tool_config is None
    assert config.tool_registry is None
    assert config.papers_to_read_count > 0


def test_get_search_config_honors_run_paper_count() -> None:
    config = lr.search_config_for(make_state(literature_review_papers_count=12))
    assert config.papers_to_read_count == 12


def test_get_search_config_reads_dev_mode_from_state() -> None:
    config = lr.search_config_for(
        make_state(dev_mode=True, literature_review_papers_count=12)
    )
    assert config.is_dev_mode is True
    assert config.papers_to_read_count == LITERATURE_REVIEW_PAPERS_COUNT_DEV


def test_get_search_config_ignores_the_ambient_dev_mode_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run boundary resolves dev mode; rereading process env changes its
    budget."""
    monkeypatch.setenv("COSCIENTIST_DEV_MODE", "true")
    config = lr.search_config_for(make_state(literature_review_papers_count=12))
    assert config.is_dev_mode is False
    assert config.papers_to_read_count == 12


def test_literature_cache_key_covers_tool_contract_and_budget() -> None:
    legacy_state = make_state(
        model_name="model-a", literature_review_papers_count=4
    )
    registry_state = make_state(
        model_name="model-a",
        literature_review_papers_count=8,
        tool_registry=ToolRegistry(skip_user_config=True),
    )
    legacy = lr._literature_cache_params(
        legacy_state, lr.search_config_for(legacy_state)
    )
    multi_source = lr._literature_cache_params(
        registry_state, lr.search_config_for(registry_state)
    )

    assert legacy["cache_schema_version"] == 3
    assert legacy["papers_to_read_count"] == 4
    assert legacy["tool_contract"]["legacy_search_tool"] == (
        "pubmed_search_with_fulltext"
    )
    assert multi_source["papers_to_read_count"] == 8
    workflow = multi_source["tool_contract"]["workflows"]["literature_review"]
    # The literature review searches the public databases; the group's own
    # papers reach a run as an injected catalog, not as a search source.
    assert [source["tool"] for source in workflow["search_sources"]] == [
        "pubmed_fulltext",
        "openalex_search",
        "europepmc_search",
        "web_search",
        "arxiv_search",
        "biorxiv_search",
    ]
    assert legacy != multi_source


def test_a_tier_that_researches_cannot_replay_one_that_did_not() -> None:
    """Cross-tier cache reuse can import or erase another tier research
    ledger."""
    shallow = make_state(model_name="model-a", research_tier="")
    deep = make_state(model_name="model-a", research_tier="extended")

    assert lr._literature_cache_params(
        shallow, lr.search_config_for(shallow)
    ) != lr._literature_cache_params(deep, lr.search_config_for(deep))


async def test_review_threads_goal_and_user_literature_into_each_model_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.agents.generation.literature_review import queries

    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload={
            "paper": {
                "title": "Measured signaling",
                "authors": ["Scientist Author"],
                "year": 2024,
                "fulltext": "A specific measured mechanism.",
            }
        },
    )
    captured: dict[str, str] = {}

    async def query(*, prompt: str, **_: Any) -> dict[str, Any]:
        captured["query"] = prompt
        return {"queries": ["specific signaling"]}

    async def analyze(*, prompt: str, **_: Any) -> dict[str, Any]:
        captured["analysis"] = prompt
        return {"key_findings": "A measured finding to synthesize"}

    async def synthesize(*, prompt: str, **_: Any) -> str:
        captured["synthesis"] = prompt
        return "Completed synthesis"

    monkeypatch.setattr(queries, "call_llm_json", query)
    monkeypatch.setattr(synthesis, "call_llm_json", analyze)
    monkeypatch.setattr(synthesis, "call_llm", synthesize)
    result = await literature_review_node(
        make_state(
            research_goal="Explain specific signaling",
            literature=["User supplied signaling literature"],
        )
    )
    assert "User supplied signaling literature" in captured["query"]
    assert all(
        "Explain specific signaling" in prompt for prompt in captured.values()
    )
    assert all(
        text in captured["analysis"]
        for text in (
            "Measured signaling",
            "Scientist Author",
            "2024",
            "A specific measured mechanism.",
        )
    )
    assert "A measured finding to synthesize" in captured["synthesis"]
    assert "{{MISSING" not in captured["query"]
    assert "{{MISSING" not in captured["synthesis"]
    assert result["articles_with_reasoning"] == "Completed synthesis"


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

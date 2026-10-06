from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.config.schema import ResponseFormat
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    LITERATURE_REVIEW_PAPERS_COUNT_DEV,
)
from co_scientist.evidence import article_support, search_support
from co_scientist.generator.core import HypothesisGenerator
from tests._llm_fake import install_fake_llm
from tests._mcp import stub_mcp_availability
from tests._research_fakes import (
    _stub_node,
    provider_registry,
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

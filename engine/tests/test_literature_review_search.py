"""Ranked, deduplicated literature-search collection tests."""

from typing import Any, cast

import pytest

from co_scientist.mcp_client import MCPToolClient
from co_scientist.nodes.literature_review import search
from co_scientist.nodes.literature_review.search_support import SearchConfig
from co_scientist.state import WorkflowState


@pytest.mark.asyncio
async def test_single_source_overfetches_dedupes_ranks_and_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expanded queries fill one unique, quality-ranked evidence budget."""
    observed: dict[str, int] = {}

    async def fake_search_all_queries(
        queries: list[str],
        papers_per_query: int,
        remainder: int,
        *_args: Any,
        **_kwargs: Any,
    ) -> list[tuple[int, dict[str, dict[str, Any]]]]:
        observed["queries"] = len(queries)
        observed["papers_per_query"] = papers_per_query
        observed["remainder"] = remainder
        return [
            (
                1,
                {
                    "p1": {
                        "title": "Shared paper",
                        "source": "pubmed",
                        "year": 2025,
                    },
                    "p2": {
                        "title": "Independent paper",
                        "source": "pubmed",
                        "year": 2024,
                    },
                },
            ),
            (
                2,
                {
                    "duplicate": {
                        "title": "shared paper",
                        "source": "pubmed",
                        "year": 2025,
                    },
                    "p3": {
                        "title": "Third paper",
                        "source": "pubmed",
                        "year": 2023,
                    },
                    "retracted": {
                        "title": "Retracted paper",
                        "source": "pubmed",
                        "year": 2026,
                        "is_retracted": True,
                    },
                },
            ),
        ]

    monkeypatch.setattr(search, "_search_all_queries", fake_search_all_queries)
    config = SearchConfig(
        tool_registry=None,
        workflow=None,
        is_multi_source=False,
        search_tool_name="pubmed_fulltext",
        search_tool_config=None,
        source_name="pubmed",
        papers_to_read_count=3,
        is_dev_mode=False,
    )

    papers, source_map = await search._phase2_collect_papers_single_source(
        ["expanded one", "expanded two"],
        "slug",
        cast(WorkflowState, {"run_id": "run-1"}),
        config,
        cast(MCPToolClient, object()),
    )

    assert observed == {
        "queries": 2,
        "papers_per_query": 3,
        "remainder": 0,
    }
    assert list(papers) == ["p1", "p2", "p3"]
    assert "duplicate" not in papers
    assert "retracted" not in papers
    assert source_map == {}

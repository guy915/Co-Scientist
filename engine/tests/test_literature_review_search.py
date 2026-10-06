from __future__ import annotations

from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.config import SearchSourceConfig, ToolRegistry, WorkflowConfig
from co_scientist.evidence import search
from co_scientist.llm import scoped_campaign_mode
from tests._mcp import make_tool_lookup_registry
from tests._research_fakes import (
    _stub_node,
    make_search_config,
    make_search_run_ctx,
    make_tool_config,
    make_two_source_workflow,
)
from tests._state import make_state


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

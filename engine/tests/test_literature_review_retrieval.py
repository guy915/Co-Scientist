from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

import co_scientist.evidence as evidence
from co_scientist.agents.reflection import deep_verification_evidence as probes
from co_scientist.config import ToolRegistry
from co_scientist.evidence import search
from co_scientist.generator.initial_state import (
    RunCapabilities,
    RunIdentity,
    _build_initial_state,
)
from co_scientist.llm import scoped_campaign_mode
from co_scientist.retrieval_degradation import (
    CAPABILITIES_LOST_WITHOUT_MCP,
    FLOOR_NONE,
    FLOOR_RUN_ATTACHMENTS,
    MCP_UNREACHABLE,
)
from tests._llm_fake import install_fake_llm
from tests._mcp import make_tool_lookup_registry
from tests._research_fakes import (
    make_search_config,
    make_search_run_ctx,
    make_tool_config,
    make_two_source_workflow,
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


def _state(*, mcp_available: bool, opts: dict[str, Any] | None = None) -> Any:
    return _build_initial_state(
        config_fields={},
        identity=RunIdentity(research_goal="reverse fibrosis", start_time=0.0, run_id="run-1"),
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
    degradation = _state(mcp_available=mcp_available, opts=opts)["retrieval_degradation"]

    assert _state(mcp_available=True)["retrieval_degradation"] is None
    assert degradation is not None
    assert degradation["reason"] == MCP_UNREACHABLE
    assert degradation["lost"] == list(CAPABILITIES_LOST_WITHOUT_MCP)
    assert "literature_review" in degradation["lost"]
    assert "deep_research" in degradation["lost"]
    assert degradation["floor"] == floor
    assert json.loads(json.dumps(degradation)) == degradation


@pytest.fixture(autouse=True)
def _hermetic_node_model(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_llm(monkeypatch)


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


async def test_a_failing_source_keeps_its_healthy_sibling_and_diagnostics() -> None:
    registry = make_tool_lookup_registry(
        {
            "src_a": make_tool_config(mcp_tool_name="search_europepmc"),
            "src_b": make_tool_config(mcp_tool_name="search_pubmed"),
        }
    )

    class Client:
        async def call_tool(self, name: str, **_: Any) -> Any:
            if name == "search_europepmc":
                return "Error calling tool 'search_europepmc': Europe PMC unavailable: HTTP 503"
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


def test_shared_evidence_modules_do_not_import_agents() -> None:
    for path in Path(evidence.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text())
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(module.startswith("co_scientist.agents") for module in modules), path

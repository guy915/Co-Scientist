from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import co_scientist.evidence as evidence
from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.reflection import deep_verification_evidence as probes
from co_scientist.config import ToolRegistry
from co_scientist.config.schema import SearchSourceConfig, WorkflowConfig
from co_scientist.evidence import retrieval_support as rs
from co_scientist.generator.initial_state import (
    RunCapabilities,
    RunIdentity,
    _build_initial_state,
)
from co_scientist.retrieval_degradation import (
    CAPABILITIES_LOST_WITHOUT_MCP,
    FLOOR_NONE,
    FLOOR_RUN_ATTACHMENTS,
    MCP_UNREACHABLE,
    resolve_retrieval_degradation,
)
from tests._llm_fake import install_fake_llm
from tests._mcp import make_tool_results_client
from tests._research_fakes import _stub_node, make_tool_config
from tests._state import make_state


@pytest.mark.parametrize("mode", ["single", "multi", "override"])
async def test_review_routes_discovery_and_content_by_source(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    _stub_node(monkeypatch, server_available=True, queries=["query"])
    registry = ToolRegistry(skip_user_config=True)
    workflow = WorkflowConfig(
        primary_search="search",
        pdf_discovery_tool="discover",
        pdf_discovery_url_field="landing",
        content_tool="read",
        content_url_field="pdf_url",
        content_params={
            "goal": "{research_goal}",
            "depth": "workflow",
            "focus": "{focus_areas}",
        },
    )
    if mode != "single":
        source = SearchSourceConfig(tool="search")
        if mode == "override":
            source.pdf_discovery_tool = "source_discover"
            source.pdf_discovery_url_field = "source_landing"
            source.content_tool = "source_read"
            source.content_params = {"depth": "source", "extra": "source-only"}
        workflow.search_sources = [source]
    registry.config.workflows = {"literature_review": workflow}
    registry.config.tools = {
        "tools": {
            name: make_tool_config(name)
            for name in (
                "search",
                "discover",
                "read",
                "source_discover",
                "source_read",
            )
        }
    }
    papers = {
        "fetch": {
            "title": "Fetch",
            "landing": "http://landing",
            "source_landing": "http://override",
        },
        "existing": {
            "title": "Existing",
            "pdf_url": "http://existing.pdf",
            "fulltext": "Already retrieved",
        },
        "abstract": {"title": "Abstract", "abstract": "Abstract evidence"},
    }
    client = make_tool_results_client(
        {
            "search": papers,
            "discover": '["http://discovered.pdf"]',
            "source_discover": '["http://discovered.pdf"]',
            "read": {"content": "Retrieved evidence"},
            "source_read": {"content": "Retrieved evidence"},
        }
    )

    async def get_client(**_: Any) -> Any:
        return client

    monkeypatch.setattr(lr, "get_mcp_client", get_client)
    result = await literature_review_node(
        make_state(
            research_goal="understand signaling",
            tool_registry=registry,
        )
    )

    articles = {article.source_id: article for article in result["articles"]}
    assert articles["fetch"].content == "Retrieved evidence"
    assert articles["existing"].content == "Already retrieved"
    assert articles["abstract"].used_in_analysis
    discovery = "source_discover" if mode == "override" else "discover"
    reader = "source_read" if mode == "override" else "read"
    assert (
        discovery,
        {"url": "http://override" if mode == "override" else "http://landing"},
    ) in client.calls
    params: dict[str, Any] = {
        "url": "http://discovered.pdf",
        "goal": "understand signaling",
        "depth": "source" if mode == "override" else "workflow",
        "focus": [],
    }
    if mode == "override":
        params["extra"] = "source-only"
    assert (reader, params) in client.calls
    assert not any(
        args.get("url") == "http://existing.pdf" for _, args in client.calls
    )


@pytest.mark.parametrize(
    "missing", ["workflow", "registry", "unconfigured", "dangling"]
)
def test_unavailable_retrieval_configuration_preserves_abstract_fallback(
    missing: str,
) -> None:
    registry = ToolRegistry(skip_user_config=True)
    registry.config.tools = {}
    workflow = WorkflowConfig()
    if missing == "dangling":
        workflow.content_tool = workflow.pdf_discovery_tool = "ghost"
    resolved_workflow = None if missing == "workflow" else workflow
    resolved_registry = None if missing == "registry" else registry
    assert (
        rs.build_content_config(resolved_workflow, resolved_registry, False)
        == {}
    )
    assert (
        rs.build_pdf_discovery_config(
            resolved_workflow, resolved_registry, False
        )
        == {}
    )


def test_retrieval_eligibility_ignores_malformed_and_unroutable_records() -> (
    None
):
    # Providers may return non-record entries; search normalization normally
    # filters them before the node sees them.
    metadata: dict[str, Any] = {
        "malformed": "not a record",
        "missing": {},
        "complete": {"pdf_url": "http://complete.pdf", "fulltext": "body"},
        "eligible": {"url": "http://landing", "pdf_url": "http://paper.pdf"},
        "unrouted": {"url": "http://unknown", "pdf_url": "http://unknown.pdf"},
    }
    source_map = {"unrouted": "missing"}
    content = {"_default": rs.ContentToolConfig("read", "pdf_url", {})}
    assert [
        pid
        for pid, *_ in rs.get_papers_needing_content(
            metadata, source_map, content
        )
    ] == ["eligible", "unrouted"]
    assert rs.get_papers_needing_content(metadata, source_map, {}) == []
    assert rs.get_papers_needing_pdf_discovery(metadata, source_map, {}) == []
    metadata["eligible"].pop("pdf_url")
    assert [
        pid
        for pid, *_ in rs.get_papers_needing_pdf_discovery(
            metadata, source_map, {"_default": ("discover", "url")}
        )
    ] == ["eligible"]
    assert rs.get_papers_needing_content({}, {}, content) == []
    assert rs.get_papers_needing_pdf_discovery({}, {}, {}) == []


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


def test_a_run_that_can_retrieve_reports_nothing() -> None:
    assert _state(mcp_available=True)["retrieval_degradation"] is None


def test_a_run_that_cannot_retrieve_names_what_it_lost() -> None:
    """Ideas and reviews can look healthy without retrieval; the loss must
    reach the report."""
    degradation = _state(mcp_available=False)["retrieval_degradation"]

    assert degradation is not None
    assert degradation["reason"] == MCP_UNREACHABLE
    assert degradation["lost"] == list(CAPABILITIES_LOST_WITHOUT_MCP)
    assert "literature_review" in degradation["lost"]
    assert "deep_research" in degradation["lost"]


def test_with_no_documents_of_its_own_the_floor_is_nothing() -> None:
    degradation = _state(mcp_available=False)["retrieval_degradation"]

    assert degradation is not None
    assert degradation["floor"] == FLOOR_NONE


def test_a_run_with_attachments_still_has_those() -> None:
    degradation = _state(
        mcp_available=False,
        opts={"context_enrichment_sources": [{"title": "a memo"}]},
    )["retrieval_degradation"]

    assert degradation is not None
    assert degradation["floor"] == FLOOR_RUN_ATTACHMENTS


def test_the_fact_is_plain_data() -> None:
    import json

    degradation = resolve_retrieval_degradation(
        mcp_available=False, private_sources=None
    )

    assert json.loads(json.dumps(degradation)) == degradation


@pytest.mark.parametrize(
    ("discovered", "expected"),
    [
        ('["http://paper.pdf", "http://ignored.pdf"]', "http://paper.pdf"),
        ('{"pdf_links": ["http://paper.pdf"]}', "http://paper.pdf"),
        ('{"links": [{"url": "http://paper.pdf"}]}', "http://paper.pdf"),
        ("http://paper.pdf", "http://paper.pdf"),
        (["http://paper.pdf"], "http://paper.pdf"),
        ([{"url": "http://paper.pdf"}], "http://paper.pdf"),
        ("not a URL", None),
        ("[]", None),
        ('{"other": "value"}', None),
        ("42", None),
        ([], None),
        (None, None),
    ],
)
async def test_review_discovers_pdf_urls_without_losing_abstract_evidence(
    monkeypatch: pytest.MonkeyPatch,
    discovered: Any,
    expected: str | None,
) -> None:
    _stub_node(monkeypatch, server_available=True)
    registry = ToolRegistry(skip_user_config=True)
    registry.config.workflows = {
        "literature_review": WorkflowConfig(
            primary_search="search",
            pdf_discovery_tool="discover",
            pdf_discovery_url_field="url",
            content_tool="read",
        )
    }
    registry.config.tools = {
        "tools": {
            name: make_tool_config(name)
            for name in ("search", "discover", "read")
        }
    }
    client = make_tool_results_client(
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
    )

    async def get_client(**_: Any) -> Any:
        return client

    monkeypatch.setattr(lr, "get_mcp_client", get_client)
    result = await literature_review_node(make_state(tool_registry=registry))
    article = result["articles"][0]
    assert article.used_in_analysis
    assert article.content == ("Retrieved fulltext" if expected else None)
    assert [args["url"] for name, args in client.calls if name == "read"] == (
        [expected] if expected else []
    )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ('{"content": "body", "text": "ignored"}', "body"),
        ('{"text": "body"}', "body"),
        ("plain text", "plain text"),
        ('{"other": "x"}', '{"other": "x"}'),
        ({"content": "body"}, "body"),
        ({"other": "x"}, "{'other': 'x'}"),
        (123, "123"),
        (None, None),
        (0, None),
    ],
)
async def test_review_publishes_content_responses_and_retains_abstract_fallback(
    monkeypatch: pytest.MonkeyPatch,
    payload: Any,
    expected: str | None,
) -> None:
    _stub_node(monkeypatch, server_available=True)
    registry = ToolRegistry(skip_user_config=True)
    registry.config.workflows = {
        "literature_review": WorkflowConfig(
            primary_search="search", content_tool="read"
        )
    }
    registry.config.tools = {
        "tools": {name: make_tool_config(name) for name in ("search", "read")}
    }
    client = make_tool_results_client(
        {
            "search": {
                "paper": {
                    "title": "A",
                    "pdf_url": "http://paper.pdf",
                    "abstract": "Abstract evidence",
                }
            },
            "read": payload,
        }
    )

    async def get_client(**_: Any) -> Any:
        return client

    monkeypatch.setattr(lr, "get_mcp_client", get_client)
    result = await literature_review_node(make_state(tool_registry=registry))
    assert result["articles"][0].content == expected
    assert result["articles"][0].used_in_analysis


@pytest.mark.parametrize("failed_tool", ["discover", "read"])
async def test_review_retrieval_failure_preserves_successful_siblings(
    monkeypatch: pytest.MonkeyPatch,
    failed_tool: str,
) -> None:
    _stub_node(monkeypatch, server_available=True)
    registry = ToolRegistry(skip_user_config=True)
    registry.config.workflows = {
        "literature_review": WorkflowConfig(
            search_sources=[
                SearchSourceConfig(tool="good"),
                SearchSourceConfig(
                    tool="bad",
                    pdf_discovery_tool="bad_discover",
                    content_tool="bad_read",
                ),
            ],
            pdf_discovery_tool="discover",
            content_tool="read",
        )
    }
    registry.config.tools = {
        "tools": {
            name: make_tool_config(name)
            for name in (
                "good",
                "bad",
                "discover",
                "read",
                "bad_discover",
                "bad_read",
            )
        }
    }
    client = make_tool_results_client(
        {
            "good": {
                "good": {
                    "title": "Good",
                    "url": "http://good",
                    "abstract": "Good abstract",
                }
            },
            "bad": {
                "bad": {
                    "title": "Bad",
                    "url": "http://bad",
                    "abstract": "Bad abstract",
                }
            },
            "discover": '["http://good.pdf"]',
            "bad_discover": '["http://bad.pdf"]',
            "read": "Good body",
            "bad_read": "Bad body",
        },
        error_tools={"bad_" + failed_tool},
    )

    async def get_client(**_: Any) -> Any:
        return client

    monkeypatch.setattr(lr, "get_mcp_client", get_client)
    result = await literature_review_node(make_state(tool_registry=registry))
    articles = {article.source_id: article for article in result["articles"]}
    assert articles["good"].content == "Good body"
    assert articles["bad"].content is None
    assert all(article.used_in_analysis for article in articles.values())


@pytest.fixture(autouse=True)
def _hermetic_node_model(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_llm(monkeypatch)

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import co_scientist.evidence as evidence
from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.reflection import deep_verification_evidence as probes
from co_scientist.config.schema import WorkflowConfig
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
)
from tests._llm_fake import install_fake_llm
from tests._mcp import make_tool_results_client
from tests._research_fakes import (
    _stub_node,
    install_mcp_client,
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

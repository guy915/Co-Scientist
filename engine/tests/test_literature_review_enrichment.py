from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.generation.literature_review.research_phase import (
    run_research_phase,
)
from co_scientist.config.schema import ToolConfig, WorkflowConfig
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.mcp_client import MCPToolClient
from tests._llm_fake import install_fake_llm
from tests._mcp import make_tool_results_client
from tests._research_fakes import (
    _PAPERS,
    FakeResearchClient,
    _ScriptedModel,
    _stub_node,
    install_mcp_client,
    make_search_config,
    research_registry,
    research_workflow,
    review_registry,
)
from tests._state import make_state


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


@pytest.fixture(autouse=True)
def _hermetic_node_model(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_llm(monkeypatch)

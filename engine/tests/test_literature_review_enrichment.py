from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
    synthesis,
)
from co_scientist.agents.generation.literature_review.research_phase import (
    run_research_phase,
)
from co_scientist.config.schema import ToolConfig, WorkflowConfig
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.mcp_client import MCPToolClient
from co_scientist.research import result_from_dict
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


async def test_review_bounds_long_enrichment_in_the_synthesis_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_node(monkeypatch, server_available=True)
    registry = review_registry(
        WorkflowConfig(
            primary_search="search",
            context_enrichment_tools=["first", "second"],
        ),
        "search",
        configs={
            name: ToolConfig(server="s", mcp_tool_name=name, display_name=name)
            for name in ("first", "second")
        },
    )
    raw = "mechanistic evidence " * 100
    install_mcp_client(
        monkeypatch,
        make_tool_results_client(
            {
                "search": {"paper": {"title": "A", "abstract": "Evidence"}},
                "first": raw,
                "second": raw,
            }
        ),
    )
    prompts: list[str] = []

    async def complete(*, prompt: str, **_: Any) -> str:
        prompts.append(prompt)
        return "SYNTHESIZED REVIEW"

    monkeypatch.setattr(synthesis, "call_llm", complete)
    result = await literature_review_node(
        make_state(
            research_goal="Study KRAS EGFR BRAF in cancer",
            tool_registry=registry,
        )
    )
    sections = [
        f"**{tool}**\n"
        + "\n\n".join(
            f"[{entity}]\n{raw[:300]}" for entity in ("KRAS", "EGFR", "BRAF")
        )
        for tool in ("first", "second")
    ]
    expected = "\n\n".join(sections)[:1500] + "\n[...truncated]"
    assert len(expected) == 1515
    assert expected in prompts[0]
    assert expected + raw[0] not in prompts[0]
    assert len(result["context_enrichment_sources"]) == 6
    assert all(
        len(item["display"]) == 300
        for item in result["context_enrichment_sources"]
    )


@pytest.mark.parametrize(
    "reason", ["disabled", "unreachable", "missing", "error", "no-entities"]
)
async def test_optional_enrichment_unavailability_preserves_review(
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    _stub_node(monkeypatch, server_available=True)
    registry = review_registry(
        WorkflowConfig(
            primary_search="search", context_enrichment_tools=["kg"]
        ),
        "search",
        configs={}
        if reason == "missing"
        else {
            "kg": ToolConfig(
                server="s", mcp_tool_name="kg", enabled=reason != "disabled"
            )
        },
    )
    install_mcp_client(
        monkeypatch,
        make_tool_results_client(
            {"search": {"paper": {"title": "A", "abstract": "Evidence"}}},
            available_tools={"search"} if reason == "unreachable" else None,
            error_tools={"kg"} if reason == "error" else None,
        ),
    )
    result = await literature_review_node(
        make_state(
            research_goal="plain lowercase goal"
            if reason == "no-entities"
            else "Study KRAS",
            tool_registry=registry,
        )
    )
    assert result["articles_with_reasoning"] == "SYNTHESIZED REVIEW"
    assert result["articles"][0].used_in_analysis
    assert not result.get("context_enrichment_sources")


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


async def test_a_run_that_asked_for_no_research_does_none(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    """Research multiplies cost and requires an explicit tier request."""
    client = _client()

    outcome = await run_research_phase(
        make_state(research_tier=""), _config(tmp_path), client, []
    )

    assert outcome is None
    assert cast(FakeResearchClient, client).calls == []
    assert scripted.prompts == []


async def test_research_seeds_its_first_level_from_what_was_read(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    analyses = [
        {"analysis": {"gaps_identified": "No human data on TGF-beta blockade"}}
    ]

    outcome = await run_research_phase(
        make_state(research_tier="extended", run_id="run-1"),
        _config(tmp_path),
        _client(),
        analyses,
    )

    assert outcome is not None
    asked = [thread["question"]["text"] for thread in outcome.ledger["threads"]]
    assert "No human data on TGF-beta blockade" in asked
    assert not any("perspectives to research" in p for p in scripted.prompts)


async def test_research_plans_its_own_coverage_when_nothing_was_stated(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    outcome = await run_research_phase(
        make_state(research_tier="extended", run_id="run-1"),
        _config(tmp_path),
        _client(),
        [{"analysis": {"key_findings": "much is known"}}],
    )

    assert outcome is not None
    assert any("perspectives to research" in p for p in scripted.prompts)


async def test_only_papers_something_was_drawn_from_join_the_pool(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    outcome = await run_research_phase(
        make_state(research_tier="extended", run_id="run-1"),
        _config(tmp_path),
        _client(),
        [],
    )

    assert outcome is not None
    assert list(outcome.records) == ["doc-a"]
    assert outcome.records["doc-a"]["title"] == "Blockade in humans"
    assert outcome.records["doc-a"]["retrieval_call_id"] in {
        call.id for call in result_from_dict(outcome.ledger).calls
    }
    assert outcome.records["doc-a"]["_source_name"] == "alpha"
    assert "Blockade reduced fibrosis in humans" in outcome.section
    assert "Human evidence exists but is thin." in outcome.section


async def test_a_run_with_no_enabled_source_researches_nothing(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    config = _config(tmp_path)
    assert config.workflow is not None
    for source in config.workflow.search_sources:
        source.enabled = False

    outcome = await run_research_phase(
        make_state(research_tier="ultra", run_id="run-1"),
        config,
        _client(),
        [],
    )

    assert outcome is None


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

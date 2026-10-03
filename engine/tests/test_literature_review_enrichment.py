from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import (
    enrichment as lr_enrichment,
)
from co_scientist.agents.generation.literature_review.research_phase import (
    _seed_questions,
    run_research_phase,
)
from co_scientist.config.schema import ToolConfig, WorkflowConfig
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.mcp_client import MCPToolClient
from co_scientist.research import result_from_dict
from tests._mcp import FakeToolResultsClient, make_tool_results_client
from tests._mcp import make_tool_lookup_registry as _registry
from tests._research_fakes import (
    FakeResearchClient,
    make_search_config,
    research_registry,
    research_workflow,
)
from tests._state import make_state


async def test_call_enrichment_tool_for_entity_success() -> None:
    client = FakeToolResultsClient(results={"kg_tool": {"statements": []}})
    result = await lr_enrichment._call_enrichment_tool_for_entity(
        "kg_tool", {"entity_name": "KRAS"}, cast(MCPToolClient, client)
    )
    assert result == {"statements": []}
    assert client.calls == [("kg_tool", {"entity_name": "KRAS"})]


async def test_call_enrichment_tool_for_entity_error_returns_none() -> None:
    client = FakeToolResultsClient(error_tools={"kg_tool"})
    result = await lr_enrichment._call_enrichment_tool_for_entity(
        "kg_tool", {"entity_name": "KRAS"}, cast(MCPToolClient, client)
    )
    assert result is None


def test_format_one_indra_statement_missing_endpoint_returns_none() -> None:
    assert (
        lr_enrichment._format_one_indra_statement(
            {"subj": {}, "obj": {"name": "MAPK1"}}
        )
        is None
    )


def test_format_indra_statements_skips_unformattable_entries() -> None:
    stmts: list[dict[str, Any]] = [
        {"subj": {}, "obj": {"name": "MAPK1"}},
        {
            "subj": {"name": "KRAS"},
            "obj": {"name": "MAPK1"},
            "type": "Activation",
            "belief": 0.9,
        },
    ]
    text, items = lr_enrichment._format_indra_statements(stmts)
    assert len(items) == 1
    assert "KRAS" in text and "MAPK1" in text


def test_format_indra_statements_survives_a_non_dict_endpoint() -> None:
    """One malformed knowledge-graph endpoint must not discard all
    enrichment."""
    stmts: list[dict[str, Any]] = [
        {"subj": "KRAS", "obj": {"name": "MAPK1"}},
        {
            "subj": {"name": "EGFR"},
            "obj": {"name": "MAPK1"},
            "type": "Activation",
            "belief": 0.9,
        },
    ]
    text, items = lr_enrichment._format_indra_statements(stmts)
    assert len(items) == 1
    assert "EGFR" in text


def test_format_one_indra_statement_formats_complex_members() -> None:
    """Complex/family statements use members rather than subject/object
    pairs."""
    formatted = lr_enrichment._format_one_indra_statement(
        {
            "members": [{"name": "BRCA1"}, {"name": "BARD1"}],
            "type": "Complex",
            "belief": 0.87,
        }
    )
    assert formatted is not None
    display, item = formatted
    assert display == "Complex(BRCA1, BARD1) [Complex] (belief: 0.87)"
    assert item["display"] == f"INDRA: {display}"


def test_format_one_indra_statement_shapeless_still_returns_none() -> None:
    assert (
        lr_enrichment._format_one_indra_statement({"type": "Activation"})
        is None
    )


def test_format_dict_result_falls_back_to_stringified_dict() -> None:
    data = {"other": "value"}
    text, items = lr_enrichment._format_dict_result(data)
    assert text == str(data)
    assert items == [{"display": str(data), "data": data}]


def test_format_dict_result_empty_dict_stringifies_braces() -> None:
    text, items = lr_enrichment._format_dict_result({})
    assert text == "{}"
    assert items == [{"display": "{}", "data": {}}]


def test_parse_enrichment_result_bare_list_raw() -> None:
    text, items = lr_enrichment._parse_enrichment_result([{"n": 1}, {"n": 2}])
    assert len(items) == 2
    assert text


def test_parse_enrichment_result_scalar_raw() -> None:
    text, items = lr_enrichment._parse_enrichment_result(42)
    assert text == "42"
    assert items == [{"display": "42", "data": {}}]


async def test_call_enrichment_tool_for_entities_queries_all_in_parallel() -> (
    None
):
    tool_config = ToolConfig(
        server="s", mcp_tool_name="kg_tool", display_name="KG Tool"
    )
    client = make_tool_results_client(
        results={"kg_tool": json.dumps({"results": [{"n": 1}]})}
    )

    text, items = await lr_enrichment._call_enrichment_tool_for_entities(
        tool_config, ["KRAS", "MAPK1"], client
    )

    assert "[KRAS]" in text
    assert "[MAPK1]" in text
    assert len(items) == 2
    assert {item["entity"] for item in items} == {"KRAS", "MAPK1"}
    # tool_id is stamped by _aggregate_enrichment_results, from the YAML tool
    # id rather than the MCP tool name; this stage leaves it unset.
    assert all("tool_id" not in item for item in items)


async def test_call_enrichment_tool_for_entities_no_result() -> None:
    tool_config = ToolConfig(server="s", mcp_tool_name="kg_tool")
    client = make_tool_results_client()

    text, items = await lr_enrichment._call_enrichment_tool_for_entities(
        tool_config, ["KRAS"], client
    )

    assert text == ""
    assert items == []


def test_resolve_enrichment_tool_configs_filters_availability() -> None:
    available = ToolConfig(
        server="s", mcp_tool_name="mcp_available", enabled=True
    )
    disabled = ToolConfig(
        server="s", mcp_tool_name="mcp_disabled", enabled=False
    )
    unreachable = ToolConfig(
        server="s", mcp_tool_name="mcp_unreachable", enabled=True
    )
    workflow = WorkflowConfig(
        context_enrichment_tools=[
            "avail",
            "disabled",
            "unreachable",
            "missing_from_registry",
        ]
    )
    registry = _registry(
        {"avail": available, "disabled": disabled, "unreachable": unreachable}
    )
    client = make_tool_results_client(available_tools={"mcp_available"})

    configs = lr_enrichment._resolve_enrichment_tool_configs(
        workflow, registry, client
    )

    assert len(configs) == 1
    assert configs[0].mcp_tool_name == "mcp_available"
    assert configs[0]._yaml_tool_id == "avail"


def test_aggregate_enrichment_results_skips_exceptions() -> None:
    tc_ok = ToolConfig(server="s", mcp_tool_name="mcp_ok", display_name="OK")
    tc_ok._yaml_tool_id = "ok_tool"
    tc_failed = ToolConfig(server="s", mcp_tool_name="mcp_failed")
    tc_failed._yaml_tool_id = "failed_tool"
    tool_results: list[Any] = [
        ("some evidence", [{"display": "x"}]),
        RuntimeError("boom"),
    ]

    sections, items = lr_enrichment._aggregate_enrichment_results(
        [tc_ok, tc_failed], tool_results
    )

    assert sections == ["**OK**\nsome evidence"]
    assert items == [{"display": "x", "tool_id": "ok_tool"}]


def test_aggregate_enrichment_results_empty_text_adds_no_section() -> None:
    tc = ToolConfig(server="s", mcp_tool_name="mcp_tool")
    tc._yaml_tool_id = "tool_id"

    sections, items = lr_enrichment._aggregate_enrichment_results(
        [tc], [("", [])]
    )

    assert sections == []
    assert items == []


def test_resolve_enrichment_context_no_tool_registry_returns_none() -> None:
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    config = make_search_config(workflow=workflow, tool_registry=None)
    state = make_state(research_goal="Study of KRAS in cancer")

    assert lr_enrichment._resolve_enrichment_context(state, config) is None


def test_resolve_enrichment_context_no_entities_returns_none() -> None:
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    config = make_search_config(workflow=workflow, tool_registry=_registry({}))
    state = make_state(research_goal="a plain lowercase research goal")

    assert lr_enrichment._resolve_enrichment_context(state, config) is None


def test_resolve_enrichment_context_success() -> None:
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    registry = _registry({})
    config = make_search_config(workflow=workflow, tool_registry=registry)
    state = make_state(research_goal="Study of KRAS in cancer")

    resolved = lr_enrichment._resolve_enrichment_context(state, config)

    assert resolved is not None
    resolved_workflow, resolved_registry, entities = resolved
    assert resolved_workflow is workflow
    assert resolved_registry is registry
    assert entities == ["KRAS"]


async def test_run_enrichment_tools_aggregates_across_tools() -> None:
    tc = ToolConfig(server="s", mcp_tool_name="kg_tool", display_name="KG")
    client = make_tool_results_client(
        results={"kg_tool": json.dumps({"results": [{"n": 1}]})}
    )

    sections, items = await lr_enrichment._run_enrichment_tools(
        ["KRAS"], [tc], client
    )

    assert len(sections) == 1
    assert "**KG**" in sections[0]
    assert len(items) == 1


def test_cap_enrichment_text_under_limit_passes_through() -> None:
    assert lr_enrichment._cap_enrichment_text("short text") == "short text"


def test_cap_enrichment_text_truncates_over_limit() -> None:
    long_text = "x" * (lr_enrichment._CONTEXT_ENRICHMENT_MAX_CHARS + 100)

    result = lr_enrichment._cap_enrichment_text(long_text)

    assert result.endswith("\n[...truncated]")
    assert len(result) == (
        lr_enrichment._CONTEXT_ENRICHMENT_MAX_CHARS + len("\n[...truncated]")
    )


async def test_phase2_6_no_available_tool_configs_returns_empty() -> None:
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    registry = _registry({})
    config = make_search_config(workflow=workflow, tool_registry=registry)
    state = make_state(research_goal="Study of KRAS in cancer")

    text, items = await lr_enrichment._phase2_6_fetch_context_enrichment(
        state, config, make_tool_results_client()
    )

    assert (text, items) == ("", [])


async def test_phase2_6_resolved_tool_yields_nothing_returns_empty() -> None:
    tool_cfg = ToolConfig(server="s", mcp_tool_name="mcp_kg")
    registry = _registry({"kg": tool_cfg})
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    config = make_search_config(workflow=workflow, tool_registry=registry)
    state = make_state(research_goal="Study of KRAS in cancer")
    client = make_tool_results_client(available_tools={"mcp_kg"})

    text, items = await lr_enrichment._phase2_6_fetch_context_enrichment(
        state, config, client
    )

    assert (text, items) == ("", [])


async def test_phase2_6_success_returns_combined_text_and_items() -> None:
    tool_cfg = ToolConfig(
        server="s", mcp_tool_name="mcp_kg", display_name="Knowledge Graph"
    )
    registry = _registry({"kg": tool_cfg})
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    config = make_search_config(workflow=workflow, tool_registry=registry)
    state = make_state(research_goal="Study of KRAS in cancer")
    client = make_tool_results_client(
        results={"mcp_kg": json.dumps({"results": [{"n": 1}]})},
        available_tools={"mcp_kg"},
    )

    text, items = await lr_enrichment._phase2_6_fetch_context_enrichment(
        state, config, client
    )

    assert "Knowledge Graph" in text
    assert len(items) == 1


_PAPERS = {
    "doc-a": {
        "title": "Fibrosis mechanisms",
        "abstract": "TGF-beta signalling drives fibrosis.",
        "pdf_url": "u/a",
    },
    "doc-b": {
        "title": "A second look",
        "abstract": "Contradicting evidence in mice.",
    },
}


def _config(tmp_path: Path) -> SearchConfig:
    registry = research_registry(tmp_path)
    return SearchConfig(
        tool_registry=registry,
        workflow=research_workflow(registry),
        is_multi_source=True,
        search_tool_name="search_alpha",
        search_tool_config=registry.get_tool("alpha"),
        source_name="alpha",
        papers_to_read_count=4,
        is_dev_mode=False,
        research_goal="reverse fibrosis",
        model_name="offline/test",
    )


class _ScriptedModel:
    """Answers each of the five research prompts by what it was asked."""

    def __init__(self) -> None:
        """Start with nothing asked."""
        self.prompts: list[str] = []

    async def __call__(
        self, prompt: str, spec: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        """Answer one prompt, recording it."""
        self.prompts.append(prompt)
        if "perspectives to research" in prompt:
            return {"stances": ["mechanism"]}
        if "questions this perspective needs" in prompt:
            return {"questions": ["what drives fibrosis?"]}
        if "search query" in prompt:
            return {"query": "fibrosis TGF-beta"}
        if "retrieved documents" in prompt:
            return {
                "findings": [
                    {
                        "document": 0,
                        "claim": "TGF-beta drives fibrosis",
                        "quote": "TGF-beta signalling drives fibrosis.",
                    }
                ],
                "follow_ups": [],
            }
        return {"summary": "TGF-beta is the consensus driver."}


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
                "read_pdf": {"content": "TGF-beta signalling drives fibrosis."},
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
    assert outcome.records["doc-a"]["title"] == "Fibrosis mechanisms"


async def test_every_researched_paper_names_the_search_that_found_it(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    outcome = await run_research_phase(
        make_state(research_tier="extended", run_id="run-1"),
        _config(tmp_path),
        _client(),
        [],
    )

    assert outcome is not None
    made = result_from_dict(outcome.ledger).calls
    assert outcome.records["doc-a"]["retrieval_call_id"] in {
        call.id for call in made
    }
    assert outcome.records["doc-a"]["_source_name"] == "alpha"


async def test_the_findings_reach_the_text_every_later_agent_reads(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    outcome = await run_research_phase(
        make_state(research_tier="extended", run_id="run-1"),
        _config(tmp_path),
        _client(),
        [],
    )

    assert outcome is not None
    assert "TGF-beta drives fibrosis" in outcome.section
    assert "TGF-beta is the consensus driver." in outcome.section


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


def test_seed_questions_stop_at_the_first_level_breadth() -> None:
    analyses = [
        {"analysis": {"gaps_identified": f"gap {n}", "unexplored_areas": ""}}
        for n in range(6)
    ]

    assert _seed_questions(analyses, 3) == ["gap 0", "gap 1", "gap 2"]


def test_the_same_gap_stated_twice_is_one_question() -> None:
    """Repeated gaps must not buy duplicate searches."""
    analyses = [
        {"analysis": {"gaps_identified": "No human data"}},
        {"analysis": {"gaps_identified": "no human data  "}},
        {"analysis": {"unexplored_areas": "Dosing is unstudied"}},
    ]

    assert _seed_questions(analyses, 4) == [
        "No human data",
        "Dosing is unstudied",
    ]

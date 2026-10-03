"""Offline contracts for literature review enrichment."""

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

# =============================================================================
# _call_enrichment_tool_for_entity
# =============================================================================


async def test_call_enrichment_tool_for_entity_success() -> None:
    """A successful call returns the raw tool result."""
    client = FakeToolResultsClient(results={"kg_tool": {"statements": []}})
    result = await lr_enrichment._call_enrichment_tool_for_entity(
        "kg_tool", {"entity_name": "KRAS"}, cast(MCPToolClient, client)
    )
    assert result == {"statements": []}
    assert client.calls == [("kg_tool", {"entity_name": "KRAS"})]


async def test_call_enrichment_tool_for_entity_error_returns_none() -> None:
    """A raising tool call is swallowed and returns None."""
    client = FakeToolResultsClient(error_tools={"kg_tool"})
    result = await lr_enrichment._call_enrichment_tool_for_entity(
        "kg_tool", {"entity_name": "KRAS"}, cast(MCPToolClient, client)
    )
    assert result is None


# =============================================================================
# _format_one_indra_statement / _format_indra_statements
# =============================================================================


def test_format_one_indra_statement_missing_endpoint_returns_none() -> None:
    """A statement missing either endpoint's name formats to None."""
    assert (
        lr_enrichment._format_one_indra_statement(
            {"subj": {}, "obj": {"name": "MAPK1"}}
        )
        is None
    )


def test_format_indra_statements_skips_unformattable_entries() -> None:
    """A mix of valid and invalid statements skips the invalid ones."""
    stmts: list[dict[str, Any]] = [
        {"subj": {}, "obj": {"name": "MAPK1"}},  # unformattable: skipped
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
    """A non-dict endpoint degrades to unformattable, not to an exception.

    A knowledge-graph server can return a bare name where an agent object is
    expected. Nothing between here and the per-tool gather catches that, so
    one such statement used to discard the whole tool's enrichment -- every
    entity, not just this one -- and read as an unavailable tool.
    """
    stmts: list[dict[str, Any]] = [
        {"subj": "KRAS", "obj": {"name": "MAPK1"}},  # subj is not an agent
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
    """A Complex/family statement formats from its members.

    These statements carry ``members`` instead of a subject and object.
    Reflection has always rendered them; enrichment dropped them silently,
    so a knowledge graph answered mostly in complexes contributed nothing.
    """
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
    """A statement with neither endpoints nor members formats to None."""
    assert (
        lr_enrichment._format_one_indra_statement({"type": "Activation"})
        is None
    )


# =============================================================================
# _format_dict_result -- fallback when neither statements nor results present
# =============================================================================


def test_format_dict_result_falls_back_to_stringified_dict() -> None:
    """A dict with neither ``statements`` nor ``results`` stringifies itself."""
    data = {"other": "value"}
    text, items = lr_enrichment._format_dict_result(data)
    assert text == str(data)
    assert items == [{"display": str(data), "data": data}]


def test_format_dict_result_empty_dict_stringifies_braces() -> None:
    """An empty dict (no statements/results) stringifies to a literal ``{}``."""
    text, items = lr_enrichment._format_dict_result({})
    assert text == "{}"
    assert items == [{"display": "{}", "data": {}}]


# =============================================================================
# _parse_enrichment_result -- list and scalar raw shapes
# =============================================================================


def test_parse_enrichment_result_bare_list_raw() -> None:
    """A raw (non-string) list input is formatted like a generic items list."""
    text, items = lr_enrichment._parse_enrichment_result([{"n": 1}, {"n": 2}])
    assert len(items) == 2
    assert text


def test_parse_enrichment_result_scalar_raw() -> None:
    """A raw scalar (not dict, list, or unparsable string) stringifies."""
    text, items = lr_enrichment._parse_enrichment_result(42)
    assert text == "42"
    assert items == [{"display": "42", "data": {}}]


# =============================================================================
# _call_enrichment_tool_for_entities
# =============================================================================


async def test_call_enrichment_tool_for_entities_queries_all_in_parallel() -> (
    None
):
    """Every entity is queried once; results are tagged and joined by entity."""
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
    """An entity whose call returns no result contributes no text or items."""
    tool_config = ToolConfig(server="s", mcp_tool_name="kg_tool")
    client = (
        make_tool_results_client()
    )  # no configured results: call_tool returns None

    text, items = await lr_enrichment._call_enrichment_tool_for_entities(
        tool_config, ["KRAS"], client
    )

    assert text == ""
    assert items == []


# =============================================================================
# _resolve_enrichment_tool_configs
# =============================================================================


def test_resolve_enrichment_tool_configs_filters_availability() -> None:
    """Only enabled tools whose MCP name the client reports available pass."""
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


# =============================================================================
# _aggregate_enrichment_results
# =============================================================================


def test_aggregate_enrichment_results_skips_exceptions() -> None:
    """A tool result that is an exception is logged and skipped, not raised."""
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
    """A tool result with empty text contributes items but no section."""
    tc = ToolConfig(server="s", mcp_tool_name="mcp_tool")
    tc._yaml_tool_id = "tool_id"

    sections, items = lr_enrichment._aggregate_enrichment_results(
        [tc], [("", [])]
    )

    assert sections == []
    assert items == []


# =============================================================================
# _resolve_enrichment_context
# =============================================================================


def test_resolve_enrichment_context_no_tool_registry_returns_none() -> None:
    """A configured workflow with no tool registry cannot resolve context."""
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    config = make_search_config(workflow=workflow, tool_registry=None)
    state = make_state(research_goal="Study of KRAS in cancer")

    assert lr_enrichment._resolve_enrichment_context(state, config) is None


def test_resolve_enrichment_context_no_entities_returns_none() -> None:
    """A research goal with no extractable entities resolves to None."""
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    config = make_search_config(workflow=workflow, tool_registry=_registry({}))
    state = make_state(research_goal="a plain lowercase research goal")

    assert lr_enrichment._resolve_enrichment_context(state, config) is None


def test_resolve_enrichment_context_success() -> None:
    """A configured workflow with extractable entities resolves cleanly."""
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


# =============================================================================
# _run_enrichment_tools
# =============================================================================


async def test_run_enrichment_tools_aggregates_across_tools() -> None:
    """Every configured tool is queried and its output aggregated."""
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


# =============================================================================
# _cap_enrichment_text
# =============================================================================


def test_cap_enrichment_text_under_limit_passes_through() -> None:
    """Text within the budget is returned unchanged."""
    assert lr_enrichment._cap_enrichment_text("short text") == "short text"


def test_cap_enrichment_text_truncates_over_limit() -> None:
    """Text over the budget is truncated with a truncation marker."""
    long_text = "x" * (lr_enrichment._CONTEXT_ENRICHMENT_MAX_CHARS + 100)

    result = lr_enrichment._cap_enrichment_text(long_text)

    assert result.endswith("\n[...truncated]")
    assert len(result) == (
        lr_enrichment._CONTEXT_ENRICHMENT_MAX_CHARS + len("\n[...truncated]")
    )


# =============================================================================
# _phase2_6_fetch_context_enrichment
# =============================================================================


async def test_phase2_6_no_available_tool_configs_returns_empty() -> None:
    """Entities extracted but no tool resolves: the phase returns empty."""
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    # "kg" not present in the registry, so resolution yields no tool configs.
    registry = _registry({})
    config = make_search_config(workflow=workflow, tool_registry=registry)
    state = make_state(research_goal="Study of KRAS in cancer")

    text, items = await lr_enrichment._phase2_6_fetch_context_enrichment(
        state, config, make_tool_results_client()
    )

    assert (text, items) == ("", [])


async def test_phase2_6_resolved_tool_yields_nothing_returns_empty() -> None:
    """A resolvable, available tool that returns no results yields empty.

    Distinct from the no-tool-configs case: here ``_resolve_enrichment_tool_
    configs`` finds an available tool, but every entity query comes back
    empty, so aggregation produces neither sections nor structured items.
    """
    tool_cfg = ToolConfig(server="s", mcp_tool_name="mcp_kg")
    registry = _registry({"kg": tool_cfg})
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    config = make_search_config(workflow=workflow, tool_registry=registry)
    state = make_state(research_goal="Study of KRAS in cancer")
    # "mcp_kg" is available but configured with no results: every entity
    # query returns None, so _call_enrichment_tool_for_entities yields
    # ("", []) for the tool.
    client = make_tool_results_client(available_tools={"mcp_kg"})

    text, items = await lr_enrichment._phase2_6_fetch_context_enrichment(
        state, config, client
    )

    assert (text, items) == ("", [])


async def test_phase2_6_success_returns_combined_text_and_items() -> None:
    """A fully configured workflow returns combined text and structured data."""
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
    """A search config over the shared research tool fixture."""
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
    """Route the adapter's model calls to a scripted answerer."""
    model = _ScriptedModel()
    monkeypatch.setattr("co_scientist.research_adapter.call_llm_json", model)
    return model


def _client() -> MCPToolClient:
    """A client whose search returns two papers and reads one of them."""
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
    """Off unless a tier asked: the loop is a multiplier on run cost."""
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
    """The gaps the papers stated beat a fresh guess from the goal."""
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
    # Seeded, so no stance planning call was made.
    assert not any("perspectives to research" in p for p in scripted.prompts)


async def test_research_plans_its_own_coverage_when_nothing_was_stated(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    """An analysis with no gaps is not a reason to skip the phase."""
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
    """A hit that was merely listed must not enter every later prompt."""
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
    """This is the link that makes the stored provenance resolvable."""
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
    """A finding that lives only in the ledger was recorded, not used."""
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
    """No source to search is a configuration state, not a failure."""
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
    """More seeds than the level can fund would be declined anyway."""
    analyses = [
        {"analysis": {"gaps_identified": f"gap {n}", "unexplored_areas": ""}}
        for n in range(6)
    ]

    assert _seed_questions(analyses, 3) == ["gap 0", "gap 1", "gap 2"]


def test_the_same_gap_stated_twice_is_one_question() -> None:
    """Two papers naming the same hole must not buy two searches."""
    analyses = [
        {"analysis": {"gaps_identified": "No human data"}},
        {"analysis": {"gaps_identified": "no human data  "}},
        {"analysis": {"unexplored_areas": "Dosing is unstudied"}},
    ]

    assert _seed_questions(analyses, 4) == [
        "No human data",
        "Dosing is unstudied",
    ]

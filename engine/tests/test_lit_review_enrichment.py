"""Tests for the Phase 2.6 context-enrichment literature review helpers.

Covers ``co_scientist.nodes.literature_review.enrichment``: the per-entity
enrichment tool call (success and exception branches), the INDRA-statement
and generic-dict result formatters not already exercised by
``test_literature_review_pure``, the per-tool/per-entity fan-out, tool-config
resolution (availability/enabled filtering), result aggregation (including
skipping a failed tool), enrichment-context resolution (missing registry, no
extractable entities, success), the parallel multi-tool runner, the
synthesis-budget truncation helper, and the Phase 2.6 entry point itself
(empty-config and success paths).

The only external seam is ``MCPToolClient``, stood in for by a tiny
duck-typed fake exposing ``call_tool`` and ``has_tool``. Everything else
(``SearchConfig``, ``WorkflowConfig``, ``ToolConfig``) is a plain,
directly-constructed dataclass.
"""

import json
from typing import Any, cast

from co_scientist.config import ToolRegistry
from co_scientist.config.schema import ToolConfig, WorkflowConfig
from co_scientist.mcp_client import MCPToolClient
from co_scientist.nodes.literature_review import enrichment as lr_enrichment
from co_scientist.nodes.literature_review.helpers import SearchConfig
from tests._state import make_state


class _FakeMCPClient:
    """Duck-typed stand-in for ``MCPToolClient`` used by enrichment tests.

    Returns the configured per-tool result, or raises ``RuntimeError`` for
    any tool name listed in ``error_tools``. ``has_tool`` reports membership
    in ``available_tools``.
    """

    def __init__(
        self,
        results: dict[str, Any] | None = None,
        available_tools: set[str] | None = None,
        error_tools: set[str] | None = None,
    ) -> None:
        """Configure per-tool canned results, availability, and failures."""
        self._results = results or {}
        self._available_tools = available_tools or set()
        self._error_tools = error_tools or set()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the call and return the canned result, or raise."""
        self.calls.append((tool_name, kwargs))
        if tool_name in self._error_tools:
            raise RuntimeError(f"tool failed: {tool_name}")
        return self._results.get(tool_name)

    def has_tool(self, tool_name: str) -> bool:
        """Report whether the given tool name was marked available."""
        return tool_name in self._available_tools


def _client(
    results: dict[str, Any] | None = None,
    available_tools: set[str] | None = None,
    error_tools: set[str] | None = None,
) -> MCPToolClient:
    """Build a fake client typed as MCPToolClient for the phase signatures."""
    return cast(
        MCPToolClient,
        _FakeMCPClient(results, available_tools, error_tools),
    )


class _FakeToolRegistry:
    """Duck-typed stand-in exposing only the ``get_tool`` lookup used here."""

    def __init__(self, tools: dict[str, ToolConfig]) -> None:
        """Store the tool_id -> ToolConfig map returned by ``get_tool``."""
        self._tools = tools

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Return the configured tool, or None for an unknown id."""
        return self._tools.get(tool_id)


def _registry(tools: dict[str, ToolConfig]) -> ToolRegistry:
    """Build a fake registry typed as ToolRegistry for the phase signatures."""
    return cast(ToolRegistry, _FakeToolRegistry(tools))


def _search_config(
    *,
    workflow: WorkflowConfig | None = None,
    tool_registry: ToolRegistry | None = None,
) -> SearchConfig:
    """Build a SearchConfig with only the enrichment-relevant fields set.

    The remaining fields are irrelevant to enrichment.py's phase functions,
    which only read ``workflow`` and ``tool_registry``.
    """
    return SearchConfig(
        tool_registry=tool_registry,
        workflow=workflow,
        is_multi_source=False,
        search_tool_name="search_tool",
        search_tool_config=None,
        source_name="unknown",
        papers_to_read_count=5,
        is_dev_mode=False,
    )


# =============================================================================
# _call_enrichment_tool_for_entity
# =============================================================================


async def test_call_enrichment_tool_for_entity_success() -> None:
    """A successful call returns the raw tool result."""
    client = _FakeMCPClient(results={"kg_tool": {"statements": []}})
    result = await lr_enrichment._call_enrichment_tool_for_entity(
        "kg_tool", {"entity_name": "KRAS"}, cast(MCPToolClient, client)
    )
    assert result == {"statements": []}
    assert client.calls == [("kg_tool", {"entity_name": "KRAS"})]


async def test_call_enrichment_tool_for_entity_error_returns_none() -> None:
    """A raising tool call is swallowed and returns None."""
    client = _FakeMCPClient(error_tools={"kg_tool"})
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
    client = _client(results={"kg_tool": json.dumps({"results": [{"n": 1}]})})

    text, items = await lr_enrichment._call_enrichment_tool_for_entities(
        tool_config, ["KRAS", "MAPK1"], client
    )

    assert "[KRAS]" in text
    assert "[MAPK1]" in text
    assert len(items) == 2
    assert {item["entity"] for item in items} == {"KRAS", "MAPK1"}
    assert all(item["tool_id"] == "kg_tool" for item in items)


async def test_call_enrichment_tool_for_entities_no_result() -> None:
    """An entity whose call returns no result contributes no text or items."""
    tool_config = ToolConfig(server="s", mcp_tool_name="kg_tool")
    client = _client()  # no configured results: call_tool returns None

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
    client = _client(available_tools={"mcp_available"})

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
    config = _search_config(workflow=workflow, tool_registry=None)
    state = make_state(research_goal="Study of KRAS in cancer")

    assert lr_enrichment._resolve_enrichment_context(state, config) is None


def test_resolve_enrichment_context_no_entities_returns_none() -> None:
    """A research goal with no extractable entities resolves to None."""
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    config = _search_config(workflow=workflow, tool_registry=_registry({}))
    state = make_state(research_goal="a plain lowercase research goal")

    assert lr_enrichment._resolve_enrichment_context(state, config) is None


def test_resolve_enrichment_context_success() -> None:
    """A configured workflow with extractable entities resolves cleanly."""
    workflow = WorkflowConfig(context_enrichment_tools=["kg"])
    registry = _registry({})
    config = _search_config(workflow=workflow, tool_registry=registry)
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
    client = _client(results={"kg_tool": json.dumps({"results": [{"n": 1}]})})

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
    config = _search_config(workflow=workflow, tool_registry=registry)
    state = make_state(research_goal="Study of KRAS in cancer")

    text, items = await lr_enrichment._phase2_6_fetch_context_enrichment(
        state, config, _client()
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
    config = _search_config(workflow=workflow, tool_registry=registry)
    state = make_state(research_goal="Study of KRAS in cancer")
    # "mcp_kg" is available but configured with no results: every entity
    # query returns None, so _call_enrichment_tool_for_entities yields
    # ("", []) for the tool.
    client = _client(available_tools={"mcp_kg"})

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
    config = _search_config(workflow=workflow, tool_registry=registry)
    state = make_state(research_goal="Study of KRAS in cancer")
    client = _client(
        results={"mcp_kg": json.dumps({"results": [{"n": 1}]})},
        available_tools={"mcp_kg"},
    )

    text, items = await lr_enrichment._phase2_6_fetch_context_enrichment(
        state, config, client
    )

    assert "Knowledge Graph" in text
    assert len(items) == 1

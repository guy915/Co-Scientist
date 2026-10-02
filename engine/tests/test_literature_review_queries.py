"""Tests for literature review phase 1 query generation (queries.py).

Covers the MCP query-generation success/failure paths, the LLM-generation
failure path, and the pure resolution helpers (``_resolve_query_format``,
``_resolve_query_generation_tool``, ``_try_mcp_query_generation``) that the
existing ``test_literature_review_node`` happy-path tests never reach, since
those always run with ``tool_registry=None`` (no configured
``query_generation_tool``).

External seams stubbed: the MCP client's ``call_tool`` (an in-memory fake) and
``queries.call_llm_json`` (following the same monkeypatch target used by
``test_literature_review_node``); no network or disk I/O anywhere here.
"""

from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import queries
from co_scientist.config import WorkflowConfig
from co_scientist.evidence.search_support import (
    SearchConfig,
)
from co_scientist.mcp_client import MCPToolClient
from tests._mcp import FakeCallToolClient, make_tool_lookup_registry
from tests._retrieval_config import make_tool_config
from tests._search_fixtures import make_search_config
from tests._state import make_state


def _search_config(**overrides: Any) -> SearchConfig:
    """Build a SearchConfig over the pubmed source, overriding given fields.

    The pubmed tool and source names are this module's own -- query
    generation reads them into the prompt -- so they stay explicit here
    rather than inheriting the shared builder's placeholders.

    Args:
        **overrides: Any SearchConfig fields to set (e.g. ``workflow``,
            ``tool_registry``).

    Returns:
        A SearchConfig naming pubmed as the search source.
    """
    return make_search_config(
        search_tool_name="pubmed_search_with_fulltext",
        source_name="pubmed",
        **overrides,
    )


# =============================================================================
# _generate_queries_via_mcp
# =============================================================================


async def test_generate_queries_via_mcp_success_returns_parsed_queries() -> (
    None
):
    """A successful MCP call returns the parsed query list."""
    client = FakeCallToolClient(response=["query one", "query two"])

    result = await queries._generate_queries_via_mcp(
        cast(MCPToolClient, client), "goal", "qgen_tool", "boolean"
    )

    assert result == ["query one", "query two"]
    assert client.calls == [
        ("qgen_tool", {"research_goal": "goal", "query_format": "boolean"})
    ]


async def test_generate_queries_via_mcp_error_returns_empty_list() -> None:
    """A raised exception falls back to an empty list, not a raise.

    An empty list here is the signal that lets ``_phase1_generate_queries``
    fall through to LLM-based generation.
    """
    client = FakeCallToolClient(error=RuntimeError("mcp down"))

    result = await queries._generate_queries_via_mcp(
        cast(MCPToolClient, client), "goal", "qgen_tool", "boolean"
    )

    assert result == []


# =============================================================================
# _generate_queries_via_llm
# =============================================================================


async def test_generate_queries_via_llm_error_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised exception from the LLM call falls back to an empty list."""

    async def _raise(**_: Any) -> dict[str, Any]:
        raise RuntimeError("llm down")

    monkeypatch.setattr(queries, "call_llm_json", _raise)
    state = make_state(research_goal="goal x")

    result = await queries._generate_queries_via_llm(state, _search_config())

    assert result == []


# =============================================================================
# _resolve_query_format
# =============================================================================


def test_resolve_query_format_defaults_to_boolean_when_unset() -> None:
    """An empty ``query_format`` on the workflow falls back to ``boolean``."""
    workflow = WorkflowConfig(query_format="")
    assert queries._resolve_query_format(workflow) == "boolean"


def test_resolve_query_format_honors_configured_value() -> None:
    """A configured ``query_format`` is returned unchanged."""
    workflow = WorkflowConfig(query_format="natural_language")
    assert queries._resolve_query_format(workflow) == "natural_language"


# =============================================================================
# _resolve_query_generation_tool
# =============================================================================


def test_resolve_query_generation_tool_missing_tool_config_returns_none() -> (
    None
):
    """A configured tool id the registry can't resolve returns None."""
    workflow = WorkflowConfig(query_generation_tool="qgen_missing")
    config = _search_config(
        tool_registry=make_tool_lookup_registry({}),
        workflow=workflow,
    )

    assert queries._resolve_query_generation_tool(config) is None


def test_resolve_query_generation_tool_returns_name_and_format() -> None:
    """A resolvable tool id returns its MCP name and configured format."""
    tool_config = make_tool_config(mcp_tool_name="qgen_mcp")
    workflow = WorkflowConfig(
        query_generation_tool="qgen_tool", query_format="natural_language"
    )
    config = _search_config(
        tool_registry=make_tool_lookup_registry({"qgen_tool": tool_config}),
        workflow=workflow,
    )

    assert queries._resolve_query_generation_tool(config) == (
        "qgen_mcp",
        "natural_language",
    )


# =============================================================================
# _try_mcp_query_generation
# =============================================================================


async def test_try_mcp_query_generation_calls_the_resolved_tool() -> None:
    """A resolved query-generation tool is invoked via the MCP client."""
    tool_config = make_tool_config(mcp_tool_name="qgen_mcp")
    workflow = WorkflowConfig(
        query_generation_tool="qgen_tool", query_format="boolean"
    )
    config = _search_config(
        tool_registry=make_tool_lookup_registry({"qgen_tool": tool_config}),
        workflow=workflow,
    )
    client = FakeCallToolClient(response=["alpha", "beta"])
    state = make_state(research_goal="goal x")

    result = await queries._try_mcp_query_generation(
        state, config, cast(MCPToolClient, client)
    )

    assert result == ["alpha", "beta"]
    assert client.calls[0][0] == "qgen_mcp"


# =============================================================================
# _phase1_generate_queries -- final fallback to the research goal
# =============================================================================


async def test_final_fallback_distills_the_goal_instead_of_sending_it_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both generators fail, the fallback query is keyword-shaped.

    Sending the prose goal verbatim -- articles, punctuation, question
    words and all -- hands Entrez a query that collapses under its own
    AND-every-term semantics before the broadening ladder even runs. The
    fallback must strip that down to the same keyword shape the query-
    generation prompt itself asks the model for.
    """

    async def _raise(**_: Any) -> dict[str, Any]:
        raise RuntimeError("llm down")

    monkeypatch.setattr(queries, "call_llm_json", _raise)
    state = make_state(
        research_goal=(
            "How does mifepristone affect the glucocorticoid receptor"
            " in glioblastoma?"
        )
    )
    client = FakeCallToolClient(response=[])

    phase_result = await queries._phase1_generate_queries(
        state, _search_config(), cast(MCPToolClient, client)
    )
    result = phase_result.queries

    assert result != [state["research_goal"]]
    assert len(result) == 1
    # Both generators were exhausted before the keyword fallback, so the
    # LLM-fallback path did run (and failed) -- it still spent one call.
    assert phase_result.llm_calls == 1
    fallback = result[0]
    assert "?" not in fallback
    for stopword in ("how", "does", "the", "in"):
        assert stopword not in fallback.lower().split()
    for keyword in (
        "mifepristone",
        "glucocorticoid",
        "receptor",
        "glioblastoma",
    ):
        assert keyword in fallback.lower()

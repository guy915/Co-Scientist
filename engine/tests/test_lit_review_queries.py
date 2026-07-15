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

import dataclasses
from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import queries
from co_scientist.agents.generation.literature_review.helpers import (
    SearchConfig,
)
from co_scientist.config import ToolConfig, ToolRegistry, WorkflowConfig
from co_scientist.mcp_client import MCPToolClient
from tests._state import make_state

_DEFAULT_SEARCH_CONFIG = SearchConfig(
    tool_registry=None,
    workflow=None,
    is_multi_source=False,
    search_tool_name="pubmed_search_with_fulltext",
    search_tool_config=None,
    source_name="pubmed",
    papers_to_read_count=5,
    is_dev_mode=False,
)


def _search_config(**overrides: Any) -> SearchConfig:
    """Build a SearchConfig with inert defaults, overriding given fields."""
    return dataclasses.replace(_DEFAULT_SEARCH_CONFIG, **overrides)


def _tool_config(mcp_tool_name: str = "query_gen") -> ToolConfig:
    """Build a minimal ToolConfig for the query-generation tests."""
    return ToolConfig(server="s", mcp_tool_name=mcp_tool_name)


class _FakeMCPClient:
    """Minimal ``call_tool``-only stand-in for ``MCPToolClient``.

    Records every call and either returns a fixed response or raises a
    configured error, so success and failure paths can be driven without a
    live MCP server.
    """

    def __init__(
        self, response: Any = None, error: Exception | None = None
    ) -> None:
        """Store the response (or error) every ``call_tool`` invocation uses.

        Args:
            response: Value returned by ``call_tool`` when no error is set.
            error: Exception raised by ``call_tool`` instead of returning.
        """
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the call and return the response or raise the error."""
        self.calls.append((tool_name, kwargs))
        if self._error is not None:
            raise self._error
        return self._response


class _StubRegistry:
    """Minimal stand-in for ``ToolRegistry`` exposing only ``get_tool``."""

    def __init__(self, tools: dict[str, ToolConfig]) -> None:
        """Store the tool-id -> ToolConfig map ``get_tool`` resolves."""
        self._tools = tools

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Resolve a tool id to its configured ToolConfig, or None."""
        return self._tools.get(tool_id)


# =============================================================================
# _generate_queries_via_mcp
# =============================================================================


async def test_generate_queries_via_mcp_success_returns_parsed_queries() -> (
    None
):
    """A successful MCP call returns the parsed query list."""
    client = _FakeMCPClient(response=["query one", "query two"])

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
    client = _FakeMCPClient(error=RuntimeError("mcp down"))

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
        tool_registry=cast(ToolRegistry, _StubRegistry({})),
        workflow=workflow,
    )

    assert queries._resolve_query_generation_tool(config) is None


def test_resolve_query_generation_tool_returns_name_and_format() -> None:
    """A resolvable tool id returns its MCP name and configured format."""
    tool_config = _tool_config(mcp_tool_name="qgen_mcp")
    workflow = WorkflowConfig(
        query_generation_tool="qgen_tool", query_format="natural_language"
    )
    config = _search_config(
        tool_registry=cast(
            ToolRegistry, _StubRegistry({"qgen_tool": tool_config})
        ),
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
    tool_config = _tool_config(mcp_tool_name="qgen_mcp")
    workflow = WorkflowConfig(
        query_generation_tool="qgen_tool", query_format="boolean"
    )
    config = _search_config(
        tool_registry=cast(
            ToolRegistry, _StubRegistry({"qgen_tool": tool_config})
        ),
        workflow=workflow,
    )
    client = _FakeMCPClient(response=["alpha", "beta"])
    state = make_state(research_goal="goal x")

    result = await queries._try_mcp_query_generation(
        state, config, cast(MCPToolClient, client)
    )

    assert result == ["alpha", "beta"]
    assert client.calls[0][0] == "qgen_mcp"

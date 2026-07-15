"""Coverage-focused tests for the reflection agent ``reflection_helpers``.

``test_reflection_helpers.py`` covers the pure heuristics and
``fetch_indra_evidence``'s ``tool_registry=None`` short-circuit, which returns
before any MCP I/O happens. This file exercises the paths past that
short-circuit: a configured registry with no extractable entities, a
successful MCP round-trip (including one entity's query failing while
another succeeds), and the outer exception-swallowing branch -- plus the
formatting helpers (``_format_evidence``, ``_agent_name``) that are only
otherwise reached via that MCP round-trip.
"""

import json
from typing import Any, cast

import pytest

from co_scientist.agents.reflection.reflection_helpers import (
    _agent_name,
    _fetch_evidence_result,
    _format_evidence,
    _pick_available_tool,
    fetch_indra_evidence,
)
from co_scientist.config import ToolRegistry


class _FakeRegistry:
    """Minimal duck-typed ToolRegistry stand-in listing one KG tool."""

    def get_tools_for_workflow(self, workflow_name: str) -> list[str]:
        """Return a single configured tool id for any workflow name."""
        del workflow_name
        return ["indra_relations"]

    def get_mcp_tool_names(self, tool_ids: list[str]) -> list[str]:
        """Resolve the configured tool id to its MCP server tool name."""
        del tool_ids
        return ["get_relations"]


def _fake_registry() -> ToolRegistry:
    """Build a fake registry typed as ToolRegistry for the helper signatures."""
    return cast(ToolRegistry, _FakeRegistry())


class _FakeMcpClient:
    """Fake MCP client for ``_fetch_evidence_result``/``fetch_indra_evidence``.

    ``has_tool`` reports availability from a fixed set of names; ``call_tool``
    dispatches per-entity via ``responses``, where a value of ``None`` means
    "raise instead of returning" (simulating a failed per-entity query).
    """

    def __init__(
        self,
        available_tools: set[str],
        responses: dict[str, Any] | None = None,
    ) -> None:
        self._available_tools = available_tools
        self._responses = responses or {}

    def has_tool(self, name: str) -> bool:
        """Report whether ``name`` is available on this fake server."""
        return name in self._available_tools

    async def call_tool(self, _tool_name: str, **kwargs: Any) -> Any:
        """Return (or raise) the canned response for the queried entity."""
        entity = kwargs["agent"]
        if entity not in self._responses:
            return {"statements": []}
        response = self._responses[entity]
        if response is None:
            raise RuntimeError(f"simulated query failure for {entity}")
        return response


_ACTIVATION_STATEMENT = {
    "type": "Activation",
    "belief": 0.9,
    "evidence": [1, 2],
    "subj": {"name": "KRAS"},
    "obj": {"name": "BRAF"},
}


# --- _pick_available_tool ---------------------------------------------------


def test_pick_available_tool_returns_first_match() -> None:
    """The first mcp_name present on the client is returned."""
    client = _FakeMcpClient(available_tools={"get_relations"})
    assert (
        _pick_available_tool(client, ["get_complexes", "get_relations"])
        == "get_relations"
    )


def test_pick_available_tool_none_available_returns_empty_string() -> None:
    """No candidate tool present on the server yields an empty string."""
    client = _FakeMcpClient(available_tools=set())
    assert _pick_available_tool(client, ["get_relations"]) == ""


# --- _fetch_evidence_result ---------------------------------------------


async def test_fetch_evidence_result_no_tool_available_returns_none() -> None:
    """With no candidate tool on the server, the result is None."""
    client = _FakeMcpClient(available_tools=set())
    result = await _fetch_evidence_result(
        client, ["get_relations"], ["KRAS", "TREM2"], max_statements=5
    )
    assert result is None


async def test_fetch_evidence_result_no_statements_returns_none() -> None:
    """A tool that resolves but yields no statements for any entity is None."""
    client = _FakeMcpClient(
        available_tools={"get_relations"},
        responses={"KRAS": {"statements": []}, "TREM2": {"statements": []}},
    )
    result = await _fetch_evidence_result(
        client, ["get_relations"], ["KRAS", "TREM2"], max_statements=5
    )
    assert result is None


async def test_fetch_evidence_result_one_entity_fails_other_succeeds() -> None:
    """A per-entity query failure does not block a sibling entity's result.

    KRAS's query raises (exercising the per-entity exception-swallow path)
    while TREM2's query succeeds, so the pooled statement list is non-empty
    and the formatted result is built from it.
    """
    client = _FakeMcpClient(
        available_tools={"get_relations"},
        responses={
            "KRAS": None,  # Simulated failure.
            "TREM2": json.dumps({"statements": [_ACTIVATION_STATEMENT]}),
        },
    )
    result = await _fetch_evidence_result(
        client, ["get_relations"], ["KRAS", "TREM2"], max_statements=5
    )
    assert result is not None
    assert "KRAS --[Activation]--> BRAF" in result["prompt_text"]
    assert len(result["enrichment_items"]) == 1
    assert result["enrichment_items"][0]["relationship"] == "KRAS → BRAF"


# --- fetch_indra_evidence: past the tool_registry=None short-circuit -------


async def test_fetch_indra_evidence_no_entities_returns_empty() -> None:
    """A configured registry but entity-free hypothesis text yields empty."""
    result = await fetch_indra_evidence(
        "the quick brown fox jumps over the lazy dog",
        tool_registry=_fake_registry(),
    )
    assert result == {"prompt_text": "", "enrichment_items": []}


async def test_fetch_indra_evidence_returns_client_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful MCP round-trip returns the formatted evidence result."""
    fake_client = _FakeMcpClient(
        available_tools={"get_relations"},
        responses={
            "KRAS": json.dumps({"statements": [_ACTIVATION_STATEMENT]}),
        },
    )

    async def fake_get_mcp_client(**_: Any) -> _FakeMcpClient:
        return fake_client

    monkeypatch.setattr(
        "co_scientist.mcp_client.get_mcp_client", fake_get_mcp_client
    )

    result = await fetch_indra_evidence(
        "KRAS drives tumor growth", tool_registry=_fake_registry()
    )

    assert "KRAS --[Activation]--> BRAF" in result["prompt_text"]
    assert result["enrichment_items"]


async def test_fetch_indra_evidence_swallows_client_construction_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure obtaining the MCP client degrades to the empty result."""

    async def raising_get_mcp_client(**_: Any) -> Any:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "co_scientist.mcp_client.get_mcp_client", raising_get_mcp_client
    )

    result = await fetch_indra_evidence(
        "KRAS drives tumor growth", tool_registry=_fake_registry()
    )

    assert result == {"prompt_text": "", "enrichment_items": []}


# --- _format_evidence ---------------------------------------------------


def test_format_evidence_renders_header_and_valid_statement_lines() -> None:
    """Renderable statements follow a header naming the queried entities."""
    malformed = {"type": "Unknown"}  # Neither subj/obj nor members.
    text = _format_evidence(
        [_ACTIVATION_STATEMENT, malformed], ["KRAS", "BRAF"]
    )
    assert text.startswith(
        "Structured knowledge from the INDRA biomedical knowledge graph "
        "(queried for: KRAS, BRAF):"
    )
    assert "KRAS --[Activation]--> BRAF" in text
    # The malformed statement contributes no line.
    assert text.count("\n") == 1


def test_format_evidence_no_renderable_statements_returns_empty() -> None:
    """No renderable statements yields "" rather than a bare header."""
    assert _format_evidence([{"type": "Unknown"}], ["KRAS"]) == ""
    assert _format_evidence([], ["KRAS"]) == ""


# --- _agent_name --------------------------------------------------------


def test_agent_name_extracts_dict_name() -> None:
    """A dict-shaped agent's name field is returned."""
    assert _agent_name({"subj": {"name": "KRAS"}}, "subj") == "KRAS"


def test_agent_name_non_dict_agent_returns_empty_string() -> None:
    """A non-dict agent value (malformed statement) falls back to ""."""
    assert _agent_name({"subj": "KRAS"}, "subj") == ""


def test_agent_name_missing_role_returns_empty_string() -> None:
    """A statement missing the requested role key falls back to ""."""
    assert _agent_name({}, "obj") == ""

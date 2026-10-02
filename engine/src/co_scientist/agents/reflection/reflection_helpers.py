"""Helpers for INDRA knowledge graph integration in the reflection node.

Pre-fetches structured mechanistic evidence from INDRA CoGex to augment
reflection analysis. Entity extraction (identifying likely gene/protein names
in the hypothesis text) lives in ``reflection_entities`` and is re-exported
here for backward compatibility.
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, NamedTuple, Optional, cast

from co_scientist.agents.reflection.reflection_entities import (
    extract_entity_names as extract_entity_names,
)
from co_scientist.tools.response_parser import parse_mcp_result

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


# Only a knowledge-graph tool can answer the entity query this path sends
# (agent/limit/evidence_limit are INDRA's own argument names). A workflow's
# search_tools list mixes both kinds -- the shipped config lists PubMed,
# OpenAlex and the biomedical databases under `reflection` for the prompt
# context, and the INDRA example config *extends* that list, so its own
# tools arrive after them. Selecting on the declared source_type rather than
# on list position is what keeps this path from calling a literature tool
# with an entity name, which the server rejects outright.
_KNOWLEDGE_GRAPH_SOURCE_TYPE = "knowledge_graph"


def get_kg_tools_for_workflow(
    tool_registry: Optional["ToolRegistry"], workflow_name: str
) -> list[str]:
    """Resolve the workflow's knowledge-graph MCP tool names, in order.

    Returns an empty list when:
    - no tool_registry is configured
    - no workflow entry exists in the yaml
    - the workflow lists no enabled knowledge-graph tool

    This is the gate: if the list is empty, no tool calls happen for that
    workflow. The shipped config declares no knowledge-graph tool at all
    (the reference server's INDRA tools are opt-in), so the gate is closed
    by default and this path costs nothing.
    """
    if tool_registry is None:
        return []
    try:
        # tool_ids are internal registry keys; get_mcp_tool_names resolves
        # them to the actual MCP server tool names used by has_tool()/
        # call_tool() below.
        tool_ids = tool_registry.get_tools_for_workflow(workflow_name)
        if not tool_ids:
            return []
        return tool_registry.get_mcp_tool_names(
            _knowledge_graph_tool_ids(tool_registry, tool_ids)
        )
    except Exception:
        # Any registry lookup error degrades to "no KG tools" rather than
        # failing reflection.
        return []


def _knowledge_graph_tool_ids(
    tool_registry: "ToolRegistry", tool_ids: list[str]
) -> list[str]:
    """Keep only the tool ids declaring the knowledge-graph source type."""
    kept = []
    for tool_id in tool_ids:
        tool = tool_registry.get_tool(tool_id)
        if tool and tool.source_type == _KNOWLEDGE_GRAPH_SOURCE_TYPE:
            kept.append(tool_id)
    return kept


async def _fetch_evidence_result(
    client: Any,
    mcp_names: list[str],
    entities: list[str],
    max_statements: int,
) -> dict[str, Any] | None:
    """Resolves an available tool, queries INDRA, and formats the results.

    Returns None (rather than the shared "empty" result) if no candidate
    tool is available on the MCP server or no statements come back, so the
    caller can decide what "nothing found" maps to.

    Args:
        client: Shared MCP client.
        mcp_names: Candidate MCP tool names, in preference order.
        entities: Extracted entity names to query.
        max_statements: Cap on statements included in the result.

    Returns:
        Dict with "prompt_text" and "enrichment_items", or None.
    """
    tool_name = _pick_available_tool(client, mcp_names)
    if not tool_name:
        return None

    all_stmts = await _query_entities(
        client, tool_name, entities, max_statements
    )
    if not all_stmts:
        return None

    # Statements from every queried entity are pooled together, then capped
    # globally here rather than per-entity, so a prolific first entity can
    # crowd out a second entity's statements.
    capped = all_stmts[:max_statements]
    return {
        "prompt_text": _format_evidence(capped, entities),
        "enrichment_items": _build_enrichment_items(capped, entities),
    }


async def fetch_indra_evidence(
    hypothesis_text: str,
    tool_registry: Optional["ToolRegistry"] = None,
    max_statements: int = 5,
    workflow_name: str = "reflection",
) -> dict[str, Any]:
    """Pre-fetch mechanistic statements relevant to a hypothesis.

    Only runs if the yaml config explicitly opts in via a workflow section
    listing the tools to use. No workflow entry → no calls, even if the MCP
    server happens to have the tools registered.

    Returns dict with:
        - "prompt_text": formatted string for LLM prompt injection
        - "enrichment_items": structured list of dicts for UI rendering
    Both empty when skipped or on any failure.
    """
    empty = {"prompt_text": "", "enrichment_items": []}

    # Enforces the yaml opt-in gate: an empty tool list here means either no
    # tool_registry, no "reflection" workflow entry, or an explicitly empty
    # tool list for it.
    mcp_names = get_kg_tools_for_workflow(tool_registry, workflow_name)
    if not mcp_names:
        return empty

    # No gene/protein-like tokens found in the hypothesis text means there
    # is nothing meaningful to query INDRA for.
    entities = extract_entity_names(hypothesis_text)
    if not entities:
        return empty

    result = await _resolve_indra_result(
        tool_registry, mcp_names, entities, max_statements
    )
    return result if result is not None else empty


async def _resolve_indra_result(
    tool_registry: Optional["ToolRegistry"],
    mcp_names: list[str],
    entities: list[str],
    max_statements: int,
) -> dict[str, Any] | None:
    """Queries INDRA via the MCP client, returning None on any failure.

    Covers MCP client/connection failures, tool-call errors, etc. This is
    best-effort enrichment, so any failure here falls back to None rather
    than propagating into reflection_node.
    """
    try:
        from co_scientist.mcp_client import get_mcp_client

        # get_mcp_client returns a shared/global client (lazily created and
        # cached), so this reuses the same connection across hypotheses and
        # nodes rather than opening one per call.
        client = await get_mcp_client(tool_registry=tool_registry)
        return await _fetch_evidence_result(
            client, mcp_names, entities, max_statements
        )
    except Exception as e:
        logger.debug("reflection evidence fetch skipped: %s", e)
        return None


def _pick_available_tool(client: Any, mcp_names: list[str]) -> str:
    """Return the first workflow-listed tool that exists on the MCP server."""
    for name in mcp_names:
        if client.has_tool(name):
            return name
    return ""


# Cap on evidence items fetched per INDRA statement (not statements
# themselves); keeps individual tool responses bounded before formatting.
_EVIDENCE_LIMIT = 25


async def _query_single_entity(
    client: Any,
    tool_name: str,
    entity: str,
    max_per_entity: int,
) -> list[dict[str, Any]]:
    """Query a knowledge graph tool for one entity; returns its statements."""
    try:
        # "agent" is the INDRA/CoGex query parameter name for the entity
        # being queried, not a generic kwarg.
        raw = await client.call_tool(
            tool_name,
            agent=entity,
            limit=max_per_entity,
            evidence_limit=_EVIDENCE_LIMIT,
        )
        result = _parse_tool_result(raw)
        return cast("list[dict[str, Any]]", result.get("statements", []))
    except Exception as e:
        # One entity's query failure does not block the others gathered in
        # _query_entities below.
        logger.debug(
            "entity query failed for '%s' via %s: %s", entity, tool_name, e
        )
        return []


async def _query_entities(
    client: Any,
    tool_name: str,
    entities: list[str],
    max_per_entity: int,
) -> list[dict[str, Any]]:
    """Query a knowledge graph tool for all entities in parallel."""
    # Only the first 2 extracted entities are queried, even though
    # extract_entity_names can return up to 3, to bound the number of
    # concurrent KG calls per hypothesis.
    tasks = [
        _query_single_entity(client, tool_name, entity, max_per_entity)
        for entity in entities[:2]
    ]
    results = await asyncio.gather(*tasks)
    return [stmt for stmts in results for stmt in stmts]


def _parse_tool_result(raw: Any) -> dict[str, Any]:
    """Decode an MCP tool result, coercing malformed or non-dict data to {}."""
    try:
        decoded = parse_mcp_result(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _format_evidence(
    statements: list[dict[str, Any]], queried_entities: list[str]
) -> str:
    """Format INDRA statements concisely for prompt injection.

    Target: ~200-300 tokens for 5 statements. Each line is one relationship.
    """
    header = (
        "Structured knowledge from the INDRA biomedical knowledge graph "
        f"(queried for: {', '.join(queried_entities)}):"
    )
    lines = [header]

    for stmt in statements:
        line = _format_single_statement(stmt)
        if line:
            lines.append(line)

    # If no statement produced a renderable line, lines holds only the
    # header; return "" (not the bare header) so callers treat this the
    # same as "no evidence" rather than injecting an empty-looking section.
    return "\n".join(lines) if len(lines) > 1 else ""


def _ev_count_str(ev_count: int) -> str:
    """Format evidence count, adding '+' when capped at the fetch limit."""
    return f"{ev_count}+" if ev_count >= _EVIDENCE_LIMIT else str(ev_count)


class IndraStatementCore(NamedTuple):
    """Core fields shared by every INDRA statement formatter."""

    subj: str
    obj: str
    member_names: list[str]
    rel_type: str
    belief: float
    ev_count: int


def parse_indra_statement(stmt: dict[str, Any]) -> IndraStatementCore:
    """Extract the fields every INDRA statement formatter renders.

    Owns the subject/object versus complex-members shape decision so the
    formatters differ only in how they lay the values out, and absorbs the
    shapes a knowledge-graph server can return for an endpoint that is not a
    plain agent dict (see ``_agent_name``). Shared with the literature
    review's context enrichment, which renders the same statements as
    causal edges for the synthesis prompt.
    """
    # INDRA statements come in two shapes: simple pairwise relations
    # (subj/obj) or "Complex"/family statements that list members instead;
    # every formatter branches on which fields are populated below.
    members = stmt.get("members", [])
    return IndraStatementCore(
        subj=_agent_name(stmt, "subj"),
        obj=_agent_name(stmt, "obj"),
        member_names=[
            m.get("name", "?") for m in members if isinstance(m, dict)
        ],
        rel_type=stmt.get("type", "Unknown"),
        belief=stmt.get("belief", 0),
        ev_count=len(stmt.get("evidence", [])),
    )


def _format_single_statement(stmt: dict[str, Any]) -> str:
    """Format one INDRA statement as a concise line."""
    core = parse_indra_statement(stmt)
    ev_str = _ev_count_str(core.ev_count)

    if core.subj and core.obj:
        return (
            f"- {core.subj} --[{core.rel_type}]--> {core.obj} "
            f"(belief: {core.belief:.2f}, {ev_str} papers)"
        )

    # complex/family statements have members instead of subj/obj
    if core.member_names:
        return (
            f"- Complex({', '.join(core.member_names)}) [{core.rel_type}] "
            f"(belief: {core.belief:.2f}, {ev_str} papers)"
        )

    # Neither shape matched (malformed statement); _format_evidence's
    # `if line:` check drops this line rather than the caller crashing.
    return ""


def _build_enrichment_items(
    statements: list[dict[str, Any]],
    queried_entities: list[str],
) -> list[dict[str, str]]:
    """Build structured items for hypothesis.enrichments (UI rendering).

    Each item has display-ready string fields that map directly to
    the customFields config in the domain JSON.
    """
    items: list[dict[str, str]] = []
    for stmt in statements:
        item = _statement_to_enrichment_item(stmt)
        if item:
            items.append(item)

    # Queried-entity context is attached to the first item only, not
    # duplicated onto every item, since the UI renders one row per item.
    if items:
        items[0]["queried_entities"] = ", ".join(queried_entities)
    return items


def _statement_to_enrichment_item(
    stmt: dict[str, Any],
) -> dict[str, str] | None:
    """Convert one INDRA statement into a flat dict for UI display."""
    # Mirrors _format_single_statement's subj/obj vs. members branching,
    # but returns a dict of individual fields instead of one text line.
    # Only the relationship text differs between the two shapes, so the
    # branch produces that string and the item is built once.
    core = parse_indra_statement(stmt)

    if core.subj and core.obj:
        relationship = f"{core.subj} \u2192 {core.obj}"
    elif core.member_names:
        relationship = f"Complex({', '.join(core.member_names)})"
    else:
        return None

    return {
        "relationship": relationship,
        "type": core.rel_type,
        "belief": f"{core.belief:.0%}",
        "evidence_count": _ev_count_str(core.ev_count),
    }


def _agent_name(stmt: dict[str, Any], role: str) -> str:
    """Extract agent name from an INDRA statement."""
    agent = stmt.get(role, {})
    if isinstance(agent, dict):
        return cast(str, agent.get("name", ""))
    return ""

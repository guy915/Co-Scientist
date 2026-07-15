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
    _ALIAS_MAP as _ALIAS_MAP,
)
from co_scientist.agents.reflection.reflection_entities import (
    _HYPHENATED_RE as _HYPHENATED_RE,
)
from co_scientist.agents.reflection.reflection_entities import (
    _STANDALONE_RE as _STANDALONE_RE,
)
from co_scientist.agents.reflection.reflection_entities import (
    _STOP as _STOP,
)
from co_scientist.agents.reflection.reflection_entities import (
    _add_hyphenated_entities as _add_hyphenated_entities,
)
from co_scientist.agents.reflection.reflection_entities import (
    _add_standalone_entities as _add_standalone_entities,
)
from co_scientist.agents.reflection.reflection_entities import (
    _is_mutation_notation as _is_mutation_notation,
)
from co_scientist.agents.reflection.reflection_entities import (
    _normalize_entity as _normalize_entity,
)
from co_scientist.agents.reflection.reflection_entities import (
    _should_skip_entity as _should_skip_entity,
)
from co_scientist.agents.reflection.reflection_entities import (
    extract_entity_names as extract_entity_names,
)
from co_scientist.tools.response_parser import parse_mcp_result

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


def get_kg_tools_for_workflow(
    tool_registry: Optional["ToolRegistry"], workflow_name: str
) -> list[str]:
    """Resolve which MCP tool names the yaml config assigned to search_tools.

    Returns an empty list when:
    - no tool_registry is configured
    - no workflow entry exists in the yaml
    - the workflow lists no enabled tools

    This is the gate: if the list is empty, no tool calls happen for that
    workflow.
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
        return tool_registry.get_mcp_tool_names(tool_ids)
    except Exception:
        # Any registry lookup error degrades to "no KG tools" rather than
        # failing reflection.
        return []


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

    try:
        from co_scientist.mcp_client import (
            get_mcp_client,
        )

        # get_mcp_client returns a shared/global client (lazily created and
        # cached), so this reuses the same connection across hypotheses and
        # nodes rather than opening one per call.
        client = await get_mcp_client(tool_registry=tool_registry)
        result = await _fetch_evidence_result(
            client, mcp_names, entities, max_statements
        )
        return result if result is not None else empty

    except Exception as e:
        # Covers MCP client/connection failures, tool-call errors, etc.
        # This is best-effort enrichment, so any failure here falls back to
        # empty rather than propagating into reflection_node.
        logger.debug("reflection evidence fetch skipped: %s", e)
        return empty


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


class _StatementCore(NamedTuple):
    """Core fields shared by the two INDRA statement formatters."""

    subj: str
    obj: str
    member_names: list[str]
    rel_type: str
    belief: float
    ev_count: int


def _parse_statement(stmt: dict[str, Any]) -> _StatementCore:
    """Extract the fields both statement formatters render.

    Owns the subject/object versus complex-members shape decision so the two
    formatters differ only in how they lay the values out.
    """
    # INDRA statements come in two shapes: simple pairwise relations
    # (subj/obj) or "Complex"/family statements that list members instead;
    # both formatters branch on which fields are populated below.
    members = stmt.get("members", [])
    return _StatementCore(
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
    core = _parse_statement(stmt)
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
    core = _parse_statement(stmt)

    if core.subj and core.obj:
        return {
            "relationship": f"{core.subj} \u2192 {core.obj}",
            "type": core.rel_type,
            "belief": f"{core.belief:.0%}",
            "evidence_count": _ev_count_str(core.ev_count),
        }

    if core.member_names:
        return {
            "relationship": f"Complex({', '.join(core.member_names)})",
            "type": core.rel_type,
            "belief": f"{core.belief:.0%}",
            "evidence_count": _ev_count_str(core.ev_count),
        }

    return None


def _agent_name(stmt: dict[str, Any], role: str) -> str:
    """Extract agent name from an INDRA statement."""
    agent = stmt.get(role, {})
    if isinstance(agent, dict):
        return cast(str, agent.get("name", ""))
    return ""

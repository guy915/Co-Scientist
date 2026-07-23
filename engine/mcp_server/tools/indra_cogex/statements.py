"""INDRA mechanistic statement queries - the core knowledge retrieval tool.

INDRA statements are machine-readable causal assertions extracted from
biomedical literature (e.g. "KRAS activates RAF1", "Sotorasib inhibits KRAS").
"""

import logging
from dataclasses import dataclass
from typing import Any

from mcp_server.tools.indra_cogex.client import (
    cap_results,
    indra_post,
    maybe_parse_agent,
    parse_id,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _StatementQuery:
    """One mechanistic-statement query, as supplied by the caller.

    Attributes:
        agent: Primary agent name or CURIE, if querying by agent.
        other_agent: Optional secondary agent to relate the primary to.
        relation_types: Optional relation-type filters.
        agent_role: Optional role constraint ("subject" or "object").
        mesh_term: MeSH identifier, if querying by disease/topic instead.
        limit: Max statements to return.
        evidence_limit: Max evidence entries per statement.
    """

    agent: str | None
    other_agent: str | None
    relation_types: list[str] | None
    agent_role: str | None
    mesh_term: str | None
    limit: int
    evidence_limit: int


async def query_mechanistic_statements(
    agent: str | None = None,
    other_agent: str | None = None,
    relation_types: list[str] | None = None,
    agent_role: str | None = None,
    mesh_term: str | None = None,
    limit: int = 30,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    """Queries INDRA mechanistic statements from curated biomedical knowledge.

    INDRA statements are structured causal claims extracted from scientific
    papers. Query by agent name(s) (plain names like "KRAS" or CURIEs like
    "HGNC:6407"), or by a MeSH disease/topic term.

    Args:
        agent: Gene, protein, or drug name, or a "NAMESPACE:id" identifier.
        other_agent: Second entity to find relationships between.
        relation_types: Filter by relation type(s), e.g. Activation,
            Inhibition, Phosphorylation, IncreaseAmount, Complex.
        agent_role: "subject" or "object" to constrain the agent's role.
        mesh_term: MeSH disease/topic ID in "MESH:id" format, e.g.
            "MESH:D002289" (lung neoplasms).
        limit: Max statements to return (default 30).
        evidence_limit: Max evidence entries per statement (default 5).

    Returns:
        Dict with mechanistic statements, evidence, and metadata.
    """
    return await _dispatch_statement_query(
        _StatementQuery(
            agent=agent,
            other_agent=other_agent,
            relation_types=relation_types,
            agent_role=agent_role,
            mesh_term=mesh_term,
            limit=limit,
            evidence_limit=evidence_limit,
        )
    )


async def _dispatch_statement_query(
    query: _StatementQuery,
) -> dict[str, Any]:
    """Routes a statement query to the MeSH or agent path, wrapping errors.

    Returns:
        Dict with statements and metadata, or an error payload.
    """
    query_meta = _statement_query_meta(query)
    try:
        if query.mesh_term:
            stmts, total = await _query_by_mesh(
                query.mesh_term, query.evidence_limit, query.limit
            )
        elif query.agent:
            stmts, total = await _query_by_agents(query.agent, query)
        else:
            return {
                "error": "provide either 'agent' or 'mesh_term'",
                "query": query_meta,
            }
        return _statements_response(stmts, total, query_meta)
    except Exception as e:
        logger.error("query_mechanistic_statements failed: %s", e)
        return {"error": str(e), "query": query_meta}


def _statements_response(
    stmts: list[Any],
    total: int,
    query_meta: dict[str, Any],
) -> dict[str, Any]:
    """Wraps capped statements and their total into the tool response dict.

    Returns:
        Dict with statements, total_statements, and query metadata.
    """
    return {
        "statements": stmts,
        "total_statements": total,
        "query": query_meta,
    }


def _statement_query_meta(query: _StatementQuery) -> dict[str, Any]:
    """Builds the query-metadata dict echoed back in every response.

    Returns:
        Dict summarizing the agent, other_agent, mesh_term, and
        relation_types the caller supplied.
    """
    return {
        "agent": query.agent,
        "other_agent": query.other_agent,
        "mesh_term": query.mesh_term,
        "relation_types": query.relation_types,
    }


async def _query_by_mesh(
    mesh_term: str,
    evidence_limit: int,
    limit: int,
) -> tuple[list[Any], int]:
    """Queries statements by MeSH disease/topic annotation.

    Args:
        mesh_term: MeSH identifier in "MESH:id" format.
        evidence_limit: Max evidence entries per statement.
        limit: Max statements to return.

    Returns:
        Tuple of (capped statement list, total statement count).
    """
    curie = parse_id(mesh_term)
    # include_child_terms also pulls statements annotated with more specific
    # MeSH descendants of this term (e.g. subtypes of a disease).
    raw = await indra_post(
        "/api/get_stmts_for_mesh",
        {
            "mesh_term": curie,
            "include_child_terms": True,
            "evidence_limit": evidence_limit,
            "include_db_evidence": True,
        },
    )
    return cap_results(raw, limit)


async def _query_by_agents(
    agent: str,
    query: _StatementQuery,
) -> tuple[list[Any], int]:
    """Queries statements by agent name(s) and optional filters.

    Args:
        agent: Primary agent name or CURIE, already narrowed to non-None.
        query: The full query whose filters and limits shape the payload.

    Returns:
        Tuple of (capped statement list, total statement count).
    """
    # Only include filters the caller specified: the CoGex endpoint treats
    # a present-but-empty filter differently from an absent one.
    payload: dict[str, Any] = {
        "agent": maybe_parse_agent(agent),
        "limit": query.limit,
        "evidence_limit": query.evidence_limit,
    }
    if query.other_agent:
        payload["other_agent"] = maybe_parse_agent(query.other_agent)
    if query.relation_types:
        payload["rel_types"] = query.relation_types
    if query.agent_role:
        payload["agent_role"] = query.agent_role

    raw = await indra_post("/api/get_statements", payload)
    return cap_results(raw, query.limit)

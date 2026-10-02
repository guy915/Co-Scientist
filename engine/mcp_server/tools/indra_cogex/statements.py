"""INDRA mechanistic statement queries - the core knowledge retrieval tool.

INDRA statements are machine-readable causal assertions extracted from
biomedical literature (e.g. "KRAS activates RAF1", "Sotorasib inhibits KRAS").
"""

import logging
from typing import Any

from mcp_server.tools.indra_cogex.client import (
    cap_results,
    indra_post,
    maybe_parse_agent,
    parse_id,
    tool_error,
)

logger = logging.getLogger(__name__)


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
    query_meta = {
        "agent": agent,
        "other_agent": other_agent,
        "mesh_term": mesh_term,
        "relation_types": relation_types,
    }
    try:
        if mesh_term:
            # MeSH descendants and curated database evidence are included.
            raw = await indra_post(
                "/api/get_stmts_for_mesh",
                {
                    "mesh_term": parse_id(mesh_term),
                    "include_child_terms": True,
                    "evidence_limit": evidence_limit,
                    "include_db_evidence": True,
                },
            )
        elif agent:
            # An omitted filter differs from a present-but-empty one in CoGex.
            payload: dict[str, Any] = {
                "agent": maybe_parse_agent(agent),
                "limit": limit,
                "evidence_limit": evidence_limit,
            }
            if other_agent:
                payload["other_agent"] = maybe_parse_agent(other_agent)
            payload.update(
                {
                    key: value
                    for key, value in (
                        ("rel_types", relation_types),
                        ("agent_role", agent_role),
                    )
                    if value
                }
            )
            raw = await indra_post("/api/get_statements", payload)
        else:
            return tool_error(
                "provide either 'agent' or 'mesh_term'", query_meta
            )
        statements, total = cap_results(raw, limit)
        return {
            "statements": statements,
            "total_statements": total,
            "query": query_meta,
        }
    except Exception as exc:
        logger.error("query_mechanistic_statements failed: %s", exc)
        return tool_error(str(exc), query_meta)

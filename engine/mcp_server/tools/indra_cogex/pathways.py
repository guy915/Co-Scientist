"""Biological pathway and causal subnetwork queries against INDRA CoGex."""

import logging
from typing import Any

from mcp_server.tools.indra_cogex.client import (
    cap_results,
    indra_post,
    parse_id,
)

logger = logging.getLogger(__name__)


async def query_pathways(
    gene_ids: list[str],
    max_results: int = 50,
) -> dict[str, Any]:
    """Queries biological pathways for genes from the INDRA knowledge graph.

    For a single gene, returns all pathways containing that gene.
    For multiple genes, returns shared pathways across all of them.

    Args:
        gene_ids: One or more gene identifiers in "HGNC:id" format.
            Single: ["HGNC:6407"] for KRAS pathways.
            Multiple: ["HGNC:6407", "HGNC:1097"] for shared KRAS/BRAF pathways.
        max_results: Max pathways to return (default 50).

    Returns:
        Dict with pathways and metadata.
    """
    try:
        return await _run_pathways(gene_ids, max_results)
    except Exception as e:
        logger.error("query_pathways failed: %s", e)
        return {"error": str(e), "query": {"gene_ids": gene_ids}}


async def _run_pathways(
    gene_ids: list[str],
    max_results: int,
) -> dict[str, Any]:
    """Fetches single-gene or shared pathways from INDRA.

    Args:
        gene_ids: One or more gene identifiers in "HGNC:id" format.
        max_results: Max pathways to return.

    Returns:
        Dict with pathways and metadata.
    """
    curies = [parse_id(gid) for gid in gene_ids]
    mode = "shared" if len(curies) > 1 else "single"

    if len(curies) == 1:
        # Single gene: all pathways it participates in.
        raw = await indra_post(
            "/api/get_pathways_for_gene",
            {"gene": curies[0]},
        )
    else:
        # Multiple genes: intersection of pathways common to all of them,
        # useful for finding shared functional context.
        raw = await indra_post(
            "/api/get_shared_pathways_for_genes",
            {"genes": curies},
        )

    pathways, total = cap_results(raw, max_results)
    return {
        "pathways": pathways,
        "total_pathways": total,
        "query": {"gene_ids": gene_ids, "mode": mode},
    }


async def query_causal_subnetwork(
    node_ids: list[str],
    find_mediators: bool = True,
    max_results: int = 50,
) -> dict[str, Any]:
    """Queries causal subnetwork between biological entities from INDRA.

    Finds mechanistic connections between entities. When find_mediators is
    True, discovers intermediate nodes X such that A -> X -> B, revealing
    indirect regulatory pathways.

    Args:
        node_ids: Two or more entity identifiers in "NAMESPACE:id" format.
            E.g. ["HGNC:6407", "HGNC:5173"] to find paths between KRAS and
            HRAS. Supports genes (HGNC), protein families (FPLX), etc.
        find_mediators: If True (default), find mediated pathways (A -> X -> B).
            If False, return direct relations between the given nodes.
        max_results: Max relations to return (default 50).

    Returns:
        Dict with subnetwork relations and metadata.
    """
    try:
        return await _run_causal_subnetwork(
            node_ids, find_mediators, max_results
        )
    except Exception as e:
        logger.error("query_causal_subnetwork failed: %s", e)
        return {"error": str(e), "query": {"node_ids": node_ids}}


async def _run_causal_subnetwork(
    node_ids: list[str],
    find_mediators: bool,
    max_results: int,
) -> dict[str, Any]:
    """Fetches a mediated or direct causal subnetwork from INDRA.

    Args:
        node_ids: Two or more entity identifiers in "NAMESPACE:id" format.
        find_mediators: If True, find mediated pathways (A -> X -> B); if
            False, return direct relations between the given nodes.
        max_results: Max relations to return.

    Returns:
        Dict with subnetwork relations and metadata.
    """
    curies = [parse_id(nid) for nid in node_ids]

    if find_mediators:
        # Search for indirect paths A -> X -> B through an unlisted
        # intermediate node X, ranked by supporting evidence count.
        raw = await indra_post(
            "/api/indra_mediated_subnetwork",
            {"nodes": curies, "order_by_ev_count": True},
        )
    else:
        # Only direct statements between the given nodes, including
        # evidence sourced from curated pathway databases.
        raw = await indra_post(
            "/api/indra_subnetwork_relations",
            {"nodes": curies, "include_db_evidence": True},
        )

    items, total = cap_results(raw, max_results)
    return {
        "subnetwork": items,
        "total_relations": total,
        "query": {"node_ids": node_ids, "find_mediators": find_mediators},
    }

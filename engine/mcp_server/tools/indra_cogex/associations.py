"""Gene-disease-variant and gene codependence queries against INDRA CoGex."""

import logging
from typing import Any

from mcp_server.tools.indra_cogex.client import (
    cap_results,
    indra_post,
    parse_id,
    tool_error,
)

logger = logging.getLogger(__name__)


async def query_gene_disease_network(
    identifier: str,
    entity_type: str = "disease",
    include_variants: bool = False,
    max_results: int = 50,
) -> dict[str, Any]:
    """Queries gene-disease-variant associations from INDRA's knowledge graph.

    Given a disease, find associated genes (and optionally genetic variants).
    Given a gene, find associated diseases (and optionally genetic variants).

    Args:
        identifier: Entity in "NAMESPACE:id" format.
            Diseases: "DOID:162" (cancer), "MESH:D000544" (Alzheimer disease),
                "MESH:D002289" (non-small cell lung carcinoma)
            Genes: "HGNC:6407" (KRAS), "HGNC:3236" (EGFR),
                "HGNC:11730" (TREM2)
        entity_type: "disease" to find genes for a disease, "gene" to find
            diseases for a gene.
        include_variants: Also return associated genetic variants.
        max_results: Max results per category (default 50).

    Returns:
        Dict with associated entities, counts, and query metadata.
    """
    query_meta = {"identifier": identifier, "entity_type": entity_type}
    try:
        curie = parse_id(identifier)
        if entity_type not in ("disease", "gene"):
            return tool_error(
                f"invalid entity_type '{entity_type}', use 'disease' or 'gene'",
                query_meta,
            )
        result: dict[str, Any] = {"query": query_meta}
        result_key = "genes" if entity_type == "disease" else "diseases"
        raw = await indra_post(
            f"/api/get_{result_key}_for_{entity_type}", {entity_type: curie}
        )
        result[result_key], result[f"total_{result_key}"] = cap_results(
            raw, max_results
        )
        if include_variants:
            raw = await indra_post(
                f"/api/get_variants_for_{entity_type}", {entity_type: curie}
            )
            result["variants"], result["total_variants"] = cap_results(
                raw, max_results
            )
        return result
    except Exception as exc:
        logger.error("query_gene_disease_network failed: %s", exc)
        return tool_error(str(exc), query_meta)


async def query_gene_codependents(
    gene_id: str,
    max_results: int = 50,
) -> dict[str, Any]:
    """Finds genes codependent with a given gene from DepMap CRISPR screens.

    Codependent genes are functionally linked: when one is essential in a cell
    line, the other tends to be too. Useful for discovering synthetic lethal
    targets and functional gene networks in cancer research.

    Args:
        gene_id: Gene in "HGNC:id" format.
            Examples: "HGNC:6407" (KRAS), "HGNC:3236" (EGFR),
                "HGNC:1097" (BRAF)
        max_results: Max codependent genes to return (default 50).

    Returns:
        Dict with codependent genes and counts.
    """
    query_meta = {"gene_id": gene_id}
    try:
        raw = await indra_post(
            "/api/get_codependents_for_gene", {"gene": parse_id(gene_id)}
        )
        genes, total = cap_results(raw, max_results)
        return {
            "codependent_genes": genes,
            "total_codependents": total,
            "query": query_meta,
        }
    except Exception as exc:
        logger.error("query_gene_codependents failed: %s", exc)
        return tool_error(str(exc), query_meta)

"""Gene-disease-variant and gene codependence queries against INDRA CoGex."""

import logging
from typing import Any

from mcp_server.tools.indra_cogex.client import (
    cap_results,
    indra_post,
    parse_id,
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
    try:  # pylint: disable=broad-exception-caught
        # Convert "NAMESPACE:id" into the [namespace, id] pair CoGex
        # expects.
        curie = parse_id(identifier)
        result: dict[str, Any] = {
            "query": {"identifier": identifier, "entity_type": entity_type},
        }

        if entity_type == "disease":
            disease_result = await _fetch_genes_for_disease(
                curie, include_variants, max_results
            )
            result.update(disease_result)
        elif entity_type == "gene":
            gene_result = await _fetch_diseases_for_gene(
                curie, include_variants, max_results
            )
            result.update(gene_result)
        else:
            entity_err = f"invalid entity_type '{entity_type}'"
            return {"error": f"{entity_err}, use 'disease' or 'gene'"}

        return result

    # Any failure (bad identifier, network error, API error) is converted
    # into a structured error payload rather than raised, since this
    # function is an MCP tool endpoint and must always return a dict.
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("query_gene_disease_network failed: %s", e)
        return {
            "error": str(e),
            "query": {"identifier": identifier, "entity_type": entity_type},
        }


async def _fetch_genes_for_disease(
    curie: list[str],
    include_variants: bool,
    max_results: int,
) -> dict[str, Any]:
    """Fetches genes (and optionally variants) associated with a disease.

    Args:
        curie: Disease identifier as a [namespace, id] CoGex pair.
        include_variants: Also fetch genetic variants linked to the disease
            (e.g. GWAS-identified SNPs).
        max_results: Max results per category.

    Returns:
        Dict with "genes"/"total_genes" and, when include_variants is True,
        "variants"/"total_variants".
    """
    # Disease -> genes known to be associated with it.
    raw = await indra_post(
        "/api/get_genes_for_disease",
        {"disease": curie},
    )
    out: dict[str, Any] = {}
    out["genes"], out["total_genes"] = cap_results(raw, max_results)
    if include_variants:
        vraw = await indra_post(
            "/api/get_variants_for_disease",
            {"disease": curie},
        )
        out["variants"], out["total_variants"] = cap_results(
            vraw,
            max_results,
        )
    return out


async def _fetch_diseases_for_gene(
    curie: list[str],
    include_variants: bool,
    max_results: int,
) -> dict[str, Any]:
    """Fetches diseases (and optionally variants) associated with a gene.

    Args:
        curie: Gene identifier as a [namespace, id] CoGex pair.
        include_variants: Also fetch genetic variants linked to the gene.
        max_results: Max results per category.

    Returns:
        Dict with "diseases"/"total_diseases" and, when include_variants is
        True, "variants"/"total_variants".
    """
    # Gene -> diseases it has been associated with.
    raw = await indra_post(
        "/api/get_diseases_for_gene",
        {"gene": curie},
    )
    out: dict[str, Any] = {}
    out["diseases"], out["total_diseases"] = cap_results(raw, max_results)
    if include_variants:
        vraw = await indra_post(
            "/api/get_variants_for_gene",
            {"gene": curie},
        )
        out["variants"], out["total_variants"] = cap_results(
            vraw,
            max_results,
        )
    return out


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
    try:  # pylint: disable=broad-exception-caught
        curie = parse_id(gene_id)
        # Codependency scores come from DepMap CRISPR knockout screens:
        # genes whose essentiality profiles correlate across cell lines.
        raw = await indra_post(
            "/api/get_codependents_for_gene",
            {"gene": curie},
        )
        genes, total = cap_results(raw, max_results)
        return {
            "codependent_genes": genes,
            "total_codependents": total,
            "query": {"gene_id": gene_id},
        }
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("query_gene_codependents failed: %s", e)
        return {"error": str(e), "query": {"gene_id": gene_id}}

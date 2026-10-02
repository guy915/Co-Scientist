"""Gene set enrichment analysis tools via INDRA CoGex."""

import logging
from typing import Any

from mcp_server.tools.indra_cogex.client import (
    indra_post,
    tool_error,
)

logger = logging.getLogger(__name__)


async def run_enrichment_analysis(
    gene_list: list[str],
    analysis_type: str = "discrete",
    alpha: float = 0.05,
    negative_genes: list[str] | None = None,
    keep_insignificant: bool = False,
    minimum_evidence_count: int = 1,
    minimum_belief: float = 0.0,
) -> dict[str, Any]:
    """Runs statistical enrichment analysis on gene/phosphosite sets via INDRA.

    Analysis types:
    - "discrete": over-representation analysis on a gene list.
    - "signed": reverse causal reasoning on up/down-regulated genes.
    - "kinase": kinase enrichment on phosphosite data.

    Args:
        gene_list: Gene identifiers. Discrete/signed: HGNC IDs. Kinase:
            phosphosites as "GENE-SITE" (e.g. "MAPK1-Y187").
        analysis_type: "discrete", "signed", or "kinase".
        alpha: Significance threshold (default 0.05).
        negative_genes: Downregulated genes (required for signed only).
        keep_insignificant: Include non-significant results (default False).
        minimum_evidence_count: Min supporting evidence (default 1).
        minimum_belief: Min belief score threshold (default 0.0).

    Returns:
        Dict with enrichment results and metadata.
    """
    query_meta = {"analysis_type": analysis_type, "gene_count": len(gene_list)}
    if analysis_type == "signed" and not negative_genes:
        return tool_error(
            "signed analysis requires 'negative_genes'", query_meta
        )
    if analysis_type not in ("discrete", "signed", "kinase"):
        return tool_error(
            f"invalid analysis_type '{analysis_type}', "
            "use: discrete, signed, kinase",
            query_meta,
        )

    payload: dict[str, Any] = {
        "alpha": alpha,
        "keep_insignificant": keep_insignificant,
        "minimum_evidence_count": minimum_evidence_count,
        "minimum_belief": minimum_belief,
    }
    gene_key = {
        "discrete": "gene_list",
        "signed": "positive_genes",
        "kinase": "phosphosite_list",
    }[analysis_type]
    payload[gene_key] = gene_list
    if analysis_type == "signed":
        payload["negative_genes"] = negative_genes
    try:
        raw = await indra_post(f"/api/{analysis_type}_analysis", payload)
        return {"results": raw, "query": query_meta}
    except Exception as exc:
        logger.error("run_enrichment_analysis failed: %s", exc)
        return tool_error(str(exc), query_meta)

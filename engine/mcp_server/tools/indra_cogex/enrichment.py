"""Gene set enrichment analysis tools via INDRA CoGex."""

import logging
from typing import Any

from mcp_server.tools.indra_cogex.client import indra_post

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

    Three analysis types available:
    - "discrete": Over-representation analysis on a gene list. Finds enriched
      GO terms, pathways, phenotypes, and upstream regulators.
    - "signed": Reverse causal reasoning on up/down-regulated genes. Identifies
      upstream regulators explaining observed expression changes.
    - "kinase": Kinase enrichment on phosphosite data. Finds kinases whose
      known substrates are overrepresented in the input.

    Args:
        gene_list: Gene identifiers as strings.
            For discrete/signed: HGNC IDs (e.g. ["613", "1116", "1119"]).
            For signed: these are the upregulated (positive) genes.
            For kinase: phosphosites as "GENE-SITE" (e.g. ["MAPK1-Y187"]).
        analysis_type: "discrete", "signed", or "kinase".
        alpha: Significance threshold (default 0.05).
        negative_genes: Downregulated genes (required for signed analysis only).
        keep_insignificant: Include non-significant results (default False).
        minimum_evidence_count: Min supporting evidence for inclusion
            (default 1).
        minimum_belief: Min belief score threshold (default 0.0).

    Returns:
        Dict with enrichment results and metadata.
    """
    query_meta = {
        "analysis_type": analysis_type,
        "gene_count": len(gene_list),
    }

    # Requires both up- and down-regulated gene sets so INDRA can reason
    # about which upstream regulators would explain the observed
    # direction of change.
    if analysis_type == "signed" and not negative_genes:
        return {
            "error": "signed analysis requires 'negative_genes'",
            "query": query_meta,
        }
    if analysis_type not in ("discrete", "signed", "kinase"):
        valid = "discrete, signed, kinase"
        return {
            "error": f"invalid analysis_type '{analysis_type}', use: {valid}",
        }

    try:  # pylint: disable=broad-exception-caught
        raw = await _dispatch_enrichment_analysis(
            analysis_type,
            gene_list,
            negative_genes,
            alpha,
            keep_insignificant,
            minimum_evidence_count,
            minimum_belief,
        )
        return {"results": raw, "query": query_meta}

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("run_enrichment_analysis failed: %s", e)
        return {"error": str(e), "query": query_meta}


async def _dispatch_enrichment_analysis(
    analysis_type: str,
    gene_list: list[str],
    negative_genes: list[str] | None,
    alpha: float,
    keep_insignificant: bool,
    minimum_evidence_count: int,
    minimum_belief: float,
) -> Any:
    """Delegates to the INDRA call matching a validated analysis_type.

    Args:
        analysis_type: One of "discrete", "signed", "kinase"; already
            validated by the caller.
        gene_list: Gene (or phosphosite, for kinase) identifiers.
        negative_genes: Downregulated genes; already validated as
            non-empty by the caller when analysis_type is "signed".
        alpha: Significance threshold.
        keep_insignificant: Include non-significant results.
        minimum_evidence_count: Minimum supporting evidence count.
        minimum_belief: Minimum belief score threshold.

    Returns:
        Raw API response from the matching INDRA enrichment endpoint.
    """
    if analysis_type == "discrete":
        # Over-representation (hypergeometric-style) test: are the given
        # genes enriched for specific pathways/GO terms/etc. more than
        # expected by chance?
        return await _run_discrete(
            gene_list,
            alpha,
            keep_insignificant,
            minimum_evidence_count,
            minimum_belief,
        )
    if analysis_type == "signed":
        assert negative_genes is not None  # validated by the caller
        return await _run_signed(
            gene_list,
            negative_genes,
            alpha,
            keep_insignificant,
            minimum_evidence_count,
            minimum_belief,
        )
    # gene_list here is actually phosphosite identifiers; see the
    # run_enrichment_analysis docstring for the "GENE-SITE" format.
    return await _run_kinase(
        gene_list,
        alpha,
        keep_insignificant,
        minimum_evidence_count,
        minimum_belief,
    )


async def _run_discrete(
    gene_list: list[str],
    alpha: float,
    keep_insignificant: bool,
    min_evidence: int,
    min_belief: float,
) -> Any:
    """Runs discrete over-representation analysis via INDRA.

    Args:
        gene_list: HGNC gene IDs as strings.
        alpha: Significance threshold.
        keep_insignificant: Include non-significant results.
        min_evidence: Minimum supporting evidence count.
        min_belief: Minimum belief score threshold.

    Returns:
        Raw API response.
    """
    # minimum_evidence_count / minimum_belief filter which INDRA
    # statements are trusted enough to feed into the enrichment sets
    # (belief is INDRA's calibrated confidence score for a statement,
    # in the range 0-1).
    return await indra_post(
        "/api/discrete_analysis",
        {
            "gene_list": gene_list,
            "alpha": alpha,
            "keep_insignificant": keep_insignificant,
            "minimum_evidence_count": min_evidence,
            "minimum_belief": min_belief,
        },
    )


async def _run_signed(
    positive_genes: list[str],
    negative_genes: list[str],
    alpha: float,
    keep_insignificant: bool,
    min_evidence: int,
    min_belief: float,
) -> Any:
    """Runs signed causal reasoning analysis via INDRA.

    Args:
        positive_genes: Upregulated gene HGNC IDs.
        negative_genes: Downregulated gene HGNC IDs.
        alpha: Significance threshold.
        keep_insignificant: Include non-significant results.
        min_evidence: Minimum supporting evidence count.
        min_belief: Minimum belief score threshold.

    Returns:
        Raw API response.
    """
    # positive_genes/negative_genes let INDRA's causal reasoning engine
    # search for upstream regulators consistent with both directions of
    # change simultaneously.
    return await indra_post(
        "/api/signed_analysis",
        {
            "positive_genes": positive_genes,
            "negative_genes": negative_genes,
            "alpha": alpha,
            "keep_insignificant": keep_insignificant,
            "minimum_evidence_count": min_evidence,
            "minimum_belief": min_belief,
        },
    )


async def _run_kinase(
    phosphosite_list: list[str],
    alpha: float,
    keep_insignificant: bool,
    min_evidence: int,
    min_belief: float,
) -> Any:
    """Runs kinase enrichment analysis on phosphosite data via INDRA.

    Args:
        phosphosite_list: Phosphosites as "GENE-SITE" strings.
        alpha: Significance threshold.
        keep_insignificant: Include non-significant results.
        min_evidence: Minimum supporting evidence count.
        min_belief: Minimum belief score threshold.

    Returns:
        Raw API response.
    """
    # Tests whether known substrates of each kinase are overrepresented
    # among the given phosphosites, pointing to which kinases are likely
    # active/inactive in the underlying experiment.
    return await indra_post(
        "/api/kinase_analysis",
        {
            "phosphosite_list": phosphosite_list,
            "alpha": alpha,
            "keep_insignificant": keep_insignificant,
            "minimum_evidence_count": min_evidence,
            "minimum_belief": min_belief,
        },
    )

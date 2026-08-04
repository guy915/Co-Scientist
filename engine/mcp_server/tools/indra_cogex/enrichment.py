"""Gene set enrichment analysis tools via INDRA CoGex."""

import logging
from dataclasses import dataclass
from typing import Any

from mcp_server.tools.indra_cogex.client import (
    indra_post,
    run_indra_tool,
    tool_error,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EnrichmentRequest:
    """One enrichment request, as supplied by the caller.

    Attributes:
        gene_list: Gene identifiers, or "GENE-SITE" phosphosites for the
            kinase analysis type.
        analysis_type: "discrete", "signed", or "kinase".
        negative_genes: Downregulated genes, required for signed analysis.
        alpha: Significance threshold.
        keep_insignificant: Whether non-significant results are returned.
        minimum_evidence_count: Min supporting evidence per result.
        minimum_belief: Min belief score threshold.
    """

    gene_list: list[str]
    analysis_type: str
    negative_genes: list[str] | None
    alpha: float
    keep_insignificant: bool
    minimum_evidence_count: int
    minimum_belief: float


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
    return await _run_enrichment(
        _EnrichmentRequest(
            gene_list=gene_list,
            analysis_type=analysis_type,
            negative_genes=negative_genes,
            alpha=alpha,
            keep_insignificant=keep_insignificant,
            minimum_evidence_count=minimum_evidence_count,
            minimum_belief=minimum_belief,
        )
    )


async def _run_enrichment(request: _EnrichmentRequest) -> dict[str, Any]:
    """Validates the request, then dispatches enrichment analysis to INDRA.

    Returns:
        Dict with enrichment results, or a structured error payload when
        validation fails or the INDRA call raises.
    """
    query_meta = {
        "analysis_type": request.analysis_type,
        "gene_count": len(request.gene_list),
    }
    error = _validate_enrichment(
        request.analysis_type, request.negative_genes, query_meta
    )
    if error is not None:
        return error

    return await run_indra_tool(
        logger,
        "run_enrichment_analysis",
        query_meta,
        _run_validated_enrichment(request, query_meta),
    )


async def _run_validated_enrichment(
    request: _EnrichmentRequest,
    query_meta: dict[str, Any],
) -> dict[str, Any]:
    """Dispatches an already-validated enrichment request to INDRA.

    Args:
        request: The enrichment request, already passed by validation.
        query_meta: Query metadata echoed back in the response.

    Returns:
        Dict with the raw enrichment results and query metadata.
    """
    filters = {
        "alpha": request.alpha,
        "keep_insignificant": request.keep_insignificant,
        "minimum_evidence_count": request.minimum_evidence_count,
        "minimum_belief": request.minimum_belief,
    }
    raw = await _dispatch_enrichment_analysis(
        request.analysis_type,
        request.gene_list,
        request.negative_genes,
        filters,
    )
    return {"results": raw, "query": query_meta}


def _validate_enrichment(
    analysis_type: str,
    negative_genes: list[str] | None,
    query_meta: dict[str, Any],
) -> dict[str, Any] | None:
    """Validates the enrichment request, returning an error dict or None.

    Returns:
        A structured error payload when the request is invalid, else None.
    """
    # Signed analysis needs both up- and down-regulated sets so INDRA can
    # reason about which upstream regulators explain the observed direction.
    if analysis_type == "signed" and not negative_genes:
        return tool_error(
            "signed analysis requires 'negative_genes'", query_meta
        )
    if analysis_type not in ("discrete", "signed", "kinase"):
        valid = "discrete, signed, kinase"
        return tool_error(
            f"invalid analysis_type '{analysis_type}', use: {valid}",
            query_meta,
        )
    return None


async def _dispatch_enrichment_analysis(
    analysis_type: str,
    gene_list: list[str],
    negative_genes: list[str] | None,
    filters: dict[str, Any],
) -> Any:
    """Delegates to the INDRA call matching a validated analysis_type.

    Args:
        analysis_type: One of "discrete", "signed", "kinase"; already
            validated by the caller.
        gene_list: Gene (or phosphosite, for kinase) identifiers.
        negative_genes: Downregulated genes; already validated as non-empty
            by the caller when analysis_type is "signed".
        filters: Shared enrichment filters (alpha, keep_insignificant,
            minimum_evidence_count, minimum_belief) forwarded to INDRA.

    Returns:
        Raw API response from the matching INDRA enrichment endpoint.
    """
    if analysis_type == "discrete":
        return await _run_discrete(gene_list, filters)
    if analysis_type == "signed":
        assert negative_genes is not None  # validated by the caller
        return await _run_signed(gene_list, negative_genes, filters)
    # gene_list here is actually phosphosite identifiers; see the
    # run_enrichment_analysis docstring for the "GENE-SITE" format.
    return await _run_kinase(gene_list, filters)


async def _run_discrete(gene_list: list[str], filters: dict[str, Any]) -> Any:
    """Runs discrete over-representation analysis via INDRA.

    Args:
        gene_list: HGNC gene IDs as strings.
        filters: Shared enrichment filters forwarded to the endpoint.

    Returns:
        Raw API response.
    """
    # filters carry minimum_evidence_count / minimum_belief, which gate
    # which INDRA statements are trusted enough to feed the enrichment sets.
    return await indra_post(
        "/api/discrete_analysis",
        {"gene_list": gene_list, **filters},
    )


async def _run_signed(
    positive_genes: list[str],
    negative_genes: list[str],
    filters: dict[str, Any],
) -> Any:
    """Runs signed causal reasoning analysis via INDRA.

    Args:
        positive_genes: Upregulated gene HGNC IDs.
        negative_genes: Downregulated gene HGNC IDs.
        filters: Shared enrichment filters forwarded to the endpoint.

    Returns:
        Raw API response.
    """
    return await indra_post(
        "/api/signed_analysis",
        {
            "positive_genes": positive_genes,
            "negative_genes": negative_genes,
            **filters,
        },
    )


async def _run_kinase(
    phosphosite_list: list[str],
    filters: dict[str, Any],
) -> Any:
    """Runs kinase enrichment analysis on phosphosite data via INDRA.

    Args:
        phosphosite_list: Phosphosites as "GENE-SITE" strings.
        filters: Shared enrichment filters forwarded to the endpoint.

    Returns:
        Raw API response.
    """
    return await indra_post(
        "/api/kinase_analysis",
        {"phosphosite_list": phosphosite_list, **filters},
    )

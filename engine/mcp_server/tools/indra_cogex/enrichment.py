# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Gene set enrichment analysis tools via INDRA CoGex."""

import logging
from typing import Any

from .client import indra_post

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
    # pylint: disable=line-too-long
    """Runs statistical enrichment analysis on gene or phosphosite sets via INDRA.

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
    # pylint: enable=line-too-long
    query_meta = {
        "analysis_type": analysis_type,
        "gene_count": len(gene_list),
    }

    try:  # pylint: disable=broad-exception-caught
        if analysis_type == "discrete":
            raw = await _run_discrete(
                gene_list,
                alpha,
                keep_insignificant,
                minimum_evidence_count,
                minimum_belief,
            )
        elif analysis_type == "signed":
            if not negative_genes:
                return {
                    "error": "signed analysis requires 'negative_genes'",
                    "query": query_meta,
                }
            raw = await _run_signed(
                gene_list,
                negative_genes,
                alpha,
                keep_insignificant,
                minimum_evidence_count,
                minimum_belief,
            )
        elif analysis_type == "kinase":
            raw = await _run_kinase(
                gene_list,
                alpha,
                keep_insignificant,
                minimum_evidence_count,
                minimum_belief,
            )
        else:
            valid = "discrete, signed, kinase"
            return {
                "error":
                    f"invalid analysis_type '{analysis_type}', use: {valid}",
            }

        return {"results": raw, "query": query_meta}

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("run_enrichment_analysis failed: %s", e)
        return {"error": str(e), "query": query_meta}


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
    return await indra_post(
        "/api/discrete_analysis", {
            "gene_list": gene_list,
            "alpha": alpha,
            "keep_insignificant": keep_insignificant,
            "minimum_evidence_count": min_evidence,
            "minimum_belief": min_belief,
        })


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
    return await indra_post(
        "/api/signed_analysis", {
            "positive_genes": positive_genes,
            "negative_genes": negative_genes,
            "alpha": alpha,
            "keep_insignificant": keep_insignificant,
            "minimum_evidence_count": min_evidence,
            "minimum_belief": min_belief,
        })


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
    return await indra_post(
        "/api/kinase_analysis", {
            "phosphosite_list": phosphosite_list,
            "alpha": alpha,
            "keep_insignificant": keep_insignificant,
            "minimum_evidence_count": min_evidence,
            "minimum_belief": min_belief,
        })

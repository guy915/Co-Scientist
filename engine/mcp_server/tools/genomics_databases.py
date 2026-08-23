"""Gene-level lookups: canonical coordinates and population constraint.

Two sources that answer questions no paper states outright. Ensembl gives
a gene its canonical identity -- the symbol a paper used, resolved to a
stable id, biotype and locus. gnomAD gives population constraint: how
strongly a gene is depleted of loss-of-function variation across ~800k
people, which is direct evidence about whether losing it is tolerated.

Both degrade to an empty-records envelope rather than raising, so one
unreachable source cannot fail a step that consults several.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ENSEMBL_URL = "https://rest.ensembl.org/lookup/symbol/homo_sapiens"
_GNOMAD_URL = "https://gnomad.broadinstitute.org/api"


def _empty_result(source: str, query: str) -> dict[str, Any]:
    """Builds the envelope a lookup returns when it cannot answer."""
    return {"source": source, "query": query, "records": []}


async def search_ensembl_gene(
    query: str, max_results: int = 1
) -> dict[str, Any]:
    """Resolve a gene symbol to its canonical Ensembl record.

    Args:
        query: A human gene symbol, e.g. "WEE1".
        max_results: Unused -- a symbol resolves to one gene. Accepted so
            every search tool shares one parameter mapping.

    Returns:
        A source-stamped record with the stable id, locus, biotype and
        description, or an empty-records envelope.
    """
    del max_results
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{_ENSEMBL_URL}/{query}",
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        gene = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Ensembl lookup failed for %r: %s", query, exc)
        return _empty_result("Ensembl", query)
    record = {
        "ensembl_id": gene.get("id"),
        "symbol": gene.get("display_name"),
        "biotype": gene.get("biotype"),
        "description": gene.get("description"),
        "locus": (
            f"{gene.get('seq_region_name')}:"
            f"{gene.get('start')}-{gene.get('end')}"
        ),
        "strand": gene.get("strand"),
        "url": f"https://www.ensembl.org/Homo_sapiens/Gene/Summary?g={gene.get('id')}",
    }
    return {"source": "Ensembl", "query": query, "records": [record]}


_GNOMAD_QUERY = """
query($symbol: String!) {
  gene(gene_symbol: $symbol, reference_genome: GRCh38) {
    gene_id
    symbol
    gnomad_constraint {
      pli
      oe_lof
      oe_lof_lower
      oe_lof_upper
      mis_z
    }
  }
}
"""


async def search_gnomad_constraint(
    query: str, max_results: int = 1
) -> dict[str, Any]:
    """Return how strongly a gene is depleted of damaging variation.

    Args:
        query: A human gene symbol, e.g. "WEE1".
        max_results: Unused -- a symbol resolves to one gene. Accepted so
            every search tool shares one parameter mapping.

    Returns:
        A source-stamped constraint record, or an empty-records envelope.
    """
    del max_results
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                _GNOMAD_URL,
                json={"query": _GNOMAD_QUERY, "variables": {"symbol": query}},
            )
            response.raise_for_status()
        gene = ((response.json().get("data") or {}).get("gene")) or {}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("gnomAD lookup failed for %r: %s", query, exc)
        return _empty_result("gnomAD", query)
    constraint = gene.get("gnomad_constraint") or {}
    if not gene.get("gene_id") or not constraint:
        return _empty_result("gnomAD", query)
    return {
        "source": "gnomAD",
        "query": query,
        "records": [_constraint_record(gene, constraint)],
    }


def _constraint_record(
    gene: dict[str, Any], constraint: dict[str, Any]
) -> dict[str, Any]:
    """Flattens one gnomAD constraint result, carrying its interpretation.

    The numbers are meaningless without their conventions -- pLI near 1
    means intolerant, LOEUF *below* 0.35 means constrained -- and a model
    reading a bare 0.23 has no way to know which direction is which.
    """
    return {
        "gene_id": gene.get("gene_id"),
        "symbol": gene.get("symbol"),
        "pli": constraint.get("pli"),
        "loeuf": constraint.get("oe_lof_upper"),
        "observed_expected_lof": constraint.get("oe_lof"),
        "missense_z": constraint.get("mis_z"),
        "interpretation": (
            "pLI near 1 means intolerant of heterozygous loss of function; "
            "LOEUF (loeuf) below 0.35 marks a constrained gene, above 1.0 an "
            "unconstrained one; missense_z above 3.09 marks missense "
            "constraint."
        ),
        "url": f"https://gnomad.broadinstitute.org/gene/{gene.get('gene_id')}",
    }

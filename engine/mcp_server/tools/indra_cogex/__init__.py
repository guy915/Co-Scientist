"""INDRA CoGex knowledge graph tool implementations."""

# Re-export each domain module's public functions so callers can import
# them directly from mcp_server.tools.indra_cogex.
from mcp_server.tools.indra_cogex.associations import (
    query_gene_codependents,
    query_gene_disease_network,
)
from mcp_server.tools.indra_cogex.drug_clinical import (
    query_clinical_trials,
    query_drug_info,
)
from mcp_server.tools.indra_cogex.enrichment import run_enrichment_analysis
from mcp_server.tools.indra_cogex.pathways import (
    query_causal_subnetwork,
    query_pathways,
)
from mcp_server.tools.indra_cogex.statements import query_mechanistic_statements

# Public API of this package: the full set of INDRA CoGex tool functions
# registered with the MCP server.
__all__ = [
    "query_causal_subnetwork",
    "query_clinical_trials",
    "query_drug_info",
    "query_gene_codependents",
    "query_gene_disease_network",
    "query_mechanistic_statements",
    "query_pathways",
    "run_enrichment_analysis",
]

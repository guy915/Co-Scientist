"""INDRA CoGex knowledge graph tool implementations."""

# Re-export each domain module's public functions so callers can import
# them directly from mcp_server.tools.indra_cogex.
from mcp_server.tools.indra_cogex.associations import (
    query_gene_disease_network,
    query_gene_codependents,
)
from mcp_server.tools.indra_cogex.drug_clinical import (
    query_drug_info,
    query_clinical_trials,
)
from mcp_server.tools.indra_cogex.pathways import (
    query_pathways,
    query_causal_subnetwork,
)
from mcp_server.tools.indra_cogex.statements import query_mechanistic_statements
from mcp_server.tools.indra_cogex.enrichment import run_enrichment_analysis

# Public API of this package: the full set of INDRA CoGex tool functions
# registered with the MCP server.
__all__ = [
    "query_gene_disease_network",
    "query_gene_codependents",
    "query_drug_info",
    "query_clinical_trials",
    "query_pathways",
    "query_causal_subnetwork",
    "query_mechanistic_statements",
    "run_enrichment_analysis",
]

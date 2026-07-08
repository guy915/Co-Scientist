"""Co-Scientist literature review MCP server.

Reference implementation using FastMCP for PubMed literature review tools.
PubMed-only implementation for biomedical research.
"""
# pylint: disable=inconsistent-quotes,wrong-import-position

import os
import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

import fastmcp

fastmcp.settings.stateless_http = True

# Import config early to load .env
from mcp_server import config

# Configure logging based on .env
log_level = getattr(logging, config.LOG_LEVEL, logging.INFO)
# Set root logger to INFO (default for all libraries)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

logging.getLogger('mcp_server').setLevel(log_level)

from mcp_server.tools.lit_review.search_pubmed import (  # pylint: disable=line-too-long
    check_pubmed_available, search_pubmed)
from mcp_server.tools.lit_review.pubmed_search_with_fulltext import (  # pylint: disable=line-too-long
    pubmed_search_with_fulltext)
from mcp_server.tools.lit_review.openalex_search import (  # pylint: disable=line-too-long
    search_openalex)
from mcp_server.tools.indra_cogex import (
    query_gene_disease_network,
    query_gene_codependents,
    query_drug_info,
    query_clinical_trials,
    query_pathways,
    query_causal_subnetwork,
    query_mechanistic_statements,
    run_enrichment_analysis,
)

logger = logging.getLogger(__name__)

# Log startup configuration
entrez_email_present = bool(os.environ.get("ENTREZ_EMAIL"))

logger.info("MCP server starting")
logger.debug("API keys present: ENTREZ_EMAIL=%s", entrez_email_present)

mcp = FastMCP("co-scientist-lit-review")

# Registered MCP tools in advertised order: literature review followed by INDRA
# CoGex knowledge-graph tools. The ``/`` handler derives its ``mcp_tools``
# manifest from this same list so registration and manifest cannot drift.
_MCP_TOOLS = (
    (check_pubmed_available, "check_pubmed_available"),
    (search_pubmed, "search_pubmed"),
    (pubmed_search_with_fulltext, "pubmed_search_with_fulltext"),
    (search_openalex, "search_openalex"),
    (query_gene_disease_network, "query_gene_disease_network"),
    (query_gene_codependents, "query_gene_codependents"),
    (query_drug_info, "query_drug_info"),
    (query_clinical_trials, "query_clinical_trials"),
    (query_pathways, "query_pathways"),
    (query_causal_subnetwork, "query_causal_subnetwork"),
    (query_mechanistic_statements, "query_mechanistic_statements"),
    (run_enrichment_analysis, "run_enrichment_analysis"),
)

for _tool_fn, _tool_name in _MCP_TOOLS:
    mcp.tool(_tool_fn, name=_tool_name)

mcp_http_app = mcp.http_app()
app = FastAPI(lifespan=mcp_http_app.lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> JSONResponse:
    """Returns API status and available tool list.

    Returns:
        A JSON response describing the running service, its version, the
        registered MCP tools, and configured integrations.
    """
    return JSONResponse({
        "status": "running",
        "service": "coscientist-lit-review",
        "version": "0.1.0",
        "mcp_tools": [name for _, name in _MCP_TOOLS],
        "api_keys_configured": {
            "ENTREZ_EMAIL": entrez_email_present,
        },
        "integrations": {
            "indra_cogex":
                os.getenv("INDRA_COGEX_URL", "https://discovery.indra.bio"),
        }
    })


app.mount("/", mcp_http_app)

if __name__ == "__main__":
    port = int(os.environ.get("COSCIENTIST_MCP_PORT", 8888))
    uvicorn.run(app, host="0.0.0.0", port=port)

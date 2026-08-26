# Co-Scientist MCP Server

MCP (Model Context Protocol) server providing literature, knowledge-graph, and web-research tools for Co-Scientist hypothesis generation.

## Features

`server.py` registers the tools below (the `/` handler derives its manifest from the same list, so registration and manifest cannot drift).

Literature search:

- **check_pubmed_available**: Test if PubMed service is accessible
- **search_pubmed**: PubMed search (metadata)
- **pubmed_search_with_fulltext**: Search PubMed, download fulltext from PMC, and extract clean text for LLM analysis
- **search_openalex**: OpenAlex scholarly search
- **fetch_paper**: Retrieve one paper of the research group's own corpus in full, by `paper_id`, from local disk

Biomedical databases and knowledge graph:

- **search_chembl**, **search_uniprot**: ChEMBL compound / UniProt protein lookups
- **query_gene_disease_network**, **query_gene_codependents**, **query_drug_info**, **query_clinical_trials**, **query_pathways**, **query_causal_subnetwork**, **query_mechanistic_statements**, **run_enrichment_analysis**: INDRA CoGex knowledge-graph queries

Open-web research and browsing:

- **search_web**: Search the open web for news, grey literature, and recent developments. Registered only when a provider API key is configured; with both keys set, a provider that is out of credit is skipped and the search falls through to the other one
- **check_web_search_available**: Report whether a search issued now would reach a provider -- false only once every configured provider has refused the key, which registration alone cannot tell you
- **read_url**: Fetch a web page or PDF and return readable text. Always available

`fetch_paper` is always registered, but it needs `SBI_CORPUS_DIR` pointing at a directory of `<paper_id>.md`/`.txt` files; without one it returns an empty result for every id. The corpus is not searched here — the caller injects the whole catalog (title + abstract per paper) into the model's context, and this tool reads one paper in full as the follow-up.

See [Web Search](../docs/WEB_SEARCH.md) for provider setup and the URL safety screen.

## Quick Start (Docker)

**Prerequisites:**
- Docker and Docker Compose installed
- NCBI Entrez email (free, required for PubMed API), Entrez API key recommended (free)

**Setup:**

```bash
# 1. copy environment template
cp .env.example .env

# 2. edit .env and add required keys:
    ENTREZ_EMAIL=your_email@example.com

# 3. start server from parent dir
cd ..        # to engine root folder
docker compose up -d

# 4. verify server is running
curl http://localhost:8888
```

MCP endpoints will be available at `http://localhost:8888/mcp`

## Alternative: Local Development Setup

**Prerequisites:**
- Python >=3.12
- Pip or UV package manager

```bash
# 1. create virtual environment (Python 3.12+)
python3.12 -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# 2. install dependencies
pip install -e .

# 3. configure environment
cp .env.example .env
# edit .env and add ENTREZ_EMAIL and API keys

# Root dir, to find mcp_server package
cd ..

# 4. run server
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888

# or with auto-reload for development:
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888 --reload
```

## Configuration

### Required Environment Variables

```bash
# required for PubMed access
ENTREZ_EMAIL=your_email@example.com
# higher rate limits (optional)
ENTREZ_API_KEY=your_ncbi_api_key  # get at https://www.ncbi.nlm.nih.gov/account/
# then https://account.ncbi.nlm.nih.gov/settings/ -> API Key Management
```

### Optional Environment Variables

```bash
# server port (default: 8888)
COSCIENTIST_MCP_PORT=8888

# web search provider key. without one, search_web is not registered and
# only read_url is available. brave or tavily; brave is preferred by default.
BRAVE_API_KEY=
TAVILY_API_KEY=
WEB_SEARCH_PROVIDER=

# paper cache directory (code default: ./cache/literature_review; the
# .env.example and the compose volume both use ./paper_cache)
COSCIENTIST_LIT_REVIEW_DIR=./paper_cache

# directory of <paper_id>.md/.txt files the fetch_paper tool reads. NO
# DEFAULT: unset means fetch_paper returns an empty result for every id.
SBI_CORPUS_DIR=./corpus/sbi_ucd
```

`.env.example` carries the full environment surface, including the shared-secret auth, INDRA CoGex, and OpenAlex settings not repeated here.

## Usage with Co-Scientist

Co-Scientist automatically connects to this MCP server if running.

Configure the MCP URL (optional, defaults to `http://localhost:8888/mcp`):

```bash
export MCP_SERVER_URL="http://localhost:8888/mcp"
```

The library will:
1. Check if MCP server is available
2. Use PubMed tools for literature review
3. Extract fulltext and analyze with LLM agents
4. Generate and validate hypotheses based on literature

## Architecture

```
mcp_server/
├── server.py                    # FastMCP server + tool registration
├── config.py                    # Configuration
├── pubmed_client.py             # PubMed/Entrez client
├── fulltext_download.py         # PMC fulltext retrieval
├── text_extraction.py           # PMC HTML to markdown
├── literature_review.py         # Shared literature-review helpers
└── tools/
    ├── biomedical_databases.py  # search_chembl, search_uniprot
    ├── lit_review/
    │   ├── search_pubmed.py                 # check availability + metadata search
    │   ├── pubmed_search_with_fulltext.py   # search + fulltext
    │   ├── openalex_search.py               # search_openalex tool
    │   └── search_paper_corpus.py           # fetch_paper: reads one corpus paper from disk
    ├── indra_cogex/             # INDRA CoGex knowledge-graph query tools
    │   ├── associations.py
    │   ├── drug_clinical.py
    │   ├── pathways.py
    │   ├── statements.py
    │   ├── enrichment.py
    │   └── client.py
    └── web/
        ├── web_search.py        # search_web tool
        ├── providers.py         # Brave / Tavily dispatch
        ├── fetch.py             # read_url tool
        ├── extract.py           # HTML and PDF to text
        └── url_guard.py         # SSRF screen for fetched URLs
```

## Docker Details

**Environment:**
- Set required keys via `.env` file or docker compose environment

**Commands:**
```bash
# build image
docker compose build

# start in background
docker compose up -d

# view logs
docker compose logs -f

# stop server
docker compose down

# rebuild after code changes
docker compose up -d --build
```

## Support

For issues or questions:
- GitHub: https://github.com/guy915/Co-Scientist
- Documentation: See main [README](../README.md)

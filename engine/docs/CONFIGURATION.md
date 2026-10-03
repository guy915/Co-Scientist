# Configuration Guide

Complete guide to configuring Co-Scientist for your needs.

## Basic Configuration

```python
from co_scientist import GeneratorOptions, HypothesisGenerator

generator = HypothesisGenerator(
    model_name="deepseek/deepseek-v4-flash",  # Default; any LiteLLM-supported model
    max_iterations=1,                         # Number of refinement cycles
    initial_hypotheses_count=5,               # Initial pool size
    evolution_max_count=3,                    # How many to evolve and keep
    options=GeneratorOptions(
        enable_cache=True,                    # LLM response caching
        cache_dir=".coscientist_cache",       # Cache location (relative to CWD)
        tools_config="path/to/tools.yaml",    # Optional: custom domain/source config
    ),
)
```

Only the four run-size knobs are top-level constructor arguments; every other
knob lives on `GeneratorOptions` and is passed as `options=`. See constants/__init__.py
for other defaults.

## Configuration Parameters

Constructor arguments:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `model_name` | `"deepseek/deepseek-v4-flash"` | LLM model in LiteLLM format (e.g., `"claude-sonnet-4-6"`, `"gpt-4o"`, `"gemini/gemini-2.5-flash"`) |
| `max_iterations` | `1` | Number of refinement cycles (0 = no evolution/meta-review phase) |
| `initial_hypotheses_count` | `5` | Initial hypothesis pool size |
| `evolution_max_count` | `3` | Number of top hypotheses to evolve in each iteration |

`GeneratorOptions` fields (see `generator/options.py`):

| Field | Default | Description |
|-----------|---------|-------------|
| `supervisor_model_name` | `None` | Model for the supervisor and meta-review steps (`None` = `model_name`) |
| `tournament_pairs` | `12` | Elo tournament comparisons per ranking pass |
| `elo_k_factor` | `24` | Rating change magnitude per match |
| `literature_review_papers_count` | `8` | Number of papers to read and analyze |
| `enable_cache` | `None` | Override caching for this generator (`None` = the `COSCIENTIST_CACHE_ENABLED` process default, which is on) |
| `cache_dir` | `None` | Cache directory (`None` = `COSCIENTIST_CACHE_DIR`, default `.coscientist_cache`) |
| `tools_config` | `None` | Path to a custom YAML tools configuration file; see [Literature Review Tools Configuration](CONFIGURATION.md) |
| `disable_tools` | `None` | Tool IDs to disable from the resolved config |
| `budget` | `None` | Serialized scheduler `Budget` (`max_iterations`, `max_llm_calls`, `max_tasks`, `max_wall_clock_s`) |
| `api_key` | `None` | Per-run provider credential; forces caching off for the run |

## Model Selection

Co-Scientist uses [LiteLLM](https://docs.litellm.ai/docs/providers), which supports 100+ LLM providers:

### OpenAI

```python
# Set API key
export OPENAI_API_KEY="your-key-here"

# Use in code
generator = HypothesisGenerator(model_name="gpt-4o")
```

### Anthropic

```python
# Set API key
export ANTHROPIC_API_KEY="your-key-here"

# Use in code
generator = HypothesisGenerator(model_name="claude-sonnet-4-6")
```

### Google Gemini

```python
# Set API key
export GEMINI_API_KEY="your-key-here"

# Use in code
generator = HypothesisGenerator(model_name="gemini/gemini-2.5-flash")
```

### Azure, AWS Bedrock, Cohere

See [LiteLLM provider documentation](https://docs.litellm.ai/docs/providers) for configuration details.

### Offline / deterministic backend

Any model name prefixed `offline/` (default: `offline/deterministic`) is
answered locally instead of calling a real provider. Call
`co_scientist.offline.llm.install_offline_router()` once at process startup
to install the router: it installs itself as the engine's completion backend
(`co_scientist.llm.request.backend`) so calls to `offline/`-prefixed models are
answered locally, while every other model passes through untouched to the
backend it replaced — real and offline models can coexist in the same process.

```python
from co_scientist.offline.llm import install_offline_router

install_offline_router()

generator = HypothesisGenerator(model_name="offline/deterministic")
```

**Determinism contract:** identical calls (same model, prompt, and response
schema) always produce byte-identical output; different prompts produce
different output. Each call seeds a `random.Random` from a SHA-256 digest of
`(model, prompt, schema name)` and fills the response schema from that seed,
drawing free-text leaves from a small pseudo-scientific phrase bank so the
output reads as presentable prose rather than placeholder hashes.

This is not a test-only fixture — it's a real runtime backend. The
`co-scientist-viewer` app installs the router unconditionally at startup and
routes every keyless, `COSCIENTIST_FORCE_OFFLINE=1`, demo-seeding, and test
run through it, so the full engine graph runs with no LLM provider key and
no API spend.

## Runtime Options

The `generate_hypotheses()` method accepts an `opts` dictionary for runtime configuration:

```python
# Non-streaming
result = await generator.generate_hypotheses(
    research_goal="Your research question",
    stream=False,  # Will have to wait with no feedback, sometimes >10 minutes, if no cache and no logging enabled
    opts={
        # Literature review control
        "enable_literature_review_node": True,
        "enable_tool_calling_generation": False,
    }
)

# Streaming
async for node_name, state in generator.generate_hypotheses(
    research_goal="Your research question",
    stream=True,
    opts={...}
):
    print(f"Completed: {node_name}")
```

### Available Runtime Options

| Option | Default | Description |
|--------|---------|-------------|
| `enable_literature_review_node` | `True` (if MCP available) | Enable/disable literature review node |
| `enable_tool_calling_generation` | `False` | Allow Generate node to use MCP tools (requires literature review) |
| `dev_test_lit_tools_isolation` | `False` | Forces all hypotheses through tool-calling generation (no debate) and forces literature review node caching. Development/testing only. |

See [MCP Integration](CONFIGURATION.md) for details on literature review modes.

## Caching

LLM caching dramatically speeds up development and testing by reusing identical LLM calls.

### Cache Management

```python
from co_scientist import clear_cache, get_cache_stats

# Clear all cached responses
cleared = clear_cache()
print(f"Cleared {cleared} responses")

# Check cache statistics
stats = get_cache_stats()
print(f"Cache: {stats['cache_files']} files, {stats['total_size_mb']:.2f} MB")
```

### Environment Variables

#### Caching

```bash
# Enable/disable caching
export COSCIENTIST_CACHE_ENABLED=true

# Custom cache directory
export COSCIENTIST_CACHE_DIR=".cache"
```

#### Literature Review (PubMed)

Literature review uses a separate MCP server that runs in its own process (Python 3.12+). Configure the MCP server by editing `mcp_server/.env`:

```bash
# Required for PubMed access
ENTREZ_EMAIL=your_email@example.com

# Optional: higher rate limits
ENTREZ_API_KEY=your_ncbi_api_key

# Optional: literature review cache directory
COSCIENTIST_LIT_REVIEW_DIR=./cache/literature_review
```

**Important Notes**:
- The MCP server runs separately with its own environment - set API keys in `mcp_server/.env`, not in the main co-scientist-engine environment
- The literature review node is gated on the MCP **server** being reachable, not on any single source. Without `ENTREZ_EMAIL` the PubMed tools report themselves unavailable, but the node still runs and the other configured sources (OpenAlex, web search) still contribute. Only an unreachable MCP server disables the node entirely, falling back to standard mode (no literature analysis)

### Cache Behavior

- **Default location**: `.coscientist_cache/` relative to current working directory
- **Cache key includes**: prompt, model name, temperature, max_tokens, cache schema version, plus the response-shape parameters when set (`tools`, `json_schema`, `force_json`, `tool_contract`)
- **Benefits**: faster iteration during development, significant cost savings
- **Safe to delete**: Cache directory can be deleted at any time

## Constants and Internal Parameters

Most users won't need to modify these, but they're centralized in `src/co_scientist/constants/__init__.py`:

### Elo Rating Parameters

Defined in `src/co_scientist/constants/__init__.py` (re-exported from `constants/__init__.py`):

```python
INITIAL_ELO_RATING = 1200  # Starting Elo rating for all hypotheses
ELO_K_FACTOR = 24          # Rating change magnitude per match
```

### LLM Token Limits

```python
DEFAULT_MAX_TOKENS = 4000     # Standard responses
EXTENDED_MAX_TOKENS = 8000    # Longer responses
LONG_MAX_TOKENS = 10000       # Very long responses
THINKING_MAX_TOKENS = 18000   # Extended thinking models
```

### Temperature Settings

```python
LOW_TEMPERATURE = 0.3     # Ranking, tournament (consistency)
MEDIUM_TEMPERATURE = 0.5  # Meta-review, supervisor (balanced)
HIGH_TEMPERATURE = 0.7    # Generation, evolution, review (creativity)
```

Some models, especially thinking ones, require temperature=1 or ignore the parameter altogether to default to 1.

### Similarity Thresholds

```python
DUPLICATE_SIMILARITY_THRESHOLD = 0.95  # Remove near-identical hypotheses
```

### Modifying Constants

If you need to tune these parameters, edit `src/co_scientist/constants/__init__.py` (or
`constants/__init__.py` for the Elo/tournament parameters above).

Modifying constants may affect result quality and should be done with careful evaluation.

## Performance Tuning

### For Speed

```python
generator = HypothesisGenerator(
    model_name="gemini/gemini-2.5-flash",   # Fast, cheap model
    max_iterations=1,                       # Not many iterations
    initial_hypotheses_count=3,             # Smaller pool
    options=GeneratorOptions(enable_cache=True),  # Reuse responses
)
```

### For Quality

```python
generator = HypothesisGenerator(
    max_iterations=4,                         # Multiple refinement cycles
    initial_hypotheses_count=8,               # Larger diverse pool
    evolution_max_count=6,                    # Evolve more hypotheses
    model_name="claude-sonnet-4-6",    # High-quality model
)
```

### For Cost Optimization

```python
generator = HypothesisGenerator(
    model_name="gemini/gemini-2.5-flash",   # Cost-effective model
    initial_hypotheses_count=5,             # Moderate pool size
    options=GeneratorOptions(enable_cache=True),  # Avoid redundant calls
)
```

## Literature Review Tools Configuration

### Overview

Co-Scientist uses a **YAML-based configuration system** to decouple literature review tools from the core library. This allows you to:

- Bring your own MCP servers without modifying co-scientist-engine code
- Configure multiple literature sources (PubMed, arXiv, Google Scholar, etc.)
- Define custom response parsing, prompt instructions, and parameter mappings
- Mix and match tools from different MCP servers
- Inject domain-specific prompt guidance without touching source code

The default configuration (`src/co_scientist/config/tools.yaml`) provides a reference implementation using the bundled PubMed MCP server (see `mcp_server/` at the top level of this repo).

For how to use these configs to adapt the system to a specific domain, see [Domain Customization](CONFIGURATION.md).

### Example Configurations

See the [examples folder](../src/co_scientist/config/examples/) (README and YAML files) for example configurations. See [Merge Strategies](#merge-strategies) for an overview of how user configs interact with the built-in defaults.

### YAML Configuration Schema

#### Top-Level Structure

```yaml
version: "1.0"

servers:
  server_id:
    url: "http://localhost:8888/mcp"
    transport: "streamable_http"
    enabled: true

prompts:
  domain_context: |
    # Optional: injected into generation, review, and evolution prompts
  generation_guidance: |
    # Optional: additional instructions for the Generate node
  review_guidance: |
    # Optional: additional criteria for the Review node
  evolution_guidance: |
    # Optional: additional priorities for the Evolve node

tools:
  search_tools:
    tool_id:
      # Tool configuration (see below)
  read_tools:
    # Content retrieval tools
  utility_tools:
    # Helper tools (PDF discovery, availability checks)

workflows:
  literature_review:
    # Workflow configuration (see below)
  draft_generation:
    # Tools available to the Generate node in tool-calling mode
  validation:
    # Tools available for novelty validation
  reflection:
    # Tools available for entity-based evidence lookup during reflection

enrichments:
  # Post-generation per-hypothesis tool calls (see below)

settings:
  merge_strategy: "replace"
```

---

#### Server Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | Yes | MCP server URL (supports `${ENV_VAR:-default}`) |
| `transport` | string | Yes | Always `"streamable_http"` |
| `enabled` | boolean | Yes | Enable/disable this server |

**Example:**
```yaml
servers:
  arxiv_server:
    url: "${ARXIV_MCP_SERVER_URL:-http://localhost:8889/mcp}"
    transport: "streamable_http"
    enabled: true
```

---

#### Prompt Customization

The `prompts` section injects domain-specific text into workflow prompts without requiring any code changes. All fields are optional.

| Field | Injected Into |
|-------|--------------|
| `domain_context` | Supervisor, Generate, Review, Evolve nodes |
| `generation_guidance` | Generate node |
| `review_guidance` | Review node |
| `evolution_guidance` | Evolve node |

**Example (cybersecurity domain):**
```yaml
prompts:
  domain_context: |
    ## Domain: Offensive Cybersecurity Research

    You are a cybersecurity research scientist. "Hypothesis" means a threat
    hypothesis — a novel attack technique or adversarial capability.

  generation_guidance: |
    ## Attack Categories to Consider
    Generate hypotheses spanning: novel exploitation, evasion techniques,
    AI-augmented attacks, supply chain compromise, and post-exploitation.

  review_guidance: |
    ## Cybersecurity Review Criteria
    Prioritize: operational feasibility, novelty over existing TTPs,
    impact potential, evasion potential, and defensive value.
```

See the [examples folder](../src/co_scientist/config/examples/) for complete domain-specific configurations.

---

#### Tool Configuration

Tools are organized into categories: `search_tools`, `read_tools`, `utility_tools`.

##### Search Tool Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `server` | string | Yes | Server ID from `servers` section |
| `mcp_tool_name` | string | Yes | Actual tool name in MCP server |
| `display_name` | string | Yes | Human-readable name |
| `description` | string | Yes | Tool description |
| `category` | string | Yes | `"search"` or `"search_with_content"` |
| `source_type` | string | Yes | See [Source Types](#source-type-and-query-generation) |
| `enabled` | boolean | Yes | Enable/disable tool |
| `response_format` | object | Yes | How to parse MCP response (see below) |
| `parameter_mapping` | object | No | Map canonical params to tool params |
| `prompt_snippet` | string | No | Instructions for LLM agents |
| `parameters` | object | No | Tool parameter definitions |

##### Response Format

Defines how to parse MCP tool responses into `Article` objects.

```yaml
response_format:
  type: "json"                    # "json" or "boolean_string"
  results_path: "."              # JSONPath to results array ("." for root)
  is_dict: true                  # true if results are {key: value}, false if [...]
  field_mapping:
    title: "title"               # Direct field
    url: "@url_from_key"         # Special: construct URL from dict key
    authors: "authors"
    year: "date_revised|split:/|index:0|int"  # Transform chain
    abstract: "abstract"
    content: "fulltext"
    source_id: "@key"            # Special: use dict key as ID
    source: "'pubmed'"           # Static value (quoted)
    venue: "publication"
    pdf_links: "pdf_url|wrap_list"  # Wrap single value in list
```

**Transform chains:**
- `split:/` - split on `/`
- `index:0` - take first element
- `int` - convert to integer
- `wrap_list` - wrap in list
- `@key` - use dict key
- `@url_from_key` - construct URL from key
- `'static'` - literal value (must be quoted)

##### Parameter Mapping

Maps canonical parameter names to tool-specific names:

```yaml
parameter_mapping:
  query: "query"              # canonical → tool param
  max_papers: "max_results"   # different name
  recency_years: null         # not supported by this tool
  slug: null                  # ignore
```

**Canonical parameters:**
- `query` - search query string
- `max_papers` - max results to return
- `recency_years` - filter to recent papers
- `slug` - research corpus identifier
- `run_id` - run tracking ID

---

#### Workflow Configuration

Defines tool usage for specific workflow phases.

```yaml
workflows:
  literature_review:
    # OPTION 1: Single-source mode
    primary_search: "pubmed_fulltext"

    # OPTION 2: Multi-source mode
    search_sources:
      - tool: "pubmed_fulltext"
        papers_per_query: 4
        enabled: true

      - tool: "google_scholar_search"
        papers_per_query: 2
        enabled: true
        # Two-step PDF retrieval
        pdf_discovery_tool: "find_pdf_links"
        pdf_discovery_url_field: "url"
        content_tool: "read_pdf"
        content_url_field: "pdf_url"

    # Multi-source settings
    deduplicate_across_sources: true

    # Availability check
    availability_check: "check_pubmed"  # or null to skip

    # Query generation
    query_generation_tool: "generate_queries"  # or null for LLM-based
    query_format: "natural_language"  # "natural_language" or "boolean"

    # Content retrieval (fallback)
    content_tool: "read_pdf"
    content_url_field: "pdf_url"

    # Additional tools available to the lit review agent
    read_tools:
      - "read_pdf"
    utility_tools:
      - "find_pdf_links"

    # Knowledge-graph/external tools called once for the phase; their results
    # are injected as background context into the phase's synthesis prompt
    context_enrichment_tools:
      - "chembl_search"

  # Tools available to the Generate node in tool-calling mode (Mode 3)
  draft_generation:
    search_tools:
      - "arxiv_search"
      - "nvd_cve_search"
    read_tools:
      - "read_pdf"

  # Tools available for novelty validation
  validation:
    search_tools:
      - "arxiv_search"
    read_tools:
      - "read_pdf"

  # Entity-based evidence lookup during reflection
  reflection:
    search_tools:
      - "arxiv_search"
```

##### Multi-Source Fields

| Field | Type | Description |
|-------|------|-------------|
| `tool` | string | Tool ID from `tools` section |
| `papers_per_query` | integer | Papers to fetch per query from this source |
| `enabled` | boolean | Enable/disable this source |
| `content_tool` | string | Tool for fetching paper content (optional) |
| `content_url_field` | string | Field containing URL for content tool (optional) |
| `pdf_discovery_tool` | string | Tool for finding PDF URLs from landing pages (optional) |
| `pdf_discovery_url_field` | string | Field containing landing page URL (optional) |
| `content_params` | object | Extra parameters passed to content tool (optional); supports `{research_goal}` placeholder |
| `reserved_slots` | integer | Evidence-budget slots guaranteed to this source before the rest are filled by retrieval score (default `0`). Use it for a source whose papers cannot compete on the scored axes — a local corpus has no citation count or publication year, so it loses to any indexed paper however well it matches |

**Content retrieval strategies:**

1. **Direct fulltext** (PubMed):
   ```yaml
   - tool: "pubmed_fulltext"
     # No content_tool needed - returns fulltext directly
   ```

2. **PDF URL provided** (arXiv):
   ```yaml
   - tool: "arxiv_search"
     content_tool: "read_pdf"
     content_url_field: "pdf_url"
   ```

3. **Two-step discovery** (Google Scholar):
   ```yaml
   - tool: "google_scholar_search"
     pdf_discovery_tool: "find_pdf_links"  # Step 1: landing page → PDF URL
     pdf_discovery_url_field: "url"
     content_tool: "read_pdf"              # Step 2: PDF URL → content
     content_url_field: "pdf_url"
   ```

4. **Research-focused content extraction** (with context params):
   ```yaml
   - tool: "arxiv_search"
     content_tool: "analyze_pdf_for_research"
     content_url_field: "pdf_url"
     content_params:
       research_goal: "{research_goal}"   # substituted at runtime
       focus_areas:
         - "methodology"
         - "key findings"
   ```

---

#### Source Type and Query Generation

The `source_type` field determines query generation strategy:

| Source Type | Query Format | Use Case |
|-------------|--------------|----------|
| `"pubmed"` | Boolean (AND/OR/NOT) | PubMed-specific syntax |
| `"academic"` | Natural language | General academic search (Google Scholar) |
| `"preprint"` | Natural language | arXiv, bioRxiv, etc. |
| `"web"` | Natural language | Open-web search (see [Web Search](CONFIGURATION.md)) |
| `"knowledge_graph"` | Gene/protein names | INDRA, STRING, etc. |
| `"vulnerability_database"` | Topic keywords | NVD/CVE databases |

**LLM-based query generation** (when `query_generation_tool: null`):
- Detects source types from enabled sources
- Selects appropriate prompt template
- Generates source-appropriate queries

**MCP-based query generation** (when `query_generation_tool` specified):
- Calls MCP tool with `query_format` parameter
- Falls back to LLM if tool unavailable

---

#### Enrichments

Post-generation enrichments call a tool once per hypothesis and attach the results to `hypothesis.enrichments`. This is useful for domain-specific data that augments the output (e.g., related CVEs in cybersecurity, or gene interaction data in biomedicine).

```yaml
enrichments:
  - tool: "nvd_cve_search"
    input_field: "text"          # Hypothesis field used as query input
    output_key: "related_cves"   # Key under hypothesis.enrichments
    results_path: "results"      # JSONPath into tool response
    enabled: true
    max_results: 5
```

Each entry in `enrichments` produces a key under `hypothesis["enrichments"]`. Multiple enrichment tools can be configured.

---

### Using These Configurations

#### Method 1: Pass to HypothesisGenerator

```python
import asyncio
from co_scientist import GeneratorOptions, HypothesisGenerator

async def main():
    generator = HypothesisGenerator(
        model_name="gemini/gemini-2.5-flash",
        options=GeneratorOptions(tools_config="path/to/my_config.yaml"),
    )

    async for node_name, state in generator.generate_hypotheses(
        research_goal="Your research question",
        stream=True
    ):
        print(f"Completed: {node_name}")

asyncio.run(main())
```

#### Method 2: Copy to User Config Directory

```bash
cp my_config.yaml ~/.coscientist/tools.yaml
```

The registry automatically loads from `~/.coscientist/tools.yaml` if present.

#### Method 3: Modify and Merge

Create a custom config that extends or overrides specific tools:

```yaml
version: "1.0"

settings:
  merge_strategy: "extend"  # Extend built-in config

tools:
  search_tools:
    my_custom_tool:
      # Your custom tool config
```

---

### Merge Strategies

Control how user configs interact with the built-in `tools.yaml`:

| Strategy | Behavior |
|----------|----------|
| `"replace"` | User config completely replaces built-in config |
| `"extend"` | User config adds to built-in config (tools are merged) |
| `"override"` | User tools override built-in tools with same ID |

Set in `settings.merge_strategy`.

---

### Limitations and Future Work

1. **Single query set for all sources:** Multi-source configs use the same queries for all sources. If sources are mixed in the same run, some may yield no results for certain source types. Alternatives include running hypothesis generation once per source, or extending the project to support per-source query generation in the same run.

2. **MCP caching:** Caching of MCP tool responses is assumed to occur on the MCP server side.

### Getting Help

- **Schema validation errors:** Check field names and types against this document
- **MCP connection errors:** Verify `url` and `enabled` in server configs
- **Missing tools:** Check MCP server logs — tool must be registered
- **Empty results:** Check `response_format.field_mapping` matches MCP response structure

## MCP Integration & Literature Review

The MCP (Model Context Protocol) server integration is **recommended** for best results. While Co-Scientist will work without it, the quality of hypotheses is significantly enhanced when grounded in real published research.

### Reference Implementation

The bundled MCP server in `mcp_server/` provides PubMed integration and serves as a starting point. The core engine is domain-agnostic: literature sources, prompt guidance, and post-generation enrichments are controlled by a YAML configuration — no code changes needed. See [Domain Customization](CONFIGURATION.md) for working examples (biomedical, cybersecurity, multi-source academic).

### With MCP Server

Co-Scientist will:
- Automatically detect the MCP server at startup
- Search PubMed biomedical database for real published papers
- Retrieve fulltext XML/HTML from PubMed Central (PMC)
- Analyze literature with per-paper analysis and synthesis
- Use the Reflection node to validate hypotheses against actual research findings
- Generate hypotheses informed by current biomedical literature

**Limitations without MCP:**
- Relies solely on LLM's training data (limited awareness of recent discoveries)
- No validation against current scientific literature

### Setting Up MCP Server

#### Quick Start with Docker

The easiest way to get started is with Docker:

```bash
# 1. copy and configure environment
cp mcp_server/.env.example mcp_server/.env
# edit mcp_server/.env: set ENTREZ_EMAIL and ENTREZ_API_KEY

# 2. start server with docker compose from project root (engine/)
docker compose up -d

# 3. verify server is running
curl http://localhost:8888
```

MCP endpoints will be available at `http://localhost:8888/mcp` (auto-detected by Co-Scientist).

#### Alternative: Local Development Setup

For local development without Docker:

```bash
cd mcp_server

# create Python 3.12+ environment
python3.12 -m venv venv
source venv/bin/activate

# install dependencies
pip install -e .

# configure environment
cp .env.example .env
# edit .env: set ENTREZ_EMAIL, ENTREZ_API_KEY

# Run from root dir, to find the mcp_server package
cd ..

# run server (from root dir)
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888
```

**For complete setup instructions, Docker commands, and configuration options, see [mcp_server/README.md](../mcp_server/README.md).**

#### Required Environment Variables (See mcp_server/.env.example)

MCP server requires:
- `ENTREZ_EMAIL`: Your email (required for PubMed API)
- `ENTREZ_API_KEY`: For higher rate limits (get at https://www.ncbi.nlm.nih.gov/account/)

### Generation Modes

Co-Scientist supports three generation modes with different levels of literature integration:

1. **No Literature Review** (Fastest) - Uses only LLM knowledge
2. **Literature-Informed Generation** - Pre-processes literature, then generates
3. **Tool-Calling Generation** - Generate node queries literature in real-time

**For detailed information on each mode, configuration examples, and when to use each, see [Generation Modes Documentation](ARCHITECTURE.md).**


### Bringing Your Own MCP Tools

Co-Scientist supports any MCP-compatible server via the YAML configuration system — no modifications to Co-Scientist code or prompts are needed. The YAML config handles:

- Registering your server URL and transport
- Defining tools (search, read, utility) with response parsing rules
- Mapping tool parameters to canonical names used by the workflow
- Injecting domain-specific prompt instructions per tool

Supported literature source types: `pubmed`, `academic`, `preprint`, `web`, `knowledge_graph`, `vulnerability_database`.

The bundled server also provides `search_web` and `read_url` for open-web research and browsing. See [Web Search](CONFIGURATION.md).

See [Literature Review Tools Configuration](CONFIGURATION.md) for the full YAML schema reference, and [Domain Customization](CONFIGURATION.md) for complete worked examples.

For implementing custom MCP tools, refer to the [Model Context Protocol specification](https://modelcontextprotocol.io).

## Web Search and Browsing

The co-scientist can search the open web and read the pages it finds, alongside
its academic sources (PubMed, OpenAlex, ChEMBL, UniProt, INDRA CoGEx).

This fills gaps the academic indexes leave: news and grey literature,
consortium and regulatory material, company and clinical announcements,
conference coverage, and any domain without a strong paper index. It also lets
the agent read a URL it already has, such as an OpenAlex landing page or a DOI
link.

### The two tools

| Tool | What it does |
|---|---|
| `search_web` | Searches the open web. Returns titles, URLs, and snippets. |
| `read_url` | Fetches a web page or PDF and returns readable text. |

They are meant to be used together. Search alone returns links, which an agent
cannot reason over; the pairing is what makes browsing agentic.

### Where they are reachable

There are two paths, and they activate differently.

**Agentic browsing — the `draft_generation` phase.** The draft node runs the
LLM tool-calling loop, and both tools are in its whitelist by default. Here the
model decides for itself when to search, which results are worth opening, and
whether to search again with what it learned. This loop is active only when the
run enables tool-calling generation (`enable_tool_calling_generation=True`),
which also requires the MCP server and the literature-review node. An omitted
option is not a request: each tool call is an LLM round-trip carrying every
prior result forward, so the loop is opt-in rather than default-on. The web app
exposes no user-facing toggle — it opts in by run tier, asking for the loop on
the `extended` and `ultra` tiers only. From the library, request it explicitly:

```python
result = await generator.generate_hypotheses(
    research_goal="...",
    opts={
        "enable_literature_review_node": True,
        "enable_tool_calling_generation": True,
    },
)
```

**Grounded web search — the `literature_review` phase.** `web_search` is a
literature-review search source in the default config, alongside PubMed and
OpenAlex, with `read_url` as its content tool so snippets are expanded into
real page text before analysis. It is weighted lower than the peer-reviewed
sources (`papers_per_query: 2` against their 4) and its results carry
`source: "web"`, so web-derived evidence stays distinguishable from
peer-reviewed evidence downstream.

This is the path that runs on every tier, including the ones where the
tool-calling generation loop above stays off. If you would rather keep
web content out of the evidence base entirely, delete the `web_search` entry
from `literature_review.search_sources` — the tool stays available to the
agentic phase.

`web_search` is deliberately **not** in the `validation` or `reflection`
workflows. Those are direct-call paths, not tool-calling loops: validation
picks the first search tool in order and should check novelty against academic
sources, and reflection queries knowledge graphs by entity rather than by
free-text search.

### Setup

Both tools live on the bundled MCP server (`mcp_server/`). `read_url` needs no
configuration. `search_web` needs an API key from one provider:

```bash
# Brave: independent index, low latency. The default.
BRAVE_API_KEY=...

# Tavily: agent-oriented, returns extracted page content with each result,
# which often saves a follow-up read_url call.
TAVILY_API_KEY=...

# Optional. Defaults to whichever key is set, preferring Brave.
WEB_SEARCH_PROVIDER=brave
```

Without a key, the server does not register `search_web` at all. The workflow
whitelist skips tools the server never advertised, so a key-less deployment
behaves exactly as it did before — no failing tool, no wasted tool-calling
turn. Check what a running server exposes:

```bash
curl http://localhost:8888/ | jq '.mcp_tools, .integrations.web_search_provider'
```

### The app's Web search connector

The workbench composer lists **Web search** in its Connectors menu next to
PubMed, on by default. It appears only when the API's `/status` probe finds
the MCP server advertising `search_web` — that is, only when a provider key is
configured — so a deployment without a key never offers a toggle it cannot
honor. `/status` exposes this as `web_search_available` and a
`probes.web_search` entry.

Turning it off sends `enable_web_search: false` with the run, which the API
maps to `disable_tools=["web_search"]` on the engine's tool registry.
`read_url` stays enabled: it is the shared content-fetch tool that the arXiv,
Google Scholar, and web configs use to pull PDFs and full text, so disabling
it here would break literature retrieval for unrelated sources.

### Web-first research

The default config keeps academic sources primary and web search supplementary.
For domains with no strong academic index, create a YAML overlay with the web as
its leading source and OpenAlex as a secondary source.

The overlay must set two properties:

- `query_format: "natural_language"`. The default is `"boolean"`, which emits
  PubMed `AND`/`OR`/`NOT` syntax. A web engine ANDs every token in a query
  like that and returns nothing.
- `availability_check: null`. The default gates the node on a PubMed probe,
  which a web-only config never uses.

It also sets `content_tool: "read_url"` on the web source, so search snippets
are expanded into full page text before analysis.

### Adding a provider

`mcp_server/tools/web/providers.py` holds a dispatch table. A provider is one
async function `(query, max_results, recency_days) -> dict[str, Any]` that
calls its vendor API and normalizes the response into
`{result_id: {title, url, abstract, source, published_date}}`, plus one entry
in `_PROVIDERS` naming its key env var. Normalization is a pure function, so
test it directly against a captured payload — see `mcp_server/tests/test_web_search.py`.

### Safety

**Fetched page content is data, not instructions.** A page the agent reads may
contain text addressed to an AI system. The engine treats all tool results as
data to evaluate, and nothing about these tools changes that.

**No raw HTML reaches the model.** `read_url` runs HTML through the extractor
in `extract.py` (headings, paragraphs, and lists preserved; scripts, styles,
nav, and footers dropped) and PDFs through pypdf. Search snippets are cleaned
too — Brave wraps matched query terms in `<strong>` — so neither tool emits
markup.

**`read_url` screens every URL before fetching it.** The URL comes from an LLM,
influenced by search results the LLM did not write, and in production the MCP
server sits on a private network beside the API service. The screen
(`mcp_server/tools/web/url_guard.py`) rejects non-`http(s)` schemes and any
host that resolves to a loopback, private, link-local, or reserved address, and
re-screens every redirect hop. Resolution happens through DNS rather than
string matching, so hostnames that point at internal addresses
(`127.0.0.1.nip.io`, decimal-encoded IPs) are caught too.

If you extend the fetching path, keep the redirect re-check. Validating only
the first URL lets a redirect walk straight past the screen.

## Domain Customization

Co-Scientist is domain-agnostic by design. The default configuration targets biomedical research (PubMed), but the system can be adapted to any research domain — cybersecurity, materials science, climate research, bioinformatics, or subdomains like Alzheimer's drug repurposing — through a YAML configuration file. No changes to source code or prompts are needed.

A domain config controls:

- **Which MCP servers and literature sources to use** (arXiv, Google Scholar, NVD, INDRA, etc.)
- **Prompt guidance** injected into hypothesis generation, review, and evolution
- **Post-generation enrichments** that attach domain-specific data to each hypothesis (e.g., related CVEs, knowledge graph entries)

See [Literature Review Tools Configuration](CONFIGURATION.md) for the full YAML schema reference.

---

### How It Works

#### 1. Choose Your Sources

Point to an MCP server and define which tools it exposes:

```yaml
servers:
  my_server:
    url: "${MY_MCP_URL:-http://localhost:8889/mcp}"
    transport: "streamable_http"
    enabled: true

tools:
  search_tools:
    arxiv_search:
      server: "my_server"
      mcp_tool_name: "search_arxiv"
      source_type: "preprint"
      # ...
```

#### 2. Add Domain Prompt Guidance

The `prompts` section injects text into the Generate, Review, and Evolve nodes without modifying any code:

```yaml
prompts:
  domain_context: |
    You are a cybersecurity researcher. "Hypothesis" means a threat hypothesis —
    a novel attack technique or adversarial capability.

  generation_guidance: |
    Generate hypotheses spanning: novel exploitation, evasion techniques,
    AI-augmented attacks, and supply chain compromise.

  review_guidance: |
    Prioritize: operational feasibility, novelty over existing TTPs,
    and defensive value (purple team utility).
```

#### 3. Add Enrichments (Optional)

Enrichments call a tool once per hypothesis after generation and attach results to `hypothesis["enrichments"]`. Useful for domain-specific data that complements the literature:

```yaml
enrichments:
  - tool: "nvd_cve_search"
    input_field: "text"
    output_key: "related_cves"
    results_path: "results"
    enabled: true
    max_results: 5
```

#### 4. Set Merge Strategy

Use `merge_strategy: "replace"` to fully replace the default PubMed config, or `"extend"` to add sources alongside it:

```yaml
settings:
  merge_strategy: "replace"
```

---

### Retained domain examples

`indra_cancer.yaml` extends the default sources with oncology guidance and INDRA
mechanistic evidence. `indra_hfpef.yaml` provides a cardiac-remodeling example.
Both live in `src/co_scientist/config/examples/` and exercise the same custom
server, prompt, enrichment and merge options described above.

### Using a Custom Config

Pass the YAML path when creating `HypothesisGenerator`:

```python
import asyncio
from co_scientist import GeneratorOptions, HypothesisGenerator

async def main():
    generator = HypothesisGenerator(
        model_name="gemini/gemini-2.5-flash",
        options=GeneratorOptions(tools_config="path/to/my_domain.yaml"),
    )

    async for node_name, state in generator.generate_hypotheses(
        research_goal="Your domain-specific research question",
        stream=True
    ):
        print(f"Completed: {node_name}")
        if node_name == "ranking":
            for h in state["hypotheses"]:
                print(h["text"])
                print(h.get("enrichments", {}))  # domain-specific enrichment data

asyncio.run(main())
```

Alternatively, place the config at `~/.coscientist/tools.yaml` and it will be loaded automatically.

---

### Writing a Config for a New Domain

1. **Identify your literature sources** — what databases or APIs exist for your domain? Any MCP-compatible server can be integrated.
2. **Define prompt guidance** — what terminology does your domain use? What makes a hypothesis "good" in this domain? What should the experiment section look like?
3. **Consider enrichments** — is there structured domain data (CVEs, pathway databases, patent records) that should be attached per hypothesis?
4. **Pick a merge strategy** — `replace` if you're fully replacing PubMed, `extend` if you want to add to it.

Refer to the [Literature Review Tools Configuration](CONFIGURATION.md) for the full YAML schema, and the two retained example YAMLs.

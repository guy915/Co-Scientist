# Web Search and Browsing

The co-scientist can search the open web and read the pages it finds, alongside
its academic sources (PubMed, OpenAlex, ChEMBL, UniProt, INDRA CoGEx).

This fills gaps the academic indexes leave: news and grey literature,
consortium and regulatory material, company and clinical announcements,
conference coverage, and any domain without a strong paper index. It also lets
the agent read a URL it already has, such as an OpenAlex landing page or a DOI
link.

## The two tools

| Tool | What it does |
|---|---|
| `search_web` | Searches the open web. Returns titles, URLs, and snippets. |
| `read_url` | Fetches a web page or PDF and returns readable text. |

They are meant to be used together. Search alone returns links, which an agent
cannot reason over; the pairing is what makes browsing agentic.

## Where they are reachable

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

## Setup

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

## The app's Web search connector

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

## Web-first research

The default config keeps the academic sources primary and web search
supplementary. For domains with no strong academic index, or when recency
matters more than peer review, `web_research.yaml` inverts that — web leads,
OpenAlex backs it up:

```bash
export TOOLS_CONFIG=src/co_scientist/config/examples/web_research.yaml
```

It makes the web the leading literature-review source and sets the two things
such a configuration must get right:

- `query_format: "natural_language"`. The default is `"boolean"`, which emits
  PubMed `AND`/`OR`/`NOT` syntax. A web engine ANDs every token in a query
  like that and returns nothing.
- `availability_check: null`. The default gates the node on a PubMed probe,
  which a web-only config never uses.

It also sets `content_tool: "read_url"` on the web source, so search snippets
are expanded into full page text before analysis.

## Adding a provider

`mcp_server/tools/web/providers.py` holds a dispatch table. A provider is one
async function `(query, max_results, recency_days) -> dict[str, Any]` that
calls its vendor API and normalizes the response into
`{result_id: {title, url, abstract, source, published_date}}`, plus one entry
in `_PROVIDERS` naming its key env var. Normalization is a pure function, so
test it directly against a captured payload — see `mcp_server/tests/test_web_search.py`.

## Safety

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

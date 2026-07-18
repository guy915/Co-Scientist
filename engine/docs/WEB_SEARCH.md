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
which also requires the MCP server and the literature-review node. It is an
engine-level option; the web app does not expose a toggle for it yet, so reach
it through the library:

```python
result = await generator.generate(
    research_goal="...",
    enable_tool_calling_generation=True,
)
```

**Grounded web search — the `literature_review` phase.** When a config lists
`web_search` as a literature-review search source, the node searches the web
and (with `read_url` as the content tool) reads the pages as part of its fixed
search-then-analyze pipeline. This is not model-driven, but it is how a running
deployment — which selects behavior through its tools YAML — puts the web to
use. See the opt-in section below.

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

## Opt in to grounded web search

By default `web_search` is **not** a literature-review search source. That node
is the evidence grounding path, and its citations are quality-checked against
academic sources; adding arbitrary web pages there would quietly change what a
verified citation means.

To opt in — appropriate for domains with no strong academic index, or when
recency matters more than peer review — use the `web_research.yaml` example:

```bash
export TOOLS_CONFIG=src/co_scientist/config/examples/web_research.yaml
```

It makes the web a first-class literature-review source and sets the two
things that configuration must get right:

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
test it directly against a captured payload — see `tests/test_web_search.py`.

## Safety

**Fetched page content is data, not instructions.** A page the agent reads may
contain text addressed to an AI system. The engine treats all tool results as
data to evaluate, and nothing about these tools changes that.

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

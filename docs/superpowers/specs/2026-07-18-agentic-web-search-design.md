# Agentic web search for the co-scientist engine

Date: 2026-07-18
Status: approved-by-default (see "Decisions defaulted" below)

## Problem

The engine can only reach the outside world through MCP tools that index
*academic* corpora: PubMed, OpenAlex, ChEMBL, UniProt, INDRA CoGEx. It has no
way to read the open web. That leaves three gaps:

- **Grey literature and news.** Preprint-adjacent blog posts, consortium
  reports, regulatory notices, company announcements, and conference
  coverage never enter a hypothesis's evidence base.
- **Non-biomedical domains.** The cybersecurity and general-science configs
  have no grounding source at all once PubMed is dropped.
- **Browsing.** Even where a URL is known (an OpenAlex landing page, a DOI),
  nothing in the engine can fetch and read it. `read_url` appears in the
  example YAML configs but was never implemented in the bundled MCP server —
  those examples assume a user-supplied server on port 8889 that this repo
  does not ship.

"Agentic" is the operative word: the goal is not a single search call bolted
onto the literature-review node, but a search-then-read loop the model drives
itself.

## Approach

Web access is added as **two new tools on the bundled MCP server**
(`engine/mcp_server/`), exposed to agents through the existing YAML tool
registry. No engine (`src/co_scientist/`) code changes.

This follows the path OpenAlex took: the engine makes zero direct outbound
HTTP calls, and that property is worth preserving. Every external I/O concern
(API keys, rate limits, retries, HTML parsing, SSRF) stays inside the MCP
server, which is separately installable, separately deployed (the Railway
`mcp` service), and independently testable.

### Two tools, not one

| Tool | Purpose |
|---|---|
| `search_web` | Query a general-web search API, return ranked `{id: metadata}` results with title, URL, and snippet. |
| `read_url` | Fetch an arbitrary URL and return clean, truncated markdown. |

A search tool alone returns a list of links, which an agent cannot act on.
The pairing is what makes browsing agentic: the model searches, reads the
promising hits, and searches again with what it learned. Both tools are
registered in the `draft_generation`, `validation`, and `reflection`
workflows, which run through `call_llm_with_tools` — the model chooses when
and whether to call them, and how to follow up.

### Provider abstraction

`search_web` dispatches to a pluggable provider behind a small internal
interface. Two are implemented:

- **Brave Search** (default) — independent index, lowest latency in current
  benchmarks, and the only large non-Google/non-Bing western index still
  offered to developers after Bing's API shutdown.
- **Tavily** — agent-optimized; returns extracted page content alongside
  results, which lets the model skip a `read_url` round trip on easy hits.

Selection is `WEB_SEARCH_PROVIDER` (`brave` | `tavily`), defaulting to
whichever API key is present. Adding a third provider means one module and
one dict entry, but the design deliberately stops at two — this is a
dispatch table, not a framework.

Both providers normalize to the same `{result_id: metadata}` shape the
engine's `ResponseParser` field mapping already consumes, so results become
`Article` objects and flow into `WorkflowState` exactly like OpenAlex hits.

### Graceful degradation

`search_web` is registered on the MCP server **only when a provider key is
configured**. The server's `/` manifest derives from the same registration
tuple, so it stays honest about real capability, and the engine's whitelist
filter simply doesn't surface a tool the server never advertised. This is
better than registering an always-failing tool, which would burn a
tool-calling turn on every run of a key-less deployment.

`read_url` needs no key and is always registered.

Inside each tool, network and parse failures return `{}` / an error
placeholder string rather than raising — matching `search_openalex`, so one
dead source never fails a whole literature-review step.

## Components

### `mcp_server/tools/web/providers.py`

Provider dispatch. Each provider is an async function
`(query, max_results, recency_days) -> dict[str, Any]` that calls its vendor
API with `httpx` and normalizes the response. `resolve_provider()` reads
`WEB_SEARCH_PROVIDER` and the key env vars, returning `None` when nothing is
configured (which is what suppresses registration).

Normalized metadata per result: `title`, `url`, `abstract` (the snippet, or
Tavily's extracted content), `source` (`"web"`), `published_date`, `score`.
`abstract` rather than `snippet` because that is the field name the engine's
article pipeline already reads.

### `mcp_server/tools/web/web_search.py`

`async def search_web(query, max_results=10, recency_days=0, run_id=None)`.
Thin: resolve provider, delegate, clamp `max_results`, return. `run_id` is
accepted and unused, for interface parity with the other search tools.

### `mcp_server/tools/web/fetch.py`

`async def read_url(url, max_chars=50_000) -> str`. Fetches with `httpx`
(redirects followed, capped), then extracts by content type:

- **HTML** — BeautifulSoup (already a dependency): drop `script`, `style`,
  `nav`, `header`, `footer`, `aside`, `form`, `noscript`; convert `h1`–`h6`
  to `#` headings and `p`/`li` to text blocks. Raw HTML costs roughly an
  order of magnitude more tokens than the extracted text, so this is the
  difference between a usable tool and one that blows the context window.
- **PDF** — delegate to the existing fulltext extraction path.
- **Plain text / JSON** — pass through.

Output is truncated with `text_extraction._truncate_markdown`, reusing the
existing truncation marker convention.

### SSRF guard — `mcp_server/tools/web/url_guard.py`

**Load-bearing.** `read_url` takes a URL chosen by an LLM, which may be
influenced by search results the LLM did not write. In production the MCP
server sits on Railway's private network alongside the API service and its
volume. An unguarded fetcher is an internal-network read primitive.

`is_fetchable(url)` rejects, before any request: non-`http(s)` schemes; hosts
that resolve to loopback, link-local, private, or reserved ranges (checked
after DNS resolution, not by string matching, so `127.0.0.1.nip.io` and
decimal-encoded IPs are caught); and the cloud metadata endpoint. Redirect
targets are re-checked at each hop, since only the first URL is validated
otherwise.

Fetched page content is **data, not instructions**. The engine already treats
all tool results as data; nothing in this design changes that, and the
`read_url` docstring and prompt snippet say so explicitly so the behavior is
not accidentally regressed later.

### Configuration

**`src/co_scientist/config/tools.yaml`** (default config) gains:

- `search_tools.web_search` — `source_type: "web"`, field mapping to
  `Article`, `parameter_mapping` with `slug`/`recency_years`/`run_id` nulled
  (web providers take neither a corpus slug nor a publication-year filter;
  recency is expressed in days).
- `read_tools.read_url`.
- Both added to `workflows.draft_generation`, `workflows.validation`, and
  `workflows.reflection`.

Deliberately **not** added to `workflows.literature_review.search_sources`.
That node is the evidence-grounding path, and its citations are quality-gated
against academic sources; mixing arbitrary web pages into it silently changes
what a "verified citation" means. Domains that want it opt in explicitly.

**`src/co_scientist/config/examples/web_research.yaml`** — a new example for
exactly that opt-in: web as a first-class literature-review source, with
`query_format: "natural_language"` (the default `boolean` would send PubMed
`AND`/`OR`/`NOT` syntax to a web engine, which ANDs every token and returns
nothing) and `availability_check: null` (no PubMed in that config).

**Env** (`mcp_server/.env.example`): `WEB_SEARCH_PROVIDER`, `BRAVE_API_KEY`,
`TAVILY_API_KEY`.

## Data flow

```
LLM (draft/validation/reflection)
  -> call_llm_with_tools loop
  -> MCPToolProvider.execute_tool_call
  -> MCPToolClient (unwraps result)
  -> MCP server: search_web -> provider -> vendor API
                 read_url   -> url_guard -> httpx -> extractor
  -> ResponseParser field mapping -> Article -> WorkflowState.articles
```

The literature-review node's direct `call_tool` path is unchanged and
unaffected unless a config opts web in as a search source.

## Error handling

| Failure | Behavior |
|---|---|
| No provider key | `search_web` not registered; manifest reflects it |
| Vendor API error / timeout | `{}`, warning logged |
| Malformed vendor response | `{}`, warning logged |
| `read_url` blocked by guard | Explicit `[blocked: ...]` string so the model learns not to retry |
| `read_url` fetch/parse error | `[error: ...]` placeholder string |

No exception crosses the MCP boundary. Every path degrades to "this source
returned nothing," which the engine already handles.

## Testing

Following `test_openalex.py`: normalization and parameter-building are pure
functions tested directly, with no network.

- `test_web_search.py` — per-provider response normalization (including
  malformed and empty payloads), provider resolution precedence,
  `max_results` clamping.
- `test_fetch.py` — HTML→markdown extraction (chrome stripped, headings
  preserved), truncation, content-type dispatch.
- `test_url_guard.py` — the guard's reject cases: loopback, private ranges,
  DNS-rebind-style hostnames, metadata endpoint, non-HTTP schemes, and the
  redirect-hop re-check. Highest-value tests in the change.

Engine-side: no new tests, since no engine code changes. The YAML additions
are exercised by the existing registry tests.

## Docs

- New `engine/docs/WEB_SEARCH.md` — providers, keys, workflow wiring, the
  opt-in example, and the untrusted-content note.
- `engine/docs/MCP_INTEGRATION.md` — add `web` to the `source_type` list.
- `engine/mcp_server/README.md` — new tools in the tool table.

## Decisions defaulted

The user is not present to arbitrate; both open choices are cheap to reverse,
so they are defaulted rather than blocked on:

- **Provider: Brave.** Swap with `WEB_SEARCH_PROVIDER=tavily`, no code change.
- **Bundled server, not external.** Reversible by pointing a YAML overlay at
  a different `servers:` entry.

## Out of scope

Headless-browser rendering of JS-heavy pages, crawling beyond a single fetch,
a persistent web-page cache separate from the existing LLM cache, and
per-domain allow/deny policy beyond the SSRF guard.

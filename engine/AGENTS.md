# Engine — `co-scientist-engine`

LangGraph multi-agent hypothesis-generation library. Repo-wide conventions, cross-cutting Gotchas, and required environment live in the [root AGENTS.md](../AGENTS.md) — read that too.

Package name: `co-scientist-engine`. Source under `src/co_scientist/`.

**Commands** (run from `engine/`):
```bash
pip install -e '.[dev]'          # install with dev deps
python examples/run.py            # interactive CLI demo
pytest                            # unit tests (testpaths = ["tests"])
ruff format .                     # format (80 cols)
ruff check .                      # lint
mypy .                            # typecheck
```

Individual nodes can be exercised in isolation via the scripts in `dev/` (`run_supervisor_standalone.py`, `run_generate_standalone.py`, `run_lit_review_standalone.py`, etc.) — useful for iterating on a single agent without spinning up the full graph. These scripts load a `.env` from `dev/` itself, not from the engine root — copy your API keys there before running.

**Architecture**

`HypothesisGenerator` (`src/co_scientist/generator/`) is the public entry point. It compiles a LangGraph `StateGraph` whose nodes are implemented across eight agent packages under `src/co_scientist/agents/`: **Supervisor plus six specialists** (Generation, Reflection, Ranking, Evolution, Proximity, Meta-review), plus a cross-cutting Safety screen that is not one of the six. The old `src/co_scientist/nodes/` shim layer has been removed — import node callables from `co_scientist.agents.*`. The graph still registers each node under its original key string (so durable-run resume is unaffected), and `co_scientist.agents.NODE_TO_AGENT` is the source-of-truth node→agent mapping:

| Node | File |
|---|---|
| Supervisor (planning) | `agents/supervisor/supervisor.py` |
| Orchestrator (per-cycle routing) | `agents/supervisor/orchestrator.py` |
| Literature Review (MCP-gated) | `agents/generation/literature_review/` (node, helpers, search/retrieval/article support) |
| Generate | `agents/generation/generate.py` (+ `coordinator.py`, `debate.py`, `citations.py`, `literature_tools/`) |
| Reflection | `agents/reflection/reflection.py`, `reflection_helpers.py` |
| Review | `agents/reflection/review.py` |
| Comprehensive Reflection | `agents/reflection/comprehensive_reflection.py` |
| Deep Verification (probing questions) | `agents/reflection/deep_verification.py` |
| Ranking + Tournament (Elo pairwise) | `agents/ranking/` (`ranking.py`, `ranking_elo.py`, `ranking_matchmaking.py`, ...) |
| Meta-Review | `agents/meta_review/meta_review.py` |
| Research Overview (synthesis/roadmap) | `agents/meta_review/research_overview.py` |
| Evolve | `agents/evolution/evolve.py` |
| Proximity (dedup) | `agents/proximity/proximity.py` |
| Safety screen (cross-cutting) | `agents/safety/safety_screen.py` |

**The simulation review can run what it simulates.** Reflection's
`simulation` review asks the model to step through a hypothesis's mechanism
and find where it breaks; its prompt used to say *mentally, in your mind's
eye*. `agents/reflection/simulation_execution.py` gives it a confined
workspace and a bounded tool loop (`MAX_SIMULATION_TURNS`) first, and hands
what it observed to the same schema-constrained review call as before -- so
the verdict vocabulary and every downstream consumer are untouched, and a run
that cannot execute produces exactly the review it always did. This is the
first production caller of the conversational tool surface. Gated three ways,
all of which must hold: the app asks by **tier** on `extended`/`ultra` only
(`opts._resolve_simulation_execution_toggle` -- a tool loop per hypothesis is
a cost that multiplies by pool size), the engine refuses it for the offline
backend (`run_setup._resolve_simulation_execution`), and the review itself
falls back to mental simulation where no sandbox backend can confine a
command. Each review gets its **own** workspace
(`open_review_workspace(run_id, hypothesis_id)`) because review items fan out
as concurrent leased tasks. Whether it ran is stamped on the result by the
caller (`executed`), never asked of the model.

**Computational discovery** is a second, separate product built on the same
foundations, and is *not* a node in the hypothesis graph.
`agents/code_evolve/` proposes one child program per generation as a V4A
patch under a named code operator and picks parents from a MAP-Elites
diversity archive (`archive.py` for MOME cells, `grid.py` for the
fixed/adaptive/CVT strategies, `behaviour.py` for the structural
features they niche by -- including `metric:*`, the one axis derived from
what a program *computed* rather than from its text, which is what
separates two programs sharing a shape since no static reading can --
`fingerprint.py` for the hashed AST n-gram that separates two algorithms
sharing a surface shape, `tessellation.py` for the frozen projection that
keeps a cell meaning the same thing from one generation to the next while
still growing cells and columns for behaviour it has never seen); `code_eval/` runs the resulting cascade
and scores it against one or more objectives, keeping the extra ones
separate via Pareto dominance (`pareto.py`) rather than summing them; `workspace/` and `sandbox/` confine every command --
including ones that outlive the call that started them
(`workspace/command_session.py`: `run_command` hands back a session id
rather than killing a command at its deadline, `poll_command` continues
it from a cursor, and `llm_tool_transcript.normalize_tool_transcript`
turns a turn cut off mid-call into an explicit aborted result instead of
a conversation the provider rejects). The app
drives the loop as durable tasks rather than through LangGraph. See
`docs/DISCOVERY.md`.

Shared state flows through `WorkflowState` in `state.py`; note the custom `deduplicate_hypotheses` reducer that auto-dedupes on every state update. Prompts are markdown files in `src/co_scientist/prompts/templates/` (also bundled via `package-data`), loaded by the `prompts/` package. YAML tool/domain configs live in `src/co_scientist/config/` with examples per domain (biomed/cyber/web-research/etc.).

Key supporting modules: `models.py` (dataclasses: `Hypothesis`, `HypothesisReview`, `ExecutionMetrics`, `Article`), `schemas/` (JSON-schema package for structured LLM output — one module per prompt family plus `registry.py`), `constants.py` (Elo params, token limits, temperatures), `exceptions.py` (domain exception hierarchy), `progress.py` (shared progress-event emission used by all agent nodes), `tools/` (tool registry subpackage for YAML-based tool configuration).

**LLM dispatch and bounds.** Calls go through LiteLLM (`llm.py`). Every completion is bounded twice: `llm_request.llm_timeout_seconds()` (env `COSCIENTIST_LLM_TIMEOUT_SECONDS`, default 600s, `0` disables) is passed to litellm *and* re-imposed as a hard `asyncio.wait_for` ceiling in `llm._acompletion_within_timeout` (+30s grace), raising `LLMTimeoutError`. `call_llm_json` retries up to `max_attempts` (default 5) but treats failure kinds differently in `llm_json_retry.py`: a schema failure retries immediately with validation feedback appended to the prompt, a throttled call backs off a **jittered** exponential (unjittered releases every throttled caller at once and reproduces the burst), and `LLMTimeoutError` is never retried — a stalled provider will not answer the same request faster.

**MCP and the web.** Literature-review tools are pulled from an external MCP server via `mcp_client.py` using `langchain-mcp-adapters`, bounded independently by `COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS` (default 300s). The graph auto-detects MCP availability — without a server, the literature/reflection nodes fall back to LLM-only mode. The literature-review pre-flight gate checks **server** reachability (`check_mcp_available`), not any single source's health: gating on one source let an unreachable remote service veto sources that were fine, including the always-available local corpus. For conditionally-registered tools, ask `mcp_client.check_tool_available(tool_name)`.

The engine can also search and read the open web. `web_search` (MCP `search_web`) is a default `literature_review` search source alongside PubMed/OpenAlex, weighted lower (`papers_per_query: 2` against their 4) with `read_url` as its content tool; its results carry `source: "web"` so web evidence stays distinguishable downstream. It is deliberately absent from `validation` and `reflection`, which are direct-call paths. The agentic path — the model deciding when to search and what to open — lives in `draft_generation` and is active only when a caller passes `enable_tool_calling_generation=True`; the tools being available is a precondition, never on its own a request. The app opts in **by tier**, not by user toggle: `engine_adapter/opts.py::_resolve_tool_calling_generation_toggle` asks for it on `extended` and `ultra` only. Each tool call is an LLM round-trip that re-sends every prior result, so one hypothesis costs ~9 calls on prompts growing past 12k tokens, per cycle — measured as the largest single line in an express run's token budget during the window this was default-on. See `engine/docs/WEB_SEARCH.md`.

**Per-run tool disabling is reconciled once, at registry load.** Connector toggles reach the engine as `HypothesisGenerator(disable_tools=[...])` (built in `app/app/engine_adapter/opts.py`), which `generator/run_setup.py` passes on as `ToolRegistry(disabled_tools=...)`. `registry._apply_disabled_tools` flips `enabled = False` on the tool *and* on every workflow `search_source` backed by it, covering every way a tool can be off — the `disabled_tools` argument, a YAML `enabled: false`, or a source naming a tool that does not exist. That one pass is load-bearing: the multi-source pipeline selects on `SearchSourceConfig.enabled` alone and never consults the tool's own flag, so a source left enabled over a dead tool keeps being searched. The Phase 2 searches in `literature_review/search.py` therefore trust `workflow.get_enabled_search_sources()` and deliberately do not re-check the registry — a second filter there was removed once the registry covered every case, so new gating belongs at the registry, not at the call site. `engine/tests/test_config_registry.py` pins the reconciliation.

**Evidence budget and `reserved_slots`.** Multi-source search fills its budget through `literature_review/search_budget.py::select_within_budget`, not by truncating the ranked list. Retrieval score rewards source quality, citation count, and recency — axes a local corpus can lack entirely rather than score poorly on, so it sorts below every indexed paper however well it matches. Such a source claims guaranteed places via `reserved_slots` in its `SearchSourceConfig`; reserved places are filled best-first within the source, never padded, never over budget.

Caching (`cache.py`) is on by default and controlled by `COSCIENTIST_CACHE_ENABLED` / `COSCIENTIST_CACHE_DIR` env vars.

Engine-specific docs live in `engine/docs/` (`ARCHITECTURE.md`, `CONFIGURATION.md`, `DEVELOPMENT.md`, `DOMAIN_CUSTOMIZATION.md`, `GENERATION_MODES.md`, `LITERATURE_REVIEW_TOOLS_CONFIGURATION.md`, `LOGGING.md`, `MCP_INTEGRATION.md`, `WEB_SEARCH.md`).

**Reference MCP server** lives in `mcp_server/` as a separately installable package. Install with `pip install -e mcp_server/` and run with `uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888`. **Requires Python 3.12** (engine itself is 3.10+) — install into a 3.12 venv or you'll hit cryptic solver errors. Registered tool families (see `mcp_server/server.py`): PubMed search + full-text retrieval, OpenAlex search, ChEMBL/UniProt lookups, SBI paper-corpus fetch, INDRA CoGex queries, and web search/fetch.

**Style conventions** (from the repo-root `CONTRIBUTING.md`, enforced informally):
- Code follows the Google Python Style Guide: ruff (formatter + linter, 80 columns, config in `pyproject.toml`), Google-format docstrings (`Args:`/`Returns:`/`Raises:`).
- Docstrings capitalized, full sentences.
- `logger.debug()` lowercase; `info`/`warning`/`error` capitalized.
- No emojis or unicode decoration in code or logs.
- Rich library only in `examples/` and `dev/`, never in core library code.

## Reference MCP server (`engine/mcp_server/`)

A separately installable package. Install with `pip install -e mcp_server/` and run with `uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888`. **Requires Python 3.12** (engine itself is 3.10+) — install into a 3.12 venv or you'll hit cryptic solver errors.

It registers 17 tools (16 without a web-search provider key) in four families:
- **Literature** — `search_pubmed`, `pubmed_search_with_fulltext`, `check_pubmed_available` (Biopython/Entrez), `search_openalex` (keyless, cross-disciplinary), `fetch_paper` (local corpus).
- **Open web** — `read_url` (always registered) and `search_web` (key-gated).
- **Direct biomedical lookups** — `search_chembl`, `search_uniprot` (EBI REST).
- **8 INDRA CoGex knowledge-graph queries.**

The `_MCP_TOOLS` tuple in `server.py` is the single source for both registration and the `mcp_tools` manifest at `GET /`. **Adding a tool takes two edits**: register it there, and declare it in the engine's `src/co_scientist/config/tools.yaml` with a matching `mcp_tool_name` (plus the `draft_generation` whitelist if the model should call it directly).

- **`search_web` is registered only when a provider key resolves** — `BRAVE_API_KEY` or `TAVILY_API_KEY`, with `WEB_SEARCH_PROVIDER=brave|tavily` selecting one (otherwise autodetect, brave first). Without a key the tool is *absent from the manifest*, not failing — so "the agent never searched the web" is a deployment question first. `curl http://localhost:8888/` returns the live `mcp_tools` list plus `integrations.web_search_provider`.
- **`read_url` fetches a URL an LLM chose**, so every URL passes `url_guard.check_fetchable`: http(s) only, cloud metadata hosts blocked, and the hostname resolved via `getaddrinfo` *before* the range check, so `nip.io`-style names pointing at loopback/private/link-local addresses are refused too. `fetch.py` follows redirects manually (`follow_redirects=False`, max 5), re-screening each hop, because httpx's own redirect handling would skip the check. In production this server sits on Railway's private network next to the api, so weakening the guard is a live SSRF. Page content is untrusted data, never instructions.
- **`fetch_paper`** reads the group's papers off disk, not an API. `SBI_CORPUS_DIR` points at a directory of `<paper_id>.md`/`.txt` files. The corpus is not searched here — the app injects the full title+abstract catalog into run context and the model fetches one paper whole by `paper_id`. The MCP-side var has **no default**: unset means the tool returns `{}`, indistinguishable from "no such paper", so `Dockerfile.mcp`'s `COPY corpus/` and `ENV SBI_CORPUS_DIR` must stay together.
- **Every tool is wrapped by `tool_logging.with_call_logging`** in the registration loop, emitting one INFO line per call (`tool search_pubmed(query='...') -> 2 items, 4102 chars in 812ms`). These tools degrade to an empty result rather than raising, so a missing key, a failed HTTP call, and a genuine zero-hit query are otherwise indistinguishable. Any wrapper added here **must copy `__signature__`** — FastMCP derives the advertised parameter schema from it, and a bare `*args, **kwargs` wrapper silently strips every parameter from what the agent sees.
- **Its own env surface**, in `engine/mcp_server/.env.example`, loaded from a `.env` co-located in `mcp_server/` (not the engine's; a missing file only warns): `ENTREZ_EMAIL`/`ENTREZ_API_KEY`, `DISABLE_SSL_VERIFY`, `COSCIENTIST_LIT_REVIEW_DIR`, `COSCIENTIST_MCP_PORT`, `COSCIENTIST_MCP_LOG_LEVEL`, `COSCIENTIST_MCP_SHARED_SECRET` (optional shared-secret auth — see `docs/DEPLOYMENT.md`), `WEB_SEARCH_PROVIDER`/`BRAVE_API_KEY`/`TAVILY_API_KEY`, `INDRA_COGEX_URL`/`INDRA_COGEX_TIMEOUT`, plus `SBI_CORPUS_DIR` (read by the corpus tool but omitted from the example file). Setting these in the app's `.env` does nothing.
- **Its own pytest suite.** `mcp_server/` is its own project; the engine's `testpaths = ["tests"]` does not reach it and the engine's mypy excludes it. Run `pytest` *and* `mypy .` from `engine/mcp_server/`.

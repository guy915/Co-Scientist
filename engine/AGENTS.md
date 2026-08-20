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
first production caller of the **workspace** tool surface -- `call_llm_with_tools`
itself has driven the literature tools on these tiers for some time. Gated three ways,
all of which must hold: the app asks by **tier** on `extended`/`ultra` only
(`opts._resolve_simulation_execution_toggle` -- a tool loop per hypothesis is
a cost that multiplies by pool size; measured below), the engine refuses it for the offline
backend (`run_setup._resolve_simulation_execution`), and the review itself
falls back to mental simulation where no sandbox backend can confine a
command. Measured cost, four mechanisms through the real path concurrently
(`deepseek-v4-flash`, 2026-08-20): **231s wall clock for all four**, against
824s if they had run one after another -- so the pool multiplies *tokens*,
not wall clock, as long as the review fan-out actually runs concurrently.
Three of the four finished in 6-8 turns and ~150s. The fourth exhausted the
14-turn ceiling and returned nothing, and that is the expensive outcome
rather than a cheap one: it spent 291k prompt tokens against the ~104k a
successful one spends, because every turn resends the whole transcript. Budget
~150k prompt tokens per hypothesis and assume roughly one in four pays double
for no observation.

Each review gets its **own** workspace
(`open_review_workspace(run_id, hypothesis_id)`) because review items fan out
as concurrent leased tasks. Whether it ran is stamped on the result by the
caller (`executed`), never asked of the model.

**The literature review can go back for what it did not answer.** Phases 1-5
search once, from the research goal, and synthesize what came back.
`src/co_scientist/research/` is a standalone capability that reads a result,
takes what it leaves open, and searches again -- a budgeted descent whose
breadth halves per level with a floor, so the whole cost is arithmetic before
the first call (`8 + 4 + 2` threads, never `8 x 4 x 2`). It imports nothing
else in this repo and states its needs as two protocols;
`src/co_scientist/research_adapter/` is the implementation of those for this
engine (MCP search and full text over the run's configured sources, the five
model judgements over `call_llm_json`, and the tier-to-ceilings tables), and
`literature_review/research_phase.py` is where Generation calls it. Assigning
the same loop to another agent is a budget and a seed-question policy, not a
second implementation -- which is exactly what Reflection is (below).

Seeded from the gaps Phase 3's per-paper analysis already recorded, so the
first level asks what the reading raised rather than what the goal suggests.
What it finds merges back into the review's own paper pool and its synthesis --
a finding that lived only in a ledger would be recorded and never used. Gated
the same three ways as the executed simulation: the app passes its tier
verbatim (`engine_adapter/opts.py`) and `research_adapter.budget` alone decides
which tiers buy it -- `extended` and `ultra` -- so the two sides cannot drift;
`run_setup._resolve_research_tier` refuses it where MCP is unavailable, since a
loop whose whole shape is search-read-search has nowhere to go; and a run with
no enabled search source researches nothing. Whether the literature review
*node* runs is deliberately not a gate -- the reviews below resolve the run's
sources from its tool registry themselves.
Unlike the tool loops, the offline backend is *not* a refusal -- these are
ordinary schema-constrained completions it answers deterministically, which is
what makes the whole path testable without a key.

Everything the phase did leaves the node in `research_ledgers` on the state
(plain data, because a checkpoint carries JSON only -- see
`research/serialization.py`), and each researched paper carries the id of the
search that surfaced it. The app writes both: `retrieval_calls` rows and the
`evidence.retrieval_call_id` that resolves to them, so a run can say which
query found a piece of evidence and which question that query was serving.
Note the channel is a *list* with an accumulating reducer
(`state_reducers.accumulate_research_ledgers`, mirrored in
`task_runtime._CHANNEL_REDUCERS` -- a reducer missing from that table falls
through to last-write-wins in silence on the durable path). Research has two
owners, and under a single-ledger channel whichever ran last was the only one
on record.

**The deep reviews go back too, and their cost is a product.** The full and
simulation reviews already retrieve once per hypothesis;
`reflection/research_evidence.py` gives them the same loop as a second round,
sharing one gathering between both modes (`reflection/review_evidence.py`).
The policy is what differs from Generation's, and it has to be: the literature
review researches once per *run*, a review once per *hypothesis*, so a
per-hypothesis budget alone bounds nothing. Both factors are capped in
`research_adapter/budget.py` -- what one hypothesis may buy
(`review_budget_for_tier`: 4 threads on extended, 5 on ultra) and how many
hypotheses buy anything (`reviewed_hypothesis_limit`: the 3 or 5 best of the
pool, ordered by the canonical `rank_by_elo` and selected from the whole pool
so the in-process node and a per-hypothesis durable task choose identically).
Note *which* half of that key decides: this node runs before ranking, so on the
first cycle -- where every hypothesis gets its one full review -- every Elo is
still the default and the tie breaks on the initial review's score, written by
the node immediately upstream. The product of the two caps is a per-run
ceiling of 12 threads on extended and 25 on ultra, and that quote depends on
the two review modes sharing one gathering per hypothesis: they are separate
leased tasks, and it is the run cohort executing them on one thread's loop
that lets the second reuse the first's in-flight retrieval. A lease lost
mid-task re-pays one gathering, as the probe round already did. Seeds are the
doubts this run already recorded about *this* claim: assumptions a previous
cycle's full review marked
uncertain or likely false, and its simulation's failure points. Research that
fails degrades to the probe round rather than failing the review, and the
ledger travels beside the review rather than inside it -- through the item
result and the fan-out aggregate -- so a provenance record does not ride into
every later checkpoint through `enrichments`.

**Deep verification is a third owner of that same gathering and costs
nothing extra.** It runs after ranking, after comprehensive reflection, on
the same cohort's loop and over largely the same leaders, so
`review_evidence.researched_articles_for` finds the gathering already in the
flight cache and merges those papers into its probe round
(`deep_verification._with_researched`). It deliberately *reads* and never
starts one: a gathering begun there would be a third per-hypothesis
retrieval multiplying by pool size and iteration, which is the exact shape
of the 299-call incident. A leader the reviews did not fund is verified
against its probes alone, as it always was. Its seeding needs no new policy
either -- research is seeded from assumptions a previous cycle marked
uncertain or likely false, and those assumptions are deep verification's own
output, so the loop it now reads from was already being pointed by it.

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

**A run that reaches no source now says so.** "Falls back to LLM-only" is four silent branches, not one: the graph routes around `literature_review` and `reflection` (`task_runtime`), `run_setup._resolve_research_tier` resolves to no research, and the deep reviews' probes and evolution's grounding each refuse themselves on `mcp_available`. All four are correct, and none of them is visible — the run publishes ideas, reviews and a tournament that look exactly like a healthy run's, with nothing saying they were never checked against a paper. `retrieval_degradation.py` turns that into a fact the run carries: set at setup and again if the server is lost mid-node, drained into the report payload, and carried on every node event after it so a watcher sees it live. Note what the floor actually is, because the plan for this work assumed a corpus floor that did not exist: the group's papers stopped being a literature search source when their whole catalogue began arriving in run context instead (`config/tools.yaml`), and `fetch_paper` is served by the same MCP server the gate just failed, so an outage took the corpus with it. `research_adapter/local_corpus.py` is that floor built for real — the same directory, searched from disk with SQLite FTS5 over `catalog.json` and read straight off the filesystem, so nothing about it touches the network. Two consequences. `_resolve_research_tier` no longer refuses research on `mcp_available` alone: with a corpus the loop has one source rather than none, so `deep_research` and `review_evidence` survive an outage and drop out of the reported `lost` list, while the four branches gated on the server itself stay lost. And the floor is reported as the strongest thing left — `group_corpus`, else `run_attachments`, else `none` — because a reader needs to know how far the run could still see. **The corpus is one lab's library, so the permission is not re-derived here**: `corpus_search_permitted` reads the `paper_corpus_fetch` tool's `enabled` flag, which is exactly the audience decision the app already made by withholding the corpus tools, and `run_setup._resolve_local_corpus_dir` pairs it with the directory the app passes. A second gate is one more thing to keep in step, and the one that gets forgotten is the one that leaks a library. Note the source is appended *last* and the loop admits a fixed number of documents per question across all sources, so on a healthy run the network sources usually fill the quota first and the corpus contributes nothing — deliberately, since one lab's library should not displace the public literature. Making it compete on a healthy run means guaranteeing it places the way the evidence budget's `reserved_slots` does for the same reason, which is a policy change to cost on its own.

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

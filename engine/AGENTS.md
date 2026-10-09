# Engine — `co-scientist-engine`

Read the [root AGENTS.md](../AGENTS.md) first. This package (`src/co_scientist/`,
Python 3.12+) holds the whole server. This guide covers the package map, the
research workflow, the LLM layer, retrieval, the sandbox and the reference MCP
server (`mcp_server/`). The HTTP API, durable task runtime and SQLite store are
in [app/AGENTS.md](../app/AGENTS.md), because `app/tests/` tests them. Paths
are relative to `src/co_scientist/`; under the LLM, Retrieval, Sandbox and MCP
server headings, a path not starting with a top-level package is relative to
that heading's package. `tests/` and `mcp_server/` are under `engine/`; paths
starting with `engine/`, `app/`, `evaluations/` or `vendor/`, and root files,
are from the repository root.

From `engine/` (the root `make` targets wrap these):

```bash
pip install -e '.[dev]'   # editable install with dev extras
pytest                    # tests/, four xdist workers by default
ruff format . && ruff check .   # 100 columns; also covers mcp_server/
mypy .                    # strict; excludes mcp_server/
```

## Package map

| Package | Holds |
|---|---|
| `serving.py`, `main.py`, `api/` | Production app factory, FastAPI app, lifespan, middleware, routers, wire contracts (app guide) |
| `orchestration/` | Node registry, topology and per-node execution (here); generator; durable executor `engine_tasks/`, worker `task_worker/`, queue `repository/`, drain (app guide) |
| `science/` | One package per agent, plus `safety_screen.py`, `prompts/` (templates in `prompts/templates/*.md`), `schemas/` (structured-output schemas), `scheduling/`, `research_model.py` |
| `domains/` | `research_state/` (models, `WorkflowState`, claims), `safety/`, `report/`, `chat/`, `documents/`, `access/`, `feedback/` |
| `platform/` | `llm/`, `retrieval/`, `sandbox/`, `db/`, `telemetry/` |
| `core/` | Config, constants, metrics, exceptions, run tiers; no I/O |

- Layers, highest first: serving, main, api, orchestration, science, domains
  (chat, report, safety, research_state, then documents, access and feedback),
  platform (retrieval, then llm, sandbox and db, then telemetry), core.
  `.importlinter` (`make arch`) also keeps the science agents
  independent of each other and confines `fastapi` to serving, main and api,
  `litellm` to `platform.llm`, `httpx` to `platform.llm` and
  `platform.retrieval`, and `sqlite3` to the store, domains and orchestration.
  There are no ignored imports and `evaluations/tests/test_import_contracts.py`
  holds that at zero, so fix a crossing import in the structure: move code down,
  invert the dependency or pass it in.
- Inside `platform/llm`, `tests/test_agents.py` enforces the `_LAYERS` order
  and no import cycles; add a new top-level module there. A new public name
  goes in `__all__`, `_EXPORTS` and the `TYPE_CHECKING` imports of
  `platform/llm/__init__.py`.
- Never name a package directory `cache`, `reports`, `build` or `dist`:
  `.gitignore` and `.dockerignore` drop it without an error
  ([ADR-001](../docs/adr/001-module-map.md)).
- A package's `__init__.py` holds its public names; import siblings by full
  path. Private helpers are tested from their defining modules; re-exports are
  not a supported boundary.

## Research workflow

`orchestration/generator/core.py::HypothesisGenerator` prepares capabilities,
the tool registry and initial state (`prepare_task_state`) for durable tasks.
`orchestration/registry.py` maps node keys to agents (`NODE_REGISTRY`,
`NODE_TO_AGENT`). `orchestration/task_runtime.py::execute_task_node` runs one
node and commits its update; `next_task_type` follows committed state, stops on
`safety_blocked` and returns `None` at termination. Each node's successor
(fixed, literature-gated or state-resolved) is declared once in
`orchestration/workflow_topology.py::WORKFLOW_ROUTES`; `plan_portfolio` and
`FANNING_NODES` in `task_runtime.py` add durable scheduling on top.

| Node key | File |
|---|---|
| `supervisor`, `orchestrator` | `science/supervisor/supervisor.py`, `orchestrator.py` |
| `literature_review` (MCP-gated) | `science/generation/literature_review/` |
| `generate` | `science/generation/generate.py` (+ `operations.py`, `debate.py`, `literature_tools/`) |
| `review`, `reflection` | `science/reflection/review.py`, `reflection.py` |
| `comprehensive_reflection` | `science/reflection/comprehensive_reflection.py` |
| `deep_verification` | `science/reflection/deep_verification.py` |
| `ranking` | `science/ranking/` (Elo tournament: `ranking.py`, `ranking_debate.py`, `ranking_matchmaking.py`) |
| `evolve` | `science/evolution/evolve.py` (prompt in `evolve_prompt.py`) |
| `proximity` | `science/proximity/proximity.py` |
| `meta_review`, `research_overview` | `science/meta_review/meta_review.py`, `research_overview.py` |
| `safety_screen` | `science/safety_screen.py` |

- Node keys persist in task types (`engine.node.<key>`), checkpoints and
  idempotency keys; never rename one without a migration.
- Shared state is `WorkflowState` (`domains/research_state/state/__init__.py`).
  The durable path reads each channel's reducer from its annotation
  (`task_runtime.channel_reducers`), so a list channel written by several nodes
  (such as `research_ledgers`) needs an accumulating reducer, not
  last-write-wins.
- Generation, Ranking, Reflection and Evolution export the operations durable
  tasks call (for example `prepare_generation`, `finalize_generation`,
  `EvolutionContext`); keep callers on those exports. Generation finalization
  may call enrichment tools, so run it outside store transactions.

### Cost rules

Run size comes from the tier (`core/run_modes/__init__.py::RUN_TIER_DEFAULTS`).
These rules keep cost bounded; a change that breaks one multiplies spend.

- Only `extended` and `ultra` buy the expensive capabilities.
  `orchestration/engine_adapter/opts.py::_apply_capability_opts` turns on
  tool-calling drafting, executed simulation review and overview review for
  them (`app/tests/test_engine_configuration.py`) and passes the tier on; deep
  research is funded only by the extended and ultra tables in
  `platform/retrieval/research_adapter/`.
- Depth goes to finalists only (`science/scheduling/funnel.py`). Every idea gets
  the safety screen, one screening review and the tournament. Full, observation
  and simulation reviews, deep verification and claim checks run only for the
  top 3/5/6/8 ideas by Elo, once each. Terminal depth never follows a budget,
  clock, task-count or safety stop, or passes the call ceiling
  (`tests/test_funnel.py`).
- Per-hypothesis work multiplies by pool size and iterations. Review research is
  capped per hypothesis (`platform/retrieval/research_adapter`:
  `review_budget_for_tier`, 4 threads on extended and 5 on ultra) and per cycle
  (`reviewed_hypothesis_limit`, 5 and 8 hypotheses). Deep verification only
  reads a completed shared gathering (`review_evidence.researched_articles_for`)
  and never starts one. Check every caller's multiplicity before adding a
  per-item LLM pass to a shared helper.
- `max_llm_calls` is a runaway cap, not an allowance, and it also gates
  features ([OPERATIONS](../docs/OPERATIONS.md)).

## LLM layer (`platform/llm/`)

- **Bounds.** Every completion has `COSCIENTIST_LLM_TIMEOUT_SECONDS` (default
  600, `0` disables; read in `request/completion.py`) passed to the provider
  and re-imposed with 30 s grace as an `asyncio.wait_for` in
  `request/transport.py`, raising `LLMTimeoutError`.
- **One dispatch path.** Engine and app calls share
  `request/transport.py::complete_request`. `request/backend.py` holds the
  installed `CompletionBackend` (`active_backend`, `install_backend`,
  `using_backend`): `LitellmBackend` by default (SDK retries off; Azure
  deployments go to `request/azure.py`), `offline/llm.py::OfflineRouter` under
  the test double, or a test fake (`tests/_llm_fake.py`: `install_fake_llm`,
  `patch_acompletion`). The registry is a module global, not a `ContextVar`, and
  holds no asyncio primitive. Tests install a fake backend and never patch
  litellm; fakes skip operator routing, so routing tests wrap `LitellmBackend`
  (`app/tests/test_provider_order.py`).
- **One retry loop.** `attempts/retry.py::run_attempts` serves `call_llm` (3
  attempts walking `attempts/escalation.py::BudgetEscalation`: as asked, raised
  budget, thinking off; a fourth rung answers reasoning-cap refusals),
  `call_llm_json` (5; parse and schema judge in `attempts/json_attempt.py`) and
  tool turns (3 physical attempts, never spanning tool execution). It owns the
  never-retried set (`LLMTimeoutError`, `LLMCallBudgetExceededError`,
  `ContextWindowExceededError`), rate-limit parking (`LLMRateLimitParkError`),
  jittered backoff and retry telemetry. Supply an attempt and a judge; never add
  a second loop (`tests/test_llm_attempt_loop.py`).
- **Model facts.** Each route is one `ModelProfile` in
  `profile/__init__.py` (`FAMILIES`, then exact `ROUTES`): reasoning controls,
  response formats, temperature floor, gateway pin and fallbacks, price. It is
  the only place a price is stated (`MODEL_PRICING` is derived;
  `tests/test_model_profile.py` pins the invariants). Add or retire a model
  there, not with a name check at a call site. `request/thinking.py` applies
  routing policy (price ceiling, upstream order, at most 3 fallbacks); role
  effort is in `roles.py` (override with `LLM_EFFORT_<ROLE>`). Never append paid
  fallbacks under a free route.
- **Defaults and routing.** `core/config.py::DEFAULT_MODEL` is a zero-priced
  OpenRouter route with free fallbacks for worker, supervisor, chat and semantic
  safety. Operator-funded Express runs try free OpenRouter, then Anthropic
  Haiku within its monthly credit, then Azure within the euro budget, then fail
  with "No model is available right now" (`routing.py`, `admission/`,
  [docs/azure-setup.md](../docs/azure-setup.md)). BYOK runs skip operator
  routing. `COSCIENTIST_REQUIRE_FREE_MODELS` allows free routes only;
  `LLM_ENABLED=false` stops dispatch.
- `process_mode.py` answers "offline?" and "credential available?"; only
  `COSCIENTIST_TEST_DOUBLE=deterministic` selects the deterministic mode.

## Retrieval (`platform/retrieval/`)

- `mcp_client/` talks to the MCP server (langchain-mcp-adapters), sends
  `X-MCP-Shared-Secret`, and bounds each tool call by
  `COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS` (default 300). The literature review
  gates on server reachability (`check_mcp_available`), not one source's health.
  Without MCP the literature and reflection paths run LLM-only, and
  `degradation.py` records that floor on the run and every later event, so a
  run that reached no source says so.
- The tool registry is `config/tools.yaml` with `config/registry.py`. A tool
  missing from `tools.yaml` is unreachable even if the MCP server registers it.
  Per-run disabling (`GeneratorOptions(disable_tools=...)`, built in
  `orchestration/engine_adapter/opts.py`) is reconciled once in
  `registry._apply_disabled_tools`, which also disables every search source
  backed by that tool. The search pipeline trusts `SearchSourceConfig.enabled`,
  so new gating belongs in the registry, not at a call site. A tool's
  `parameter_mapping` is written in its caller's vocabulary (OPERATIONS).
- Default literature sources are PubMed full text, OpenAlex, Europe PMC, web
  search, arXiv and bioRxiv; web results carry `source: "web"` and web search is
  absent from validation and reflection. Entity-keyed lookups (ChEMBL, UniProt,
  STRING, Reactome, Open Targets, Ensembl, gnomAD, ClinicalTrials) serve
  literature enrichment and reflection, not literature search.
- `evidence/search_fusion.py::select_within_budget` fills the evidence budget
  best-first, drops retracted papers, and honours `reserved_slots` for sources
  that score low by construction.
- `research/` is a standalone, budgeted search-read-search loop. It imports
  nothing else from the repo (`tests/test_research_loop.py`) and states its
  needs as two protocols, implemented by `research_adapter/` (tier budgets, MCP
  retrieval) and `science/research_model.py` (model judgements). The literature
  review, generation expansion and comprehensive reflection each append to
  `research_ledgers`.

## Sandbox and skills (`platform/sandbox/`)

- Every command a node runs is confined (Linux: Landlock, seccomp, cgroups;
  macOS: Seatbelt). Where no backend can confine a command, execution tools are
  withheld and the review reasons instead. Workspaces, skill scripts included,
  have no network (`network_allowed=False`; `tests/test_generated_program_egress.py`),
  although the `read_skill` preamble still claims otherwise. Script
  execution also needs the cgroup boundary described in
  [DEPLOYMENT](../docs/DEPLOYMENT.md).
- `workspace/run_workspace.py` opens a workspace per run, per review
  (`open_review_workspace`, since reviews fan out concurrently) and per drafting
  pass. Long commands hand back a session id to poll (`workspace/tools.py`).
- `science/reflection/simulation_execution.py` lets the simulation review run
  its model in a workspace with a bounded tool loop (`MAX_SIMULATION_TURNS`,
  `SIMULATION_TOKEN_BUDGET`, both measured) before the usual schema-constrained
  review. It is refused for the offline backend
  (`run_setup._resolve_simulation_execution`).
- Tool loops re-send their whole transcript each turn, so
  `platform/llm/tools/transcript.py` elides superseded writes, then aged
  evidence, then repeated papers; the order is pinned by
  `tests/test_llm_tool_loop.py`. Reaching a ceiling buys one closing turn
  without tools (`platform/llm/tools/loop.py::_harvest_partial_answer`).
- Science skills: `platform/sandbox/skills/` reads `vendor/science-skills/`
  only when `COSCIENTIST_SKILLS_DIR` is set (the API image sets it) and runs
  scripts with the prebuilt `COSCIENTIST_SKILLS_PYTHON`, because uv cannot run
  inside the sandbox. Skills are enabled per consumer: only the drafting pass
  (`science/generation/literature_tools/draft.py`) gets them, through
  `workspace/run_workspace.py::open_draft_workspace`, since the simulation
  review measured worse with them. The catalogue withholds
  skills whose script or dependencies are missing. Credentials reach only a
  recognized vendored script, and `read_skill` paths stay inside the skill
  (`tests/test_skills_catalog.py`). Skills used are recorded in
  `ExecutionMetrics.skills_used` and named in the report, which carries their
  licence attribution.

## Reference MCP server (`mcp_server/`)

- A separate project (Python 3.12, `.venv-mcp`). The package maps to the
  directory, so run `uvicorn mcp_server.server:app` and its pytest from
  `engine/`. `make test-mcp` runs `pytest mcp_server/tests` from `engine/` and
  strict `mypy .` from `engine/mcp_server/`. `make dev-mcp` serves port 8888 with
  local unauthenticated access; production binds `::` on 8888 (`Dockerfile.mcp`).
- Every route except `GET /` needs `X-MCP-Shared-Secret` equal to
  `COSCIENTIST_MCP_SHARED_SECRET`, the same value the API holds. With no secret,
  only loopback callers with `COSCIENTIST_MCP_ALLOW_UNAUTHENTICATED_LOCAL=1`
  pass. A healthy `GET /` with every tool call refused means a missing or
  mismatched secret.
- `_MCP_TOOLS` in `server.py` is the single source for registration and the
  `GET /` manifest. Adding a tool takes two edits: register it there and declare
  it in `platform/retrieval/config/tools.yaml` with a matching
  `mcp_tool_name` (and in `draft_generation` if the drafting model calls it).
  No test ties the two lists together.
- Families: literature (PubMed, OpenAlex, OpenCitations, Europe PMC and its
  preprint searches, arXiv, bioRxiv); open web (`read_url` always; `search_web`
  and `check_web_search_available` only when `BRAVE_API_KEY` or
  `TAVILY_API_KEY` resolves); biomedical lookups (ChEMBL, UniProt, STRING,
  Reactome, Open Targets, Ensembl, gnomAD, GWAS Catalog, ClinicalTrials).
  `GET /` lists the live tools.
- Searches return `{"status": "ok" | "failed", "records": [...]}` with a short
  `error` (`tools/_results.py`) and never raise; a failed source is unknown for
  novelty and named in the report. A wrapper must copy `__signature__`, because
  FastMCP builds the advertised schema from it
  (`tool_logging.with_call_logging`). Logs carry counts, never queries, URLs or
  provider error text.
- A provider that refuses its key (401, 402, 403, 432 or 433, never 429) is
  recorded and reported by `check_web_search_available`, which the API's
  `/status` asks. Within a call, a refused provider falls through to the next
  configured one; an empty result is an answer and does not fall through.
- `read_url` fetches model-chosen URLs: `safe_http` resolves the host and
  rejects non-global addresses, metadata hosts, embedded credentials and
  invalid ports, re-screens every hop (at most 5 requests), pins the validated
  IP, and caps size and time. The
  server sits on the private network beside the API, so weakening this is SSRF.
  Page content is untrusted data, never instructions.
- Its environment is `engine/mcp_server/.env` (template beside it); the API's
  `.env` does not reach it. Startup deletes everything under
  `<COSCIENTIST_LIT_REVIEW_DIR>/pubmed/` except the shared public-paper cache,
  so never point that variable at other data. `DISABLE_SSL_VERIFY` is refused.

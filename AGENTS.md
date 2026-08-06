# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Repository Layout

This is a research/reference workspace organized around replicating Google's AI Co-Scientist.

- `app/` — FastAPI + React workbench viewer
- `engine/` — LangGraph-based multi-agent hypothesis-generation engine
- `corpus/` — sanitized full text of the research group's own papers (`sbi_ucd/`, one markdown file per paper plus `catalog.json`), committed in full so retrieval works from a clean checkout. Audience-gated: only `sbi_ucd` runs can see it. Env `SBI_CORPUS_DIR`, default `corpus/sbi_ucd`.
- `evaluations/` — offline evaluation harness (`parity_check.py`, `citation_eval.py`, `safety_eval.py`, `scaling_eval.py`, `release_gate.py`, `smoke.py`, plus `datasets/`, `results/`, `tests/` and its own `pyproject.toml`; see `evaluations/README.md`)
- `e2e/` — Playwright browser end-to-end suite (`tests/*.spec.ts`, `support/` fixtures)
- `references/` — folder containing research, product screenshots, and design specs
  - `core/google-co-scientist/` — long-form architecture/spec markdown analyzing the original system (incl. `media/` UX captures and `research/` papers)
  - `peripheral/` — secondary reference projects (`antigravity-science-skills/`, `coding-agent-harness/`, `ai-chatbot-interface/`, `deep-research-agent/`)
  - `ui-ux/` — UX captures and product references (`gemini/`, `gemini-enterprise/`, `idea-generator/`, `notebooklm/`, `legacy-workbench-ui/`)
- `docs/` — live project docs; `docs/README.md` indexes them (`ARCHITECTURE.md`, `CI.md`, `EXPLAINER.md`, `FIDELITY.md`, `PARITY.md`, `PARITY-VERIFICATION.md`, `RUNNING-LOCALLY.md`, `UI-FIDELITY.md`), plus `decisions/` (dated ADRs) and `assets/` (screenshots + SVG diagrams)
- `.github/` — GitHub Actions. `ci.yml` runs as presubmit (on `pull_request`, with `dorny/paths-filter` job-level path filters, superseded runs cancelled) and as postsubmit (on push to `main`: every job, never cancelled); `nightly.yml` re-runs the whole pipeline on cron via `workflow_call`. Every CI command is hermetic — no network, no API keys, no retries — so a test needing a provider key must be skipped or offline. Rationale in `docs/CI.md`.
- `.remember/` — session handoff notes (`remember.md` is the live handoff file; also `now.md`, `recent.md`, daily logs, `logs/`, `tmp/`)
- `Makefile` — root-level build orchestration (`setup`, `start`, `dev-api`, `dev-ui`, `dev-mcp`, `test`, `test-app`, `test-engine`, `test-mcp`, `test-all`, `e2e`, `parity`, `eval-smoke`, `lint`, `typecheck`, `build`, `clean`, `stop`, `reset-db`)
- `CLAUDE.md` — symlink to this file
- `README.md` — project overview, features, installation, and usage

**Root Makefile targets**: `setup`, `start`, `stop`, `dev-api`, `dev-ui`, `dev-mcp`, `dev-all`, `test`, `test-app`, `test-engine`, `test-mcp`, `test-all`, `e2e`, `parity`, `eval-smoke`, `lint`, `typecheck`, `build`, `clean`, `reset-db`. **`make start` is the single entry point** — installs missing deps, frees ports 8008/5173/8888, runs MCP + API + UI together, opens the browser. There is no `make dev`. Note the asymmetries: `make test-all` is engine + app + mcp_server pytest **plus the `parity` gate**, so editing `docs/PARITY.md` or deleting a test it cites fails the suite; `make lint` also covers `evaluations/`; `make typecheck` covers `app/`, the engine, and `evaluations/` (the mcp_server's strict mypy runs inside `make test-mcp` instead, from the dedicated 3.12 venv at `.venv-mcp`).

`make e2e` installs its own deps and Chromium, then launches an isolated stack (FastAPI on 8108, Vite on 5273 — deliberately off the `make start` ports) against a fresh per-invocation SQLite store, headless and pinned to the deterministic offline backend, so it needs no API key. Requires `make setup` first.

`docs/PARITY.md` is machine-checked: a `verified` row must cite at least one backticked test/eval reference that resolves on disk, and a literal `|` inside a cell breaks the column count.

Each project is also independently installable and runnable.

## engine (Python library)

LangGraph-based multi-agent hypothesis-generation framework. Package name: `co-scientist-engine`. Source under `src/co_scientist/`.

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

`HypothesisGenerator` (`src/co_scientist/generator/`) is the public entry point. It compiles a LangGraph `StateGraph` whose nodes are implemented in the six agent packages under `src/co_scientist/agents/` (Generation, Reflection, Ranking, Evolution, Proximity, Meta-review, plus Supervisor and a cross-cutting Safety screen). The old `src/co_scientist/nodes/` shim layer has been removed — import node callables from `co_scientist.agents.*`. The graph still registers each node under its original key string (so durable-run resume is unaffected), and `co_scientist.agents.NODE_TO_AGENT` is the source-of-truth node→agent mapping:

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

Shared state flows through `WorkflowState` in `state.py`; note the custom `deduplicate_hypotheses` reducer that auto-dedupes on every state update. Prompts are markdown files in `src/co_scientist/prompts/templates/` (also bundled via `package-data`), loaded by the `prompts/` package. YAML tool/domain configs live in `src/co_scientist/config/` with examples per domain (biomed/cyber/web-research/etc.).

Key supporting modules: `models.py` (dataclasses: `Hypothesis`, `HypothesisReview`, `ExecutionMetrics`, `Article`), `schemas/` (JSON-schema package for structured LLM output — one module per prompt family plus `registry.py`), `constants.py` (Elo params, token limits, temperatures), `exceptions.py` (domain exception hierarchy), `progress.py` (shared progress-event emission used by all agent nodes), `tools/` (tool registry subpackage for YAML-based tool configuration).

**LLM dispatch and bounds.** Calls go through LiteLLM (`llm.py`). Every completion is bounded twice: `llm_request.llm_timeout_seconds()` (env `COSCIENTIST_LLM_TIMEOUT_SECONDS`, default 600s, `0` disables) is passed to litellm *and* re-imposed as a hard `asyncio.wait_for` ceiling in `llm._acompletion_within_timeout` (+30s grace), raising `LLMTimeoutError`. `call_llm_json` retries up to `max_attempts` (default 5) but treats failure kinds differently in `llm_json_retry.py`: a schema failure retries immediately with validation feedback appended to the prompt, a throttled call backs off a **jittered** exponential (unjittered releases every throttled caller at once and reproduces the burst), and `LLMTimeoutError` is never retried — a stalled provider will not answer the same request faster.

**MCP and the web.** Literature-review tools are pulled from an external MCP server via `mcp_client.py` using `langchain-mcp-adapters`, bounded independently by `COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS` (default 300s). The graph auto-detects MCP availability — without a server, the literature/reflection nodes fall back to LLM-only mode. The literature-review pre-flight gate checks **server** reachability (`check_mcp_available`), not any single source's health: gating on one source let an unreachable remote service veto sources that were fine, including the always-available local corpus. For conditionally-registered tools, ask `mcp_client.check_tool_available(tool_name)`.

The engine can also search and read the open web. `web_search` (MCP `search_web`) is a default `literature_review` search source alongside PubMed/OpenAlex, weighted lower (`papers_per_query: 2` against their 4) with `read_url` as its content tool; its results carry `source: "web"` so web evidence stays distinguishable downstream. It is deliberately absent from `validation` and `reflection`, which are direct-call paths. The agentic path — the model deciding when to search and what to open — lives in `draft_generation` and is active only when a caller passes `enable_tool_calling_generation=True` (library-only; the app exposes no toggle). See `engine/docs/WEB_SEARCH.md`.

**Per-run tool disabling is reconciled once, at registry load.** Connector toggles reach the engine as `HypothesisGenerator(disable_tools=[...])` (built in `app/app/engine_adapter/opts.py`), which `generator/run_setup.py` passes on as `ToolRegistry(disabled_tools=...)`. `registry._apply_disabled_tools` flips `enabled = False` on the tool *and* on every workflow `search_source` backed by it, covering every way a tool can be off — the `disabled_tools` argument, a YAML `enabled: false`, or a source naming a tool that does not exist. That one pass is load-bearing: the multi-source pipeline selects on `SearchSourceConfig.enabled` alone and never consults the tool's own flag, so a source left enabled over a dead tool keeps being searched. The Phase 2 searches in `literature_review/search.py` therefore trust `workflow.get_enabled_search_sources()` and deliberately do not re-check the registry — a second filter there was removed once the registry covered every case, so new gating belongs at the registry, not at the call site. `engine/tests/test_config_registry.py` pins the reconciliation.

**Evidence budget and `reserved_slots`.** Multi-source search fills its budget through `literature_review/search_support.py::select_within_budget`, not by truncating the ranked list. Retrieval score rewards source quality, citation count, and recency — axes a local corpus can lack entirely rather than score poorly on, so it sorts below every indexed paper however well it matches. Such a source claims guaranteed places via `reserved_slots` in its `SearchSourceConfig`; reserved places are filled best-first within the source, never padded, never over budget.

Caching (`cache.py`) is on by default and controlled by `COSCIENTIST_CACHE_ENABLED` / `COSCIENTIST_CACHE_DIR` env vars.

Engine-specific docs live in `engine/docs/` (`ARCHITECTURE.md`, `CONFIGURATION.md`, `DEVELOPMENT.md`, `DOMAIN_CUSTOMIZATION.md`, `GENERATION_MODES.md`, `LITERATURE_REVIEW_TOOLS_CONFIGURATION.md`, `LOGGING.md`, `MCP_INTEGRATION.md`, `WEB_SEARCH.md`).

**Reference MCP server** lives in `mcp_server/` as a separately installable package. Install with `pip install -e mcp_server/` and run with `uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888`. **Requires Python 3.12** (engine itself is 3.10+) — install into a 3.12 venv or you'll hit cryptic solver errors. Registered tool families (see `mcp_server/server.py`): PubMed search + full-text retrieval, OpenAlex search, ChEMBL/UniProt lookups, SBI paper-corpus fetch, INDRA CoGex queries, and web search/fetch.

**Style conventions** (from `CONTRIBUTING.md`, enforced informally):
- Code follows the Google Python Style Guide: ruff (formatter + linter, 80 columns, config in `pyproject.toml`), Google-format docstrings (`Args:`/`Returns:`/`Raises:`).
- Docstrings capitalized, full sentences.
- `logger.debug()` lowercase; `info`/`warning`/`error` capitalized.
- No emojis or unicode decoration in code or logs.
- Rich library only in `examples/` and `dev/`, never in core library code.

### Reference MCP server (`engine/mcp_server/`)

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
- **Its own env surface**, in `engine/mcp_server/.env.example`, loaded from a `.env` co-located in `mcp_server/` (not the engine's; a missing file only warns): `ENTREZ_EMAIL`/`ENTREZ_API_KEY`, `DISABLE_SSL_VERIFY`, `COSCIENTIST_LIT_REVIEW_DIR`, `COSCIENTIST_MCP_PORT`, `COSCIENTIST_MCP_LOG_LEVEL`, `WEB_SEARCH_PROVIDER`/`BRAVE_API_KEY`/`TAVILY_API_KEY`, `INDRA_COGEX_URL`/`INDRA_COGEX_TIMEOUT`, plus `SBI_CORPUS_DIR` (read by the corpus tool but omitted from the example file). Setting these in the app's `.env` does nothing.
- **Its own pytest suite.** `mcp_server/` is its own project; the engine's `testpaths = ["tests"]` does not reach it and the engine's mypy excludes it. Run `pytest` *and* `mypy .` from `engine/mcp_server/`.

## app (FastAPI + React viewer)

Web UI and HTTP/SSE API that wraps the `co-scientist-engine` for live hypothesis-generation runs.

### Backend (`app/`)

FastAPI app with settings in `app/config.py` (pydantic-settings, loads `.env`). Package name: `co-scientist-viewer`.

**Commands** (run from `app/`):
```bash
make install         # pip install -e ".[dev]"   (also: pixi install)
make dev             # uvicorn app.main:app --reload --reload-dir app, port 8008
make start           # same, without --reload
make test            # pytest (asyncio_mode = "auto", testpaths = ["tests"])
make format / lint / typecheck   # ruff format / ruff check / mypy
```

Use `make start` whenever a run may be in flight: `--reload` restarts the process on any edit under `app/`, dropping the embedded worker cohort mid-task and leaving the run to startup reconciliation. Tasks are mirrored under `[tool.pixi.tasks]` — `pixi run dev` etc. work identically.

**Source modules** (`app/app/`) — the ones worth knowing; the package holds ~45:

| Module | Purpose |
|---|---|
| `main.py` | App setup, lifespan, ownership middleware; the diagnostics endpoints (`/health`, `/config`, `/status`) live in `diagnostics_api.py`, re-exported from `app.main` |
| `config.py` | Pydantic settings (model names, API keys, cache dir, Elo tuning, safety mode, worker/concurrency caps, auth). The DB path is *not* here — `COSCIENTIST_DB_PATH` is read directly in `store/db.py` |
| `runs.py` | Durable run-lifecycle router (`/api/runs` endpoint group); sibling routers `runs_lifecycle.py` (start/cancel/pause/resume), `runs_collections.py` (read-only getters + report), `runs_contrib.py` (scientist input + attachments), and `runs_support.py` (shared guards) are included into `runs.router`, every name re-exported from `app.runs` |
| `runs_models.py` / `runs_events.py` | Create-run request models, SSE replay/tail helpers (re-exported from `app.runs`) |
| `engine_tasks.py` | Node-level durable executor: run entry points (bootstrap/node/finalize) and the `execute_engine_task` dispatcher; siblings `engine_tasks_support.py` (task vocabulary + checkpoint plumbing), `engine_tasks_gate.py` (pre-ranking evidence gate), `engine_tasks_fanout.py` + `engine_tasks_fanout_aggregates.py`, `engine_tasks_ranking.py`, and `engine_tasks_inputs.py` (bootstrap enqueue + scientist-input merge) hold the rest, all re-exported from `app.engine_tasks` |
| `task_worker.py` | Lease/heartbeat worker loop, bounded per-run cohort, `python -m app.task_worker` |
| `store/` | SQLite persistence layer (WAL mode, append-only event log); `tasks.py` is the durable queue, `checkpoints.py` the resume points |
| `engine_adapter/` | Split by concern: `provider` (selection — always `"engine"` — plus `offline_mode` and the lazy engine import), `events` (node → canonical event/milestone), `opts` (run config/steering → engine opts, incl. `disable_tools`), `tools` (`TOOLS_CONFIG` resolution/validation), `drain` (final-state persistence), `checkpoints` (`is_engine_checkpoint`) — the legacy streaming loop (`engine_stream*`, `workflow.run_workflow`) was removed; the durable `engine_tasks` path is the only engine drive |
| `report_render.py` | Shared report payload/markdown builders and the `finalize_report` path (final safety gate + report/completed emission) |
| `auth.py` | Invite-based researcher auth: `/api/auth` router, `Principal`, `auth_required()` |
| `audience.py`, `content/sbi_ucd_context.md` | Audience enum (`general`/`google`/`sbi_ucd`) and its verbatim injected context |
| `paper_corpus.py` | SBI/UCD paper catalog access; offline corpus tooling (`corpus_ingest.py`, `build_catalog.py`, `harvest_group_pubmed.py`) lives in `app/dev/` |
| `interviews.py` | `/api/interviews` — durable, model-driven research-goal interview |
| `qa.py` | Grounded Q&A: offline answer + SSE streaming; evidence manifest and prompt assembly live in `qa_manifest.py`, re-exported from `app.qa` (`runs.py` owns HTTP) |
| `claims.py`, `claim_grounding.py`, `claim_verifier.py` | Atomic-claim extraction, per-claim entailment, publication gate → `claim_evidence` |
| `hypothesis_safety.py`, `hypothesis_screening.py` | Pre-tournament per-hypothesis screening writing `safety_status` |
| `human_input.py` | Scientist-authored hypotheses/reviews (`origin="scientist_manual"`), admitted through the same safety path |
| `document_ingest.py`, `run_corpus.py` | Attachment extraction + per-run keyword (BM25-style) retrieval |
| `documents.py` | `/api/documents` — pre-run document staging, owned by client id. An attachment made in the composer is uploaded here *before* any run exists, so the goal interview quotes it and `POST /api/runs` copies it into the new run's corpus as part of creating it |
| `shares.py` | Revocable public Goal Report share tokens |
| `feedback.py`, `notifications.py` | `POST /api/feedback` (write-only); SMTP completion notices as the `notification.email` task |
| `diagnostics.py` | `/health` checks and the cached MCP/PubMed/web-search probes behind `/status` |
| `elo.py`, `citations.py`, `safety.py`, `run_modes.py`, `seed.py` | Elo utilities; citation classification; intake/final screening; run tier/focus normalization; demo seeder |
| `logging_setup.py`, `logs_api.py` | Persistent log capture (root logger → `app_logs`) and the `/api/logs` filter/payload logic |

**Durable task execution — this is the real run path.** `POST /api/runs/{id}/start` does **not** run a workflow in-process. It enqueues `engine.bootstrap` (`task_worker.enqueue_run_workflow` → `engine_tasks.enqueue_bootstrap`) into the `scientific_tasks` table, and a worker cohort drains it; `POST /resume` re-enters the same queue keyed on the last checkpoint. In `engine_tasks.py` each graph node (`engine.node.<name>`), fan-out item (`engine.fanout.review.item`, `.verification.item`, `.generation.strategy`, `.reflection.item`, plus their `.aggregate` partners) and tournament match (`engine.ranking.match`) is its own leased, idempotent task checkpointing through `store/checkpoints.py`. `store/tasks.py` is the queue: leases with heartbeat renewal, `idempotency_key` dedup, retry budget, pause/resume/cancel by row. Losing a lease mid-task (`_LeaseLostError`) or being superseded by a newer checkpoint (`SupersededTaskError`) are normal outcomes that keep the retry budget. `COSCIENTIST_EMBEDDED_WORKER=1` (default) runs the cohort inside the API process; a separate worker service runs `python -m app.task_worker` with `COSCIENTIST_EMBEDDED_WORKER=0` on the API. The legacy `run.workflow` task type and its in-process handler were removed (a defensive filter in `store/tasks.py` still skips legacy persisted rows of that type); demo seeding (`seed.py`) also runs through the durable queue, so the durable path is the only way any run executes.

**No generator is held across requests.** The `lifespan` hook installs log capture and the offline LLM router, validates `tools_config`, prunes superseded checkpoints (`_reclaim_disk_space` — never VACUUMs, see Gotchas), reconciles runs left non-terminal by a previous process, and launches resume/recovery cohorts *off* the startup critical path. Each durable task builds its own `HypothesisGenerator` via `engine_adapter.opts._build_generator`.

**Run size comes from the tier, not the request body.** `run_modes.RUN_TIER_DEFAULTS` defines express/standard/extended/ultra, each scaling `initial_hypotheses_count`, `max_iterations`, `evolution_max_count`, `tournament_pairs`, `evidence_count`, and `max_llm_calls` (a runaway backstop, not a work allowance) together. Numeric overrides in the request body may only **raise** a tier baseline, never lower it. `focus` (`prefer_evidence`/`balance`/`prefer_novelty`/`breakthrough`) contributes prompt guidance instead, threaded through as `run_focus_guidance`.

**Auth and ownership.** `main.enforce_run_ownership` is an HTTP middleware over every `/api/*` path. Only `/api/auth/*` and `/api/shared/*` are public; everything else 401s when `auth_mode=required` and no principal resolves. A `/api/runs/{id}` request whose principal subject differs from the run's `client_id` gets **404, not 403** (demo-owned runs exempt) — so a "missing" run is usually an ownership mismatch, not deleted data. In `compatibility` mode (the default) the principal comes from the `X-Client-ID` header, so send a consistent one before concluding anything is gone. Settings: `auth_mode`, `auth_secret`, `researcher_access_codes` (JSON id→code), `auth_session_hours`.

**Audience and the paper corpus.** A run carries an `audience` (`general` | `google` | `sbi_ucd`). Only `sbi_ucd` has injected context: `app/app/content/sbi_ucd_context.md` is served **verbatim and in full** to every surface (planning, generation, reflection, evolution, meta-review, every tournament comparison, chat Q&A, the goal interview) — do not reintroduce a summarized variant; the module docstring records why that was removed. For that audience the corpus `catalog.json` (titles + abstracts) is injected wholesale rather than retrieved, and the model pulls whole papers with the MCP `fetch_paper` tool. Access is gated by `paper_corpus.disabled_tools_for()` feeding `disable_tools` in `engine_adapter/opts.py`, so no non-`sbi_ucd` run can reach another lab's papers (`enable_paper_corpus` defaults True and is a no-op for every other audience). Rebuilding is offline and two-step: `python -m app.corpus_ingest SOURCE_DIR --out corpus/sbi_ucd` sanitizes PDFs (needs `pdftotext` from poppler, which the deployed image lacks), then `app/dev/build_catalog.py` regenerates `catalog.json` — that script is also where a new paper gets added.

**Notable settings** beyond the obvious: `worker_pool_size` (default 8) bounds how many durable tasks one run executes concurrently — the ceiling is SQLite's single writer, not the provider (24 concurrent completions return in the same wall clock as 4), and at 12 across several runs the write lock saturated and ordinary API writes failed. `max_concurrent_runs` (default 10) caps in-flight runs *per client*, counted across every tier together; over it, start returns 409. (Counting each tier separately let one client hold a full allowance per tier, i.e. four times the advertised ceiling.) `claim_assessor` (`llm` default) picks the entailment assessor; offline tests pin `deterministic`. `semantic_safety_enabled`/`semantic_safety_model` add a contextual model assessment on top of the deterministic hard blocks — those run first and a `block` short-circuits. `smtp_*` plus `public_app_url` back the `notification.email` task. `status_probe_timeout_seconds`/`status_probe_cache_ttl_seconds` bound and cache the `/status` probes.

**Key endpoints**

Diagnostics (in `main.py`): `GET /health`, `/config`, `/status` — `/status` reports MCP/PubMed/web-search availability.

Run lifecycle (in `runs.py`, mounted at `/api/runs`) — **primary API used by the frontend**:
- `POST /api/runs` — create a draft run; `GET /api/runs` — list runs; `GET /api/runs/demo`.
- `GET /api/runs/{id}` — details; `POST /{id}/start`, `/cancel`, `/pause`, `/resume`. Pause marks the run's queued/leased `engine.*` tasks paused (404 if not active); resume requires a checkpoint or a paused engine task (409 otherwise).
- `GET /api/runs/{id}/events` — SSE stream (live + replay).
- `GET /api/runs/{id}/hypotheses` — hypotheses with Elo + lineage.
- `GET /api/runs/{id}/evidence`, `/reviews`, `/matches`, `/citations`, `/safety`, `/proximity`, `/metrics`, `/claim-evidence`.
- `GET /api/runs/{id}/report` (JSON) and `/report.md` (Markdown).
- `POST /api/runs/{id}/messages` — queue user steering message; `GET` to list. `POST /{id}/messages/ask` — Q&A with streaming LLM response (uses `chat_model_name`).
- `POST /api/runs/{id}/hypotheses` / `/reviews` — scientist-authored input; passes the same per-hypothesis safety screen, persists with `origin=scientist_manual`, enqueues a continuation task.
- `POST /api/runs/{id}/attachments`, `/attachments/upload`, `GET /attachments/search` — per-run private corpus (for a run that already exists; setup-time attachments go through `/api/documents` and ride in on `document_ids` at create).
- `POST /api/runs/{id}/safety/{decision_id}/adjudicate` — human adjudication of a safety decision.
- `POST|GET /api/runs/{id}/shares`, `DELETE /{id}/shares/{share_id}`, `GET /api/shared/{token}` — revocable public Goal Report links.

Elsewhere: `POST /api/interviews`, `GET /{iid}`, `POST /{iid}/turns`, `PUT /{iid}/fields` (the goal interview that feeds `interview_id` on run create); `POST /api/feedback`; `POST /api/auth/exchange`.

Additional routers mounted in `main.py`: `interviews`, `shares`, `feedback`, `auth`, and `logs` (see each module for its endpoint group).

**Persisted logs** (`logs_api.py` + `logging_setup.py` + `store/logs.py`) — one app-wide, durable log in the SQLite `app_logs` table:

- **Run stages**: every `run_events` row is mirrored into the log as a compact `app.run_stage` record (`store/events.py`), so a run's stage narrative — `lifecycle`, `safety.intake`, `supervisor.plan`, `literature_review`, `generate`, `reflection`, `proximity`, `ranking`, `evolve`, `meta_review`, `deep_verification`, `citation_audit`, `research_overview`, `report`, `status` — is readable from the Logs panel and `cosci logs --run <id>` rather than only over SSE. Payloads are summarized to `key=value` scalars and capped at 200 chars: ~21 stage records per run instead of full event bodies. Mirroring happens in the inner `_append_event`, so every event writer is covered, and it is best-effort — it can never fail an event write.
- **What is captured**: every record reaching the Python root logger (app modules, `co_scientist` engine, store/database) *except* the per-call dependency chatter that `logging_setup.UNPERSISTED_LOGGERS` refuses to persist below WARNING, *plus* uvicorn's non-propagating `uvicorn`/`uvicorn.access` loggers, *plus* frontend records POSTed by the UI (namespaced `ui.*`: session diagnostics, route navigation, uncaught JS errors, unhandled rejections, React render errors, and interactions as `ui.interaction` — via `lib/ui_logging.ts`). Access records for `/api/logs` itself are filtered out so polling cannot grow the log.
- **Hidden vs. never persisted — two different lists, both gated at WARNING.** The *read* path (`NOISE_LOGGERS` in `logs_api.py`) hides `uvicorn.access`, `ui.interaction`, and `ui.navigation` from the default view; those rows stay in the table and `verbose=1` / `cosci logs --all` shows them. The *capture* path (`UNPERSISTED_LOGGERS` in `logging_setup.py`: `httpx`, `httpcore`, `urllib3`, `litellm`, `openai`, `mcp.client`, `co_scientist.mcp_client`) **drops** sub-WARNING records before any row is written, so `--all` will never show per-LLM-call or per-HTTP-call lines — read those from stdout. WARNING+ always persists and always shows. The drop exists because each row is an open-write-close against the single SQLite writer; LiteLLM alone was 9,928 of 20,021 production rows, and that stream starved ordinary API writes until run creation failed with "database is locked". Stay on the default view; reach for `--all` only when debugging request- or interaction-level behavior.
- **How**: a `QueueHandler` (run-id stamped) feeds a background `QueueListener` that writes rows and prunes to a cap; writes never block or raise into the caller. Settings: `log_capture_enabled` / `log_capture_level` / `log_capture_max_rows`. DEBUG records are only captured when the root logger also emits them (set `COSCIENTIST_DEBUG=true` plus `log_capture_level=DEBUG`).
- **Repeat suppression**: capture persists the first of a record and drops verbatim repeats for `REPEAT_SUPPRESS_SECONDS` (10 min), keyed by exact `(logger, level, run id, message)` — so a different message from the same logger, or the same line from another run, still lands. This exists because the level filters exempt WARNING+, so any steady-state condition wrote a row per poll forever: the MCP availability probe warned twice per `/status` refresh, and inside a single run the tool registry logged two identical "initialized" lines per agent call (229 copies of each in one run). Those repeats were ~77% of the readable stream and, since the Logs panel shows a fixed newest-100 window, they crowded out the run narrative entirely and the log read as empty. Suppression is by *repetition*, not by logger name — do not fix a new flood by adding its logger to a deny-list.
- **Endpoints**: `GET /api/logs` (filters `after_id`/`limit`/`min_level`/`run_id`/`q`/`verbose`, plus a `last_id` polling cursor and a `total` matching-row count that ignores the window), `GET /api/runs/{id}/logs` (run-scoped view), `POST /api/logs` (client ingestion; batch ≤50, messages truncated to 2000 chars), `DELETE /api/logs` (clear all; ids restart at 1, and followers detect the reset by `last_id` dropping below their cursor — `cosci logs --follow` handles this automatically).
- **Access control**: the log carries other tenants' research goals and server internals, so reads and clears are scoped. Operators -- loopback callers (the local CLI/agents) or holders of `LOGS_ADMIN_TOKEN` via the `X-Logs-Token` header (`cosci logs --logs-token`, env `COSCIENTIST_LOGS_TOKEN`) -- get the app-wide view and a full clear. Every other caller sees only records it submitted plus records for runs it owns, and `DELETE` removes only those (leaving the shared id sequence alone). Un-owned server records are operator-only. Ingestion stays open because browsers must report their own errors, but records are stamped with the caller's client id, control characters are collapsed (a newline would otherwise forge lines in the CLI's tab-delimited output), and it is rate-limited per client (`LOGS_INGEST_PER_MINUTE`, 429 over the ceiling). Because scoping keys off caller identity, `src/api/logs.ts` must send `clientHeaders()` on every read *and* write: an unidentified caller matches nothing, so omitting them leaves the panel permanently empty wherever the browser does not reach the API over loopback (i.e. any real deployment) and stores submitted records ownerless.
- **Consumers**: `cosci logs` (`--run`/`--level`/`--grep`/`--follow`/`--clear`/`--all`) and the workbench Logs popover, which renders this single stream identically on every route (the newest 100 records, messages as plain text with the level in each entry's meta row; rows are renumbered consecutively by position in the filtered stream (store ids are global, so hidden noise would otherwise leave visible gaps like `#12, #13, #30`); the panel is scoped to the browsing session, whose baseline id lives in `sessionStorage` (`cosci-logs-session-baseline`) rather than module memory — a tab reload is the reflex for "did that just get logged?" and keeps the view, while closing the tab ends the session and starts clean; the badge and Total chip carry that stream size, which is also the newest row's number, and Copy still emits real store ids alongside the display number so it stays cross-referenceable with `cosci logs`; the level chips (`layout_diagnostics_chips.tsx`) split Python's numeric levels the way the rows print them — Errors is ERROR/CRITICAL (40+), Warnings is WARNING (30), Info everything below — and tally only the loaded window, so they stop summing to Total past 100 records. There is no Success band: the levels are Python's, and the old chip was structurally always 0), jumps to the newest record on open but never while the user is scrolled up reading, and whose Clear deletes server-side. Copy (`layout_diagnostics_export.ts`) writes a self-describing export — a preamble covering what the log is, what it deliberately omits, where and when the export was taken, the tallies, and a field legend, then the newest 100 entries as JSON under an `=== LOGS (JSON) ===` marker (the whole panel window, so an export is never a shorter story than the reader was looking at) — because a bare array pasted into an issue carries none of that; the "Copied" label expires after two seconds so the button never reads as stuck. The badge refreshes on a background poll plus a `cosci-app-logs-changed` window event fired by the api layer after every successful client POST/clear, so it stays current without opening the panel. The popover is **audience-gated** in `layout_header.tsx`: only the `general` audience (and an unchosen one) gets it — `google` sees a team note and `sbi_ucd` a feedback form in the same header slot, never both, so a missing Logs button usually means the `cosci-audience` localStorage key rather than a regression.

A single `HypothesisGenerator` instance is constructed in the `lifespan` startup hook and reused across requests. Per-run overrides (`max_iterations`, `initial_hypotheses_count`, `evolution_max_count`) come from the request body. Every run executes on the real engine (`engine_adapter.select_provider()` always returns `"engine"`; the engine is a hard runtime dependency). Keyless runs and runs with `COSCIENTIST_FORCE_OFFLINE=1` set are pinned instead to the engine's deterministic offline LLM backend (`co_scientist.offline_llm`), which intercepts `litellm.acompletion` for `offline/`-prefixed models rather than calling a real provider.

### CLI (`cosci`)

`app/app/cli/` ships an operator CLI — console script `cosci`, also runnable as `python -m app.cli` — that drives the running API over HTTP. It is the intended way for terminal-based agents to exercise the app without the UI.

Core loop:

```bash
cosci runs create "goal" --tier express --start   # create (+ start in one step)
cosci runs wait <id>                              # poll until settled; exit code = outcome
cosci runs report <id> --md                       # final report as Markdown
```

- **Commands**: `status`, `config`, `logs` (persisted backend logs: `--run`, `--level`, `--grep`, `--after-id`, `--limit`, `--follow`, `--interval`, `--clear`, `--all`); `runs list|demo|show|create|start|pause|resume|cancel|watch|wait|steer|ask|report` plus reads `hypotheses|evidence|reviews|citations|safety|matches|proximity|metrics|claim-evidence`.
- **Exit codes**: `runs wait` encodes the outcome — 0 completed, 3 failed, 4 blocked, 5 cancelled, 6 paused, 124 `--max-wait` exceeded; every command uses 130 for Ctrl-C and 141 for a broken pipe.
- **Global flags** (per subcommand): `--api-url` (env `COSCIENTIST_API_URL`), `--client-id` (env `COSCIENTIST_CLIENT_ID` — run listings are scoped by this header, so use a consistent id), `--logs-token` (env `COSCIENTIST_LOGS_TOKEN`), `--timeout` (env `COSCIENTIST_TIMEOUT`), `--json` (raw API payloads), `--verbose` (request log on stderr).
- Text arguments (`create` goal, `steer` message, `ask` question) accept `-` to read from stdin.
- GETs retry transient failures (connect errors, 502/503/504); POSTs never retry. `runs watch` auto-reconnects a dropped SSE stream from the last seen `seq`.

Tests live in `tests/test_cli_*.py`; `test_cli_commands.py` spins up a real offline-mode uvicorn server, so the whole suite runs offline.

### Frontend (`frontend/`)

React 19 + Vite 7 + TypeScript + Tailwind v4. Package manager is **Bun**. Linter/formatter is **gts** (Google TypeScript Style: ESLint + Prettier).

**Design system:** `frontend/DESIGN.md` is the authoritative design reference for all UI work. It follows the [google-labs-code/design.md](https://github.com/google-labs-code/design.md) spec: YAML design tokens in frontmatter, markdown rationale in body. Read it before making visual changes — it documents the color system, typography scale, spacing grid, radius rules, component inventory, and Do's & Don'ts. Key points:
- Palette is Material Design 3, generated at runtime from seed `#1A6B6B` via `applyMd3Theme()` in `src/lib/theme.ts`. Never hardcode `--md-sys-color-*` values.
- Two token bridges live in `src/index.css`'s `@theme` block: `--color-th-*` over the MD3 seed palette (data and status UI — run tones, error/success, primary actions) and `--color-cosci-*` over the `--cosci-*` Gemini product palette (shell, home, chat surfaces). `cosci-` is the larger layer; use the named utility, never an arbitrary `[var(--cosci-*)]` class.
- The palette and layout CSS itself lives in `src/styles/`, imported by `main.tsx` via `styles/surfaces.css` in a fixed order (`reference_surface` → `component_tokens` → `shell_surface*` → `home_surface*` → `tooltips` → `proposals*` — the shell/home/proposals sheets are split into sequential parts whose concatenated order matches the original cascade) so component tokens can alias palette tokens defined before them. Theme a new surface by adding a paired light/dark token in `component_tokens.css` — never an inline `dark:[#hex]` in a component.
- Three border-radius values only: `rounded-md` (8px) for data blocks, `rounded-xl` (12px) for interactive containers, `rounded-full` (9999px) for pills/buttons/chips.
- No `box-shadow` on cards or inputs — tonal layers only.

**Commands** (run from `app/frontend/`):
```bash
bun install
bun run dev          # vite dev server on :5173
bun run build        # tsc && vite build && node scripts/prerender.mjs
bun run lint         # gts lint
bun run fix          # gts fix (format + autofix)
bun run test         # vitest run (jsdom + React Testing Library)
```

Frontend tests are colocated `*.test.ts`/`*.test.tsx` files run by Vitest (config in `vite.config.ts`, setup in `src/test_setup.ts`); they are typechecked by `tsc` and linted by gts like any other source.

Vite reads `VITE_API_BASE_URL`; when it is unset the api client falls back to **same-origin relative paths** (`src/api/runs.ts`), and `vite.config.ts` proxies `/api`, `/status`, and `/health` to `http://localhost:8008` in dev — so localhost only works via that proxy, and a production build with the var unset calls its own origin. The live UI is the **workbench**: `src/main.tsx` mounts `BrowserRouter` + `src/workbench/workbench_app.tsx`. Theme state is in `src/workbench/theme_context.tsx` — no Redux/Zustand. Shared primitives: `src/components/error_boundary.tsx`, `src/components/icon.tsx`, and helpers under `src/lib/`. Styling: `src/index.css` (Tailwind layers, fonts, `--color-th-*` token bridge) plus the surface sheets under `src/styles/`, aggregated by `src/styles/surfaces.css`.

**Routing** (`workbench_app.tsx`): `/` (chat workspace — session home), `/runs/:id/:tab` (run detail; bare `/runs/:id` redirects to `details`, so switching tabs is a param change rather than a remount), `/proposals` (proposals graph), `/access` (researcher access-code exchange), `/shared/:token` (read-only public Goal Report), `*` (404). `/runs` and `/runs/new` redirect to `/`; `/recommendations` redirects to `/proposals`. Providers nest `ErrorBoundary > ThemeProvider > AudienceProvider > RunHistoryProvider > Layout > Routes`. Canonical run tabs and their legacy aliases live in `src/workbench/run_tabs.ts`; `normalizeTab()` is the single resolver. The old public surface (`/about` landing page, `/demos/:slug` public demos, `/runs` dashboard) was deliberately removed; `src/public/` now holds only residual helpers (`not_found_page.tsx`, `no_index.tsx`, `public_link_button.tsx`, `seo.tsx`).

**Audience modes** (`src/workbench/audience_context.tsx`): a self-declared, unverified audience — `general` | `google` | `sbi_ucd` — persisted in localStorage (`cosci-audience`), defaulting to `general`. `components/audience_gate.tsx` opens the Settings dialog on its Affiliation section on first visit (skipped on the public `/shared/` and `/access` routes) and commits the default if dismissed. The audience gates real behavior, not just copy: `layout_header.tsx` swaps exactly one header control (`layout_google_control.tsx` team note, `layout_pilot_control.tsx` feedback form, or `layout_diagnostics.tsx` Logs popover), `pages/chat_composer_connectors.tsx` shows the `paper_corpus` ("Lab papers") connector only to `sbi_ucd`, `pages/chat_home_stage.tsx` swaps home suggestions, and `api/runs.ts` forwards the audience on run creation, the goal interview, and run Q&A. Audience-facing wording lives in `audience_content.ts` (`AUDIENCE_OPTIONS`, `GOOGLE_NOTE`, `PILOT_FEEDBACK`, `FEEDBACK_CATEGORIES`, `SBI_SUGGESTIONS`) — edit copy there, not in the components.

**Run detail** (`src/workbench/pages/`): `run_detail.tsx` is a thin router — `run_detail_specifications.tsx` (details), `run_detail_learning.tsx`, `run_detail_overview.tsx`, and `components/tabs/ideas_tab.tsx` (+ `ideas_detail_pane.tsx` / `ideas_detail_data.ts`) render the four tabs, and `run_detail_active.tsx` replaces them while a run is in flight. Data fetching is `useRunDetailData` (`run_detail_data.ts`); titlebar, tab nav, skeleton, and toast live in `run_detail_shell.tsx`; the static views share document primitives from `run_detail_document.tsx`. The earlier `overview_tab.tsx`, `evidence_tab.tsx`, `tournament_tab.tsx`, `run_specifications_tab.tsx`, and `chat_tab.tsx` were retired under `references/ui-ux/legacy-workbench-ui/retired-orphan-tabs/`.

**Proposals graph** (`src/workbench/proposals/`, page `pages/proposals_page.tsx`, route `/proposals`, styles `src/styles/proposals.css`): a static relationship graph of proposed Co-Scientist improvements. `proposals_data.ts` is the single source of truth and holds **content only** — no coordinates, colors, or class names — so editing the argument is a pure content edit (types + `EDGE_KINDS` live in `proposals_types.ts`, the `edges` array in `proposals_edges.ts`, both re-exported from `proposals_data.ts`); geometry lives in `proposals_layout.ts` (`computeLayout`, pixel space) and presentation in `proposals_graph.tsx` / `proposals_legend.tsx` / `proposals_detail.tsx`. The selected node lives in the `?node=` query param so a proposal can be linked to.

**Workbench hooks** (`src/workbench/hooks/`): `use_chat_session.ts` is the chat workspace's session state machine — composer input, message log, and the draft → confirmed → started run-spec lifecycle. It is split across `chat_session_state.ts`, `chat_session_handlers.ts` (module-level handlers bound to a shared deps bag), `chat_session_start_run.ts`, `chat_session_helpers.ts`, and `chat_session_types.ts`; view concerns (history reload, composer focus, toasts) are injected so the hook stays testable headless. Also here: `run_history_context.tsx` + `use_run_history.ts` (run list fetched once, shared by the shell sidebar and home recents), `use_system_status.ts` (polls `/status`), `use_global_shortcuts.ts`, `use_toast.ts`, `use_is_mobile.ts`, `use_overflowing.ts`.

**HTTP clients** live under `src/api/`: `runs.ts` (run lifecycle, SSE, steering; fetch/auth primitives in `runs_http.ts`, interview calls in `runs_interviews.ts`, collection/report/share getters in `runs_collections.ts` — all re-exported from `runs.ts`, incl. `exchangeAccessCode`), `system.ts` (`/status`, incl. the composer's connector list), `logs.ts`, `feedback.ts` (categories `bug|suggestion|question|praise`, kept in lockstep with `FEEDBACK_CATEGORIES` in `app/feedback.py` and `audience_content.ts`). SSE/streaming also runs through `src/hooks/use_run_stream.ts`. `src/lib/client_id.ts` holds two identities with different lifetimes: a localStorage client id and a sessionStorage researcher token set by `pages/researcher_access.tsx`. `clientHeaders()` sends one or the other — `Authorization: Bearer <token>` when a researcher session exists, else `X-Client-ID` — so an authenticated tab is not scoped by client id, and the session dies with the tab.

### Docker workflow

`app/docker-compose.yml` runs three services: `api` (FastAPI), `ui` (Vite), `mcp` (reference MCP server). The api container expects a sibling engine checkout mounted at `/workspace/co-scientist-engine`; if absent, the entrypoint clones from `COSCIENTIST_ENGINE_REPO` at ref `COSCIENTIST_ENGINE_REF`. Override `COSCIENTIST_ENGINE_PATH` in `.env` if the engine checkout is elsewhere. The container hardcodes `TOOLS_CONFIG` to `indra_cancer.yaml` — change it there, not in `.env`, when iterating on tools.

Compose builds `api` from `app/docker/Dockerfile.api` + `app/docker/entrypoint.sh` — **a different file** from the repo-root `Dockerfile.api` that Railway builds, and the two diverge (compose installs the engine at startup from the mount; Railway bakes it into the image), so container changes usually need applying to both. Both `api` and `mcp` mount `../corpus:/app/corpus:ro` and set `SBI_CORPUS_DIR`: the corpus lives at the repo root, outside either service's build context, so compose mounts it where the Railway images `COPY` it in.

## Production hosting

The app is deployed as three services:

| Layer | Platform | URL |
|---|---|---|
| Frontend (Vite/React) | Vercel — project `co-scientist-ui` | Public: https://ai-co-scientist.com/; Vercel deployment: https://co-scientist-ui.vercel.app |
| API (FastAPI) | Railway — service `api` | https://api-production-97eb.up.railway.app (custom domain https://api.ai-co-scientist.com also live) |
| MCP server | Railway — service `mcp` | internal only (`mcp.railway.internal:8888`) |

**Railway project**: `co-scientist` (id `74f2b037-0094-49d2-b645-4849991234af`), environment `production`.

Both Railway services build from `guy915/Co-Scientist` using repo-root Dockerfiles (`Dockerfile.api`, `Dockerfile.mcp`). The api service has a persistent volume mounted at `/app/data` (the SQLite DB — **not** the cache; see below). Both images `COPY corpus/` and set `SBI_CORPUS_DIR=/app/corpus/sbi_ucd` — the COPY and the ENV must stay together, since the app-side repo-relative default does not survive the move into the image and the MCP corpus tool has no default at all. The api honors Railway's injected `PORT`; the **mcp image deliberately ignores it** and pins 8888, binding `--host ::` for Railway's IPv6 private network with a healthcheck against `[::1]:8888` (a 127.0.0.1 probe can miss the socket on IPv6-only kernels).

Env var *names* set on the Railway **api** service (values are secrets — read them from Railway, never commit them):

```
MODEL_NAME=deepseek/deepseek-v4-flash     # worker tier
SUPERVISOR_MODEL_NAME=deepseek/deepseek-v4-pro
CHAT_MODEL_NAME=deepseek/deepseek-v4-pro
SEMANTIC_SAFETY_MODEL=deepseek/deepseek-v4-flash
DEEPSEEK_API_KEY=<secret>
LOGS_ADMIN_TOKEN=<secret>
MCP_SERVER_URL=http://mcp.railway.internal:8888/mcp
COSCIENTIST_DB_PATH=/app/data/coscientist.db
COSCIENTIST_CACHE_DIR=/tmp/coscientist-cache   # deliberately OFF the volume
COSCIENTIST_EMBEDDED_WORKER=1
SBI_CORPUS_DIR=/app/corpus/sbi_ucd
ALLOWED_ORIGINS=https://ai-co-scientist.com,https://www.ai-co-scientist.com
PORT=8008
```

The **mcp** service carries `BRAVE_API_KEY` (which is what registers `search_web` at all), `ENTREZ_EMAIL`/`ENTREZ_API_KEY`, `COSCIENTIST_MCP_PORT=8888`, and `SBI_CORPUS_DIR`.

Production calls DeepSeek directly (`deepseek/` prefix), the same tiers the local defaults use, so there is one thinking contract everywhere: DeepSeek's native `thinking` object plus `reasoning_effort`. The DashScope route this deployment previously used is gone from config, env templates, and tests.

Vercel reads `VITE_API_BASE_URL=https://api-production-97eb.up.railway.app` (set in production environment).

## Gotchas

Each of these was a production outage or a silent data-correctness failure. The comments in the code record the incident; do not re-litigate them from first principles.

- **Never VACUUM from the serving process.** VACUUM and truncating WAL checkpoints need exclusive access, and a SQLite writer waiting for one blocks every writer queued behind it. This process can never grant that: the log-capture thread writes a row for every record the app emits, so the VACUUM waits for a quiet moment that never comes. The symptom is unmistakable and misleading — an idle database, no writes for minutes, every run creation failing with "database is locked" despite the 30s busy timeout. Production wedged this way from both sides of the lifespan. `_reclaim_disk_space()` in `app/app/main.py` therefore prunes superseded checkpoints and stops there; the file keeps its high-water mark, which is the accepted cost. `store.compact_database()` was **removed entirely** so nothing could reintroduce a serving-process VACUUM (`app/tests/test_main_diagnostics.py` documents the removal); offline compaction means running VACUUM by hand against a stopped database.
- **Never hold the SQLite write lock across network I/O, and never write on a poll tick.** There is one writer and no fair queuing, so a transaction spanning an LLM call freezes every other writer for its duration, and a per-tick write stream starves waiters indefinitely. Both look identical from outside: an idle-looking database while ordinary API writes exhaust their busy timeout. Hence the shape of the code — `claim_grounding.py` splits `assess_hypothesis_claims` (provider work, no DB) from `persist_grounding` (writes only) so `engine_adapter/drain.py` assesses *between* two transactions; `store/tasks.py::_has_claimable_task` probes read-only before `claim_task` opens `BEGIN IMMEDIATE`; and `task_worker.py`'s heartbeat wakes each second to check cancellation in memory but renews its 300s lease only on the lease's own schedule. When a lock symptom appears with an idle database, run `py-spy dump` first.
- **Startup work runs before uvicorn binds a port — keep it cheap and never fatal.** Two rules pull in opposite directions, both learned in production (`main.py` lifespan). Run recovery does not schedule interrupted runs, it *executes* them, so awaiting it put provider calls ahead of the port and blew the deploy healthcheck — and a failed healthcheck kills the container mid-run, leaving one more interrupted run for the next boot, so each attempt started further behind. It is now `asyncio.create_task` alongside startup with its cohorts on `asyncio.to_thread` (their SQLite writes are synchronous and would starve the loop). The checkpoint sweep, by contrast, must stay **inline**: it needs the reader-free window startup uniquely provides, since alongside a serving process a long-lived SSE reader blocks it forever. It catches `sqlite3.Error` and continues, because a full volume is exactly the state in which the DELETE that relieves it cannot get its journal written. Serving with a bloated table beats not serving.
- **Only `UnsupportedTaskError` is a permanent task failure** (`app/app/task_worker.py`). Every other exception keeps its retry budget (`max_attempts` defaults to 3), so widening that branch strands runs — the reported shape is bursts of progress separated by silence, tasks sitting at attempt 1/3 with retries unused. Nothing *automatic* recovers a `failed` task: `resume_run_tasks` only requeues `paused`, and the expired-lease rescue skips tasks whose attempts are spent. Recovery is explicit — a Supervisor `retry` action or a resume, which must call `revive_task_for_retry` **before** enqueueing, since the `{task_type}:{checkpoint_seq}` idempotency key cannot change while the run makes no progress and `ON CONFLICT DO NOTHING` would otherwise create nothing. `revive_task_for_retry` rescues a `leased` task only once its lease has expired (its owner is then provably gone); reviving an unexpired lease would run the same boundary twice concurrently.
- **No process-global asyncio primitives.** Each durable run's worker cohort executes on its own thread with its own event loop (`task_worker.run_run_worker_pool_sync` calls `asyncio.run`), so several loops are live in one process. An asyncio primitive binds to the loop that first waits on it and raises from every other. The ranking judge semaphore is therefore created per running loop and held weakly (`agents/ranking/ranking_debate.py::_get_ranking_semaphore`) — as a module-level singleton it stayed hidden until tournament waves grew large enough to actually contend, then killed a production ranking task with "bound to a different event loop". Bound concurrency per loop, or via the cohort's `worker_pool_size`, never with a shared primitive. Module scope is safe only for primitives touched exclusively from the API loop.
- **Never score a short claim against a long document with Jaccard.** Jaccard divides by the *union*, which the longer side dominates, so the score is capped near `len(claim) / len(document)` however perfectly the document supports the claim. `citations.classify_citation` matched a one-sentence claim against a whole abstract that way: an abstract quoting the claim verbatim scored 0.18 against a 0.35 "verified" threshold, and a relevant paraphrase scored 0.078 against a 0.10 "partial" threshold, so **both upper states were unreachable** and every citation in every real run classified `unsupported` (one production run: `citation_audit verified=0 partial=0 unsupported=47`). It reads as a model or evidence-quality problem, not a metric bug, because the numbers are individually plausible. Use coverage — intersection over the *claim's* tokens — whenever the two texts are asymmetric, and sanity-check any new threshold by feeding it a document that literally contains the claim. Note the fix stops there: a bag-of-words score still cannot tell a claim's subject from its assertion, so an abstract sharing only the topic nouns lands in the same band as one stating half the claim. Sharpening that is the LLM entailment assessor's job (`claim_verifier`, feeding `claim_evidence`), not this deterministic fallback's — do not tune thresholds between two hand-picked examples, which is how the previous test ended up pinning the broken metric in place.
- **An early gate that never reverses decides the whole run, not just one node.** `agents/reflection/review.py::_apply_initial_review_gate` sets `review_disposition` once, from the *first* review, and nothing revisits it. A blocking value bars the idea from the Elo tournament for the rest of the run (`Hypothesis.is_rankable`), reads as "Disqualified" in the UI, and skips it in comprehensive reflection — and, because `_select_evolution_pool` breeds from the ranked survivors, it also shrinks the gene pool. One production run blocked 20 of 22 ideas, which left a two-idea tournament, an Elo ordering built from four matches, and an evolution pool that kept re-deriving the same drug; the visible symptom was "why is every idea about empagliflozin", not "the review gate is strict". So the thresholds track the rubric the prompt itself hands the model (`NOT_VIABLE_SCORE`/`NEEDS_REVISION_SCORE` in `constants.py` mirror its 1-2 "not viable" and 3-4 "needs substantial rework" bands) rather than being tuned independently — and note the batch prompt *requires* the model to spread scores across the pool, so a relative low scorer exists on every run whatever the absolute quality. Only the non-viable band blocks; the rework band is `needs_revision`, which ranks and publishes but skips the deep-review cascade. Two related traps: a *missing* score must not read as the worst score (it defaulted to 0 and disqualified the idea, and prod's json_object mode does not enforce the schema); and "excluded from the report" is not one fact — `duplicate` (proximity archived it) and `rejected` (it failed review) share `EXCLUDED_HYPOTHESIS_STATUSES` but must reach the reader as different words.
- **The near-duplicate guard has to see everything it is guarding against.** `evolve.py` passes `other_hypotheses_texts` to `_apply_evolution_result`, which discards a child too similar to any of them. Sampling those from the round's `top_k` instead of `state["hypotheses"]` left the guard blind to every idea outside the current round, so duplicates passed and proximity archived them afterwards — the run still ends up with the near-identical ideas, just labelled later. The 15-item cap plus `sample_context_hypotheses`'s top-5-by-Elo-plus-random sampling is what bounds the token cost; against `top_k` that sampling never even ran.
- **Counts named for different things must be computed differently.** The report payload carries `idea_count` (everything explored), `hypothesis_count` (released by the safety/contradiction gates), and `verified_count` (released *and* carrying a `supports`/`partial` claim edge). Reading one where another is meant produces a report that contradicts its own tabs and looks like a data-loss bug: the lead stat read `hypothesis_count` and announced "A total of 2 ideas were explored" above a list of 22, and the "Verified ideas" tile was handed the High Potential count, so a run claimed two verified ideas while badging every idea "Unverified". `verified_count` is derived by `report_content_gates._verified_hypothesis_count`, the exact complement of `_unverified_hypothesis_ids` over the released set, because the tile and the per-idea badge are one fact shown twice. For the same reason `idea_buckets` must partition — `non_viable` is defined as everything not in `high_potential`, so capping either half silently stops the pair summing to the run's idea count.
- **Structured-output schemas must not echo input back.** When a node's JSON schema names items from a pool, identify them by the positional index the prompt assigns, never by repeating their text — an echoing schema makes output length scale with the pool, so a large run overruns the token budget (46 hypotheses at ~1250 chars needed ~14k output tokens against 10k), truncates the JSON identically on *every* retry, and degrades silently. That is exactly how proximity clustering stopped deduplicating; `agents/proximity/proximity_dedup.py::_match_cluster_member` keeps text-prefix matching only as a fallback. **Trim the schema, never the input.** Proximity is the one node that sends the whole pool in a single prompt, which makes it the obvious place to economise by truncating hypothesis text — and the wrong one: it is being asked to find differences, three of its six similarity dimensions are argued in a hypothesis's tail, and its verdict *deletes* work, so a false "high" drops a distinct hypothesis silently. The saving is illusory anyway (a few thousand input tokens on a call whose spend is reasoning output). This was tried and reverted; `test_proximity.py::test_long_hypotheses_are_sent_whole` pins it out. If the prompt is genuinely too large, chunk the pool.
- **`max_tokens` funds the chain of thought too, not just the answer.** Reasoning is billed and counted against the same allowance even though it comes back in a separate `reasoning_content` field, so a budget sized for the answer lets a long chain of thought consume all of it: `finish_reason="length"`, empty `content`, paid for in full, then retried four more times by `call_llm_json`. Switching thinking on for a call site without revisiting its `max_tokens` in the same edit is what produces this; it did, on thirteen engine nodes and two app call sites at once. Both codebases therefore apply a floor rather than trusting per-site budgets — `co_scientist.constants.THINKING_FLOOR_MAX_TOKENS` via `_apply_thinking_args`, and `app.config.thinking_safe_max_tokens` at the call sites that bypass the engine (`interviews.py`, `claim_verifier.py`). The symptom is quiet: a run degrades a node at a time, and for the claim verifier it reads as "the LLM assessor is configured but never wins" rather than as an error. Note that *omitting* `max_tokens` is not the safe option — it takes the provider's own default, which is small enough for thinking to exhaust; `safety.py` sent no budget at all and every screened item was heading for `hold` + `requires_review`, i.e. runs parked for human adjudication on a truncation rather than on their content.
- **The token budget and the wall clock are one setting in two places.** Funding a chain of thought without extending the deadline only moves the failure — the call is abandoned mid-reasoning instead of returning empty — and both land in the same silent fallback, so the fix looks like it did nothing. `app.config.thinking_safe_timeout` mirrors `thinking_safe_max_tokens` and raises the deadline the same way, and `test_config_thinking.py` pins the floor against the token floor so a later tightening cannot re-break what raising the budget fixed. **On a streaming call, bound silence, not duration** (`app/app/llm_stream.py::stream_chunks`): a stream delivering tokens is healthy however long it runs, and on a thinking model the long-but-alive case is the normal one, so any total tight enough to catch a hung provider also kills a good turn. The interview and Q&A streams relay reasoning to the reader as it arrives, which is why a generous deadline there is visible progress rather than a blank wait — do not copy those numbers to a blocking call that shows the caller nothing.
- **Two independent wall-clock ceilings on outbound calls**, and they expire differently. `COSCIENTIST_LLM_TIMEOUT_SECONDS` (default 600s) bounds `litellm.acompletion` only; MCP tool calls are bounded by `COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS` (default 300s). Set either to `0` to disable. The two MCP call sites diverge deliberately: `call_tool` raises `MCPToolTimeoutError` (callers degrade per-source), while `execute_tool_call` returns the timeout as the tool's *result*, because it runs under an `asyncio.gather` without `return_exceptions` where raising would kill every sibling call.

## Working in this repo

- The `engine/` and `app/` directories are vendored as plain directories (not submodules). `co-scientist-engine` is not published to PyPI; it's installed editable from the local checkout (`pip install -e ../engine`, which `make setup` and the Dockerfiles do). Where the app is installed with `--no-deps` (make setup, CI, the compose dev image), its runtime deps come from the single-source list `app/requirements-app.txt` — keep it in sync with `app/pyproject.toml`.
- Both the app (`app/`) and the engine (`engine/`) have committed pytest suites under `tests/`. `mypy .` is strict-clean for each (the engine excludes the separate `mcp_server` package and the `dev/` scripts). `mcp_server/` is its own project with its own `tests/` — run `pytest` *and* `mypy .` from `engine/mcp_server/`. `evaluations/` likewise has its own suite, reached via `make parity`.
- When invoked from this workspace, `.remember/remember.md` is the session-handoff file — read/update it per the `remember` skill instructions.

## Required environment

Both projects use **LiteLLM** for model dispatch. Set the relevant provider key (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) and `MODEL_NAME` before running.

The app's model defaults live in `app/app/config.py` and are DeepSeek on every tier: `MODEL_NAME=deepseek/deepseek-v4-flash` (worker — generation, review, ranking, reflection, evolve, proximity, literature review, safety screening), `SUPERVISOR_MODEL_NAME=deepseek/deepseek-v4-pro` (planning + final synthesis), `CHAT_MODEL_NAME=deepseek/deepseek-v4-pro` (interview, Q&A, titling), `SEMANTIC_SAFETY_MODEL=deepseek/deepseek-v4-flash`. Production runs those same defaults.

The viewer also reads `MCP_SERVER_URL` (default `http://localhost:8888/mcp`), `TOOLS_CONFIG` (path or http URL to a YAML tools config), `CLAIM_ASSESSOR` (default `llm`), `FORCE_LITERATURE_REVIEW` (`0` is a hard kill switch for tests/dev), and `SBI_CORPUS_DIR` (default `corpus/sbi_ucd`). Most viewer env vars are documented in `app/.env.example` — but not `SBI_CORPUS_DIR`. The reference MCP server has a **separate** env surface (`engine/mcp_server/.env.example`); setting those vars in the app's `.env` does nothing.

With no provider key set, or with `COSCIENTIST_FORCE_OFFLINE=1` (deprecated alias `COSCIENTIST_FORCE_MOCK=1`), the viewer runs every hypothesis-generation call through the engine's deterministic offline LLM backend (`co_scientist.offline_llm`, which intercepts `litellm.acompletion` for `offline/`-prefixed models) instead of a real provider — no key required.

## Git hygiene

Never mention yourself or any other AI tool in commits, pull requests, or pushes. This applies to all AI agents working in this repo.

- No `Co-Authored-By: <AI name>` trailers in commit messages.
- No "Generated with [tool]" or "Created by [AI]" lines in commit messages or PR bodies.
- No references to AI tools (Claude, Devin, ChatGPT, Copilot, etc.) anywhere in git history.

Commit messages should read as if written directly by the human developer.

Commit messages must follow the format `<type>(<scope>): <subject>`. Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`. Example:

```
feat(runs): add markdown_text column to reports table
fix(report-tab): handle missing markdown gracefully
docs(engine): rename docs to UPPER_SNAKE_CASE
```

Branch names must follow the format `<type>/<description>` using the same type vocabulary. Example:

```
feat/report-markdown-persistence
fix/report-tab-empty-state
docs/restructure-engine-docs
```

Pull requests should follow Google's public CL-description conventions, adapted
for a concise personal-project workflow:

- PR titles are short, standalone, imperative summaries of the change. Do not
  use Conventional Commit prefixes in PR titles. Prefer `Remove unused
  generate endpoints` over `refactor: remove unused generate endpoints`.
- PR bodies should briefly explain what changed, why it changed, and how it was
  tested. Add implementation context or tradeoffs only when they help future
  review or maintenance.

# ADR-001: Module map and allowed dependencies

**Status:** accepted, 7 October 2026. Re-architecture phase 1. The owner may
overrule it on the campaign board.

## Context

`docs/REARCHITECTURE.md` wants one Python package organized by domain, in
layers. The survey (`docs/rearchitecture/survey.md`) shows the starting point:
two distributions (`co-scientist-engine`, import name `co_scientist`, 159
modules; `co-scientist-viewer`, import name `app`, 131 modules) joined by
adapters in both directions. The engine already imports neither `sqlite3` nor
`fastapi`; the app's `store/` holds every table; LLM policy sits on both sides.

The plan left the package name to shrink lever 11, which was not done ("not
worth its risk": about 48k moved lines for about 250 deleted). Phase 4 moves
every module anyway, so merging the packages adds no move of its own.

## Decision

**One package, `co_scientist`.** The app's modules move into the engine's
package; `app` empties and is deleted in phase 8. Keeping the engine's import
name leaves every engine import, logger name (`co_scientist.*`), sandbox
launcher string and test patch target as it is. Rejected: a new name
(`coscientist`) renames about 700 more import sites for no structural gain;
two packages organized by layer keeps the adapters, the untyped boundary
(`follow_imports = "skip"`) and two sets of configuration.

**Its source stays at `engine/src/co_scientist/` for this campaign.** The
api's Railway watch paths already cover `/engine/src/**` and `/app/app/**`,
so no move needs a dashboard change, and the `Dockerfile.api` `COPY` lines
keep working until `app/app` is empty. The `co-scientist-engine` distribution
takes the app's runtime dependencies in the first move that needs them; the
locks are regenerated with uv. Moving `engine/src` to a repository-root `src/`
is a path-only change with its own owner step (watch paths); it is left for
after the campaign.

**Layers**, top to bottom. A layer imports only layers below it.

| Layer | Package | Holds |
|---|---|---|
| 1 | `co_scientist.main` | Composition root: builds the FastAPI app, lifespan, wiring |
| 2 | `co_scientist.api` | Routers, SSE, wire contracts, request auth; the only `fastapi` user |
| 3 | `co_scientist.orchestration` | Workflow, node registry, durable runtime (queue, leases, cohorts, recovery), run lifecycle, drain, finalize |
| 4 | `co_scientist.science` | One package per agent; shared `prompts`, `schemas`, `research` and `node_degradation` |
| 5 | `co_scientist.domains` | `research_state`, `safety`, `report`, `chat`, `documents`, `access`, `feedback` |
| 6 | `co_scientist.platform` | `db`, `llm`, `retrieval`, `sandbox`, `telemetry` |
| 7 | `co_scientist.core` | Types, errors, configuration, run modes, context and async helpers; no I/O |

Two target names change because `.dockerignore` and `.gitignore` drop any
directory named `reports` or `cache`: the domain is `domains/report`, and
`platform/cache` is not created (no cache module exists). `domains/feedback`
is added for the feedback tables and admission budgets.

**Within layers:**

- `science` agents are independent of each other; they share only `prompts`,
  `schemas`, `research` and `node_degradation`.
- `domains` are layered: `chat` > `report` > `safety` > `research_state` >
  `documents` | `access` | `feedback`. These are the only cross-domain edges.
- `platform` adapters are independent of each other except that `retrieval`
  may use `llm` (relevance scoring) and every adapter may use `telemetry`.

**Third parties:** `fastapi`/`starlette` only in `api` and `main`; `sqlite3`
only in `platform/db`, domain repositories and the orchestration runtime
store; `litellm` only in `platform/llm`; `httpx` only in `platform/llm` and
`platform/retrieval`; `langgraph`/`langchain_*` only where they are today
(`research_state` reducers, `orchestration` checkpoints, `platform/retrieval`).

**Public interface:** a package's `__init__.py` is its interface. Other
packages import from it, not from its submodules, once phase 5 has deepened
that package; until then the contracts check layers and independence only.

## Module map

Each phase 4 PR moves one row group with `git mv`. Files keep their names
unless the table renames them; a rename happens only to drop a prefix the new
location makes redundant.

| Target | Current modules |
|---|---|
| `core/` | engine `exceptions.py`, `_context.py`, `backoff.py`, `config/env_vars.py`, `models/metrics.py`, `constants/`; app `config.py`, `run_modes/`, `async_bridge.py` |
| `platform/db/` | app `store/db.py`, `store/schema.py`, `store/checkpoints.py`, `store/models.py` |
| `platform/llm/` | engine `llm/`, `offline/`, `tool_effects.py`; app `llm_request.py`, `llm_scope.py`, `execution_policy.py`, `process_mode.py`, `offline_guard.py`, `provider_usage.py` |
| `platform/retrieval/` | engine `mcp_client/`, `tools/`, `config/` (registry, schema, `tools.yaml`), `evidence/`, `retrieval_degradation.py`, `research_adapter/`; app `pinned_http.py`, `retraction_set.py` (+ `data/retractions.txt.gz`), `citations/`, `run_corpus.py`, `engine_adapter/tools.py` |
| `platform/sandbox/` | engine `sandbox/`, `workspace/`, `skills/`, `patch/` |
| `platform/telemetry/` | engine `progress.py`; app `logging_setup.py`, `error_tracking.py`, `diagnostic_events.py`, `store/logs.py`, `store/retrieval_calls.py` |
| `domains/research_state/` | engine `models/` (rest), `state/`; app `elo.py`, `text_utils.py`, `claims/` (with `evidence_chunking.py` as `claims/chunking.py`), `store/hypotheses.py`, `store/records.py`, `engine_adapter/drain/{hypotheses,reviews,matches}.py` |
| `domains/safety/` | engine `safety.py`; app `safety/`, `hypothesis/` |
| `domains/report/` | app `report/`, `store/reports.py` |
| `domains/chat/` | app `qa/`, `interviews/`, `run_start_announcement.py`, `goal_text.py`, `seed/` (+ `data/demo_runs.json.gz`), `store/messages.py`, `store/interviews.py`, `store/examples.py` |
| `domains/documents/` | app `document_ingest.py`, `pdf.py`, `pdf_worker.py`, `staged_documents.py`, `store/documents.py` |
| `domains/access/` | app `credentials.py`, `byok_models.py`, `free_usage.py`, `retention.py` |
| `domains/feedback/` | app `store/feedback.py` |
| `science/` | engine `agents/{generation,reflection,ranking,evolution,proximity,meta_review,supervisor}` → `science/<agent>`; `agents/safety.py` → `science/safety_screen`; `agents/node_degradation.py`; `scheduling/` → `science/scheduling` (meta-review and orchestration read it too, so it is not the supervisor's alone); `prompts/`, `schemas/`, `research/` |
| `orchestration/` | engine `agents/__init__.py` (node registry), `workflow_topology.py`, `task_runtime.py`, `checkpoint.py`, `generator/`; app `engine_tasks/`, `task_worker/`, `run_events.py`, `notifications.py`, `engine_adapter/{__init__,opts,events}.py`, `engine_adapter/drain/{__init__,final_state}.py`, `store/{tasks,tasks_lifecycle,runs,runs_views,events,supervisor_plan,receipts}.py` |
| `api/` | app `api_contracts/` → `api/contracts`, `runs/`, `diagnostics_api.py`, `diagnostics.py`, `logs_api.py`, `feedback_api.py`, `documents.py`, `sse.py`, `operator_access.py`, `auth.py` |
| `main.py` | app `main.py`, `__init__.py` (`API_VERSION`) |

Known straddlers move whole and are split in phase 5, each split removing its
ignore-list entries: `credentials.py` (five concerns), `config.py` (provider
maps and thinking delegates belong to `platform/llm`), `store/records.py`
(`safety_decisions` belongs to `domains/safety`), `store/runs_views.py` and
`store/examples.py` (direct writes to research-state tables), `runs/crud.py`
and `runs/lifecycle.py` (run state machine belongs to `orchestration`),
`interviews/` (routers belong to `api`), `byok_models.py` and `free_usage.py`
(routers), `provider_usage.py` (`HTTPException`), `constants/` (LLM, Elo and
run defaults), `research_adapter/` (LLM and MCP adapters plus tier budgets),
`async_bridge.py` (`litellm` logging worker).

## Consequences

- Every phase 4 PR updates the import-linter configuration's module names in
  the same PR; the ignore list is renamed, never extended.
- `app/tests/test_architecture.py`'s "engine does not depend on app" test is
  replaced by the layer contract, because moved modules import not-yet-moved
  ones across the old boundary. Its other checks stay.
- The engine's Python 3.10 floor is kept: the app's code already targets 3.10
  in its ruff and mypy settings.
- After the last move, `app/` holds only the frontend, `app/tests` and the
  development tooling; phase 8 removes the `co-scientist-viewer` distribution
  and its `requirements-app.txt` sync rule, and records the Railway start
  command change on the board first (production overrides the Dockerfile
  `CMD` with `app.main:app`).

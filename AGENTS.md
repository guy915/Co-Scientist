# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Repository Layout

This is a research/reference workspace organized around replicating Google's AI Co-Scientist.

- `app/` — FastAPI + React workbench viewer
- `engine/` — Internal multi-agent hypothesis-generation engine
- `evaluations/` — offline evaluation harness (`citation_eval.py`, `safety_eval.py`, `claim_support_eval.py`, `citation_usefulness_eval.py`, `smoke.py`, plus `datasets/`, `tests/` and its own `pyproject.toml`; see `evaluations/README.md`)
- `e2e/` — Playwright browser end-to-end suite (`tests/*.spec.ts`, `support/` fixtures)
- Historical research dossiers, experiments and the completed external-reference campaign are preserved at [immutable revision `33ec8984`](https://github.com/guy915/Co-Scientist/tree/33ec8984c6f9292a6653cc6a661d32210f55c688). Historical source material remains available in git.
- `vendor/` — third-party code shipped as-is, pinned to an upstream revision and never reformatted (a root `.ruff.toml` excludes it, after a repo-root format sweep once silently rewrote 63 vendored files). `science-skills/` is Google DeepMind's Science Skills bundle; the api image copies it and points `COSCIENTIST_SKILLS_DIR` at it. Provenance and revision: the root `NOTICE`.
- `docs/` — live project docs; `docs/README.md` indexes them (`ARCHITECTURE.md`, `CI.md`, `DEPLOYMENT.md`, `OPERATIONS.md`, `RUNNING-LOCALLY.md`, `LAUNCH.md`); retired guides, audits and screenshots remain in immutable Git history
- `.github/` — GitHub Actions. `ci.yml` runs as presubmit (on `pull_request`, with `dorny/paths-filter` job-level path filters, superseded runs cancelled) and as postsubmit (on push to `main`: every job, never cancelled); `nightly.yml` re-runs the whole pipeline on cron via `workflow_call`; `benchmark.yml` is not CI but a manual, live quality benchmark that uses the `OPENROUTER_API_KEY` repository secret (see `docs/OPTIMIZATION.md`); `prune-branches.yml` is a manual branch cleanup that keeps `main`, branches with open PRs and recent branches. Every CI command is hermetic — no network, no API keys, no retries — so a test needing a provider key must be skipped or offline. Rationale in `docs/CI.md`.
- `.remember/` — session handoff notes (`remember.md` is the live handoff file; also `now.md`, `recent.md`, daily logs, `logs/`, `tmp/`)
- `docs/CAMPAIGNS.md` — the active cuts, shrink and optimization campaigns: schedule, ownership and merge rules; use `docs/LAUNCH.md` for launch work.
- `Makefile` — root-level build orchestration (`setup`, `start`, `dev-api`, `dev-ui`, `dev-mcp`, `test`, `test-app`, `test-engine`, `test-mcp`, `test-all`, `test-frontend`, `check`, `docker-build`, `e2e`, `test-evaluations`, `eval-smoke`, `lint`, `arch`, `typecheck`, `build`, `clean`, `stop`, `reset-db`)
- `README.md` — project overview, features, installation, and usage

**Root Makefile targets**: `setup`, `start`, `stop`, `dev-api`, `dev-ui`, `dev-mcp`, `dev-all`, `test`, `test-app`, `test-engine`, `test-mcp`, `test-all`, `test-frontend`, `check`, `docker-build`, `e2e`, `test-evaluations`, `eval-smoke`, `lint`, `arch`, `typecheck`, `build`, `clean`, `reset-db`. `make lint` also runs `make arch`, the import contracts in `.importlinter` (ADR-002): a new layer-crossing import fails it, and a fix deletes its `ignore_imports` entry and lowers the ceiling in `evaluations/tests/test_import_contracts.py`. **`make start` is the single entry point** — installs missing deps, frees ports 8008/5173/8888, runs MCP + API + UI together, opens the browser. There is no `make dev`. Note the asymmetries: `make test-all` is engine + app + mcp_server pytest, frontend Vitest **plus the evaluation harness tests**; `make lint` also covers `evaluations/`; `make typecheck` covers `app/`, the engine, and `evaluations/` (the mcp_server's strict mypy runs inside `make test-mcp` instead, from the dedicated 3.12 venv at `.venv-mcp`).

`make e2e` installs its own deps and Chromium, then launches an isolated stack (FastAPI on 8108, Vite on 5273 — deliberately off the `make start` ports) against a fresh per-invocation SQLite store, headless and pinned to the deterministic offline backend, so it needs no API key. Requires `make setup` first.

Each project is also independently installable and runnable.

## Project guides (nested)

Per-project detail lives beside the code and loads when you touch that subtree. Read the one you are working in:

- **[`engine/AGENTS.md`](engine/AGENTS.md)** — Durable engine workflow, node→file map, LLM dispatch/bounds, MCP + web search, tool registry, prompts, style conventions, and the reference MCP server (`engine/mcp_server/`).
- **[`app/AGENTS.md`](app/AGENTS.md)** — FastAPI backend and module map, durable task execution (the real run path), auth/ownership, persisted logs, key endpoints, the React frontend, and the Docker workflow.

## Production hosting

Three services: **frontend** on Vercel (`co-scientist-ui`, https://ai-co-scientist.com/), **api** and **mcp** on Railway (project `co-scientist`, env `production`), both built from repo-root `Dockerfile.api` / `Dockerfile.mcp`. Full build, env-var and networking detail: **[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)**.

These two are load-bearing — each was an outage or a silent data-loss bug. Do not "clean them up" without reading the rationale in `docs/DEPLOYMENT.md`:

- **`RAILWAY_RUN_UID=0` must stay set on the api.** Railway mounts the persistent volume over `/app/data` at runtime, so an unprivileged process cannot write the SQLite DB; the app then dies in its lifespan hook before binding a port and every deploy fails its healthcheck. This is not an oversight to restore non-root on.
- **The api service runs at exactly one replica.** The store is SQLite in WAL mode with `synchronous=NORMAL` — sound only single-writer. A second replica is unserialized concurrent writes to one file, a correctness bug no tuning fixes. Growing past this is a store migration, not a knob.

## Operational invariants

The full incident rationale lives in [docs/OPERATIONS.md](docs/OPERATIONS.md).
Read the relevant entries before editing their implementation. In particular:

- Never VACUUM or run truncating checkpoints from the serving process.
- Never hold a SQLite write lock over network I/O or write on every poll tick.
- Keep startup cheap; recovery executes outside the port-binding critical path.
- Preserve durable task idempotency, leases, retry budgets, and explicit recovery.
- Future-due queued tasks keep their cohort alive; log cursor IDs may have gaps.
- Steering admission permits one extra cycle to incorporate input before it is marked applied.
- Node keys persist in task types, checkpoints and idempotency keys; rename them only with a migration.
- No asyncio primitive may be shared between the worker cohorts' event loops.
- Preserve bounded provider calls, token/reasoning budget escalation, and spend caps.
- Evidence gates must distinguish missing, unsupported, contradictory, and unsafe
  findings. Preserve append-only hypothesis lineage and per-run provenance.
- Source retrieval and model-written programs cross trust boundaries. Preserve
  MCP URL guards, sandbox confinement, and the absence of execution tools when
  confinement is unavailable.

## Working in this repo

- The `engine/` and `app/` directories are vendored as plain directories (not submodules). `co-scientist-engine` is not published to PyPI; it's installed editable from the local checkout (`pip install -e ../engine`, which `make setup` and the Dockerfiles do). Where the app is installed with `--no-deps` (make setup, CI, the compose dev image), its runtime deps come from the single-source list `app/requirements-app.txt` — keep it in sync with `app/pyproject.toml`.
- Both the app (`app/`) and the engine (`engine/`) have committed pytest suites under `tests/`. `mypy .` is strict-clean for each, tests included (both exclude their `dev/` scripts; the engine also excludes the separate `mcp_server` package). `mcp_server/` is its own project with its own `tests/` — run `pytest` *and* `mypy .` from `engine/mcp_server/`. `evaluations/` likewise has its own suite, reached via `make test-evaluations`.
- When invoked from this workspace, `.remember/remember.md` is the session-handoff file — read/update it per the `remember` skill instructions.

## Documentation policy

- **Hidden reasons only.** A comment or docstring survives only for a reason the code can't show: why something is the way it is, an invariant, or an outside fact. Keep it to about two lines.
- **Delete what restates code:** Args/Returns/Raises blocks, narration, `Attributes:` lists repeating fields, and dated finding or ADR references. Long incident histories belong in `docs/OPERATIONS.md`, compressed to their lesson.
- **Test names carry the behavior.** Test docstrings and comments go unless they explain a non-obvious reason.
- **Runtime content is not documentation:** MCP tool docstrings become the model's tool descriptions, and schema field descriptions are sent to the model. Both stay.

## Required environment

Use Python 3.12, Node.js 22.13+ and Bun 1.3.14 for the full application.
The internal engine package supports Python 3.10+. Run `make setup` first.
`make check` covers lint, types, backend/frontend suites, evaluation
smoke, the production frontend build, and isolated browser tests.
`make e2e-production` separately serves built assets and checks deep links,
report reloads, and anonymous ownership isolation.
Both browser targets disable local dotenv loading and use offline evidence
checks. The production target builds with the isolated test API URL into its
temporary state directory, leaving normal frontend `dist/` untouched.
`make docker-build` builds both production images without deploying them.

The app's current system model defaults are declared in `engine/src/co_scientist/core/config.py`:
`openrouter/inclusionai/ling-3.1-flash` for worker, supervisor, chat and
semantic safety, at pinned medium effort. Set its provider credential to use
it. It is a zero-priced trial route without a `:free` id, with free-only
Nemotron fallbacks, a checked zero-price ceiling and expiry, and no response
format.
Explicit production environment overrides take precedence; an old deployment
snapshot is not evidence of the current configuration. Do not append paid
fallbacks under free routes. Every model fact (capabilities, routing pin and
fallbacks, price) is one `ModelProfile` declared in `engine/src/co_scientist/platform/llm/profile/`;
`platform/llm/request/thinking.py` holds the routing policy applied to it.

With no usable provider credential, or `COSCIENTIST_FORCE_OFFLINE=1`, the
viewer uses the deterministic offline backend. Use this for local checks;
provider-backed experiments require deliberate execution. App configuration is
in `.env.example` and `app/.env.example`; MCP has its separate
`engine/mcp_server/.env.example`.

Production Python 3.12/Linux runtime closures are hash-pinned under
`requirements/`. Regenerate the relevant lock when changing runtime dependency
metadata; see [requirements/README.md](requirements/README.md). Never reformat
vendored sources or edit generated lock hashes by hand.

`make audit-deps` is a separate online advisory check, requiring uv. It retains
all detector findings; see [dependency guidance](requirements/README.md).
Reassess reachability before mounting LiteLLM proxy routes or adding FastMCP
OAuth or a disk-backed key/value store; see [operations](docs/OPERATIONS.md).

## Trust boundaries

`main` is protected. Treat production Railway targets (`api-production-97eb.up.railway.app`, `api.ai-co-scientist.com`) and any `prod` or `production` target as protected.

- Keep `.env`, `.env.local`, `app/.env`, `engine/mcp_server/.env`, credentials, MCP shared secrets, `coscientist.db`, and run outputs out of commits and external sharing.
- Read-only `railway status` / `railway logs` and local read-only SQLite queries are routine. Confirm before `railway up`, `deploy`, `redeploy`, `variables` writes, `run`, `down`, service deletion, or environment deletion.
- Local services are API `:8008`, UI `:5173`, and reference MCP `:8888`; use only the documented localhost and production domains.

Contributions use Apache 2.0. Preserve third-party notices and vendored sources;
keep package LICENSE/NOTICE copies synchronized with the root copies.
Use `Any` only for truly dynamic JSON, not known interfaces.

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

## Durable execution preferences

- Preserve uncommitted work. Never use `git commit --amend`, `git reset`, `git stash`, `git checkout <file>`, or `git restore <file>` to alter it. Make follow-up changes in new commits, and verify the files you changed are present on disk before reporting completion. Before the final gates, inspect `git reflog -5` and `git stash list`.
- Do not automate merges or other hard-to-reverse Git operations end to end. Review both sides and the intended diff before committing; inspect snapshot/reference paths for rename-detection artifacts.
- `main` is protected. Do not try to bypass that protection or promise a direct push; use the repository's review and merge path.
- Keep the app and engine pytest suites serialized. Stop leftover local `uvicorn` verification servers before a full suite, and do not re-run an unchanged full suite merely to reconfirm it.
- Run named gates directly and record their real exit status. Do not hide one behind a pipeline; redirect output to a log if needed, then capture the command's status. For repository architecture and published-source invariants, run `evaluations/tests/` explicitly.
- Before accepting a result as unverifiable, inspect the relevant primary source tree rather than relying on a derived or mirrored document. Record the source scope and direct evidence for the finding.
- Before declaring a production probe or polling check failed, fetch the artifact once and derive its assertion from the observed output. For shared UI work, verify both light and dark themes.

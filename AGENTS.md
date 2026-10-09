# AGENTS.md

Co-Scientist (public name Open Co-Scientist, https://open-coscientist.com) is an
open replication of Google's AI Co-Scientist: a multi-agent engine that
generates, reviews, ranks and evolves research hypotheses, served by a FastAPI
API and a React workbench. This file is for coding agents arriving cold. Read
it, then the guide for the code you touch:

- [`engine/AGENTS.md`](engine/AGENTS.md): package map, science agents, LLM
  layer, retrieval, sandbox and the reference MCP server.
- [`app/AGENTS.md`](app/AGENTS.md): HTTP API, durable task runtime and SQLite
  store (their Python lives in `engine/src/co_scientist/`), the backend test
  harness, the React frontend and local Docker Compose.

## Layout

| Path | Holds |
|---|---|
| `engine/` | Package `co-scientist-engine` (import `co_scientist`, source in `src/co_scientist/`): the whole server, from science agents to API. Installed editable, never published. `mcp_server/` is the reference MCP server, a separate project. |
| `app/` | `frontend/` (React, Vite, Bun), `tests/` (backend suite), `docker/` and `docker-compose.yml` (local stack), `dev/` scripts. No production Python. |
| `evaluations/` | Offline evaluation gates, the manual live quality benchmark, and repository guards in `tests/`. Not installable: run `python -m evaluations.<module>` from the root ([README](evaluations/README.md)). |
| `e2e/` | Playwright suites: `tests/` (dev server), `production/` (built assets), `support/` ([README](e2e/README.md)). |
| `docs/` | Live documentation, indexed by [docs/README.md](docs/README.md): start with `ARCHITECTURE.md` and `RUNNING-LOCALLY.md`; decisions in `adr/`. |
| `scripts/` | `presubmit.py` and `select_targets.py` (gate selection), `ci/` (CI guards), `api-entrypoint.sh` (production API start), `operations/`. |
| `requirements/` | Hash-pinned Python 3.12 Linux locks for the images and the reviewed licence inventory ([README](requirements/README.md)). |
| `vendor/` | Third-party code shipped as-is at a pinned revision (`NOTICE`); never edit or reformat it. `science-skills/` is Google DeepMind's Science Skills bundle, copied into the API image. |

## Set up and run

Use Python 3.12, Node.js 22.13+ and exactly Bun 1.3.14 (`make check-tools`
rejects other Bun and Node versions). uv is only for `make audit-deps` and locks.

- `make setup` creates `.venv` (prefers `python3.12`; never rebuilds an existing
  venv), installs the engine editable with dev extras and the frontend
  packages, copies `.env.example` to `.env` and links `app/.env` to it.
  `make dev-mcp` or `make test-mcp` creates the MCP server's `.venv-mcp`.
- `make start` is the single entry point: it installs missing dependencies,
  frees ports 8008, 5173 and 8888, runs MCP, API and UI and opens the browser.
  `make stop` frees the ports; `make dev-api`, `dev-ui` and `dev-mcp` run one
  service. The API reads the root `.env`; the MCP server reads only
  `engine/mcp_server/.env`.

A real run needs a provider credential; without one, requests fail with "No
model is available right now" and nothing falls back to offline. Tests, browser
suites and offline evaluations select the deterministic backend with
`COSCIENTIST_TEST_DOUBLE=deterministic` (exact value; `COSCIENTIST_FORCE_OFFLINE`
is retired). Default models are declared in `engine/src/co_scientist/core/config.py`;
environment overrides win, so read a deployment's environment back.

## Gates

| Command | Runs |
|---|---|
| `make lint` | Ruff (engine with `mcp_server`, `app/tests`, evaluations, gate scripts), gts on the frontend, then `make arch` |
| `make arch` | Import contracts in `.importlinter` ([ADR-002](docs/adr/002-layering-enforcement.md)) |
| `make typecheck` | Strict mypy on app tests, engine, evaluations and gate scripts (MCP mypy runs in `make test-mcp`) |
| `make test-all` | Engine, app and MCP pytest (plus MCP strict mypy), evaluation tests, frontend Vitest |
| `make eval-smoke` | Offline safety and citation gate |
| `make e2e` | Chromium suite on an isolated stack (API 8108, Vite 5273, fresh SQLite, test double); installs its own packages and browser after `make setup` |
| `make e2e-production` | The same harness against built assets: deep links, reloads, headers, ownership isolation |
| `make build` | Production frontend build; `make build-checked` adds bundle budgets |
| `make check` | lint, typecheck, test-all, eval-smoke, build, e2e, e2e-production |
| `make presubmit` | The targets CI selects for your committed diff against `origin/main`, then `make ci-guards`; `PRESUBMIT_ARGS=--dry-run` lists them |
| `make ci-guards` | Checker tests, Markdown links, commit hygiene, secret scan (downloads Linux x64 tools) |
| `make docker-build` | Builds three images (api, mcp, dev UI) and validates the Compose config |
| `make audit-deps` | Online dependency advisories (uv); separate from the offline gates |

Before pushing, merge current `main`, commit, and run `make presubmit`; it
ignores uncommitted changes. Code changes also need `make check`; docs-only
changes need `make lint` and `.venv/bin/python -m pytest evaluations/tests -q`;
launch-wide changes also need `make docker-build`. Record each gate's real exit
status in the pull request ([CONTRIBUTING.md](CONTRIBUTING.md)).

**CI** ([docs/CI.md](docs/CI.md)): `ci.yml` runs on pull requests (a new push or
title/body edit cancels the running check) and on every push to `main` (all
jobs, never cancelled); `nightly.yml` calls it daily. Jobs are chosen by
`.github/ci_paths.json` through `scripts/select_targets.py`, as in presubmit; a
path no rule matches selects everything. The only required status is `Required
checks`; `.github/rulesets/main.json` allows squash merges only and does not
require an up-to-date branch, so merge `main` yourself. Tests never call live
models, fetch external URLs or retry. `benchmark.yml` is a manual live benchmark
that spends money; `prune-branches.yml` deletes branches unless `dry_run` is set.

## Rules no tool checks

The gates check layering, lint, types, links, secrets, licences and commit and
PR text. Nothing checks what follows.

### Operational invariants

Each is an incident's lesson; read its [OPERATIONS.md](docs/OPERATIONS.md) entry
before changing the code involved.

- Never VACUUM or run a truncating checkpoint from the serving process; while
  Litestream replicates, it owns checkpoints.
- Never hold a SQLite write lock across network I/O, never write on every poll
  tick, and never add a table that grows per task or per LLM call.
- Keep startup cheap; run recovery executes outside the port-binding path.
- Preserve durable task idempotency, leases, retry budgets and explicit
  recovery. Node keys persist in task types, checkpoints and idempotency keys;
  rename them only with a migration.
- Future-due queued tasks keep their run's cohort alive; log cursor IDs may
  have gaps.
- Steering admission permits one extra cycle to incorporate input before it is
  marked applied.
- No asyncio primitive may be shared between the worker cohorts' event loops.
- Every provider call goes through the LLM layer, so call ceilings and spend
  admission see it. Preserve bounded calls, budget escalation, admission
  reservations and spend caps. Lower a test envelope when a change lowers a
  tier; never raise one to make a test pass.
- Evidence gates distinguish missing, unsupported, contradictory and unsafe
  findings. Hypothesis lineage is append-only; provenance is per run.
- Source retrieval and model-written programs cross trust boundaries: keep the
  MCP URL guards, sandbox confinement, and no execution tools where
  confinement is unavailable.

### Production hosting

Keep in step with [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Hosting settings
live in the dashboards, not in this repository.

- Frontend and DNS on Cloudflare: Worker `open-coscientist` (`wrangler.jsonc`)
  serves `app/frontend/dist` through `app/frontend/worker.mjs` at
  https://open-coscientist.com; headers and CSP are in `public/_headers`.
- api and mcp in one Railway project, built from `Dockerfile.api` and
  `Dockerfile.mcp` on `main`, no start-command override. The API is
  https://api.open-coscientist.com; MCP is private-network only, port 8888.
  Merging to `main` deploys every service whose watched paths changed.
- With all four `LITESTREAM_R2_*` variables set, the API entrypoint restores
  from and replicates SQLite to Cloudflare R2; without them it serves directly.

Load-bearing; each was an outage or silent data loss:

- **The api runs at exactly one replica.** SQLite in WAL mode with
  `synchronous=NORMAL` is sound only with one writer; growing past one replica
  is a store migration, not a setting.
- **`RAILWAY_RUN_UID=0` stays set on the api.** Railway mounts a root-owned
  volume over `/app/data`; an unprivileged process cannot write the database,
  dies in its lifespan hook, and every deploy fails its healthcheck.
- **Caches stay off the volume.** `/app/data` holds only the SQLite database and
  its WAL and backup files (`Dockerfile.api`).

### Trust boundaries

- `main` is protected; change it only through a pull request. Treat
  https://api.open-coscientist.com, the Railway production environment, the
  Cloudflare Worker, DNS and the R2 bucket as protected. Use only the local
  ports above (browser suites: `:8108`, `:5273`) and the production domains.
- Keep out of commits and shared output: `.env`, `.env.local`, `app/.env`,
  `engine/mcp_server/.env`, provider keys and other secrets
  (`COSCIENTIST_MCP_SHARED_SECRET`, `LOGS_ADMIN_TOKEN`, `BYOK_ENCRYPTION_KEY`,
  `LITESTREAM_R2_*`), `coscientist.db` and its sidecars, caches, run outputs.
- `railway status`, `railway logs` and local read-only SQLite queries are
  routine. Confirm before `railway up`, `deploy`, `redeploy`, `run`, `down`,
  variable writes or service/environment deletion, and before any Cloudflare
  deploy or DNS, Worker or R2 change.

### Code, dependencies and documentation

- Use `Any` only for truly dynamic JSON. Contributions are Apache 2.0;
  preserve third-party notices.
- Regenerate the relevant `requirements/` lock when runtime dependency metadata
  changes; never edit lock hashes by hand. Reassess reachability (OPERATIONS)
  before mounting LiteLLM proxy routes or adding FastMCP OAuth or a disk-backed
  key/value store.
- **Hidden reasons only.** A comment or docstring survives only for a reason
  the code cannot show (why, an invariant, an outside fact), in about two lines.
  Delete Args/Returns/Raises blocks, narration, `Attributes:` lists and dated
  finding or ADR references; incident histories go to `docs/OPERATIONS.md` as
  their lesson. Test names carry the behavior. MCP tool docstrings and schema
  field descriptions are sent to the model, so they stay.

### Git hygiene

Never mention yourself or any other AI tool in commits, pull requests, pushes
or merge messages: no AI co-author trailers, no "Generated with" or "Created
by" lines. Messages read as written by the human developer.
`scripts/ci/git_hygiene.py` rejects tool names, attribution trailers, commit
subjects without `<type>(<scope>): ` and PR titles with such a prefix. It
matches tool names as whole words, so ordinary words such as "cursor" fail.

- Commits: `<type>(<scope>): <subject>`, type `feat`, `fix`, `docs`,
  `refactor`, `test` or `chore`, e.g. `fix(report-tab): handle missing markdown`.
  Branches: `<type>/<description>`, e.g. `fix/report-tab-empty-state`.
- PR titles are short, standalone and imperative with no type prefix (`Remove
  unused generate endpoints`); bodies say what changed, why, and how it was tested.
- **Squash merges.** A squash copies every branch commit message into the
  merge commit, so a trailer on a branch commit reaches `main` even when the PR
  body is clean. An empty squash body does not help: GitHub then fills in the
  branch commit messages. Always pass an explicit `<type>(<scope>): ` subject
  and a non-empty, neutral body, then read the merged message. Keep every
  branch commit clean; the checker never sees the squash message.

### Working preferences

- Preserve uncommitted work: never `git commit --amend`, `git reset`,
  `git stash`, `git checkout <file>` or `git restore <file>` over it; follow-ups
  are new commits. Before final gates, inspect `git reflog -5` and
  `git stash list`. Do not automate merges or other hard-to-reverse Git
  operations end to end; review both sides and the intended diff.
- Run the app and engine suites one after the other, with no leftover local
  `uvicorn`, and never re-run an unchanged full suite to reconfirm it. Run
  named gates directly and record their real exit status, not via a pipeline.
- Before calling a result unverifiable, inspect the primary source tree and
  record the evidence. Before declaring a production probe failed, fetch the
  artifact once and derive the assertion from its output.

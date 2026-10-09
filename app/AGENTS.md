# App — HTTP API, durable runtime, store and frontend

Read the [root AGENTS.md](../AGENTS.md) first. `app/` holds the React frontend
(`frontend/`), the backend test suite (`tests/`), local Docker Compose and
`dev/` scripts; it has no production Python. The server it tests lives in
`engine/src/co_scientist/` (package map in [engine/AGENTS.md](../engine/AGENTS.md)).
This guide covers that server's HTTP API, durable task runtime and SQLite
store. Backend paths below are relative to `engine/src/co_scientist/`.

## Backend

### Run and test

- From the root: `make dev-api` (`co_scientist.main:app --reload` on 8008, with
  `coscientist.db` at the root) and `make test-app` (pytest, four workers).
  `app/Makefile` has similar targets for an activated venv (`install`, `dev`,
  `start`, `test`, `format`, `lint`, `typecheck`), but its server keeps the
  database in `app/`, its `test` runs serially, and format and lint cover
  `tests/` only. `app/pyproject.toml` configures only tooling for `tests/`.
- Use a server without `--reload` (`app/Makefile`'s `start`) whenever a run
  may be in flight: `--reload` restarts on any edit under `engine/src/` and
  drops the embedded worker cohort mid-task.
- Production serves `co_scientist.serving:create_app` through
  `scripts/api-entrypoint.sh`; it wraps `main.app` in the trusted-proxy
  middleware ([docs/TRUSTED-PROXY.md](../docs/TRUSTED-PROXY.md)).
- Settings are `core/config.py` (pydantic-settings; reads `.env` from the
  working directory unless `PYTHON_DOTENV_DISABLED=1`, and `main.py` also loads
  the root `.env`). `COSCIENTIST_DB_PATH` (default `./coscientist.db`) is read
  in `platform/db/__init__.py`.
- Test harness: the autouse `isolated_db` fixture (`tests/conftest.py`) gives
  each test a temporary database, strips provider keys, sets the test double
  and an operator token. Use `tests/_client.py` (`make_client`,
  `make_operator_client`), the `fake_process_mode` fixture and
  `tests/_engine_tasks_helpers.py::FakeEngineTaskRuntime` rather than patching
  each consumer. Offline cost envelopes per tier are in
  `tests/test_run_envelopes.py`.

### Durable task execution

This is the real run path; nothing runs a workflow in-process.

- `POST /api/runs/{id}/start` (`api/runs/lifecycle.py`) enqueues
  `engine.bootstrap` into `scientific_tasks` and starts the run's worker cohort
  inside the API process. Resume and safety-hold release re-enter the same
  queue from the last checkpoint (`task_worker.enqueue_run_workflow`).
- Each node (`engine.node.<key>`), fan-out item and aggregate
  (`engine.fanout.{review,verification,reflection}.{item,aggregate}`,
  `engine.fanout.generation.{strategy,aggregate}`), tournament step
  (`engine.ranking.match`, `engine.ranking.finalize`) and `engine.finalize` is
  its own leased, idempotent task. Items restore the planning checkpoint and
  stop as superseded if it moved; the other tasks write checkpoints through
  `platform/db/checkpoints.py`. The vocabulary is in
  `orchestration/engine_tasks/support.py` and dispatch in its `__init__.py`.
  Lookahead and resume tasks key on `{task_type}:after:{predecessor_task_id}`.
- `orchestration/repository/tasks.py` is the queue: leases with heartbeat
  renewal, `idempotency_key` dedup, retry budgets, park, resume and cancel.
  Outcomes (`orchestration/task_worker/outcomes.py`): `LeaseLostError` writes
  nothing, `SupersededTaskError` completes as superseded, safety holds and
  `LLMRateLimitParkError` park, `UnsupportedTaskError` and
  `LLMCallBudgetExceededError` fail permanently, an `LLMTimeoutError` without
  zero-cost admission (an unknown provider outcome) fails the task and stops the
  run, and anything else retries within its budget. Nothing automatic revives a
  failed task.
- Each task builds its own `HypothesisGenerator`
  (`orchestration/engine_adapter/opts.py::build_generator`); none is held across
  requests. `orchestration/engine_tasks/runtime.py` is the seam for what a task
  calls outside the store, and tests install `FakeEngineTaskRuntime` there.
- `main.py`'s lifespan installs log capture and tracing, prunes superseded
  checkpoints (`_reclaim_disk_space`, never VACUUM), reconciles interrupted runs,
  starts recovery off the startup path and seeds the three example runs from
  `domains/chat/data/demo_runs.json.gz`. Shutdown releases leases and
  checkpoints the WAL unless Litestream is active.
- Final state goes through `orchestration/drain.py::persist_final_state`;
  `orchestration/engine_tasks/report_finalize.py` runs the final safety gate and
  emits the report.

### Store (`platform/db/`)

- One SQLite writer: WAL, `synchronous=NORMAL`, `BEGIN IMMEDIATE` transactions
  (`platform/db/__init__.py`). Callers import the defining leaf modules. A
  column added to a deployed table must also be listed in
  `schema.ADDED_COLUMNS`. Run events are append-only.
- `worker_pool_size` (default 8) bounds how many tasks one run executes at
  once. The limit is the single SQLite writer, not the provider; at 12 across
  several runs the write lock saturated. The load-tested production width is 1
  (OPERATIONS "If traffic spikes").

### Requests, ownership and admission

- Identity is the anonymous per-browser `X-Client-ID` (`api/auth.py`; no
  accounts, `Authorization` ignored). `main.enforce_run_ownership` answers
  **404, not 403**, for another client's run, so a "missing" run is usually an
  ownership mismatch: send a consistent `X-Client-ID` before concluding data
  is gone. Example runs are readable; mutating one returns 403 except
  `POST .../example-chat`, which copies it.
- Operators send `X-Logs-Token` equal to `LOGS_ADMIN_TOKEN`
  (`api/operator_access.py`); a loopback address grants nothing. Operator-only:
  the app-wide log view, health and status detail, `/api/spend`,
  `/api/launch-control` and safety adjudication. API docs are not served.
- Refusals that look like bugs: 503 `launch_paused` (`api/launch_admission.py`)
  while an operator has paused launch; 413 and 429 from `api/request_limits.py`
  (256 KB JSON, 26 MB uploads, daily write budgets); 410 for an erased identity;
  409 on start when active runs reach `max_concurrent_runs` (10, per client and
  across the instance) or `concurrent_runs_per_host` (10).
- Run size comes from the tier: `core/run_modes/__init__.py::RUN_TIER_DEFAULTS`
  (express, standard, extended, ultra) scales hypotheses, iterations,
  evolution, matches, evidence, finalists and `max_llm_calls`. Numeric
  overrides may only raise a baseline; `focus` adds prompt guidance.
- A run without a BYOK key must be Express and takes a `free_run_usage` slot
  (`domains/access/free_usage.py`: 3 per client per UTC day, with host and
  global caps); deleting the run does not return it. BYOK headers
  (`X-LLM-API-Key`, `X-LLM-Provider`, optional model and supervisor headers)
  need `BYOK_ENCRYPTION_KEY`; off-catalog models are validated with the user's
  key (`domains/access/byok_models.py`).
- App model calls (interview, Q&A, titles, run-start announcement, credential
  probes) go through `platform/llm/llm_request.py` with their own budget
  (`platform/llm/llm_scope.py`, `APP_LLM_MAX_CALLS`, default 4). Streams bound
  silence and total duration separately (`llm_scope.stream_chunks`).
- Safety: deterministic hard blocks run first. The optional semantic assessor
  may only resolve a Tier B "needs context" hold, and any assessor failure
  leaves the hold standing (`domains/safety/hypothesis/safety.py`).
- Completion email is disabled: the enqueue and delivery hooks in
  `orchestration/notifications.py` are no-ops, and nothing calls the SMTP
  sender that remains there.

### Routers

`main.py` mounts `api/runs/` (`/api/runs`: `crud.py`, `lifecycle.py`,
`collections.py`, `chat.py`, `contrib.py`), `api/interviews/`,
`api/documents.py`, `data_rights`, `free_usage`, `byok_models`, `logs_api`,
`spend_api`, `feedback_api`, `diagnostics_api` (`/`, `/health`, `/status`),
`launch_control_api` and `sentry_alerts`. Read the router for its routes.
`GET /api/runs/{id}/events` streams events over SSE with replay;
`POST /api/runs` honours an `Idempotency-Key`; a run's research goal cannot be
edited; documents staged at `/api/documents` before a run exists are copied
into it on create. The `/status` web-search probe asks the MCP server's
`check_web_search_available` rather than whether `search_web` is listed (older
servers without that tool fall back to presence).

### Logs

`app_logs` is one durable, app-wide log (`platform/db/log_capture.py`,
`platform/telemetry/capture_queue.py`, `api/logs_api.py`). Records below
WARNING from per-call loggers (`UNPERSISTED_LOGGERS`) are dropped, because
each row is a write on the single writer; verbatim repeats are suppressed for
10 minutes per logger, level, run and message. Fix a new flood by repetition,
never by deny-listing its logger. `GET /api/logs` is scoped: operators see
everything, other callers only what they submitted or what belongs to their
runs, so the frontend sends `clientHeaders()` on every read and write.

### Wire contracts

Edit `api/contracts/` for run, artifact, report and interview JSON shapes; the
status, feedback and client-log models in `api/diagnostics_api.py`,
`api/feedback_api.py` and `api/logs_api.py` are also exported
(`generate.py::MODEL_GROUPS`). From the repository root run
`.venv/bin/python -m co_scientist.api.contracts.generate`, then format the
generated `frontend/src/shared/api/wire_*.ts` with the frontend linter.
`tests/test_architecture.py` fails when generated files drift or a contract
name is declared by hand. Plain-dict payloads (log reads, free usage) stay
hand-typed.

## Frontend (`frontend/`)

React 19, Vite 8, TypeScript, Tailwind v4, Vitest; Bun; gts (ESLint and
Prettier). From `app/frontend/`: `bun install`, `bun run dev` (5173, proxies
`/api`, `/status` and `/health` to 8008), `bun run build` (`tsc`, `vite build`,
prerender), `bun run lint`, `bun run fix`, `bun run test`. Tests are colocated
`*.test.ts(x)` (setup `src/test_setup.ts`, config in `vite.config.ts`).

- `VITE_API_BASE_URL` sets the API origin; unset, the client uses same-origin
  paths. Only `VITE_*` values reach the build; never put a backend secret there.
- `src/app/` is the composition root (`workbench_app.tsx` routes, layout,
  header, rail). Features are `src/features/{access,chat,diagnostics,legal,report,runs}/`;
  shared code is `src/shared/{api,hooks,lib,testing,ui}/`. Lint
  (`eslint.config.cjs`) stops access, chat, diagnostics, report and runs from
  importing `@/app`, each other or `../`, and `shared` from importing app or
  features; `legal` is not covered. Tailwind scans only the `@source` folders
  in `index.css` (not `shared/lib`), so a new top-level folder must be listed
  there or its classes vanish.
- Routes: `/` (chat home, with the landing below it on wider screens),
  `/chats/:id`, `/examples/:id`, `/runs/:id/:tab` (bare `/runs/:id` goes to
  `details`; tabs and legacy aliases resolve through
  `shared/lib/run_tabs.ts::normalizeTab`), `/operations`, `/operations/spend`,
  `/privacy`, `/terms`, and `*` (404). `shared/lib/routes.ts` builds paths.
- HTTP lives in `shared/api/`: `runs.ts` holds the fetch primitives, SSE,
  `clientHeaders()` (`X-Client-ID`) and BYOK headers, and `fetchWithSession` is
  the only raw `fetch`. Generated `wire_*.ts` own the contract types and
  `runs.ts` re-exports them. `shared/ui/icon.tsx` is generated by
  `scripts/generate_icons.mjs`.
- Run detail (`features/report/`): `run_detail.tsx` routes the four tabs,
  `run_detail_active.tsx` replaces them while a run is in flight, data comes
  from `run_detail_data.ts`, and shell and document primitives are in
  `run_detail_shell.tsx`. Model prose renders through
  `shared/ui/markdown_message.tsx`; its lazy renderer owns Markdown parsing and
  the raw-HTML policy, so keep heavy imports behind it.
- Chat (`features/chat/`): `use_chat_session.ts` is the session state machine
  (draft, confirmed, started run spec) and delegates to `chat_session_*.ts`.
  Clickable answers (`chat_questions.tsx`) are an affordance, never a gate.

### Design invariants

- Material 3 roles derive from `MD3_SEED` `#1A6B6B` in
  `shared/ui/md3_scheme.ts`, whose test fails until the precomputed schemes are
  regenerated from the seed; never hardcode `--md-sys-color-*`. `index.css`
  bridges those roles as `--color-th-*` and the `--cosci-*` tokens as
  `--color-cosci-*`; use the named utilities.
- `main.tsx` imports sheets in order: `index.css`, `styles/tokens.css`,
  `shell_surface.css`, `home_surface.css`, `home_landing.css`, `tooltips.css`,
  `boot_skeleton.css`, `shared/ui/motion.css`, so tokens precede consumers.
- Add paired light and dark tokens in `tokens.css`, never an inline dark hex.
  Theme swaps update both palettes; verify shared UI in both themes.
- `rounded-md` (6px) for data blocks, `rounded-xl` (12px) for interactive
  containers, `rounded-full` for pills; a bare `rounded` is 8px. Cards and
  inputs use tonal layers, not shadows; elevation is for overlays.
- Breakpoints are the `index.css` variants `phone:` (≤700px, equal to
  `MOBILE_MEDIA_QUERY` in `shared/hooks/dom.ts`), `above-phone:`, `tablet:`
  (701–1180px) and `desktop:` (≥1181px). CSS files are not linted, so keep
  their media queries in step by hand.
- Page stacking uses the named layers (`z-header` < `z-drawer-scrim` < `z-rail`
  < `z-dialog-scrim` < `z-dialog` < `z-toast` < tooltips); a small integer
  orders children inside one component only.
- `index.css` gives every focused control except text entry a 2px `th-ring`
  outline; a component may restyle it but never remove it.
- There is no Tailwind preflight; report Markdown relies on browser-default
  spacing, so reset individual components, never globally.
- Motion durations and curves are tokens. Overlays enter with
  `@starting-style` and leave through `usePresence` (`EXIT_MS`). Never delay
  input, focus or content; keep everything but progress under 300 ms and honour
  reduced motion. Tests wait for an overlay's role or removal, never sleep.

### UI building blocks

New UI composes `src/shared/ui/` (import from `@/shared/ui`). Shape, radius,
colour, focus ring and motion live in the component; a call site passes only
layout (`layoutClassName`). Outside `src/shared/ui/` and tests, lint rejects a
raw `<button>`, hex, `rgb()` or `hsl()` colours, arbitrary radii, `z-[…]`,
`[&:hover]:`, arbitrary spacing, hand-written phone breakpoints and native
`title`. Colours come from component tokens in `styles/tokens.css`, which a
surface with its own palette re-points in its own scope.

| Need | Use |
|---|---|
| Action | `Button`: `filled` for the one primary action, `outlined` for its alternatives, `tonal` for header and toolbar pills, `text` for low emphasis, `link` inline; also `accent` and `disclosure`. Sizes `sm`, `md`, `lg`. `buttonClasses()` styles a router `Link`. |
| Icon-only action | `IconButton`, round, `ghost` or `elevated`; sizes `xs`, `sm`, `md`. `label` is required and becomes the tooltip. |
| Modal | `Dialog` (`md` form, `lg` Settings): portals, traps focus, inerts the background, closes on Escape and scrim, restores focus. |
| Popup list | `Menu` + `MenuItem` (`item`, `radio`, `checkbox`). |
| Choose from a list | `Select`: a field-styled trigger over `Menu` that flips above when there is more room and groups options. |
| One value in place | `SegmentedControl` (`md` shell, `lg` landing); `SectionNav` for the sections of one surface. |
| Route sections | `TabNav` + `TabNavLink` (`underline` for report sections, `pill` for the session switch), real links with `aria-current`. |
| Hint | `tooltip` on `Button`/`IconButton`, `Tooltip` for other content; never native `title`. |
| Label or status | `Chip`: `tonal` or `outlined`; tones `neutral`, `info`, `success`, `accent`, `warning`, `danger`; sizes `xs` to `lg`. |
| Text input | `TextField` / `TextArea`, `outlined` or `bare` inside a surface that draws the box. |
| Grouping surface | `Card`: `block`, `tile` or `panel`; tones `neutral`, `raised`, `warning`, `danger`. `CardButton` is a card that is one action. |
| Link off the app | `ExternalLink`: new tab, `rel="noopener noreferrer"`, and its `fallback` for anything but `http(s)` or `mailto` (model-written URLs reach it). |
| Status, error, loading | `StatusText` (`muted`, or `danger` as an alert), `ErrorNotice` for a blocking failure, `DocumentSkeleton` or `Skeleton` shapes in a `SkeletonRegion`. Reds come from `cosci-danger-*`. The boot skeleton in `index.html` has its inline script's hash in the CSP in `public/_headers`. |
| Rail destination | `NavItemButton` / `NavItemLink`. |

## Docker Compose

`app/docker-compose.yml` runs `api`, `ui` and `mcp` for local work and needs
`app/.env`. Its api image is `app/docker/Dockerfile.api` with
`app/docker/entrypoint.sh`, which installs the engine mounted at
`/workspace/co-scientist-engine` (the repo's `engine/` by default; otherwise it
clones `COSCIENTIST_ENGINE_REPO` at `COSCIENTIST_ENGINE_REF`). That is a
different file from the root `Dockerfile.api` that production bakes, so
container changes usually need both. The SQLite store persists in `./data`.
api and mcp run with `--reload`, a dev-only trade-off never carried into the
production images. `make docker-build` validates the Compose config.

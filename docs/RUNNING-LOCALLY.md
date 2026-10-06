# Running locally

## Prerequisites

- Python 3.12 for the complete application and MCP service. The internal
  engine package supports Python 3.10+.
- Node.js 22.13+ for frontend tooling and Bun 1.3.14 for the committed locks.
  Install Bun from [the official instructions](https://bun.sh/docs/installation)
  and select `bun upgrade --version 1.3.14` if necessary.
- Optional provider credentials for real model responses. No key is needed
  to exercise the deterministic offline pipeline.
- Optional Tesseract for image OCR and scanned-document extraction.
  The production API image includes it.

## Start a checkout

From the repository root:

```bash
make setup
make start
```

`make setup` installs the local engine and viewer into `.venv`, installs
frontend dependencies from `bun.lock`, copies `.env.example` when `.env` is
missing, and links `app/.env` to that root file. Existing `.env` files are
preserved. Edit the root file for API settings. The MCP service uses the
separate `engine/mcp_server/.env`; its provider keys do not come from the
API's environment file.

`make start` installs missing dependencies, frees the three development
ports, launches the services, and opens the workbench once it is ready.
It stops existing listeners on those ports; reserve them for this checkout.

| Service | Address | Notes |
| --- | --- | --- |
| Workbench | http://localhost:5173 | Vite proxies API requests to port 8008 |
| API | http://localhost:8008 | Local operator docs at `/docs` |
| MCP | http://localhost:8888 | Literature/database tools; Python 3.12 required |

Use `make stop` to stop the development services. Run individual services
with `make dev-api`, `make dev-ui`, and `make dev-mcp` in separate terminals.
The API uses hot reload; an edit can interrupt an active task. For a stable
backend during a run:

```bash
cd app
COSCIENTIST_DB_PATH=../coscientist.db ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8008
```

Do not expose the development stack publicly. See [launch guidance](LAUNCH.md)
and [DEPLOYMENT.md](DEPLOYMENT.md) for authenticated hosting.

## Model and retrieval configuration

The default system model is `openrouter/inclusionai/ling-3.1-flash` and needs
`OPENROUTER_API_KEY`. Setting only another provider's key does not select its
model: set the appropriate `MODEL_NAME` and role overrides too.
Inspect `/status` for the selected backend and retrieval availability.

`COSCIENTIST_FORCE_OFFLINE=1` withholds deployment-funded model calls.
An explicit BYOK request can still use the scientist's own credential.
Offline mode applies to model calls; MCP retrieval may still contact public
scientific services. The test harnesses isolate their state and mock or
withhold external calls.

MCP configuration is documented in
[`engine/mcp_server/.env.example`](../engine/mcp_server/.env.example).
PubMed can retrieve anonymously; `ENTREZ_EMAIL` is an optional courtesy
identifier and a valid API key can raise source rate limits. Live literature
availability is determined by reachability, not the presence of an email.

## Validate changes

```bash
make check         # lint, types, suites, evaluations, smoke, build, browser tests
make docker-build  # production image builds; no deployment
```

`make test-all` includes backend and frontend unit tests and the evaluation harness tests.
`make e2e` runs Playwright with a fresh temporary SQLite store, offline model
responses, API port 8108, and UI port 5273. `make e2e-production` builds the
frontend and serves its bundled assets with required researcher authentication.
It checks login, report retrieval after a reload, and ownership isolation.
Both targets typecheck the browser harness, disable local dotenv loading,
and explicitly select offline evidence/claim checks. Chromium is normally
installed
through Playwright. To use an already installed browser when downloads are
unavailable:

```bash
COSCI_E2E_CHROMIUM_EXECUTABLE=/usr/bin/chromium make e2e
```

That override can differ from the Chromium revision used in CI. CI uses the
Playwright-managed browser. Port overrides are `COSCI_E2E_API_PORT` and
`COSCI_E2E_UI_PORT`. Run the targets sequentially when using the same ports.
The production browser target builds into its temporary state directory and
leaves the normal frontend `dist/` artifact untouched. Vite preview tests built
assets and browser flows; it does not verify Vercel or Railway routing and
configuration.

## Worktrees

Each worktree needs its own dependencies and environment because Git does not
copy ignored `.env`, `.venv`, databases, or `node_modules` directories.
Run `make setup` inside the worktree. Copy an existing `.env` only when you
intend to reuse those credentials. Keep its SQLite store separate.
Do not reuse an editable engine install from another checkout: it imports
that checkout's source and can make a test exercise the wrong branch.
Only one development stack can use the default ports at a time.

## Local data

The root development database is `coscientist.db`; reports and caches are
ignored. Deleting these is separate from dependency cleanup. Before a reset,
make a backup using [the backup procedure](LAUNCH.md#backup-and-restore).
`make reset-db` deletes the local store, and `make clean` removes development
virtual environments, frontend dependencies/build output, and local caches.

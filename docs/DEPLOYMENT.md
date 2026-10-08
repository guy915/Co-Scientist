# Deployment (production hosting)

How the deployed services are built and configured. The load-bearing
invariants are also summarised in the [root AGENTS.md](../AGENTS.md)
Production hosting section; keep the two in sync when either changes.

[LAUNCH.md](LAUNCH.md) covers release validation, backup and restore, and
repository publication. Deployment settings live in the hosting dashboards,
not in this repository; read the intended environment back before relying on
any value below.

## Services

| Layer | Platform | URL |
|---|---|---|
| Frontend (Vite/React) | Cloudflare Worker `open-coscientist` with static assets (Vercel until launch) | https://open-coscientist.com |
| API (FastAPI) | Railway service `api` | https://api.open-coscientist.com |
| MCP server | Railway service `mcp` | private network only, port 8888 |

The repository carries both frontend configurations until launch:
Cloudflare (`wrangler.jsonc`, below) and Vercel (`vercel.json`), which the
launch removes. The API and MCP run in one Railway project with exactly one
API replica. Production starts with an empty database.

The worker runs embedded in the API process; there is no separate worker
service. The single-writer SQLite store bounds worker width
(`worker_pool_size`, see `app/AGENTS.md`).

## Images

Both Railway services build from the repository's root Dockerfiles
(`Dockerfile.api`, `Dockerfile.mcp`). They install the hash-pinned runtime
closures in [`requirements/`](../requirements/README.md) before installing
local source without dependency resolution, and pin the base image by digest.
Build contexts exclude local secrets, databases, session notes and generated
artifacts; keep those exclusions when adding an image or context.

- **API.** The entrypoint (`scripts/api-entrypoint.sh`) honors Railway's
  injected `PORT` (default 8008) and passes `--timeout-graceful-shutdown 20`
  so open SSE streams cannot hold shutdown until the platform kills the
  process; keep the Railway draining window at least that long. With the four
  `LITESTREAM_R2_*` credentials set it runs the API under Litestream (below);
  without them it serves directly. The image has a `HEALTHCHECK` on `/health`, installs
  `tesseract-ocr` (image and PDF-figure OCR; uploads fail without it, and the
  test suite fakes the dependency), and defaults `COSCIENTIST_DB_PATH` to
  `/app/data/coscientist.db`, the persistent volume mount.
- **MCP.** Deliberately ignores `PORT` and pins 8888, binding `--host ::` for
  Railway's IPv6 private network. Its healthcheck probes `[::1]:8888`, since
  a 127.0.0.1 probe can miss an IPv6-only socket. It runs as the unprivileged
  `coscientist` user.
- Railway's healthcheck gates only the deploy going live; nothing on Railway
  polls it afterwards ([MONITORING.md](MONITORING.md) covers uptime). A
  service with a volume cannot run two deployments at once, so an API deploy
  has a short gap and never overlaps two writers.

### Invariants: do not clean these up

**`RAILWAY_RUN_UID=0` must stay set on the API.** Both images create a
non-root `coscientist` user, but Railway mounts the volume over `/app/data` at
runtime as a root-owned filesystem that the image's `chown` cannot reach. An
unprivileged API cannot write SQLite, dies in its lifespan hook before
binding a port, and every deploy fails its healthcheck regardless of content.
Making the API genuinely unprivileged needs a root entrypoint that chowns the
mounted volume and then drops privileges.

**The API runs at exactly one replica.** The store is SQLite in WAL mode with
`synchronous=NORMAL` (`platform/db/__init__.py`). That pairing never corrupts
the database but can lose the last few commits on an OS crash, a trade that
is only sound single-writer. Nothing in the code refuses a second replica,
and a second process writing the same file is unserialized concurrent
writes that WAL locking does not make safe across volume backends. Growing
past one replica is a store migration (Postgres or similar), not a tuning
knob. See [OPERATIONS.md](OPERATIONS.md).

## Frontend

Both hosts serve the same build: `cd app/frontend && bun run build` (`tsc`,
`vite build`, prerender) into `app/frontend/dist`, installed with
`bun install --frozen-lockfile`. Build-time variables (read at build, not
runtime): `VITE_API_BASE_URL=https://api.open-coscientist.com`, and
`VITE_SENTRY_DSN` when error tracking is on (see
[MONITORING.md](MONITORING.md)). Only `VITE_` variables belong on the
frontend host; everything there is compiled into public assets.

- **Cloudflare** (`wrangler.jsonc`): a Worker (`app/frontend/worker.mjs`)
  serves the `dist` assets and answers any missing path outside `/assets/`
  with `/index.html`, so deep links load the app while a missing hashed asset
  stays a 404 instead of returning HTML. `app/frontend/public/_headers` sets
  the headers below. CI checks the config and runs `worker.test.mjs`.
- **Vercel** (`vercel.json`): the same rewrite and headers, plus an
  `ignoreCommand` that skips the build when neither `app/frontend` nor
  `vercel.json` changed.
- Headers: `/assets/*` is cached for a year and immutable; every path sends
  `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`,
  `X-Frame-Options: DENY`, and a `Permissions-Policy` that denies camera,
  microphone, geolocation and payment.

## Database replication (optional)

Setting `LITESTREAM_R2_BUCKET`, `LITESTREAM_R2_ENDPOINT`,
`LITESTREAM_R2_ACCESS_KEY_ID` and `LITESTREAM_R2_SECRET_ACCESS_KEY` on the
API (optionally `LITESTREAM_R2_PATH`, default `api/coscientist`) turns on
continuous replication of the SQLite file to Cloudflare R2 (`litestream.yml`).
On start the entrypoint restores the database from the replica only when the
volume has none, and fails closed on a network or corrupt-backup error rather
than starting empty. While Litestream runs, the API disables SQLite's
automatic and shutdown checkpoints and the config keeps the WAL high-water
mark (`truncate-page-n: 0`), because Litestream owns checkpointing and a
truncating checkpoint can stall serving writers. Replication does not replace
tested restores ([backup and restore](LAUNCH.md#backup-and-restore)).

## API configuration

Non-secret routing and storage variables on the `api` service:

```
MCP_SERVER_URL=http://<mcp-private-host>:8888/mcp
COSCIENTIST_DB_PATH=/app/data/coscientist.db
RAILWAY_RUN_UID=0                                  # must stay set
ALLOWED_ORIGINS=https://open-coscientist.com
```

- **CORS.** `ALLOWED_ORIGINS` is a comma-separated allowlist and enables
  credentialed CORS. When unset, `main.py` uses `DEFAULT_ALLOWED_ORIGINS`
  (the local dev origins and, until launch, the new and old public sites).
  Set it explicitly to an empty
  value and the API falls back to `Access-Control-Allow-Origin: *` without
  credentials, so any origin can call it from a browser.
- **Models.** The defaults are declared in
  `engine/src/co_scientist/core/config.py` and the per-model facts (routing,
  fallbacks, price) in `engine/src/co_scientist/platform/llm/profile/`.
  Production can override the four role variables (`MODEL_NAME`,
  `SUPERVISOR_MODEL_NAME`, `CHAT_MODEL_NAME`, `SEMANTIC_SAFETY_MODEL`); a
  default change reaches production only when those variables are unset or
  changed. Leave `CLAIM_VERIFIER_MODEL` unset so claim assessment inherits the
  worker model, and keep `COSCIENTIST_REQUIRE_FREE_MODELS` off so explicit
  BYOK stays available.
- **Secrets** (values never enter this repository or document): the provider
  keys (`OPENROUTER_API_KEY`, and any other provider in use), the SMTP
  credentials, and:
  - `BYOK_ENCRYPTION_KEY`, which encrypts bring-your-own-key credentials for
    the run lifetime; BYOK is unavailable without it.
  - `LOGS_ADMIN_TOKEN`, the operator token for the app-wide persisted-log
    view, sent as `X-Logs-Token`. Without it, only loopback callers get that
    view.
- **MCP shared secret.** `COSCIENTIST_MCP_SHARED_SECRET` must be identical on
  both services. When set, every MCP call except the plain `/` status route
  must carry it in `X-MCP-Shared-Secret` or receive 401
  (`engine/mcp_server/auth_middleware.py`); the engine client adds the header
  (`platform/retrieval/mcp_client/__init__.py`). Unset on both, the check is
  a no-op. Read back its presence on both services without exposing it. MCP
  is server-to-server only and allows no browser origin.
- **MCP service variables:** `COSCIENTIST_MCP_PORT=8888`, the search keys
  (`WEB_SEARCH_PROVIDER` with `BRAVE_API_KEY` or `TAVILY_API_KEY`),
  `OPENALEX_API_KEY`, and `ENTREZ_EMAIL`/`ENTREZ_API_KEY`; see
  `engine/mcp_server/.env.example`.

### Science skills

The skills bundle is enabled on the API image and only for hypothesis
drafting. `Dockerfile.api` copies `vendor/science-skills/` and sets
`COSCIENTIST_SKILLS_DIR`; keep the COPY and the ENV together, because the
variable is the entire gate and the catalogue is empty without it.
`WorkspaceSession.skills_enabled` defaults off and only the drafting pass
sets it (the simulation reviewer measured worse with the bundle). Scripts run
under a purpose-built interpreter at `/app/skills-venv/bin/python`
(`COSCIENTIST_SKILLS_PYTHON`) built with `polite-http` and `python-dotenv`;
`uv run` cannot work because uv's cache holds a `.git` directory the sandbox
refuses. The heavy AlphaGenome and Predicting-the-Past closure is
deliberately not installed, and the catalogue withholds skills whose
dependencies or scripts are absent rather than advertising them. Script
execution also needs the cgroup boundary below. Rationale: `engine/AGENTS.md`.

### Completion email

Public completion emails are withheld until recipient verification and
durable delivery admission exist, even with SMTP configured. The private
transport is stock `smtplib` over STARTTLS in
`co_scientist.orchestration.notifications`; with Resend as the relay:

```
SMTP_HOST=smtp.resend.com
SMTP_PORT=587                                      # STARTTLS; 465 (implicit TLS) is not supported
SMTP_USERNAME=resend                               # literal, not an address
SMTP_PASSWORD=<resend api key>
SMTP_FROM_EMAIL=notifications@open-coscientist.com # domain must be verified in Resend
PUBLIC_APP_URL=https://open-coscientist.com        # base of the run link in the mail
```

`PUBLIC_APP_URL` defaults to `http://localhost:5173`, so SMTP settings alone
mail a link that resolves to nothing; `/status` reports
`email_notifications_available=false` regardless.

### Generated commands

Generated draft programs have no network access; source retrieval uses the
guarded MCP boundary. Linux confines each command with Landlock (explicit
workspace and immutable runtime read roots), seccomp, and its own cgroup v2
with a 512 MiB memory, 64-process and one-CPU ceiling. Descendants join the
cgroup before untrusted code starts and are killed on completion, timeout,
cancellation or workspace close. Set `COSCIENTIST_CGROUP_ROOT` only to a
writable, operator-delegated cgroup v2 subtree providing `cgroup.kill`,
`memory.max`, `pids.max` and `cpu.max`. Landlock needs Linux 5.13+ with the
LSM enabled.

Verify both capabilities:

```
python -c "from co_scientist.platform.sandbox import sandbox_backend, command_lifecycle_available; print(sandbox_backend(), command_lifecycle_available())"
```

A filesystem backend alone does not enable execution. When either capability
is missing (including macOS without a lifecycle boundary), command tools and
runnable skills are withheld and research continues without generated
programs. Do not assume Railway delegates cgroups, and do not grant the API
broad host privileges to make the probe pass.

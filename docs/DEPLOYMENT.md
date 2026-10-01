# Deployment (production hosting)

How the three deployed services are built and configured. The load-bearing invariants are also summarised in the [root AGENTS.md](../AGENTS.md) Production hosting stub — keep the two in sync when either changes.

Use [LAUNCH.md](LAUNCH.md) for release validation, public authentication,
backup and restore, and repository publication requirements. Deployment
settings and receipts below include dated historical snapshots; read back
the intended environment before treating any of them as current.

The production images install the hash-pinned Python runtime closures in
[`requirements/`](../requirements/README.md) before installing local source
without dependency resolution. Build contexts exclude local secrets,
databases, session notes, and generated artifacts. Keep these exclusions
when adding a new image or build context.

The app is deployed as three services:

| Layer | Platform | URL |
|---|---|---|
| Frontend (Vite/React) | Vercel — project `co-scientist-ui` | Public: https://ai-co-scientist.com/; Vercel deployment: https://co-scientist-ui.vercel.app |
| API (FastAPI) | Railway — service `api` | https://api-production-97eb.up.railway.app (custom domain https://api.ai-co-scientist.com also live) |
| MCP server | Railway — service `mcp` | internal only (`mcp.railway.internal:8888`) |

**Railway project**: `co-scientist` (id `74f2b037-0094-49d2-b645-4849991234af`), environment `production`.

Both Railway services build from `guy915/Co-Scientist` using repo-root Dockerfiles (`Dockerfile.api`, `Dockerfile.mcp`). The api service has a persistent volume mounted at `/app/data` (the SQLite DB — **not** the cache; see below); both images now default `COSCIENTIST_DB_PATH`/`COSCIENTIST_CACHE_DIR` (api) to that same layout in the Dockerfile itself, so a deployment that forgets to set them still gets a correct, non-ephemeral default — Railway's own values simply override. The api honors Railway's injected `PORT`; the **mcp image deliberately ignores it** and pins 8888, binding `--host ::` for Railway's IPv6 private network with a healthcheck against `[::1]:8888` (a 127.0.0.1 probe can miss the socket on IPv6-only kernels). Both images declare a non-root `coscientist` user (ownership is `chown -R`'d before the final `USER` switch, since a later chown from an unprivileged user would fail), but **only the mcp service actually runs unprivileged** — the api sets `RAILWAY_RUN_UID=0`, which overrides the image's `USER` and runs it as root. That is not an oversight to clean up: Railway mounts the api's persistent volume over `/app/data` at *runtime*, replacing the image's chown'd directory with a root-owned filesystem, so an unprivileged process cannot write the SQLite database. The app then dies in its lifespan hook with `attempt to write a readonly database` before binding a port, the healthcheck fails for its whole retry window, and the deploy is rejected — the api ran 0/1 replicas for ~20 hours the first time the `USER` switch shipped, and every push during that window failed the same way regardless of its content. Railway documents the caveat and `RAILWAY_RUN_UID=0` as its remedy. Do not "restore" non-root on the api by deleting that variable; making it genuinely unprivileged requires a root entrypoint that chowns the mounted volume and then drops privileges. Both images pin their base image (`python:3.12-slim@sha256:...`) by digest rather than the mutable `3.12-slim` tag, so the same source always builds the same image; the api image also carries a `HEALTHCHECK` against `/health` and installs `tesseract-ocr`, which `document_ingest.py`'s image-OCR and PDF-figure-OCR paths need — without it every image/scanned-figure upload fails with "image OCR is unavailable" in a way no test caught, since the test suite fakes the dependency.

**The science skills are enabled on the api image, and only for hypothesis drafting.** `Dockerfile.api` copies `vendor/science-skills/` and sets `COSCIENTIST_SKILLS_DIR=/app/vendor/science-skills/skills`; the COPY and the ENV must stay together, because the env var is the *entire* gate — the engine's catalogue is empty unless it points somewhere, which is why a checkout, a test and a CI job all behave as if skills never existed. Setting it does not arm every consumer: `WorkspaceSession.skills_enabled` defaults off and only the drafting pass asks for it, which matters because the simulation reviewer was measured *worse* with the same bundle. The scripts run under a purpose-built interpreter at `/app/skills-venv/bin/python` (`COSCIENTIST_SKILLS_PYTHON`), built at image time with `polite-http` and `python-dotenv` — the bundle's `uv run` instruction cannot work here, since `uv`'s cache holds a `.git` directory the sandbox refuses. The heavy AlphaGenome/Predicting-the-Past closure (52 packages, 695 MB) is deliberately not installed; enabling those six scripts is a separate image decision. The catalogue withholds what it cannot run rather than advertising it: two skills for absent dependencies and four that ship no script at all (`pymol`, `uv`, `credentials`, `workflow_skill_creator`), leaving 32 offered. Nothing needs setting on Railway for any of this. Full rationale and the measurements: `engine/AGENTS.md`.

**Decided: production runs the worker embedded in the API process, not a separate worker service.** `COSCIENTIST_EMBEDDED_WORKER=1` is what the api service actually runs on today (see the env list below), and the three-service table above is the complete deployed shape — there is no fourth "worker" service. `python -m app.task_worker` with `COSCIENTIST_EMBEDDED_WORKER=0` on the api remains a supported code path (see `runs/lifecycle.py` / `task_worker.py`) for the day the single-writer SQLite ceiling (`worker_pool_size`, see the root AGENTS.md Gotchas and the Notable settings section of `app/AGENTS.md`) actually requires scaling workers independently of the api — it is not a recommendation to run that way today, and nothing in this deployment does.

The Railway **api** service's non-secret routing and storage settings, read back
on 23 September 2026 **before** the M2 release, are a historical snapshot, not
a current production readback:

```
MODEL_NAME=openrouter/minimax/minimax-m3:free
SUPERVISOR_MODEL_NAME=openrouter/minimax/minimax-m3:free
CHAT_MODEL_NAME=openrouter/minimax/minimax-m3:free
SEMANTIC_SAFETY_MODEL=openrouter/minimax/minimax-m3:free
MCP_SERVER_URL=http://mcp.railway.internal:8888/mcp
COSCIENTIST_DB_PATH=/app/data/coscientist.db
COSCIENTIST_CACHE_DIR=/tmp/coscientist-cache   # deliberately OFF the volume
COSCIENTIST_EMBEDDED_WORKER=1
RAILWAY_RUN_UID=0                                 # must stay set -- see the non-root note above
ALLOWED_ORIGINS=https://ai-co-scientist.com,https://www.ai-co-scientist.com
PORT=8008
```

The API has `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, and operational/SMTP
credentials configured; their values must never enter this document. The **mcp**
service has `BRAVE_API_KEY`, `TAVILY_API_KEY`, `OPENALEX_API_KEY`,
`ENTREZ_EMAIL`/`ENTREZ_API_KEY`, `WEB_SEARCH_PROVIDER=tavily`, and
`COSCIENTIST_MCP_PORT=8888`. Pre-release, neither service has
`COSCIENTIST_MCP_SHARED_SECRET`, and the API has no `CAMPAIGN_RESEARCHER_IDS`.
The M2 release must set the **same new secret on both services** before enabling
request-scoped campaign policy, then read back its presence without exposing it.
When set, every MCP call but the plain `/` status route must carry the secret in
an `X-MCP-Shared-Secret` header or the server returns 401
(`engine/mcp_server/auth_middleware.py`); the engine client supplies that header
(`mcp_client_helpers.py::_resolve_server_configs`). Left unset, the check is a
no-op. The CORS wildcard is gone regardless; MCP is server-to-server only.

The desired default for the next release is exact
`openrouter/stealth/space-bunny-alpha` on all four system roles. The gateway
pins it to Stealth, disables provider and model fallback, checks the current
zero-price listing before calls, and enforces a zero-price ceiling. This is the
selected code default, not a current production readback: the values above are
still the 23 September snapshot, and production must be read back after its
environment update and deployment. `CLAIM_VERIFIER_MODEL` should remain unset
so claim assessment inherits the worker model. Keep the process-global
`COSCIENTIST_REQUIRE_FREE_MODELS` flag off so ordinary explicit BYOK remains
available; campaign restrictions stay request-scoped. Record the verified
post-release values and deployment IDs in the campaign dossier.

Vercel reads `VITE_API_BASE_URL=https://api-production-97eb.up.railway.app` (set in production environment).

**Completion emails go out through Resend's SMTP relay**, which the api service reaches with the stock `smtplib` code in `app/app/notifications.py` -- there is no Resend SDK and no API-specific branch, because Resend's relay is ordinary STARTTLS SMTP. Two of the five variables are not guessable: `SMTP_USERNAME` is the *literal string* `resend` rather than an address, and `SMTP_PASSWORD` is a Resend API key rather than a mailbox password. `SMTP_FROM_EMAIL` must sit at a domain verified in the Resend dashboard, since Resend rejects a `From` it cannot authenticate instead of silently rewriting it.

```
SMTP_HOST=smtp.resend.com
SMTP_PORT=587                                     # STARTTLS; 465 would need implicit TLS, which smtplib.SMTP does not do
SMTP_USERNAME=resend                              # literal, not an address
SMTP_PASSWORD=<resend api key>
SMTP_FROM_EMAIL=notifications@ai-co-scientist.com  # domain must be verified in Resend
PUBLIC_APP_URL=https://ai-co-scientist.com        # base of the run link inside the mail
```

`PUBLIC_APP_URL` is easy to leave behind and fails quietly: it defaults to `http://localhost:5173`, so a deployment that sets the SMTP block alone still mails a link that resolves to nothing on the reader's own machine. `SMTP_HOST` plus `SMTP_FROM_EMAIL` are separately load-bearing -- `/status` derives `email_notifications_available` from exactly those two, and the plan card's notification field goes inert without them rather than promising a message the server has no transport to send.

**Durability and replica-count contract (decided, not migrated off SQLite).** The store is SQLite in WAL mode with `PRAGMA synchronous=NORMAL` (`app/app/store/db.py`) — the standard, deliberate pairing for WAL: it never corrupts the database, but a handful of the most-recent commits can be lost on OS crash or power loss between the WAL write and its checkpoint (`PRAGMA synchronous=FULL` would close that window at a throughput cost this deployment does not need on top of the single-writer ceiling documented in the root AGENTS.md Gotchas). That durability trade-off is only sound single-writer: **the api service must run at exactly one replica.** Nothing in the code refuses a second one today — a second replica writing the same SQLite file from a different process (let alone a different host sharing the volume) is unserialized concurrent writes to one file, which WAL's locking does not make safe across processes on most volume backends, and is a correctness bug no amount of `worker_pool_size` tuning fixes. Railway services default to one replica and this deployment has never scaled the api service past that; treat this note as reserving the choice explicitly rather than leaving it to whatever the platform default happens to be. If replica count or write throughput past the single-writer ceiling ever needs to grow, that is a store migration (Postgres or similar), not a SQLite tuning knob — pick it deliberately rather than discovering the constraint from a corrupted database.

**Code execution is confined inside the api container; there is no separate exec service and nothing extra to install.** On Linux the backend is **Landlock** (filesystem) plus a **seccomp** filter (network). Both restrict the calling process rather than asking the kernel for a privilege, which is why they work here and bubblewrap does not: bwrap builds confinement out of namespaces, and a container runtime's default seccomp profile refuses `unshare(CLONE_NEWUSER)` — measured EPERM in a stock image, with `seccomp=unconfined`, `apparmor=unconfined` and `cap-add SYS_ADMIN` each failing and only `--privileged` working, which Railway does not give an app container. bubblewrap is still preferred wherever it genuinely runs (it isolates pid, ipc, uts and the network as namespaces rather than as policy), and `sandbox_backend()` *probes* it rather than trusting that it is installed — present-but-unusable is the case that reads as a broken harness instead of a platform limit. Verify a deployment with `python -c "from co_scientist.sandbox import sandbox_backend; print(sandbox_backend())"`: `landlock` or `bwrap` means commands run confined, while `None` means the host offers neither and the execution tools are **withheld from the model entirely** rather than offered and refused per call. Landlock needs Linux 5.13+ with the LSM enabled; on a host lacking it, code execution is simply unavailable and nothing else changes. Regression coverage is `make test-sandbox-linux`, which runs real escape attempts in one image twice — unprivileged (what production is) and `--privileged` (the only way to exercise bubblewrap) — and prints the selected backend, because a suite whose sandbox never started passes every denial test for the wrong reason.

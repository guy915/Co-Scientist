# Local API/UI/MCP preparation — cycle 171

Observed 2026-09-21 17:32–17:37 UTC at source revision
`9c758d6a8773251873d0350fa42cb74518e3fc59`. This is an inference-free local
startup and boundary check for the campaign workflow. It is not model
qualification, scientific workflow acceptance, or production evidence.

## Scope and isolation

- Ports `8208` (API), `5373` (UI), and `8988` (reference MCP) were free before
  launch and free after shutdown.
- Every service was launched with `env -i`, `HOME=/tmp`, an explicit `PATH`,
  `PYTHON_DOTENV_DISABLED=1`, no provider credentials, and fresh temporary
  database, report, cache, and MCP literature-cache paths.
- `MODEL_NAME`, supervisor, chat, safety, and claim-verifier roles were all
  `offline/local`; `COSCIENTIST_FORCE_OFFLINE=1` and
  `COSCIENTIST_REQUIRE_FREE_MODELS=1` were set.
- API auth was set to `required` with an ephemeral local invite and signing
  secret. MCP used an ephemeral shared secret on both processes. Neither
  secret is retained here.
- No run was started. One draft run was created only to verify authenticated
  SQLite persistence; it has no durable task. The final temporary database
  contained one run row and zero `scientific_tasks` rows.
- No production endpoint, deployment, email, BYOK credential, or research
  workflow was touched.

## Observed results

The reference MCP service started on `127.0.0.1:8988`. `GET /` returned HTTP
200 with service `coscientist-lit-review`, campaign policy
`coscientist-public-retrieval-v1` enabled, 16 public tools, and no web-search
provider. Startup logged `ENTREZ_EMAIL` and `ENTREZ_API_KEY` as unset. The
shared-secret middleware reported enabled.

The API started on `127.0.0.1:8208`. `GET /health` returned HTTP 200 and
`healthy`; store, engine, queue, and disk checks were all true. `GET /config`
returned HTTP 200. `GET /status` returned HTTP 200 with `llm_backend=offline`,
`provider=engine`, `model_name=offline/local`, `has_provider_key=false`,
`mcp_available=true`, `pubmed_available=true`,
`literature_review_available=true`, and `web_search_available=false`. The
status probe initialized the local MCP streamable-HTTP client, negotiated
protocol `2025-11-25`, discovered all 16 tools, and issued one public PubMed
availability check. That check used anonymous public retrieval; it did not
use a provider credential or an LLM completion.

The UI started on `127.0.0.1:5373`. `GET /` returned HTTP 200, Vite served
the HTML entry point, and the response was 6,275 bytes. The API returned
`Access-Control-Allow-Origin: http://127.0.0.1:5373` and
`Access-Control-Allow-Credentials: true` for that origin.

Auth and storage behaved as configured: `GET /api/runs` without a bearer
token returned 401; the local invite exchange returned a bearer token; the
authenticated list returned 200; and an authenticated draft `POST /api/runs`
returned 200 with `status=draft`, `llm_backend=offline`, and
`provider=engine`. No `/start` request was sent, and no task row was created.

All three processes were stopped cleanly. The final socket check reported
`8208=FREE`, `5373=FREE`, and `8988=FREE`.

## Reusable local launch shape

Use a new `TMPDIR` for each check. Replace the two `LOCAL_*` placeholders with
ephemeral values and use the same MCP value in both processes. Keep the
provider variables explicitly empty; do not rely on an empty inherited shell.

```bash
TMPDIR="$(mktemp -d /tmp/coscientist-local-prep.XXXXXX)"
LOCAL_MCP_SHARED_SECRET='<ephemeral-local-mcp-secret>'
LOCAL_AUTH_SECRET='<ephemeral-local-auth-secret>'

env -i HOME=/tmp PATH=/opt/homebrew/bin:/usr/bin:/bin \
  PYTHONUNBUFFERED=1 PYTHON_DOTENV_DISABLED=1 \
  COSCIENTIST_REQUIRE_FREE_MODELS=1 \
  COSCIENTIST_MCP_PORT=8988 COSCIENTIST_MCP_SHARED_SECRET="$LOCAL_MCP_SHARED_SECRET" \
  COSCIENTIST_LIT_REVIEW_DIR="$TMPDIR/mcp-cache" \
  ENTREZ_EMAIL= ENTREZ_API_KEY= OPENALEX_MAILTO= OPENALEX_API_KEY= \
  WEB_SEARCH_PROVIDER= BRAVE_API_KEY= TAVILY_API_KEY= \
  ALPHAGENOME_API_KEY= INDRA_COGEX_TIMEOUT=1 \
  /Users/guy/Code/co-scientist/.venv-mcp/bin/python \
  -m uvicorn mcp_server.server:app --host 127.0.0.1 --port 8988
```

For a no-inference API boot, the temporary launch used the normal explicit
offline environment plus the fresh paths below. The small `seed_demo_runs`
override is a runtime-only preparation hook: the normal API lifespan seeds
three deterministic demo records on an empty database, which is useful for
the product but outside this boundary check.

```bash
MODEL_NAME=offline/local
SUPERVISOR_MODEL_NAME=offline/local
CHAT_MODEL_NAME=offline/local
SEMANTIC_SAFETY_MODEL=offline/local
CLAIM_VERIFIER_MODEL=offline/local
COSCIENTIST_FORCE_OFFLINE=1
COSCIENTIST_REQUIRE_FREE_MODELS=1
COSCIENTIST_DB_PATH="$TMPDIR/coscientist.db"
COSCIENTIST_REPORTS_DIR="$TMPDIR/reports"
COSCIENTIST_CACHE_DIR="$TMPDIR/cache"
COSCIENTIST_CACHE_ENABLED=0
MCP_SERVER_URL=http://127.0.0.1:8988/mcp
COSCIENTIST_CAMPAIGN_MCP_URL=http://127.0.0.1:8988/mcp
COSCIENTIST_MCP_SHARED_SECRET="$LOCAL_MCP_SHARED_SECRET"
AUTH_MODE=required
AUTH_SECRET="$LOCAL_AUTH_SECRET"
RESEARCHER_ACCESS_CODES='{"local":"<ephemeral-local-invite>"}'
ALLOWED_ORIGINS=http://127.0.0.1:5373
CLAIM_ASSESSOR=deterministic
EVIDENCE_RESOLVER=offline
SEMANTIC_SAFETY_ENABLED=0
COSCIENTIST_EMBEDDED_WORKER=1

env -i HOME=/tmp PATH=/opt/homebrew/bin:/usr/bin:/bin \
  PYTHONUNBUFFERED=1 PYTHON_DOTENV_DISABLED=1 \
  PYTHONPATH=/Users/guy/Code/co-scientist/app:/Users/guy/Code/co-scientist/engine/src \
  OPENROUTER_API_KEY= OPENAI_API_KEY= ANTHROPIC_API_KEY= DEEPSEEK_API_KEY= \
  GEMINI_API_KEY= GOOGLE_API_KEY= \
  MODEL_NAME=offline/local SUPERVISOR_MODEL_NAME=offline/local \
  CHAT_MODEL_NAME=offline/local SEMANTIC_SAFETY_MODEL=offline/local \
  CLAIM_VERIFIER_MODEL=offline/local COSCIENTIST_FORCE_OFFLINE=1 \
  COSCIENTIST_REQUIRE_FREE_MODELS=1 COSCIENTIST_DB_PATH="$TMPDIR/coscientist.db" \
  COSCIENTIST_REPORTS_DIR="$TMPDIR/reports" COSCIENTIST_CACHE_DIR="$TMPDIR/cache" \
  COSCIENTIST_CACHE_ENABLED=0 MCP_SERVER_URL=http://127.0.0.1:8988/mcp \
  COSCIENTIST_CAMPAIGN_MCP_URL=http://127.0.0.1:8988/mcp \
  COSCIENTIST_MCP_SHARED_SECRET="$LOCAL_MCP_SHARED_SECRET" \
  AUTH_MODE=required AUTH_SECRET="$LOCAL_AUTH_SECRET" \
  RESEARCHER_ACCESS_CODES='{"local":"<ephemeral-local-invite>"}' \
  ALLOWED_ORIGINS=http://127.0.0.1:5373 CLAIM_ASSESSOR=deterministic \
  EVIDENCE_RESOLVER=offline SEMANTIC_SAFETY_ENABLED=0 \
  COSCIENTIST_EMBEDDED_WORKER=1 FORCE_LITERATURE_REVIEW=1 \
  /Users/guy/Code/co-scientist/.venv/bin/python -c \
  'import asyncio,uvicorn,app.main as m; m.seed_demo_runs=lambda *a,**k: asyncio.sleep(0); uvicorn.run(m.app,host="127.0.0.1",port=8208)'
```

Start the UI separately with:

```bash
env -i HOME=/tmp PATH=/opt/homebrew/bin:/usr/bin:/bin \
  VITE_API_BASE_URL=http://127.0.0.1:8208 \
  /opt/homebrew/bin/bun run dev -- --host 127.0.0.1 --port 5373
```

The MCP package currently calls `load_dotenv` from its co-located config
module. `PYTHON_DOTENV_DISABLED=1` is still set consistently, but the robust
local isolation measure is the explicit `env -i` allowlist plus empty values
for every credential-bearing MCP variable. This preparation made no product
change to that loader behavior.

## Limits

This verifies local process startup, API diagnostics, CORS, required auth,
SQLite writes, and the API-to-reference-MCP streamable-HTTP path. It does not
verify an LLM provider, current model price eligibility, a live research run,
browser interaction beyond the UI HTML response, report quality, production
deployment policy, or campaign acceptance. The one PubMed availability probe
was public retrieval and is recorded above; no scientific search or inference
workflow was created or started.

# Hosting Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the AI Co-Scientist app to production — Vercel for the React frontend, Railway for the FastAPI backend and MCP server — accessible at `ai-co-scientist.com`.

**Architecture:** The frontend is a static Vite/React build deployed on Vercel (free). The FastAPI backend and MCP server each run as a separate Railway service, communicating over Railway's private network. A single Railway persistent volume holds the SQLite DB and LLM cache so data survives deploys.

**Tech Stack:** Vercel (frontend static hosting), Railway (Docker-based services, persistent volumes), GoDaddy (DNS), FastAPI, Bun/Vite, Python 3.12, Docker

---

## File map

| File | Change |
|---|---|
| `ai-coscientist-app/docker/entrypoint.sh` | Remove `--reload`/`--reload-dir` flags (dev-only) |
| `ai-coscientist-app/frontend/vercel.json` | Create: tell Vercel the build command, output dir, and SPA fallback |

---

## Task 1: Fix production entrypoint

The current entrypoint starts uvicorn with `--reload`, which watches the filesystem for changes. This is fine for local dev but wastes CPU on Railway and restarts the process unnecessarily. Remove it.

**Important:** Keep `--workers 1` (the default). The app stores in-flight generation tasks in a module-level dict (`_active_tasks` in `main.py`) — multiple workers each get their own memory and would lose track of tasks started on a different worker.

**Files:**
- Modify: `ai-coscientist-app/docker/entrypoint.sh`

- [ ] **Step 1: Edit entrypoint.sh**

Replace the last block of `ai-coscientist-app/docker/entrypoint.sh` from:
```bash
exec python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8008 \
    --reload \
    --reload-dir app
```
to:
```bash
exec python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8008
```

- [ ] **Step 2: Verify the file looks right**

```bash
cat ai-coscientist-app/docker/entrypoint.sh
```

Expected output — last 5 lines:
```
pip install --no-cache-dir -q -e "$WORKSPACE"

exec python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8008
```

- [ ] **Step 3: Commit**

```bash
git add ai-coscientist-app/docker/entrypoint.sh
git commit -m "fix: remove --reload flag from production entrypoint"
git push
```

---

## Task 2: Add Vercel config for the frontend

Vercel needs to know the build command, output directory, and that this is a single-page app (so all routes serve `index.html`). Without the SPA rewrite, refreshing any route other than `/` gives a 404.

**Files:**
- Create: `ai-coscientist-app/frontend/vercel.json`

- [ ] **Step 1: Create vercel.json**

Create `ai-coscientist-app/frontend/vercel.json` with:
```json
{
  "buildCommand": "bun run build",
  "outputDirectory": "dist",
  "rewrites": [
    { "source": "/((?!assets/).*)", "destination": "/index.html" }
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add ai-coscientist-app/frontend/vercel.json
git commit -m "chore: add vercel.json for SPA routing and build config"
git push
```

---

## Task 3: Deploy MCP service on Railway

The MCP server is the PubMed/literature-review tool provider. Deploy it first so you have its private hostname before configuring the API service.

**Files:** No code changes — Railway dashboard only.

- [ ] **Step 1: Create a Railway project**

Go to [railway.com](https://railway.com) → **New Project** → **Deploy from GitHub repo** → select `guy915/Google-DeepMind-AI-Co-Scientist`.

Name the project: `ai-co-scientist`

- [ ] **Step 2: Configure the MCP service**

In the new service's settings:
- **Name:** `mcp`
- **Root Directory:** `ai-coscientist-engine`
- **Dockerfile Path:** `mcp_server/Dockerfile`
- **Watch Paths:** `ai-coscientist-engine/mcp_server/**`

Railway will auto-trigger rebuilds only when files under `mcp_server/` change.

- [ ] **Step 3: Set MCP environment variables**

Under the `mcp` service → **Variables**:

```
COSCIENTIST_MCP_PORT=8888
ENTREZ_EMAIL=<your-email@example.com>
```

`ENTREZ_API_KEY` is optional but increases PubMed rate limits. Leave blank if you don't have one.

- [ ] **Step 4: Deploy and confirm healthy**

Click **Deploy**. Wait for the build to finish (2–4 min). Once deployed, the health check at `http://localhost:8888` should pass — Railway shows a green dot in the service card.

- [ ] **Step 5: Note the private hostname**

In the `mcp` service → **Settings** → **Networking**, note the **private hostname**. It looks like: `mcp.railway.internal`

This is what the API service will use for `MCP_SERVER_URL`. Do **not** expose a public domain for MCP — it doesn't need one.

---

## Task 4: Deploy API service on Railway with persistent storage

The API service needs a persistent volume for the SQLite database (`coscientist.db`) and the LLM response cache. Without it, every redeploy starts with a blank database.

**Files:** No code changes — Railway dashboard only.

- [ ] **Step 1: Add a second service to the same Railway project**

In the `ai-co-scientist` project → **+ New** → **GitHub Repo** → same repo.

- **Name:** `api`
- **Root Directory:** `ai-coscientist-app`
- **Dockerfile Path:** `docker/Dockerfile.api`
- **Watch Paths:** `ai-coscientist-app/**`

- [ ] **Step 2: Add a persistent volume**

In the `api` service → **Volumes** → **Add Volume**:
- **Mount Path:** `/app/data`
- **Size:** 5 GB (sufficient; can grow later)

- [ ] **Step 3: Set API environment variables**

Under the `api` service → **Variables**:

```
GEMINI_API_KEY=<your-gemini-key>
MCP_SERVER_URL=http://mcp.railway.internal:8888/mcp
COSCIENTIST_DB_PATH=/app/data/coscientist.db
COSCIENTIST_CACHE_DIR=/app/data/cache
COSCIENTIST_CACHE_ENABLED=true
OPEN_COSCIENTIST_REPO=https://github.com/jataware/open-coscientist.git
OPEN_COSCIENTIST_REF=main
```

**Do not set `ALLOWED_ORIGINS` yet** — you'll add it after the Vercel domain is known (Task 6).

- [ ] **Step 4: Generate a public domain for the API**

In the `api` service → **Settings** → **Networking** → **Generate Domain**.

Railway gives you something like `api-production.up.railway.app`. Note it down.

- [ ] **Step 5: Deploy and verify**

Click **Deploy**. The entrypoint clones `open-coscientist` from GitHub on first boot (takes ~60s). Wait for the health check to pass.

Smoke test:
```bash
curl https://api-production.up.railway.app/health
```
Expected: `{"status":"ok"}` (or similar JSON)

---

## Task 5: Deploy frontend to Vercel

Vercel needs to know where the frontend lives (it's nested under `ai-coscientist-app/frontend/`) and what URL to call for API requests. The `VITE_API_BASE_URL` is baked into the build at compile time by Vite, so it must be set before deploying.

**Files:** Uses `vercel.json` created in Task 2.

- [ ] **Step 1: Import project in Vercel**

Go to [vercel.com](https://vercel.com) → **Add New Project** → **Import Git Repository** → select `guy915/Google-DeepMind-AI-Co-Scientist`.

- [ ] **Step 2: Configure project settings**

In the import wizard:
- **Framework Preset:** Vite
- **Root Directory:** `ai-coscientist-app/frontend`
- **Build Command:** `bun run build` (Vercel auto-reads from `vercel.json` but set it here too)
- **Output Directory:** `dist`
- **Install Command:** `bun install`

- [ ] **Step 3: Set environment variable**

In **Environment Variables** (before first deploy):

```
VITE_API_BASE_URL=https://api-production.up.railway.app
```

Use the Railway domain from Task 4 Step 4. You'll update this to the custom subdomain later.

- [ ] **Step 4: Deploy**

Click **Deploy**. Vercel builds and deploys in ~90 seconds.

Note the Vercel-generated domain, e.g. `ai-co-scientist.vercel.app`.

- [ ] **Step 5: Smoke test**

Open the Vercel URL in a browser. The dashboard should load. Try creating a run — it should call the Railway API without CORS errors.

If you see CORS errors in the browser console, skip ahead to Task 6 and come back.

---

## Task 6: Lock down CORS

Right now `ALLOWED_ORIGINS` is unset on Railway, which defaults to `*` (any origin). For a public site this is fine short-term but should be locked to your actual domains.

**Files:** Railway dashboard only.

- [ ] **Step 1: Add ALLOWED_ORIGINS to the API service**

In Railway → `api` service → **Variables**, add:

```
ALLOWED_ORIGINS=https://ai-co-scientist.com,https://www.ai-co-scientist.com,https://ai-co-scientist.vercel.app
```

Include the Vercel preview domain so previews of future PRs still work.

- [ ] **Step 2: Redeploy the API**

Railway triggers an automatic redeploy when env vars change. Wait for the green dot.

- [ ] **Step 3: Verify CORS header**

```bash
curl -I -H "Origin: https://ai-co-scientist.vercel.app" \
  https://api-production.up.railway.app/health
```

Expected response headers include:
```
access-control-allow-origin: https://ai-co-scientist.vercel.app
```

---

## Task 7: Custom domains and DNS

Point `ai-co-scientist.com` at Vercel and `api.ai-co-scientist.com` at Railway.

**Files:** GoDaddy DNS + Vercel + Railway dashboards only.

- [ ] **Step 1: Add custom domain to Vercel**

In Vercel → your project → **Settings** → **Domains**:
- Add `ai-co-scientist.com`
- Add `www.ai-co-scientist.com`

Vercel gives you DNS records to add. For the apex domain (`@`) it provides an **A record** (Vercel's IP). For `www` it provides a **CNAME** to `cname.vercel-dns.com`.

- [ ] **Step 2: Add custom domain to Railway**

In Railway → `api` service → **Settings** → **Networking** → **Custom Domain**:
- Add `api.ai-co-scientist.com`

Railway gives you a **CNAME target** (something like `<id>.proxy.rlwy.net`).

- [ ] **Step 3: Configure GoDaddy DNS**

Log into GoDaddy → DNS for `ai-co-scientist.com`. Add/update these records:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `@` | `76.76.21.21` (Vercel's IP — confirm in Vercel dashboard) | 600 |
| CNAME | `www` | `cname.vercel-dns.com` | 600 |
| CNAME | `api` | `<your-railway-cname-target>` | 600 |

TTL of 600 (10 min) lets you fix mistakes quickly. Raise to 3600 after DNS is stable.

- [ ] **Step 4: Wait for DNS propagation**

DNS propagates in 5–30 minutes. Check status:

```bash
dig ai-co-scientist.com A +short
dig api.ai-co-scientist.com CNAME +short
```

Both should resolve before proceeding.

- [ ] **Step 5: Update VITE_API_BASE_URL on Vercel**

In Vercel → your project → **Settings** → **Environment Variables**:
- Update `VITE_API_BASE_URL` to `https://api.ai-co-scientist.com`

Then **Redeploy** (Deployments tab → **...** → Redeploy) to bake the new URL into the build.

- [ ] **Step 6: Update ALLOWED_ORIGINS on Railway**

In Railway → `api` service → **Variables**, update `ALLOWED_ORIGINS`:

```
ALLOWED_ORIGINS=https://ai-co-scientist.com,https://www.ai-co-scientist.com,https://ai-co-scientist.vercel.app
```

Railway auto-redeploys.

- [ ] **Step 7: End-to-end smoke test**

Open `https://ai-co-scientist.com` in a browser. Create a new run. Verify:
1. Page loads over HTTPS
2. API calls go to `api.ai-co-scientist.com` (check Network tab)
3. SSE stream connects and events flow
4. Run completes or progresses past the first node

---

## Verification checklist

- [ ] `https://ai-co-scientist.com` loads the React app
- [ ] `https://api.ai-co-scientist.com/health` returns `{"status":"ok"}`
- [ ] Creating a run works end-to-end
- [ ] SSE stream delivers events in real-time
- [ ] After Railway redeploy, previous runs are still visible (SQLite volume persists)
- [ ] Browser console shows no CORS errors
- [ ] Both domains have valid HTTPS certs (Vercel and Railway provision these automatically)

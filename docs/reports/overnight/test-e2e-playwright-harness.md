# Browser E2E Harness — Final Report

A Playwright browser-level end-to-end harness that exercises the React
frontend against a live FastAPI backend, closing the gap left by the existing
API-only integration coverage. The stack runs fully offline against the
deterministic seeded mock workflow — no provider keys, no external network.

## How to run

```bash
make setup     # once: backend venv + frontend node_modules (prerequisite)
make e2e       # installs harness deps + Chromium if missing, runs headless
```

`make e2e` is self-contained: it launches its own isolated stack (FastAPI +
Vite on non-default ports) and tears it down afterwards. It touches no CI
workflow, so CI can call the same target later.

## Harness layout

Everything lives under `e2e/` at the worktree root, with its own
`package.json`/`bun.lock` so no Playwright dependency leaks into
`app/frontend`:

```
e2e/
  package.json            # @playwright/test + @types/node only
  tsconfig.json           # node types, strict
  playwright.config.ts    # webServer x2, serial (workers:1), globalTeardown
  support/
    paths.ts              # repo/app/frontend paths, ports, per-invocation temp dir
    fixtures.ts           # seeded client id + backend API client fixtures
    global_teardown.ts    # removes the per-invocation temp state dir
  tests/
    01_home.spec.ts             # home renders seeded demo runs
    02_not_found.spec.ts        # unknown route -> 404 page
    03_create_run.spec.ts       # create -> start -> live SSE -> complete
    04_run_detail_tabs.spec.ts  # details / ideas / learning / overview tabs
    05_cancel.spec.ts           # cancel a running run -> terminal state in UI
```

### Stack the harness launches (Playwright `webServer`)

- **Backend** — `uvicorn app.main:app` from `app/`, via the worktree
  `.venv` Python, on **port 8108** (vs. `make dev`'s 8008). Pinned to the
  deterministic mock and an isolated on-disk store:
  - `COSCIENTIST_FORCE_MOCK=1` — mock workflow regardless of any provider key.
  - `COSCIENTIST_DB_PATH` / `COSCIENTIST_REPORTS_DIR` / `COSCIENTIST_CACHE_DIR`
    point into a fresh `mkdtemp` directory computed **once per invocation** (so
    "passes twice from clean state" never inherits prior runs); removed in
    `globalTeardown`.
  - `ALLOWED_ORIGINS=http://127.0.0.1:5273` — the exact UI origin. Required
    because the frontend calls the backend cross-origin (see below) and
    Starlette's wildcard CORS default withholds the `Access-Control-Allow-Origin`
    header once credentials are enabled. This is a config env var, not a code
    change.
- **Frontend** — `vite` from `app/frontend/` on **port 5273** (vs. 5173), with
  `VITE_API_BASE_URL=http://127.0.0.1:8108` so the browser talks **directly** to
  the isolated backend. Going direct (rather than through Vite's dev proxy)
  keeps the SSE event stream browser→backend with nothing in the path — the most
  reliable arrangement for long-lived streaming responses.

Startup seeds three completed mock demo runs before the port answers, so the
backend boot window is generous (120s webServer timeout).

### Determinism / isolation choices

- `workers: 1`, `fullyParallel: false` — one shared, stateful backend; serial
  so runs created by the create/cancel flows never leak into the home
  assertions.
- Fresh temp DB + reports dir per `make e2e` invocation; cleaned on teardown.
- A fixed client id (`e2e-client`) is seeded into `localStorage` via
  `page.addInitScript` **and** sent as `X-Client-ID` on every direct backend
  call, so a run created over the API is owned by the same browser session and
  appears in its home recents.
- Assertions check **presence, not counts** (each demo goal has a distinctive
  phrase), so owned runs from other tests can coexist harmlessly.
- No bare sleeps anywhere — every wait is Playwright auto-waiting
  (`toBeVisible`, `waitForResponse`, `expect.poll`).

## Flows covered

| # | File | What it asserts |
|---|------|-----------------|
| 1 | `01_home` | Home renders the three seeded demo runs (Staphylococcus aureus / synaptic pruning / ferroptosis) in the Recents panel; also the plumbing smoke. |
| 2 | `03_create_run` | Type a goal in the chat composer → draft run-spec card → **Start research** → "session started" card → open run detail. Asserts the **SSE events stream opened** (HTTP 200 to `/api/runs/{id}/events`), then the **Ideas** tab shows hypotheses with **Elo ratings** and the **Overview** tab shows the synthesized report (**Specific aims** + **Winning ideas**) — content that exists only because streamed pipeline events drove the refetches to completion. |
| 3 | `04_run_detail_tabs` | Opens a completed demo run from its recents card and walks **details / ideas / learning / overview**: research-goal details, the ranked hypothesis list with Elo scores, the learning references list + search box, and the research-overview report (winning ideas + tournament summary). |
| 4 | `05_cancel` | Creates + starts an intentionally long run (ultra tier, raised iterations/hypotheses) over the API, polls until it is **running**, cancels it, polls until it is **cancelled**, then observes the terminal state in the UI: the owned run's recents card shows the **"Status: Cancelled"** chip. |
| 5 | `02_not_found` | An unknown route renders the **404** page ("Page not found", "Return home"). |

### Note on the cancel flow (deliberate design)

There is **no in-product affordance to cancel a running run** (no button in the
run-detail UI). Adding one would change frontend behavior, which is out of
scope. So the cancel flow drives create/start/cancel over the backend API —
each call tagged with the browser's own `X-Client-ID` — and the **observable
under test is the terminal state rendered in the UI** ("Status: Cancelled" on
the home recents card), which is exactly what the requirement asks for.

## data-testid additions

**None.** Every selector uses role/text/label queries
(`getByRole`, `getByText`, accessible names, `aria-label`), so no product
component was modified. The only product-code change permitted (data-testid)
was not needed — the app's existing semantics were sufficient to write stable
selectors.

## Change footprint

- `e2e/` — new directory (the entire harness).
- `Makefile` — added the `e2e` target, its `.PHONY` entry, and a help line.

No backend or frontend source, no unit tests, no CI workflows, no diagnostics
endpoints, no CLI, and no comments/refactors were touched. `git status` shows
only `Makefile` (modified) and `e2e/` (new).

## Verification output

All commands run from the worktree root.

**`make e2e` — twice in a row from clean state (determinism check):**

```
===== RUN 1 =====
  ✓  01_home.spec.ts ... home page renders the seeded demo runs (726ms)
  ✓  02_not_found.spec.ts ... unknown route shows the 404 page (299ms)
  ✓  03_create_run.spec.ts ... creates a run from chat, starts it, and watches it complete (2.5s)
  ✓  04_run_detail_tabs.spec.ts ... run detail tabs render hypotheses, Elo scores, and report content (1.1s)
  ✓  05_cancel.spec.ts ... cancels a running run and shows the cancelled state on home (543ms)
  5 passed (7.3s)

===== RUN 2 =====
  ✓  01_home ... (396ms)
  ✓  02_not_found ... (324ms)
  ✓  03_create_run ... (2.4s)
  ✓  04_run_detail_tabs ... (1.2s)
  ✓  05_cancel ... (713ms)
  5 passed (7.9s)
```

**Existing suites stay green:**

```
make test-all
  engine:  961 passed in 4.20s
  app:     231 passed, 1 warning in 36.28s
  parity:  OK — 62 rows (54 verified), all cited evidence exists on disk

cd app/frontend && bun run test    -> Test Files 39 passed (39) | Tests 254 passed (254)
cd app/frontend && bun run lint    -> gts lint, exit 0
cd app/frontend && bun run build   -> tsc + vite build + prerender, exit 0 (built in 862ms)

cd e2e && bunx tsc --noEmit        -> exit 0 (harness TypeScript clean)
```

## Unresolved blockers

None. The one legitimate potential blocker — Playwright's Chromium download —
succeeded (`bunx playwright install chromium` fetched
`chromium-headless-shell v1228`), so the harness runs end to end.

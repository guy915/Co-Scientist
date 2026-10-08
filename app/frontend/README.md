# Co-Scientist Frontend

React 19, Vite and Tailwind CSS v4 workbench for the Co-Scientist API, built
with Bun and linted with gts.

The frozen closure is audited through root `make audit-deps`. See
[requirements](../../requirements/README.md) for dependency update procedures.

Follow the design invariants in [app/AGENTS.md](../AGENTS.md) before visual changes.

## Commands

Use Node.js 22.13+ and Bun 1.3.14 to match the root setup and CI.

```bash
bun install --frozen-lockfile
bun run dev       # Vite dev server on :5173
bun run build     # tsc + vite build + prerender
bun run test      # Vitest (test:watch to rerun on change)
bun run preview   # serve the built assets
bun run lint      # gts lint
bun run fix       # gts format + autofix
```

## Environment

Create `app/frontend/.env` only when you need to override defaults:

```env
VITE_API_BASE_URL=http://localhost:8008
```

When unset, `VITE_API_BASE_URL` uses same-origin paths. The local Vite
server proxies `/api`, `/status`, and `/health` to `http://localhost:8008`.
Set an explicit API origin for a separately hosted production frontend.

`COSCI_FRONTEND_DIST` optionally sets the build/preview output directory.
The production browser harness uses it for temporary assets; normal builds
and prerendering default to `dist/`.

## Source map

| Path | Purpose |
| --- | --- |
| `src/main.tsx` | Mounts `BrowserRouter` and `WorkbenchApp`; imports the style sheets in order |
| `src/app/` | Route table (`workbench_app.tsx`), layout shell, header, navigation rail and 404 page |
| `src/features/chat/` | Chat workspace, landing page and example chats |
| `src/features/report/` | Run detail views and the ideas tab |
| `src/features/runs/` | Run cancellation and session switching |
| `src/features/access/` | Settings dialog, including BYOK credentials |
| `src/features/diagnostics/` | Diagnostics and feedback dialogs |
| `src/shared/api/` | REST and streaming client (`runs.ts`); `wire_*.ts` are generated from the backend models |
| `src/shared/hooks/` | Theme, history, system status and run-stream hooks |
| `src/shared/ui/` | Shared primitives: buttons, dialogs, Markdown renderer, Material 3 color scheme |
| `src/shared/lib/` | Framework-free helpers: client ID, error tracking, routes, safe storage, HTML sanitizing, text and time |
| `src/shared/testing/` | Test render helpers and fixtures |
| `src/types/`, `src/assets/` | Ambient type declarations and landing-page images |
| `src/index.css`, `src/styles/` | Token bridge and Tailwind layers |

Tests sit beside the files they cover as `*.test.ts(x)`; the Vitest setup is
`src/test_setup.ts`.

## Routes

| Route | Page |
| --- | --- |
| `/` | Chat workspace |
| `/chats/:id` | A persisted chat |
| `/examples/:id` | A read-only example chat |
| `/runs`, `/runs/new` | Redirect to `/` |
| `/runs/:id` | Redirect to the details tab |
| `/runs/:id/:tab` | Run detail tab |
| `*` | 404 |

Live progress uses fetch-based server-sent events from `/api/runs/{id}/events`
rather than `EventSource`, so stream requests keep their client headers.

# Co-Scientist Frontend

React + Vite + TypeScript workbench for the Co-Scientist API server.

## Stack

- React 19 and React Router 7
- Vite 7
- TypeScript
- Tailwind CSS v4
- Material Design 3 theme generation in `src/workbench/theme_context.tsx`
- Bun for package management
- gts for linting and formatting
- Vitest + React Testing Library for unit tests

The frozen closure is audited through root `make audit-deps`. See
[requirements](../../requirements/README.md) for dependency update procedures.

Follow the design invariants in [app/AGENTS.md](../AGENTS.md) before visual changes.

## Commands

Use Node.js 22.13+ and Bun 1.3.14 to match the root setup and CI.

```bash
bun install --frozen-lockfile
bun run dev       # Vite dev server on :5173
bun run build     # tsc + vite build + prerender
bun run test      # Vitest
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

## Source Map

| Path | Purpose |
| --- | --- |
| `src/main.tsx` | Mounts `BrowserRouter` and `WorkbenchApp` |
| `src/workbench/workbench_app.tsx` | Route table for the chat workspace and run views |
| `src/workbench/pages/` | Chat workspace (session home), run detail, researcher access, shared report |
| `src/workbench/components/tabs/` | Ideas tab (other run views render inline in `run_detail.tsx`) |
| `src/workbench/hooks/` | Chat-session state, shared chat/run history, toast, and system status |
| `src/api/runs.ts` | Product REST operations and streaming message helpers |
| `src/hooks/` | Shared app-level hooks (e.g. `use_run_stream.ts`) |
| `src/components/` | Shared primitives (error boundary, icon) |
| `src/index.css`, `src/styles/` | Token bridge + Tailwind layers (`index.css`); surface sheets imported in order by `main.tsx` |
| `src/public/` | 404 page and no-index metadata |

## Routing

| Route | Page |
| --- | --- |
| `/` | Chat workspace (session home) |
| `/chats/:id` | Reopen a persisted chat |
| `/runs`, `/runs/new` | Redirect to `/` |
| `/runs/:id` | Redirect to the details tab |
| `/runs/:id/:tab` | Run detail tab |
| `/access` | Researcher access |
| `/shared/:token` | Shared goal report |
| `*` | 404 |

## API Integration

The frontend talks to the FastAPI backend through `src/api/runs.ts`. Run
detail data uses REST, and live progress uses fetch-based SSE from
`/api/runs/{id}/events`, preserving authentication headers on stream requests.

The chat workspace uses:

- `GET /api/runs/{id}/messages`
- `POST /api/runs/{id}/messages/ask`

## Testing

Tests are colocated with the files they cover as `*.test.ts` and `*.test.tsx`. The Vitest setup file is `src/test_setup.ts`.

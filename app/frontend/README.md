# Co-Scientist Frontend

React + Vite + TypeScript workbench for the Co-Scientist API server.

## Stack

- React 19 and React Router 7
- Vite 7
- TypeScript
- Tailwind CSS v4
- Material Design 3 theme generation in `src/lib/theme.ts`
- Bun for package management
- gts for linting and formatting
- Vitest + React Testing Library for unit tests

Read `DESIGN.md` before visual changes. It is the source of truth for theme tokens, typography, spacing, radii, and component conventions.

## Commands

```bash
bun install
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

`VITE_API_BASE_URL` defaults to `http://localhost:8008`.

## Source Map

| Path | Purpose |
| --- | --- |
| `src/main.tsx` | Mounts `BrowserRouter` and `WorkbenchApp` |
| `src/workbench/workbench_app.tsx` | Route table for the chat workspace and run views |
| `src/workbench/pages/` | Chat workspace (session home), run detail, proposals, researcher access, shared report |
| `src/workbench/proposals/` | Proposals-graph data, layout, and rendering |
| `src/workbench/components/tabs/` | Ideas tab (other run views render inline in `run_detail.tsx`) |
| `src/workbench/hooks/` | Workbench-specific hooks: chat-session cluster, run history, and utilities (shortcuts, toast, system status) |
| `src/api/runs.ts` | Typed REST, SSE URL, and streaming message helpers |
| `src/hooks/` | Shared app-level hooks (e.g. `use_run_stream.ts`) |
| `src/components/` | Shared primitives (error boundary, icon) |
| `src/index.css`, `src/styles/` | Token bridge + Tailwind layers (`index.css`); surface sheets aggregated by `styles/surfaces.css` |
| `src/public/` | Residual helpers: 404 page, no-index/SEO, link button |

## Routing

| Route | Page |
| --- | --- |
| `/` | Chat workspace (session home) |
| `/runs`, `/runs/new` | Redirect to `/` |
| `/runs/:id` | Redirect to the details tab |
| `/runs/:id/:tab` | Run detail tab |
| `/access` | Researcher access |
| `/proposals` | Proposals graph (`/recommendations` redirects here) |
| `/shared/:token` | Shared goal report |
| `*` | 404 |

## API Integration

The frontend talks to the FastAPI backend through `src/api/runs.ts`. Run detail data is loaded through REST endpoints, and live progress is streamed from `/api/runs/{id}/events` with browser `EventSource`.

The chat workspace uses:

- `GET /api/runs/{id}/messages`
- `POST /api/runs/{id}/messages`
- `POST /api/runs/{id}/messages/ask`

## Testing

Tests are colocated with the files they cover as `*.test.ts` and `*.test.tsx`. The Vitest setup file is `src/test_setup.ts`.

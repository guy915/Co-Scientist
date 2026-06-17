# Co-Scientist Frontend

React + Vite + TypeScript workbench for the Co-Scientist API server.

## Stack

- React 19 and React Router 7
- Vite 7
- TypeScript
- Tailwind CSS v4
- Material Web wrappers in `src/md3/`
- Material Design 3 theme generation in `src/lib/theme.ts`
- Bun for package management
- gts for linting and formatting
- Vitest + React Testing Library for unit tests

Read `DESIGN.md` before visual changes. It is the source of truth for theme
tokens, typography, spacing, radii, and component conventions.

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
VITE_DOMAIN=scientific
```

`VITE_API_BASE_URL` defaults to `http://localhost:8008`.

## Source Map

| Path | Purpose |
| --- | --- |
| `src/main.tsx` | Mounts `BrowserRouter` and `WorkbenchApp` |
| `src/workbench/workbench_app.tsx` | Route table for public pages and run views |
| `src/workbench/pages/` | Dashboard, new run, and run detail pages |
| `src/workbench/components/tabs/` | Overview, Ideas, Evidence, Tournament, Report, and Chat tabs |
| `src/api/runs.ts` | Typed REST, SSE URL, and streaming message helpers |
| `src/hooks/use_run_stream.ts` | Live run event stream hook |
| `src/hooks/use_messages.ts` | Steering and Q&A message hook |
| `src/md3/` | Thin wrappers around Material Web components |
| `src/components/ui/` | Local shadcn-style primitives |
| `src/public/` | Landing page, demo page, SEO, and 404 page |

## Routing

| Route | Page |
| --- | --- |
| `/` | Public landing page |
| `/demos/:slug` | Public demo page |
| `/runs` | Workbench dashboard |
| `/runs/new` | New research run |
| `/runs/:id` | Run overview |
| `/runs/:id/:tab` | Run detail tab |

## API Integration

The frontend talks to the FastAPI backend through `src/api/runs.ts`.
Run detail data is loaded through REST endpoints, and live progress is streamed
from `/api/runs/{id}/events` with browser `EventSource`.

The Chat tab uses:

- `GET /api/runs/{id}/messages`
- `POST /api/runs/{id}/messages`
- `POST /api/runs/{id}/messages/ask`

## Testing

Tests are colocated with the files they cover as `*.test.ts` and
`*.test.tsx`. The Vitest setup file is `src/test-setup.ts`.

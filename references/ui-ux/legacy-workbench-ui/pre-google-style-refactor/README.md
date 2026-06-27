# Legacy Workbench UI Backup

This folder preserves the pre-Google-style refactor frontend UI from the parent
of commit `02b3524`.

It is intentionally stored under `references/` so the current app does not
import it or route to it, while the old implementation remains easy to inspect
or restore.

Included source:

- `app/frontend/src/workbench/` - old workbench shell, runs dashboard, run detail
  tabs, example-run UI, mock banner, log console, and theme toggle.
- `app/frontend/src/public/` - old public landing page, demo page, demo manifest,
  SEO helpers, and public link button.
- `app/frontend/src/api/`, `src/hooks/`, `src/lib/`, `src/index.css`, and
  `DESIGN.md` - supporting API types, hooks, utilities, styling, and design
  notes needed to understand the old UI.

To recover a file, copy it from `source/` back to the matching app path and
adapt imports against the current frontend as needed.

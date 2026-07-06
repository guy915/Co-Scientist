# Retired Orphan Workbench Tabs

This folder preserves five run-detail tab components (and one supporting chart)
that were removed from the shipped app after `RunDetail` was reworked to render
its own views inline. At removal time none of these files had any importers in
`app/frontend/src` — only `ideas_tab.tsx` remained wired into `run_detail.tsx`.

They are intentionally stored under `references/` so the current app does not
import them or route to them, while the implementations remain easy to inspect
or restore. Unlike the commit-pinned `../pre-google-style-refactor/` backup
(a full snapshot of the earlier UI), this folder captures a single, later
retirement event: the current-tree orphan tabs at the point they were retired.

Included source (paths mirror the live app layout):

- `app/frontend/src/workbench/components/tabs/` - the five orphaned tabs:
  - `overview_tab.tsx` (+ `overview_tab.test.tsx`)
  - `evidence_tab.tsx` (+ `evidence_tab.test.tsx`)
  - `tournament_tab.tsx` (+ `tournament_tab.test.tsx`)
  - `run_specifications_tab.tsx`
  - `chat_tab.tsx`
- `app/frontend/src/workbench/components/elo_trajectory_chart.tsx` - the Elo
  trajectory chart, which was used only by `tournament_tab.tsx`. It was retired
  alongside the tab; its `--color-th-phase0..4` tokens (previously in
  `index.css`) were removed at the same time and would need to be restored to
  use this chart again.

The wired `ideas_tab.tsx` (and its test) stayed in the live app and is not
mirrored here.

To recover a file, copy it from `source/` back to the matching app path and
adapt imports against the current frontend as needed.

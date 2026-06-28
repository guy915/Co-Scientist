# Legacy Preview Fixture

`old-workbench-mock-api.mjs` is a standalone local fixture for viewing the
pre-Google-style workbench backup. It serves the old API shape on
`http://127.0.0.1:8008`, matching the original frontend's default API target.

The fixture includes:

- two legacy workbench rows for the research-runs dashboard;
- three example/demo runs for the public/demo surfaces;
- populated hypotheses, evidence, citations, reviews, tournament matches, report
  markdown, safety decisions, and progress events for
  `demo-ferroptosis-pancreatic-cancer`.

Verified routes:

- `/runs`
- `/runs/demo-ferroptosis-pancreatic-cancer/ideas`
- `/runs/demo-ferroptosis-pancreatic-cancer/summary`
- `/runs/demo-ferroptosis-pancreatic-cancer/progress`

If the old frontend is run from a temporary checkout with `node_modules`
symlinked from the main app, Vite may block Material Symbols font assets unless
that external `node_modules` path is allowed in `server.fs.allow`. A normal
install inside the preview checkout does not need that workaround.

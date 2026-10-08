# Browser tests

Playwright suite for the workbench. It starts its own API and UI against a
throwaway store, so it never touches `coscientist.db` or a running
`make start` stack.

```bash
make setup                # once: backend venv and frontend dependencies
make e2e                  # development server suite (tests/)
make e2e E2E_ARGS="--shard=1/3" # one development shard, as in CI
make e2e-production       # built assets under vite preview (production/)
make e2e E2E_ARGS="tests/03_run_lifecycle.spec.ts --headed"
```

`make e2e` installs this folder's locked dependencies, typechecks the
harness and installs Playwright's Chromium before running.

## What the harness guarantees

- **Isolated ports.** The API listens on 8108 and the UI on 5273, away from
  the development ports. Override with `COSCI_E2E_API_PORT` and
  `COSCI_E2E_UI_PORT`; run suites one at a time on the same ports.
- **Fresh state.** Each invocation creates one temporary directory
  (`COSCI_E2E_STATE_DIR`) for the SQLite store and build output; global
  teardown removes it.
- **Offline.** The API runs with `COSCIENTIST_FORCE_OFFLINE=1`,
  `EVIDENCE_RESOLVER=offline`, dotenv loading disabled and an unreachable MCP
  URL, so leaked credentials cannot reach a provider.
- **Serial.** One worker, because every spec shares the same servers and
  store.
- **Production build kept apart.** `make e2e-production` builds the frontend
  into the state directory with the test API URL baked in, so the normal
  `app/frontend/dist/` is untouched. It checks deep links, report reloads and
  ownership isolation.

`COSCI_E2E_CHROMIUM_EXECUTABLE` points the suite at an installed browser when
downloads are unavailable; its revision can differ from CI's.

## Layout

- `tests/` — development-server specs: home, run lifecycle, acceptance,
  mobile interview, example chats, landing and feedback.
- `production/` — built-asset specs.
- `support/paths.ts` — ports, paths, state directory and teardown.
- `support/fixtures.ts` — the API fixture, viewports and helpers such as
  `createCompletedRun`.

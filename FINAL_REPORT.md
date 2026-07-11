# Final report: Google-style CI/presubmit pipeline

## What was delivered

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Presubmit (on `pull_request`) + postsubmit (on `push` to `main`) pipeline; also callable via `workflow_call` |
| `.github/workflows/nightly.yml` | Scheduled full pass (cron `17 6 * * *` UTC + `workflow_dispatch`) that calls `ci.yml` |
| `docs/CI.md` | Choice-by-choice mapping to the documented Google practices, honest list of adaptations and non-replications, recommended (not configured) branch protection |
| `Makefile` | One-line fix: root `typecheck` target no longer masks app mypy failures with `\|\| true` |

No pushes were made to any remote. No deploy automation was added (Railway/
Vercel stay manual). No tests were added and no product code was changed.

## Workflow design

One workflow, three roles:

- **Presubmit** (`pull_request`): a `changes` job (dorny/paths-filter@v4)
  approximates affected-target selection; each downstream job is gated on
  the relevant output. A concurrency group cancels superseded PR runs.
- **Postsubmit** (`push` to `main`): same workflow; the filter is bypassed
  (every job runs) and runs are never cancelled, so every main commit keeps
  a complete result for culprit-finding.
- **Nightly** (`schedule` via `nightly.yml` → `workflow_call`): identical
  full pass, catching commit-less breakage (dependency drift, runner image
  changes).

Jobs (all `ubuntu-latest`, per-job `timeout-minutes`, no retries anywhere):

| Job | Python/tooling | Commands |
|---|---|---|
| `changes` | — | paths-filter (PR only), else all-targets |
| `format-lint` | 3.12, ruff==0.15.21 | `ruff format --check` + `ruff check` for engine/, app/ (app tests included), evaluations/ |
| `typecheck` | 3.12 | `mypy .` (engine), `mypy app/` (app), `mypy .` (evaluations) — blocking |
| `test-engine` | 3.10 + 3.12 matrix, `fail-fast: false` | `python -m pytest -q` in engine/ |
| `test-app` | 3.12 | `COSCIENTIST_TEST_MODE=1 python -m pytest -q` in app/ (mock provider, offline) |
| `evaluations` | 3.12 | `python -m evaluations.parity_check`; `python -m pytest evaluations/tests -q`; `python -m evaluations.smoke` |
| `frontend` | bun 1.3.14 (oven-sh/setup-bun@v2, cache keyed on `bun.lock`) | `bun install --frozen-lockfile`; `bun run lint`; `bun run test`; `bun run build` |
| `mcp-server` | 3.12 (package floor) | `pip install -e "engine/mcp_server[dev]"`; `python -m pytest mcp_server/tests -q` from engine/ |

Path-filter dependency edges (hand-declared): `app` re-runs on `engine/**`
changes (editable engine install); `evaluations` re-runs on `engine/**`,
`app/**`, `evaluations/**`, and `docs/PARITY.md` because the parity ledger
cites evidence files across all of them; every filter includes
`.github/workflows/ci.yml` itself. Filtering is at the job level (not
`on.paths`) so skipped jobs conclude `skipped`, which satisfies
branch-protection required checks.

## Local verification (fresh setup, per job)

Environment: fresh worktree; `make setup` built `.venv` (Python 3.12.12,
ruff 0.15.21, mypy 1.19.1, pytest 9.0.3) and ran `bun install`
(bun 1.3.14). Every command each job encodes was run locally to green:

| CI job | Local result |
|---|---|
| format-lint (engine) | `226 files already formatted` / `All checks passed!` |
| format-lint (app) | `78 files already formatted` / `All checks passed!` |
| format-lint (evaluations) | `14 files already formatted` / `All checks passed!` |
| typecheck (engine) | `Success: no issues found in 197 source files` |
| typecheck (app) | `Success: no issues found in 43 source files` (no `\|\| true`) |
| typecheck (evaluations) | `Success: no issues found in 14 source files` |
| test-engine py3.12 | `961 passed in 11.40s` |
| test-engine py3.10 | `961 passed in 23.74s` (uv-managed CPython 3.10.19) |
| test-app | `231 passed, 1 warning in 66.30s` |
| test-app (hermeticity re-run) | `231 passed, 1 warning in 38.33s` under `env -i` with the root `.env` removed — proves the fresh-CI-checkout, no-keys case |
| evaluations | `parity: 62 requirement rows (external=6, undisclosed=2, verified=54)` → OK; 31 checker tests passed; `evaluations smoke: OK (safety + citation offline evals passed)` |
| frontend | `bun install` clean on frozen lockfile; `gts lint` passed; `254 passed (254)` vitest; build + prerender OK |
| mcp-server | `6 passed in 0.89s` on Python 3.12 (`pip install -e "engine/mcp_server[dev]"`, pytest run from engine/) |
| `make typecheck` (post-fix) | green (43 + 14 files, exit 0) |

Workflow syntax: `actionlint 1.7.12` passes on both files with zero
findings. Action versions were confirmed to exist against the GitHub API
(checkout v7, setup-python v6, cache v6, setup-bun v2, paths-filter v4).

## Adaptations vs. documented practice

Full detail in `docs/CI.md`; summary:

- **Reproduced**: presubmit/postsubmit split with fast blocking checks
  (SWE book ch. 23); small/medium hermetic test discipline — no external
  network in any blocking job (Test Sizes; ch. 11); no auto-retries, with a
  documented quarantine-and-track flake procedure (Testing Blog 2016);
  style enforced by tooling (ruff config + gts) rather than review
  (eng-practices, Python style guide); separate lint/type/test jobs,
  `fail-fast: false` matrix, per-job timeouts, concurrency-cancel, and path
  filters, patterned on abseil-py / googleapis / adk-python workflows.
- **Adapted**: path globs stand in for Bazel build-graph affected-target
  selection; presubmit and postsubmit run the same commands (no slower tier
  exists yet — a future provider-backed suite belongs in nightly);
  registry fetches (PyPI/npm) are trusted rather than vendored; the runner
  image floats (`ubuntu-latest`).
- **Not replicated** (internal-scale machinery, documented as such): TAP,
  Bazel target-level selection, merge queue / submit queue, green-head
  sync, automated flake quarantine.

## Unresolved blockers (only provable on GitHub)

1. **Actual Actions execution.** Constraint honored: nothing was pushed, so
   no workflow has run on GitHub. Everything short of that is verified
   (every encoded command green locally; actionlint clean; action tags
   resolved against the GitHub API). First push should confirm: runner-side
   timing vs. the chosen `timeout-minutes`, pip/bun cache hit behavior, and
   `dorny/paths-filter` output shapes on a real PR.
2. **`bun run build` calls `node scripts/prerender.mjs`.** Node is
   preinstalled on `ubuntu-latest`; assumption, not proof, until a run.
3. **Skipped-check semantics for branch protection.** Documented behavior
   (job-level-skipped checks count as passing) should be sanity-checked
   once branch protection is actually enabled — which is deliberately left
   to the repo owner, per scope.
4. **Nightly cron delivery.** GitHub delays/drops cron under load; the
   off-hour time (06:17 UTC) mitigates but only a live schedule proves it.
5. **Python 3.10 on the runner.** Verified locally with uv-managed CPython
   3.10.19; `actions/setup-python` will resolve its own 3.10.x patch.

## Housekeeping notes

- Local artifacts created during verification (not committed, all
  gitignored or untracked): `.venv`, `.venv-mcp`, `.venv-310`, `.env`
  (copied from `.env.example` by `make setup`), `app/frontend/node_modules`,
  `app/frontend/dist`. This report file is also left uncommitted.

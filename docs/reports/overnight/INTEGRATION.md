# Overnight worktree integration report

Integration of the seven overnight worktree branches into `main`, performed in
the primary checkout at `/Users/guy/Code/Co-Scientist`. Work was staged on
`chore/overnight-integration` (branched from `main` at `480a3489`) and
fast-forwarded onto `main` only after every branch was merged and the full
suite — including the browser end-to-end pass — was green. Nothing was pushed
to any remote, no source branch was deleted or rewritten, and nothing was
deployed.

## Outcome summary

All seven branches carried real commits and self-reported passing,
build-clean verification, so none were skipped. Each was renamed to a clean
name before merging (the source branch names carry an AI reference that
`git merge --no-ff` would embed in the merge commit), then merged one at a
time with `git merge --no-ff`. Two `fix(integration)` commits were needed for
genuine cross-branch interactions. Final state on `main` is green across
backend tests, offline evals, lint, strict typecheck, the frontend suite/build,
and the Playwright e2e suite.

| # | Clean branch (was) | Outcome | Merge commit |
|---|---|---|---|
| 1 | `ci/presubmit-pipeline` (`claude/github-actions-ci-pipeline-bd2612`) | Merged | `131f4b61` |
| 2 | `fix/core-flow-stabilization` (`claude/co-scientist-product-flows-0d2654`) | Merged | `ac049fc2` |
| 3 | `feat/continuous-diagnostics` (`claude/co-scientist-diagnostics-ca9131`) | Merged | `d63d76df` |
| 4 | `test/e2e-playwright-harness` (`claude/coscientist-e2e-harness-a582fa`) | Merged | `255819e4` |
| 5 | `feat/operator-cli` (`claude/agent-operator-cli-703128`) | Merged | `88d60c5b` |
| 6 | `refactor/simplify-dead-code` (`claude/coscientist-cleanup-41e289`) | Merged | `6c0fd28d` |
| 7 | `docs/google-style-comments` (`claude/google-style-comments-21ed53`) | Merged | `8751141f` |

Integration fixes: `c01d871b` (dead `COSCIENTIST_TEST_MODE`), `43f9d746`
(stale CLI tests).

## Preflight

- `main` was clean at `480a3489`.
- `git rev-list main..<branch> --count` was non-zero for all seven branches
  (3, 1, 4, 1, 1, 7, 3 commits respectively), so none were skipped for
  no-work.
- Each branch's `FINAL_REPORT.md` (branch root) reported successful,
  build-passing verification with no unresolved blockers, so none were skipped
  for failed verification. The self-reports were treated as claims and
  re-verified after every merge (see the note on the harness bug below).

## Renames performed

Done before any merge, with `git branch -m OLD NEW` (works even while the
branch is checked out in a worktree; all seven worktrees stayed attached to
their renamed branches):

| Old name | New name |
|---|---|
| `claude/github-actions-ci-pipeline-bd2612` | `ci/presubmit-pipeline` |
| `claude/co-scientist-product-flows-0d2654` | `fix/core-flow-stabilization` |
| `claude/co-scientist-diagnostics-ca9131` | `feat/continuous-diagnostics` |
| `claude/coscientist-e2e-harness-a582fa` | `test/e2e-playwright-harness` |
| `claude/agent-operator-cli-703128` | `feat/operator-cli` |
| `claude/coscientist-cleanup-41e289` | `refactor/simplify-dead-code` |
| `claude/google-style-comments-21ed53` | `docs/google-style-comments` |

Every merge commit subject/body and every carried commit was scanned for AI
references (`claude|anthropic|copilot|gpt|chatgpt|ai-generated|co-authored-by`)
— none found.

## FINAL_REPORT.md handling

Each branch roots a `FINAL_REPORT.md`, which collides on every merge. Merges
used `git merge --no-ff --no-commit`, then the incoming report was
`git mv`'d to `docs/reports/overnight/<clean-name>.md` before committing, so
the repo root never carried a committed `FINAL_REPORT.md`. The seven relocated
reports live alongside this file.

## Per-branch detail

### 1. `ci/presubmit-pipeline` — merged `131f4b61`

Adds `.github/workflows/ci.yml` (presubmit/postsubmit), `.github/workflows/nightly.yml`,
`docs/CI.md`, and a one-line Makefile fix making app `mypy` blocking.

- **Conflicts:** none. All additions except the Makefile line, which touches a
  region `main` had not changed.
- **Validation:** `actionlint 1.7.12` clean on both workflows.

### 2. `fix/core-flow-stabilization` — merged `ac049fc2`

Stabilizes four offline workbench flows: grounded offline Q&A, real recents
top-hypotheses, persisted-data home progress/duration, and cancel for
restart-survivor runs.

- **Conflicts:** none — touches only `app/` and `docs/PARITY.md`, disjoint
  from branch 1.
- **Cross-branch effect (surfaced later):** this branch changed two API
  contracts that branch 5's tests (cut from `main`) still asserted — offline
  Q&A now returns a grounded answer instead of an API-key error frame, and
  cancelling a terminal run returns HTTP 409 "run already finished". See the
  integration fix in branch 5's section.

### 3. `feat/continuous-diagnostics` — merged `d63d76df`

Real `/health` checks, hardened `/status` probes, a `/metrics` endpoint,
run-correlated structured logging, streamed `total_time`/`phase_times`, and a
workbench system-status chip.

- **`app/app/runs.py` — auto-merged, both intents verified.** Git merged
  non-overlapping hunks. Confirmed by inspection that branch 2's
  cancel-after-restart logic (`_TERMINAL_STATUS_VALUES`, the non-terminal →
  `CANCELLED` transition) **and** branch 3's `run_log_context(run_id)` wrapper
  and `GET /metrics` endpoint both survived.
- **`app/app/store/runs.py` — auto-merged, both intents verified.** Branch 2's
  `top_hypotheses`/`latest_stage` enrichment and branch 3's `run_metrics`
  clearing in `clear_run_derived_data` both present.
- No manual conflict resolution was required; no conflict markers.

### 4. `test/e2e-playwright-harness` — merged `255819e4`

Adds a Playwright browser e2e harness under `e2e/` and a `make e2e` target that
launches an isolated offline mock stack (FastAPI on 8108 + Vite on 5273 against
a fresh temp store).

- **`Makefile` — auto-merged, all effects verified.** Branch 1's
  `mypy app/` (blocking), branch 4's `e2e` target/`.PHONY`/help line all
  coexist (different regions).
- **No frontend hotspot materialized.** Branch 4 makes **no** `app/frontend/src`
  changes — it uses role/text/label selectors, not `data-testid` (its report
  confirms "data-testid additions: None"). So the anticipated recents-vs-testid
  frontend conflict did not occur.
- **Integration addition (not a conflict): e2e CI job.** Because both the CI
  branch (1) and the E2E branch (4) landed, an `e2e` job was added to
  `.github/workflows/ci.yml`: an `e2e` output on the `changes` job, an `e2e`
  path filter (`e2e/**`, `app/**`, `engine/**`, plus the workflow), the
  all-targets loop entry, and the job itself (`make setup` then `make e2e`).
  Validated with `actionlint 1.7.12`. This edit is part of the branch-4 merge
  commit's tree.
- From this merge on, `make e2e` was part of every verification pass.

### 5. `feat/operator-cli` — merged `88d60c5b`; integration fix `43f9d746`

Adds the `cosci` operator CLI (`app/app/cli/`) over the runs HTTP API, the
`cosci` console-script entry point, and promotes `httpx` to a runtime
dependency.

- **Conflicts:** none — new `cli/` package + tests; `README.md`/`pyproject.toml`
  touched only by this branch.
- **Dep refresh:** after merging, `app` was reinstalled editable into `.venv`
  so the new `[project.scripts] cosci` entry point registered;
  `cosci --help` runs.
- **Integration fix `43f9d746` — stale CLI tests.** This branch was cut from
  `main`, so three of its CLI tests asserted `main`'s API behavior that branch
  2 had already changed. The **CLI code is correct** (it faithfully relays
  whatever the endpoint streams); only the tests' expected contract was stale:
  - `test_ask_offline_degrades_to_fallback` → renamed
    `test_ask_offline_returns_grounded_answer`: offline (mock provider) now
    streams a grounded answer and exits 0; assert the answer text and empty
    stderr (was: exit 1 + "requires a language model API key").
  - `test_ask_json_emits_error_frame` → renamed
    `test_ask_json_streams_answer_frames`: assert `chunk`/`done` frames and no
    `error` frame (was: an `error` frame).
  - `test_cancel_terminal_run_errors`: assert the HTTP 409 "already finished"
    relay (was: "not active").

### 6. `refactor/simplify-dead-code` — merged `6c0fd28d`; integration fix `c01d871b`

Behavior-preserving cleanup: drops dead re-export facades, an unused
`react-markdown` dep and orphan favicons, env vars documented but read nowhere,
and stale docs.

- **`app/app/engine_adapter/__init__.py` — CONFLICT, resolved to branch 6's
  pruned version.** HEAD kept the full re-export block (including branch 3's
  added `_persist_run_metrics` re-export); branch 6 removed the block. Resolved
  to branch 6's version after verifying: the five names branch 6 keeps
  (`_persist_final_state`, `_build_engine_opts`, `select_provider`,
  `system_status`, `run_workflow`) cover **every** `engine_adapter` namespace
  consumer in the integrated tree, and `_persist_run_metrics` has zero facade
  consumers (it is used only inside `engine_stream.py`). This is a reasoned
  resolution, not a blind `-X theirs`.
- **`app/app/mock_workflow.py` — CONFLICT, resolved to branch 6's pruned
  version.** HEAD kept the import + `__all__` re-export block (including branch
  3's `_persist_mock_metrics`); branch 6 removed it. Resolved to branch 6's
  version after verifying: `_persist_mock_metrics`' real consumers import from
  `mock_workflow_phases`/`mock_workflow_stages`, never from `app.mock_workflow`,
  and branch 6's body keeps only `run_mock_workflow` and references none of the
  removed helpers.
- **`app/app/store/__init__.py` — auto-merged correctly.** Kept branch 3's
  consumed `get_run_metrics`/`save_run_metrics` exports (used via the `store.`
  namespace in `runs.py`, `engine_stream.py`, and tests) and dropped branch 6's
  unreferenced `default_db_path` (no consumer anywhere in the integrated tree).
- **`Makefile` — auto-merged, all three effects verified.** Branch 1's
  `mypy app/` blocking, branch 4's `e2e` target, and branch 6's
  `COSCIENTIST_TEST_MODE` removal from `test-app` all present.
- **Integration fix `c01d871b` — dead `COSCIENTIST_TEST_MODE` in CI/docs.**
  Branch 6 proved `COSCIENTIST_TEST_MODE` is read nowhere (the app suite forces
  the mock provider via its autouse `isolated_db` fixture,
  `COSCIENTIST_FORCE_MOCK=1`). After branch 6 merged, branch 1's ci.yml
  `test-app` env var and the `docs/CI.md` note were the only remaining live
  references, so they were removed to keep branch 6's cleanup coherent.
  Behavior is unchanged (the app suite already runs offline without the var —
  branch 6 removed it from `make test-app` too). `actionlint` clean.

### 7. `docs/google-style-comments` — merged `8751141f`

Comment/docstring-only corrections in `ranking.py`, `evolve.py`,
`evolve_context.py`, and `store/hypotheses.py` (weighted matchmaking,
tier-driven tournament rounds, sampled evolution context, and the COALESCE
nullability note).

- **Conflicts:** none. The four files were untouched by branches 1–6, so the
  corrections describe the current integrated code and no comments needed
  dropping. The merged diff was confirmed to contain no code statements, only
  docstring/comment prose.

## Verification harness note (important — read before trusting per-merge claims)

The per-merge verification script had a masking bug: it piped
`make test-all` (and other targets) through `| tail`, so a non-zero exit from
the real command was hidden behind `tail`'s exit 0. This meant merges 5 and 6
were **initially reported green by a broken harness** — that green was false.

The bug hid three failing CLI tests that were introduced at **merge 5** (branch
5's tests meeting branch 2's changed API, per branch 5's section). They were
discovered while scrutinizing the merge-6 output, which showed
`3 failed, 325 passed` above the masked "green" line. The harness was fixed
(`set -o pipefail`), the three tests were corrected (`43f9d746`), and the full
suite was re-run and confirmed green.

For the record: merges 1–4 were genuinely green at the time — each showed
`parity: OK`, which `make test-all` prints only after `test-app` succeeds
(the targets run engine → app → parity in sequence, stopping on first failure).
Only merges 5–6 were affected, and only the CLI tests. **The final state below
is the authoritative green.**

## Final verification transcript (integration branch HEAD `8751141f`, = `main` after ff)

```
engine pytest         961 passed
app pytest            328 passed, 1 warning
parity                62 rows (verified=54, external=6, undisclosed=2) — OK
eval-smoke            OK (safety + citation offline evals passed)
lint (ruff, app)      All checks passed
lint (ruff, engine)   All checks passed
lint (ruff, evals)    All checks passed
mypy engine           Success: no issues found in 197 source files
mypy app              Success: no issues found in 54 source files
frontend test         41 files, 265 passed
frontend lint (gts)   clean
frontend build        tsc + vite + prerender OK
make e2e (Playwright) 5 passed (chromium, isolated offline mock stack)
```

Note on the local lint invocation: `make lint` runs `.venv/bin/python -m ruff`,
but this checkout's `.venv` has no `ruff` module, so it was linted with the
system `ruff` (0.15.15) against the same three targets (`app`, `engine`,
`evaluations`). CI installs a pinned `ruff==0.15.21` into its own environment,
so CI lint is unaffected. This is a pre-existing local-tooling quirk, not an
integration change.

## Post-integration actions (completed after the report was first written)

These were done in the same session, once the user authorized push and cleanup:

- **Pushed.** `main` was fast-forwarded on the remote (`480a3489..e64d88c5`,
  then `..a5f40b19` with the format fix below). `main` == `origin/main`.
- **First CI run surfaced one real gap, now fixed.** The push triggered the
  new pipeline (the first CI run this repo has ever had). Nine of ten jobs
  passed on the first run — including **`Browser e2e (Playwright)`, which
  succeeded on `ubuntu-latest` without `--with-deps`**, so the anticipated
  Chromium-system-deps risk did not materialize. The one failure was
  `Format and lint (ruff)`: no local verification (branch 5's, or this
  integration's) had run `ruff format --check`, only `ruff check`. The pinned
  `ruff==0.15.21` reformatted one branch-5 file
  (`app/tests/test_cli_render.py`, collapsing a call that fits in 80 cols).
  Fixed in `a5f40b19` (`style(cli): ...`, formatting only, no behavior change),
  and the re-run is **fully green — all ten jobs pass**.
- **Branch cleanup done.** The seven renamed branches, the
  `chore/overnight-integration` staging branch, and all seven worktrees under
  `.claude/worktrees/` were removed (every branch tip is an ancestor of `main`,
  so `git branch -d` succeeded). Only `main` and the pre-existing
  `goolge-ai-co-scientist-parity` branch remain.

## Remaining follow-ups for the user

1. **Branch protection.** `docs/CI.md` recommends (does not configure) marking
   the CI jobs — now including `e2e` — as required status checks on `main`.
   The workflow has now run green on GitHub, so this can be configured.
2. **Optional CI hardening.** The `e2e` job's `bunx playwright install chromium`
   worked without `--with-deps` on the current `ubuntu-latest` image, but
   adding `--with-deps` would make it robust against future runner-image
   changes that drop a Chromium system library.
3. **Superseded archived report.** `docs/reports/overnight/feat-operator-cli.md`
   (branch 5's snapshot) still describes the pre-integration offline `ask`
   behavior ("the endpoint returns HTTP 200 and emits a graceful error frame").
   That is superseded by branch 2: offline `ask` now returns a grounded answer.
   The snapshot was left as a historical record; the shipped behavior is the
   grounded-answer path, verified by the updated CLI tests.

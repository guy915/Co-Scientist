# CI: a Google-style presubmit/postsubmit pipeline on GitHub Actions

This repo's CI (`.github/workflows/ci.yml` and `nightly.yml`) reproduces
Google's *publicly documented* engineering-productivity practices where they
translate to a small GitHub-hosted project, and honestly labels everything
that is an adaptation or is not replicated at all.

Sources referenced throughout:

- [Software Engineering at Google, ch. 23 "Continuous Integration"](https://abseil.io/resources/swe-book/html/ch23.html)
- [Software Engineering at Google, ch. 11 "Testing Overview"](https://abseil.io/resources/swe-book/html/ch11.html)
- [Test Sizes (Google Testing Blog)](https://testing.googleblog.com/2010/12/test-sizes.html)
- [Flaky Tests at Google and How We Mitigate Them (Google Testing Blog)](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we-mitigate-them.html)
- [Google Engineering Practices](https://google.github.io/eng-practices/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- Google-org OSS workflows this pipeline patterns itself on:
  [abseil/abseil-py `test.yml`](https://github.com/abseil/abseil-py/blob/main/.github/workflows/test.yml),
  [googleapis/google-cloud-python `lint.yml` / `unittest.yml`](https://github.com/googleapis/google-cloud-python/tree/main/.github/workflows)
  (whose PR jobs are literally labeled "presubmit"),
  [google/adk-python `continuous-integration.yml`](https://github.com/google/adk-python/blob/main/.github/workflows/continuous-integration.yml)

## The model

| Google concept | Here |
|---|---|
| Presubmit (blocking, fast, reliable) | `ci.yml` on `pull_request`: path-filtered jobs, superseded runs cancelled |
| Postsubmit (comprehensive) | `ci.yml` on `push` to `main`: every job runs, no path filters, runs never cancelled |
| Continuous build (scheduled full pass) | `nightly.yml` (cron, 06:17 UTC) calls `ci.yml` via `workflow_call`; also `workflow_dispatch` for on-demand full passes |
| Not CI | `benchmark.yml`: manual (`workflow_dispatch`) live quality benchmark for `docs/OPTIMIZATION.md`. It calls the free default model with the `OPENROUTER_API_KEY` repository secret, so it never gates a PR or `main` |
| Not CI | `prune-branches.yml`: manual branch cleanup. It deletes branches with no open PR and no commit in the last `min_age_hours` (default 24); `main` is never touched |

SWE book ch. 23 defines presubmit as "fast and reliable" checks gating merge,
with "slower or less deterministic" comprehensive testing moved to
postsubmit. This project's full suite is small enough (a complete pass takes
on the order of ten minutes on GitHub-hosted runners) that presubmit
and postsubmit run the *same commands*; the split that remains
meaningful at this scale is (a) presubmit is path-filtered and cancellable,
(b) postsubmit runs everything on every main commit and keeps every result
for culprit-finding, and (c) the nightly pass catches breakage that arrives
without a commit (dependency drift, runner image changes).

## Choice-by-choice mapping

### Hermeticity: no external network in any blocking job

Test Sizes / ch. 11: small and medium tests get no external network access —
that is what makes them deterministic and trustworthy as merge gates.

- Engine tests: pure unit/graph tests, LLM calls mocked (1773 tests, ~18 s).
- App tests: the suite's autouse `isolated_db` fixture forces the real
  engine's deterministic offline LLM backend (`COSCIENTIST_FORCE_OFFLINE=1`);
  no model API keys exist in CI. Because every test owns its store, CI runs
  the suite as three shards (`.github/ci_shard.py`, round-robin over sorted
  node IDs), each on four `pytest-xdist` workers.
- MCP server tests: fake `httpx` clients, no network (see
  `engine/mcp_server/tests/test_literature.py` docstring).
- Browser tests: the existing development flows plus a built-asset launch
  check with `AUTH_MODE=required`. Each invocation gets a fresh temporary
  store, fixed test-only invite codes, disabled local dotenv loading, offline
  models and offline evidence/claim checks. The launch check exercises login,
  authenticated report reloads and cross-researcher access isolation. Both
  targets typecheck the TypeScript harness before running Chromium.
- Frontend, browser and root-tooling jobs explicitly install Node 24.19.0 and
  Bun 1.3.14; frontend scripts do not inherit the runner image's Node version.
- Evaluations: `evaluations.smoke` is by construction the *offline* (no-LLM,
  no-network) subset; the expensive provider-backed suites stay opt-in and
  are not in CI. Two more live, opt-in exceptions exist purely for by-hand
  release verification and are never invoked by any CI job:
  `evaluations.prod_smoke` (non-mutating checks against a deployed API) and
  `evaluations.mcp_live_smoke` (a live PubMed/OpenAlex/INDRA contract +
  rate-limit check, since `engine/mcp_server`'s own suite fakes every HTTP
  client). Both have their own hermetic unit tests, in CI, that exercise the
  check *logic* against a mocked transport rather than the network.
- Verified locally by running the app suite with a scrubbed environment
  (`env -i`, no `.env` file present): 1179 passed.

The only network CI uses is fetching the repo, actions, and packages
(PyPI/npm registry via bun, the Chromium download in `e2e`, plus apt and
the Docker base image inside `docker-build`) — infrastructure, not test
traffic. `docker-build` builds both root Dockerfiles and the frontend dev image; it never pushes or
runs them (deploys stay manual);
`root-config` runs `make setup`/`lint` against the checkout
itself (the `typecheck` job runs `make typecheck`), so it is exactly as hermetic as the jobs it exercises.

Migrating a *populated* legacy-schema database is also covered, without a
dedicated job: `app/tests/test_persistence_records.py` builds an
on-disk SQLite file shaped like a pre-migration volume (the exact danger
`app/app/store/db.py`'s migration comments call out — a column added by
`_run_migrations` but referenced by an index or backfill that runs before
it) and asserts the current store starts against it cleanly. It runs as
part of `test-app` like any other app test; a migration ordering bug fails
that job, not a separate one.

### Flake policy: no auto-retries; quarantine and track

The flaky-tests post describes Google's mitigation as detecting, tracking,
and *quarantining* flaky tests — not blanket re-running. Accordingly:

- No `retry` wrappers, no `--reruns`, no marketplace retry actions anywhere
  in the workflows.
- If a test flakes: (1) open an issue, (2) quarantine it with a skip marker
  referencing the issue (`@pytest.mark.skip(reason="flaky: #NN")` /
  `it.skip`), (3) fix or delete. A flaky test that blocks unrelated merges
  is worse than a missing test, but a silently retried test is worst of all:
  it converts a real signal into noise.
- `fail-fast: false` on the engine matrix supports this: both interpreter
  runs always report, so a flake is attributable to a version instead of
  being masked by a cancelled sibling.

### Style enforced by tooling, not review

google.github.io/eng-practices: reviewers should not argue about style;
the style guide + autoformatter are the authority (the Python style guide
itself defers formatting to the formatter). Here:

- `format-lint` runs `ruff format --check` + `ruff check` (Google-ish config
  already in each `pyproject.toml`: 100 columns, pydocstyle `google`
  convention).
- The frontend runs `gts lint` — Google TypeScript Style, literally.
- ruff is pinned exactly (`ruff==0.15.21`) in CI so a formatter release
  cannot flip presubmit red on an unrelated change; bump it deliberately.

### Typecheck is blocking

`mypy --strict` (per-project config) over `engine/`, `app/`, and
`evaluations/` is a blocking presubmit job. The root Makefile previously ran
the app typecheck with `|| true`; that escape hatch was removed in the same
change that added CI, so `make typecheck` and the CI job agree.

### Patterns lifted from Google-org OSS workflows

| Pattern | Source example | Here |
|---|---|---|
| Separate lint / type / test jobs, one concern per job | googleapis `lint.yml` + `unittest.yml` | `format-lint`, `typecheck`, `test-engine`, `test-app`, `evaluations`, `frontend`, `mcp-server`, `e2e`, `docker-build`, `root-config` |
| `fail-fast: false` matrix over interpreter versions | abseil-py `test.yml` | `test-engine` on 3.10 + 3.12 |
| Per-job `timeout-minutes` | adk-python `continuous-integration.yml` | every job (5–25 min) |
| Concurrency group cancelling superseded runs | adk-python | `concurrency:` with `cancel-in-progress` only for `pull_request` |
| Path filters as affected-targets approximation | (adaptation, see below) | `changes` job with `dorny/paths-filter` |

### Interpreter versions

Python 3.12 is the primary version for every job (it is what `make setup`
prefers and what production containers run). Two floors are covered where
they differ: the engine also runs on 3.10 (its `requires-python` floor), and
the MCP server runs on 3.12 (its own floor — the package requires >=3.12).

## Adaptations (honest divergences)

- **Path filtering is a crude approximation of affected-target selection.**
  Google computes the affected set from the Bazel build graph; we declare
  the dependency edges by hand as path globs (`app` depends on `engine`;
  `evaluations` runs on any source or docs change). Filtering happens at the
  job level rather than `on.paths` so skipped jobs still report a `skipped`
  conclusion, which branch protection counts as passing — workflow-level
  `paths:` would leave required checks pending forever. Every path in the
  repo is covered by at least one filter now: `docker` (root Dockerfiles,
  `app/docker/`, `app/docker-compose.yml`) and `root_config` (`Makefile`,
  `vercel.json`, the `.env.example` templates) exist specifically so a
  change to those files is not silently invisible to every job — it used to
  be, since none of the per-tree filters matched them.
- **Presubmit and postsubmit run the same commands.** At Google, postsubmit
  runs strictly more (larger tests, more targets). This suite has no
  slower tier yet — the split here is filters/cancellation vs. full/kept.
  If a genuinely slow suite appears (e.g. provider-backed evaluations), it
  belongs in `nightly.yml`, not presubmit.
- **`bun install` and `uv pip install` fetch from registries.** Google builds
  are hermetic down to vendored/pinned toolchains. We pin the lockfile
  (`--frozen-lockfile`), the interpreter versions, bun (`1.3.14`), and ruff,
  and cache on `bun.lock` — but the registry fetch itself is trusted.
- **`ubuntu-latest` is a floating runner image.** A fully hermetic setup
  would pin a container image. Accepted for simplicity; the nightly pass is
  the canary that catches image drift.
- **Presubmit runs on the PR merge ref** (GitHub's default `pull_request`
  behavior), which approximates but does not guarantee testing against
  current head of `main` at merge time. See merge queue, below.

## Not replicated (internal-scale machinery)

- **TAP** (Test Automation Platform): millions of tests, continuous
  build-and-test at head, culprit finding. Nothing at this scale exists or
  is needed; per-commit postsubmit is the miniature version.
- **Bazel affected-target selection**: replaced by hand-written path
  filters, above.
- **Merge queue / submit queue**: GitHub's merge queue is the platform
  analog (it tests PRs against the queued future state of `main`). Not
  configured — single-digit merge volume makes "Require branches to be up
  to date" (below) sufficient. Revisit if merge volume grows.
- **Green-head sync** (developers sync to a known-green changelist): no
  platform equivalent on GitHub; the postsubmit badge on `main` is the
  informal substitute.
- **Flake-bot automation** (automatic quarantine, flakiness scoring):
  replaced by the manual quarantine-and-track procedure above.

## Recommended branch protection (not configured by CI)

Require **Required checks** on `main`. This aggregate job runs with `always()`
and rejects a failed or cancelled dependency, while accepting path-filtered
skips only after `changes` succeeds. It provides one stable required status
across the Python matrix and conditional jobs. Setting branch protection is
an external GitHub repository setting; the workflow cannot configure it.

Require pull-request review and branches up to date before merging. Enable
private security reporting before public launch. See [LAUNCH.md](LAUNCH.md)
for repository and deployment prerequisites.

## Maintenance notes

- Every command CI runs is also runnable locally (`make lint`,
  `make typecheck`, `make test-engine`, `make test-app`, `make test-evaluations`,
  `make eval-smoke`, `bun run lint|test|build`); the test/lint jobs encode
  the same commands directly rather than shelling to make, so a Makefile
  refactor can't silently change those gates. Three jobs deliberately invoke
  `make`: `root-config`, which exists specifically to catch a Makefile edit
  that breaks a target (nothing else in CI would); `typecheck`, which runs
  `make typecheck PY=python` so mypy runs once per pipeline; and `e2e`, whose
  `make setup` + `make e2e` targets already launch the isolated stack the
  browser suite needs. CI installs Python packages with uv
  (`make setup PIP="uv pip"` with `VIRTUAL_ENV` set); its resolution matched
  pip's package for package when this was introduced.
- Version pins to bump deliberately: `ruff==0.15.21` (ci.yml), bun `1.3.14`
  (ci.yml), and every action, each pinned to a commit SHA with its version
  in a trailing comment (`actions/checkout` v7.0.1, `actions/setup-python`
  v6.3.0, `actions/cache` v6.1.0, `oven-sh/setup-bun` v2.2.0,
  `dorny/paths-filter` v4.0.3, `astral-sh/setup-uv` v10.2.0 with uv
  `0.11.32`). The composite `.github/actions/setup-backend` also pins
  `actions/setup-python` by SHA, and pins `pytest-xdist==3.8.0`, a CI-only
  test dependency.

## Launch validation

`make check` runs the complete local offline validation, including frontend
unit tests and the isolated browser suite. `make test-all` includes engine,
app, MCP and frontend tests plus the evaluation harness. `make docker-build` builds both
production images separately. Production Python runtime closures are
hash-pinned under `requirements/`; review and regenerate their locks with
runtime metadata changes. Development/test extras still use package metadata.

Changes to shared setup actions and the root Ruff configuration trigger their
consuming Python jobs. Runtime source, dependency locks, vendored skills, and
Docker exclusion files trigger image builds. `workflow_dispatch` permits a
full manual pass without manufacturing a commit. Dependency updates are
proposed through Dependabot; Python runtime updates follow
[the lock regeneration procedure](../requirements/README.md).

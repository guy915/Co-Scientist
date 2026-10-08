# CI

CI is GitHub Actions, patterned on the publicly documented presubmit and
postsubmit practices in
[Software Engineering at Google, ch. 23](https://abseil.io/resources/swe-book/html/ch23.html)
and [Test Sizes](https://testing.googleblog.com/2010/12/test-sizes.html), scaled
down to a small project. Where this repository departs from that model, the
section below says so.

## Workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | `pull_request`, `merge_group`, `push` to `main`, `workflow_call`, `workflow_dispatch` | The gate. Presubmit on pull requests: path-filtered, superseded runs cancelled. Postsubmit on `main`: every job runs, nothing is cancelled |
| `nightly.yml` | Cron (daily), manual | Calls `ci.yml` in full, catching breakage that arrives without a commit (dependency drift, runner image changes) |
| `codeql.yml` | Pull request, merge group, push, weekly cron, manual | CodeQL static analysis |
| `dependency-audit.yml` | Weekly cron, manual | `make audit-deps` against the hash-pinned runtime locks and the Bun locks; online, so not a gate |
| `benchmark.yml` | Manual | Live quality benchmark using the `OPENROUTER_API_KEY` repository secret; never gates a change. See [Quality benchmark](../evaluations/README.md#quality-benchmark) |
| `prune-branches.yml` | Manual | Deletes branches with no open pull request and no recent commit (`min_age_hours`, default 24; `dry_run` available); `main` is never touched |

## `ci.yml` jobs

| Job | Runs | Timeout (min) |
|---|---|---|
| `changes` ("Affected targets") | Path filters and target selection; builds the legacy-context matrix | 5 |
| `format-lint` | `ruff format --check` and `ruff check` over `engine`, `app/tests` and `evaluations`; when `engine/mcp_server` changed, also the MCP server tests and its strict `mypy` | 20 |
| `typecheck` | `make typecheck` (strict mypy over `app`, `engine`, `evaluations`) and `make arch` (import contracts). When root config changed: `vercel.json` and `wrangler.jsonc` syntax checks, the Cloudflare worker test (`node --test app/frontend/worker.test.mjs`), `make setup`, `make lint` | 30 |
| `test-engine` | Engine pytest on Python 3.10 (support floor) and 3.12, `fail-fast: false` | 15 |
| `test-app` | App pytest in 3 shards | 25 |
| `evaluations` | `evaluations/tests` and the offline `evaluations.smoke` suite | 15 |
| `frontend` | `bun run lint` (gts), `bun run test` (Vitest), `bun run build` | 15 |
| `e2e` | Playwright through `make e2e` (2 file shards) and `make e2e-production` (built assets, deep links, report reloads, anonymous ownership isolation) | 25 |
| `docker-build` | Builds `Dockerfile.api`, `Dockerfile.mcp` and the frontend dev image, then `docker compose config`; never pushes or runs them | 30 |
| `protected-contexts` | Legacy status names kept until only `Required checks` is required | 5 |
| `required-checks` | Aggregate gate (see Branch protection) | 5 |

Python 3.12 is the primary version everywhere, as in the production images.
The MCP server requires 3.12; the engine alone supports 3.10.

## Selection

Filtering is by job, not `on.paths`: a skipped job reports `skipped`, which
the required check accepts, whereas workflow-level `paths:` would leave a
required check pending forever. The `changes` job declares the dependency
edges by hand as path globs (the app depends on the engine; `evaluations`
runs on any source or documentation change). Every path in the repository
falls under at least one filter, including the Dockerfiles and compose files
(`docker`) and `Makefile`, `vercel.json` and the `.env.example` templates
(`root_config`).

A pull request that touches only `docs/` or `*.md` skips the test targets
(engine, app, frontend, evaluations, MCP server, e2e); `docker` and
`root_config` still follow their own filters. Pushes to `main`, nightly and
manual runs select every target.

## Hermetic rules

No blocking job uses the network for test traffic, model keys or retries.

- Engine tests mock LLM calls. App tests force the deterministic offline
  backend (`COSCIENTIST_FORCE_OFFLINE=1`), and no provider key exists in CI.
  MCP tests use fake `httpx` clients.
- Browser tests get a fresh temporary store, disabled dotenv loading and
  offline evidence checks.
- `evaluations.smoke` is the offline, no-LLM subset; provider-backed suites
  stay opt-in.
- Fetching the repository, actions, registries (PyPI, npm), the Chromium
  download and Docker base images is infrastructure, not test traffic.
  Lockfiles are frozen and tool versions pinned (`ruff==0.15.21`, Bun
  `1.3.14`, Node `24.19.0`, uv `0.11.32` in CI and `0.12.19` for lock
  regeneration and the dependency audit), but the registry fetch itself is
  trusted. `ubuntu-latest` floats; the nightly run is the canary for image
  drift.
- Actions are pinned by SHA with the version in a trailing comment;
  Dependabot proposes updates weekly (`.github/dependabot.yml`). The
  `setup-backend` composite action installs the engine and the CI-only
  `pytest-xdist` so backend jobs share one recipe.

## Sharding

`test-app` runs three shards (`.github/ci_shard.py`: round-robin over sorted
node IDs, identical in every xdist worker, which xdist requires), each on
four `pytest-xdist` workers; every test owns its store, so shards share
nothing. `make e2e E2E_ARGS=--shard=1/2` reproduces one browser shard
locally.

## Flake policy

Never retry: no `retry` wrappers, `--reruns` or marketplace retry actions. A
flaky test is tracked in an issue, quarantined with a skip marker that names
the issue, then fixed or deleted. Silent retries turn a real signal into
noise. `fail-fast: false` on the matrices keeps every interpreter and shard
result visible.

## Style and types

Tooling, not review, owns style: ruff (100 columns; rule sets in each
`pyproject.toml`) and `gts lint` for the frontend. `mypy --strict` is blocking,
and `make typecheck` and the CI job run the same recipe.

## Local equivalents

| Gate | Local command |
|---|---|
| Lint, format, import contracts | `make lint` |
| Types | `make typecheck` |
| Tests | `make test-engine`, `make test-app`, `make test-mcp`, `make test-frontend`, `make test-evaluations`, `make test-all` |
| Offline evaluation smoke | `make eval-smoke` |
| Browser | `make e2e`, `make e2e-production` |
| Production images | `make docker-build` |
| Everything offline | `make check` |

The test and lint jobs spell out their commands rather than calling `make`,
so a Makefile edit cannot silently change those gates. `typecheck` (and the
`root_config` steps) call `make` on purpose: a broken target must fail CI. A
populated legacy-schema database migration is covered by an ordinary
`test-app` test (`app/tests/test_persistence_records.py`), not a dedicated
job.

## Branch protection

`.github/rulesets/main.json` is the ruleset for `main`; GitHub does not apply
it automatically, so import it in the repository settings. It requires:

- a pull request, squash merge only, zero approving reviews, stale reviews
  dismissed on push, review threads resolved;
- the single status check `Required checks`, with
  `strict_required_status_checks_policy: false` (the branch need not be up to
  date);
- no deletion and no force-push, with no bypass actors.

`Required checks` runs with `always()`. It fails on any failed or cancelled
dependency and accepts a path-filtered skip only when `changes` succeeded,
so one stable status covers the matrix and the conditional jobs.

Presubmit tests the pull-request merge ref, which approximates but does not
guarantee current `main`. GitHub's merge queue is not available to
personal-account repositories and the ruleset configures none; the
`merge_group` triggers only keep the workflows ready for one. Enable private
security reporting before public launch; see [LAUNCH.md](LAUNCH.md).

## Not replicated

Google's TAP, Bazel affected-target selection, submit queue, green-head sync
and flake-bot automation have no GitHub equivalent at this scale. Path
filters, per-commit postsubmit, `Required checks` and the manual quarantine
procedure stand in for them. A genuinely slow suite (for example
provider-backed evaluations) belongs in `nightly.yml`, not presubmit.

Production Python runtime closures are hash-pinned under `requirements/`;
regenerate them with runtime metadata changes per
[the lock procedure](../requirements/README.md).

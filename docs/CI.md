# CI

GitHub Actions runs affected checks before merge and comprehensive checks on
`main`, nightly and manual runs. `Required checks` is the single aggregate
status. Superseded PR runs are cancelled; every other run has its own group.
Blocking tests never call live models, fetch external links or retry assertions.

## Workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | PR, including title/body edits; main push; reusable/manual | Blocking checks and aggregation |
| `nightly.yml` | Daily cron, manual | Full CI, including native browsers and macOS confinement |
| `codeql.yml` | PR, push, weekly cron, manual | Python/TypeScript static analysis |
| `sandbox-macos.yml` | Reusable/manual | Native Darwin seatbelt tests |
| `cross-browser.yml` | Reusable/manual | Production WebKit, iPhone WebKit and Firefox guards |
| `dependency-audit.yml` | Weekly cron, manual | Online runtime/Bun advisory scan; separate from the gate |
| `benchmark.yml` | Manual | Opt-in live measurements; see [Quality benchmark](../evaluations/README.md#quality-benchmark) |
| `prune-branches.yml` | Manual | Dry-run-capable cleanup; preserves main and open PR branches |

Merge queues require an organization-owned repository. These user-owned
repositories have no queue or `merge_group` trigger.

## Blocking jobs

| Job | Checks | Timeout (min) |
|---|---|---|
| `changes` | Shared rules; unknown/incomplete diffs select everything | 5 |
| `launch-checks` | Offline checker tests/style, Markdown; PR metadata/history and diff secrets | 5 |
| `format-lint` | Ruff; selected MCP pytest and strict mypy | 20 |
| `typecheck` | Strict mypy, import contracts; selected root setup/lint/routing | 30 |
| `test-engine` | Engine pytest on Python 3.12 | 15 |
| `test-app` | Four independent shards, four workers each | 25 |
| `evaluations` | Evaluation tests, licence inventory and offline smoke | 15 |
| `frontend` | gts, Vitest and production build | 15 |
| `e2e` | Eight weighted development bins and two whole-file production shards | 25 |
| `docker-build` | Three images, real API/MCP starts and Compose validation | 30 |
| `workflow-lint` | Verified actionlint, offline zizmor and detector failure controls | 5 |
| `dependency-review` | PR changes; rejects high/critical advisories in runtime/development/unknown scopes | 5 |
| `sandbox-macos` | Native sandbox tests; selected PRs, nightly and manual runs | Leaf: 15 |
| `cross-browser` / `cross-browser-full` | Six production native guard jobs, selected PRs / immediate comprehensive non-PR runs | Leaf: 10 |
| `required-checks` | Rejects failed, cancelled, omitted and incorrectly skipped dependencies | 5 |

Python 3.12 is the engine/MCP floor and production version. The Python 3.10
worker and compatibility classifiers are removed.

## Launch guards

PR titles are imperative summaries without a Conventional Commit prefix.
Non-merge subjects follow `<type>(<scope>): <subject>`. Tool attribution and
generated/session/coauthor trailers fail in titles, bodies and branch commit
messages; merge commits are exempt only from subject formatting. Event title
and body reach the checker through environment variables, never shell
interpolation. Squash explicitly with a scoped subject and empty body:
GitHub's default copying can otherwise reintroduce forbidden history.
Historical main commits are outside the new PR range.

The added-line secret scan uses checksum-verified gitleaks 8.30.1. Only exact
synthetic test placeholders are allowlisted. Inline suppression and repository
ignore fingerprints cannot silence it; a fresh scratch directory prevents
implicit ignore loading, and findings are redacted.

The Markdown checker reads every tracked `.md` file, relative target, heading
anchor and HTML image/source link; directory fragments use the tracked README.
It never requests external URLs. Three exact upstream vendor links have
owner-approved exceptions; changed lines/targets are checked normally and
vendor source remains untouched.

Workflow lint runs for `.github/**` and checker changes. actionlint 1.7.12 is
checksum-verified; zizmor 1.30.1 checks workflows/local actions offline. Narrow
self-repository annotations are justified: local calls execute this checked-out
commit, and actionlint does not support the newer self-repository syntax.
Checkout credentials are never persisted. Real unsafe workflow/secret fixtures
prove the installed detectors fail.

Axe checks landing, home, a completed report and interview in light/dark,
failing serious/critical violations. Native guards add real keyboard menus,
progress, announcements, headings and contrast. The driver must exactly match
the digest-pinned Playwright image. Each project has two whole-file bins
computed from selected cases; new tagged cases/files participate automatically.
An isolated-runner `--list` control proves assignments without starting servers.

API starts as root with a fresh empty `/app/data` volume and as the image user
without a volume, with `COSCIENTIST_FORCE_OFFLINE=1`. MCP uses a synthetic
shared secret. Every variant uses network isolation, its real entrypoint and
a 60-second readiness deadline. Failures print logs; successful API containers
are removed before the next variant. Final cleanup removes task containers and
the scratch volume. CI never pushes or deploys these images.

macOS tests require Darwin and the seatbelt executable/backend before running,
so missing confinement cannot silently skip. Sandbox source/test or workflow
changes select the native PR job; every nightly runs it. Main pushes skip it.

## Selection and local checks

`.github/ci_paths.json` is shared by Actions and `make presubmit`, which uses
`git diff origin/main...HEAD`. Renames select both paths. PR file lists are
paginated; incomplete lists and unknown paths require comprehensive checks.
Job filtering keeps the aggregate present.

Documentation-only changes skip ordinary test targets but retain launch guards
and affected lint/workflow checks. Sandbox documentation retains its native
selection. Requirement locks and every LICENSE/NOTICE select the evaluation
licence guard.

Install Bun 1.3.14 and run `make setup`, then merge current main and run
`make presubmit` before pushing. It always checks checker units/style,
Markdown, branch history and pinned diff secrets, then explicit affected local
recipes. PR title/body checks run in Actions; `--commits-only` is local history.

| Check | Local command |
|---|---|
| Affected gates | `make presubmit` (`PRESUBMIT_ARGS=--dry-run` lists selection) |
| Checker/history/link/secret guards | `make ci-guards` |
| Workflow lint and actual failure controls | `make lint-workflows` |
| Lint/contracts/types | `make lint`, `make arch`, `make typecheck` |
| Full suites and offline smoke | `make test-all`, `make eval-smoke` |
| Chromium development/production | `make e2e`, `make e2e-production` |
| Enabled-error-SDK bundle budgets | `make build-checked` |
| Production image builds | `make docker-build` |
| Linux confinement | `make test-sandbox-linux` |
| Everything offline | `make check` |

Native jobs additionally require their actual Actions platform; local recipes
retain production browser/engine tests on the developer's platform. Inspect a
native assignment with
`COSCI_E2E_PRODUCTION=1 python scripts/ci/native_browser_shards.py --project webkit --shard 1 --list`.

## Isolation and sharding

API tests own their stores. App shard IDs are deterministic in every xdist
worker. Browser invocations own temporary stores, disable dotenv and force
offline evidence; production tests serve built assets. Offline exact-union
controls exercise weighted development assignment. Production/native bins
preserve whole files and one worker.

Setup may fetch pinned actions, packages, tools and base images; test traffic
is hermetic. CI uses Python 3.12, Bun 1.3.14, Node 24.19.0, uv 0.11.32 and
Ruff 0.15.21. Runtime Python closures are hash-pinned; see
[the lock procedure](../requirements/README.md). Dependabot covers actions,
Bun and Docker digests; Bun upgrades stay held at 1.3.14 while same-tag digest
refreshes remain eligible.

No coverage threshold, external-link gate or Windows runner is configured.
Flakes need an issue and explicit quarantine, then a fix. Silent retries are
forbidden; matrix fail-fast is disabled to retain every result.

## Branch protection

Import `.github/rulesets/main.json`: PR, squash-only merge, resolved threads,
zero approvals and the single Required status, without delete/force-push/bypass.
`strict_required_status_checks_policy` is false; reviewers must integrate
current main and verify the actual head. Launch-lane merges also review CodeQL.

The aggregate runs with `always()`. Changes must succeed; selected jobs must
succeed and unselected jobs must report exactly skipped. Launch guards are
always required, dependency review runs on PRs, and macOS is required on its
selected events. Missing flags/results, cancellation and unknown failed
jobs fail closed. Offline controls include corrupt input to the actual CLI.
The event-appropriate native call must succeed and its companion must skip;
starting comprehensive native work early never waives successful selection.

There is no submit queue or automated flake bot. Provider-backed evaluation
remains explicitly opt-in.

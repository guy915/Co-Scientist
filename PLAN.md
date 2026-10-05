# Test campaign

Cut the test suites to the size a product like Co-Scientist needs while
keeping every behavior they protect. Every decision below was settled with the
owner on 4 October 2026, so the campaign runs unattended: the agent decides by
these rules and reports at the end.

**Status:** Phase 1 complete in PRs #185 and #187. The ratchets, fixed coverage
baseline and shared scaffolding pass the merge gates. Phase 2 starts with the
engine after PR #187 merges. Phase counts and verification are recorded in
`docs/test-campaign/progress.json`.
The improvements campaign is preserved in merged history; PR #184 deliberately
retired `IMPROVEMENTS.md` when it opened this campaign.

## Destination

Each suite tests behavior through the interface its users reach: the HTTP API
for the app, node and task entry points for the engine, tool calls for the MCP
server, rendered UI for the frontend and the browser for end-to-end. A test
file reads as a list of behaviors, and a reader can tell from a failing test's
name what broke.

## Baseline and expected outcome

Re-measured on `f3faefae` before the opening instruments. Outcomes are estimates,
not targets. Counts include shared helpers and both browser suites; tests are
collected cases, including four platform-dependent engine skips. The ratchet
formerly counted 706 lines of frontend test helpers as production; the opening
PR corrects that classification. The actual production baseline is 114,507
lines. The instruments and deterministic fixture fixes add 345 test lines,
three files and eight collected cases, making the opening totals 132,043 lines,
293 files and 6,863 cases.

| Suite | Test lines | Files | Tests | Test lines per production line | Expected test lines |
|---|---:|---:|---:|---:|---:|
| `app/tests` | 51,617 | 91 | 2,201 | 1.36 | ~20k |
| `engine/tests` | 49,714 | 78 | 3,211 | 1.25 | ~20k |
| `app/frontend` | 17,536 | 85 | 822 | 0.66 | ~9k |
| `engine/mcp_server/tests` | 8,232 | 11 | 386 | 1.42 | ~3.5k |
| `evaluations/tests` | 3,079 | 14 | 200 | | ~1.5k |
| `e2e` | 1,520 | 11 | 35 | | unchanged |
| **Total** | **131,698** | **290** | **6,855** | **1.15** | **45–65k, 120–160 files, 2,000–3,000 tests** |

## What stays tested

The suite shrinks; protection does not. These behaviors keep their best tests,
and the files named here are where they live today:

- leases, idempotency and retries: `test_task_worker.py`, `test_task_recovery.py`
- evidence gates: `engine/tests/test_review_gate.py`, `test_claim_grounding.py`
- lineage and provenance: `test_checkpoint.py`, `test_evolve_guard.py`,
  `test_engine_drain_provenance.py`
- spend caps: `test_llm_budget_escalation.py`, `test_llm_attempt_loop.py`
- auth and ownership: `test_authentication.py`, `test_auth_exchange.py`,
  `e2e/production/launch.spec.ts`
- URL guards: `engine/mcp_server/tests/test_web.py`
- sandbox confinement: `test_sandbox.py`, `test_workspace.py`
- SQLite invariants: `test_engine_drain_hypotheses.py`,
  `test_persistence_records.py`
- the MCP study traces: `test_pubmed_pilot_trace.py`,
  `test_pubmed_study4_recovery_trace.py`
- the repository gates in `evaluations/tests`, including the size ratchet
- both browser suites (`make e2e`, `make e2e-production`)
- every behavior the improvements campaign added tests for

## Coverage guard

Line coverage proves the cuts keep protection.

The fixed baseline and each production module's numerator and denominator live
in `docs/test-campaign/coverage-baseline.json`. Suite baselines are app 96.5248%,
engine 96.1331%, MCP 92.6262% and frontend 93.1354%. Protected Python modules
were selected from the named behavior tests and surviving improvements tests;
all frontend production modules are protected. The selection is recorded in
`docs/test-campaign/protection-inventory.json`.

- The opening PR adds `make coverage`: it runs the app, engine and MCP suites
  under `pytest-cov` and the frontend under `@vitest/coverage-v8`, offline and
  serialized, and prints production line coverage per suite and per module.
  Add `pytest-cov` to the MCP server's dev dependencies.
- Record the baseline per suite and per module in the opening PR.
- Every PR keeps each suite's coverage within 0.5 points of its baseline, and
  keeps every module behind a "What stays tested" behavior at or above its
  baseline. Put the before and after numbers in the PR body.
- Coverage that drops because production code was deleted is fine; say so in
  the PR.

## What goes

1. **Tests of private helpers** when a behavior test reaches the same path.
   Test through the public entry point instead.
2. **The same behavior asserted through several entry points.** Keep the one
   closest to the user and delete the rest.
3. **Near-identical tests,** collapsed into `pytest.mark.parametrize` or
   `it.each` tables.
4. **Hand-written arrange blocks,** replaced by builders and factories in each
   suite's `conftest.py` or a shared test helper module.
5. **Copy-pasted fakes and fixtures,** merged into one shared version per suite.
6. **Mock-choreography tests** that assert which internal collaborator was
   called how often. Assert the observable outcome instead.
7. **Trivial tests** of constants, dataclass defaults, enum members, re-exports,
   type shapes and framework behavior.
8. **Tests of retired paths:** old data shapes, historical migrations and
   compatibility code the production reset made unreachable.
9. **Production code that only tests reach.** When a test goes and nothing in
   production calls the code it covered, delete that code too and lower the
   production ceiling.

## Documentation policy

The hidden-reasons policy now lives in AGENTS.md and applies to every test the
campaign touches. Test names carry the behavior.

## Phases

Finish each phase's exit test before starting the next.

### Phase 1: instruments and shared scaffolding

- **Opening PR:**
  - Re-measure the baseline table.
  - Add a test-line ceiling to `evaluations/tests/test_code_size_ratchet.py`
    beside the production ceiling. Both move one way: down.
  - Add `make coverage` and record the coverage baseline.
- **Shared builders and fixtures** (What goes 4 and 5), suite by suite, so
  Phase 2's cuts land on short tests.
- **Exit:** the ratchet carries both ceilings, the coverage baseline is
  recorded, and every suite has one shared set of builders and fakes.

### Phase 2: cut by behavior

- Work suite by suite in this order: engine, app, MCP server, frontend,
  evaluations. Apply What goes 1–3 and 6–9.
- Per file, list the behaviors it protects, keep the best test for each, and
  delete the rest. Delete first: rewrite a test only when deleting it would
  drop a protected behavior's coverage.
- **Exit:** every suite has been through every category.

### Phase 3: organize and finish

- Organize test files by behavior. Merge files that test one behavior from
  several angles, and split files over 800 lines by behavior.
- A final sweep over each suite against What goes.
- **Exit:** the last two themed PRs each removed under 1,000 test lines.

## Rules

- **Shrink genuinely:** delete and rewrite tests. Keep formatting as the
  formatters produce it, and keep tests in counted files where the ratchet
  sees them.
- **Production behavior stays identical.** Production code changes only to
  delete code that only tests reach (What goes 9).
- **The ratchet moves one way:** lower the test ceiling, and the production
  ceiling when it moves, in every PR that shrinks the count.
- **Flaky tests get fixed,** with the cause named in the PR, rather than deleted
  or retried.
- **CI stays hermetic:** no network, no API keys, no retries.
- **One theme per PR, sized for throughput:** 5–10k test lines. A smaller PR is
  right when it finishes a theme. Run targeted tests while iterating, and
  `make coverage` before each merge; CI covers the rest. Run `make check` and
  `make e2e-production` once per suite, before the PR that finishes it.
- **No audit files:** record per-file behaviors and dispositions in the PR
  body, not in committed JSON or docs. `coverage-baseline.json` and
  `protection-inventory.json` stay as the coverage guard's baseline; add
  no new files under `docs/test-campaign/`, and drop any an open PR adds.
- **Merging:** merge each PR once CI is green, with
  `gh pr merge --squash --delete-branch --admin`. The owner authorized bypassing
  `main`'s review requirement for this campaign; this overrides the
  branch-protection rule in AGENTS.md.
- **Deploys:** every merge to `main` deploys production. After each merge,
  confirm the GitHub deployment statuses for the merge commit (`gh api`), the
  api's `/health` at `https://api.ai-co-scientist.com/health`, and the frontend
  at `https://ai-co-scientist.com/`. When one is unhealthy, ship a revert PR
  first and resume once production is healthy again.
- **Git:** follow AGENTS.md. Keep every commit additive: make follow-up fixes in
  new commits on the branch. Run the app and engine pytest suites one after the
  other. Capture each gate's exit status on its own line.
- **Delegation:** run independent suites in parallel with subagents when it
  saves time: `gpt-6-luna` for exploration, `gpt-6.1-sol` for implementation,
  each on its own suite and branch. Give each these rules, the ratchet and the
  coverage guard, and have it confirm its files are on disk before reporting.
- **Progress:** keep each PR body current with phase, suite, theme, test lines
  removed, tests and files removed, coverage before and after, and the new
  totals. After any context compaction, re-read this file and the merged PR
  history to resume.

## Done

The campaign is complete when Phase 3's exit test passes. Mark this file's
status complete in the final PR, then report:

- test lines, tests and files per suite at the start and end of each phase
- coverage per suite at the start and the end
- production lines deleted under What goes 9
- anything that looked redundant but proved load-bearing, and why
- flaky tests found and their causes

When a step depends on something outside the repository that is missing,
finish all other work first, then report that step's concrete blocker.

## Execution environment (owner, before launch)

The campaign runs in a Codex cloud environment on `main`. It needs:

- **Internet access:** GitHub, the production domains and the package
  registries.
- **GitHub:** a token with admin rights on `guy915/Co-Scientist` and the `repo`
  and `workflow` scopes, so `gh` can push, open PRs and merge with `--admin`.
- **Toolchain:** Python 3.12, Node.js 22.13+ and Bun 1.3.14, then `make setup`.
- **Quiet repository:** no other agent is editing tests.

## Previous campaigns

- The lean campaign (closed 4 October 2026), with its phase counts and
  verification evidence, is preserved at
  [`PLAN.md` @ 07fdfb0c](https://github.com/guy915/Co-Scientist/blob/07fdfb0c2e1acd77aa634ab8625e9337aedb6889/PLAN.md).
- The external-reference campaign (closed 1 October 2026) is preserved at
  [`PLAN.md` @ 33ec8984](https://github.com/guy915/Co-Scientist/blob/33ec8984c6f9292a6653cc6a661d32210f55c688/PLAN.md).

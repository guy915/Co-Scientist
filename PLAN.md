# Lean campaign

Trim Co-Scientist to a lean product without losing what it does. Every decision
below was settled with the owner on 3 October 2026, so the campaign runs
unattended: the agent decides by these rules and reports at the end.

**Status:** planned, not started. Baseline `33ec8984`.

## Destination

A researcher states a goal in the web app, the co-scientist loop runs grounded
in literature through the MCP server, and the researcher reads ranked,
evidence-backed hypotheses. Same product, far less code, far fewer tokens per
file an agent reads.

## Baseline and expected outcome

Measured at `33ec8984`. Outcomes are audit estimates, not targets.

| | Today | Expected |
|---|---:|---:|
| Production lines (`.py/.ts/.tsx/.css`, excluding `vendor/`, `references/`, tests) | 161,285 in 443 files | ~110k |
| Test lines | ~158k in 287 files | ~120k |
| Markdown doc lines (excluding prompt templates) | ~16k | ~8k |
| Comments and docstrings in production | 29% of lines, 42% of characters (~600k tokens) | hidden reasons only |

## What stays

Everything not listed under "What goes", including:

- **The whole engine:** every agent, review and ranking depth, generation
  strategies, the adaptive orchestrator, research overview, research descent,
  the execution harness, the LLM cache and campaign mode.
- **The MCP server and all its sources,** including web search, the extra
  literature sources and the study-trace instrumentation.
- **All product extras:** run chat and steering, attachments, own-key model
  choice, shares, email, outcomes and refinement.
- **Logs, metrics and dev or experiment tooling.**
- **Named by the owner:** the landing page, demo runs, the goal interview, the
  run tiers and the offline backend.

## What goes

1. **The `cosci` CLI,** entirely.
2. **The engine's standalone library surface:** public library entry points,
   `examples/`, and the in-process streaming graph path production never runs.
   The engine becomes an internal package of the app.
3. **The paper-fidelity apparatus:**
   - `docs/PARITY.md` and `evaluations/parity_check.py`
   - `docs/CORPUS-EXTRACTION.md` and `docs/PARITY-SOURCES.md`
   - `docs/FIDELITY.md`, `docs/UI-FIDELITY.md` and `docs/fidelity-audit/`
   - the tests that read them, such as `test_published_prompt_fidelity.py`,
     `_published_corpus.py` and `evaluations/tests/test_parity.py`
   - the `make parity` gate and its CI wiring
4. **Prompt saving** (`COSCIENTIST_SAVE_PROMPTS`).
5. **Report files written to disk** (`COSCIENTIST_REPORTS_DIR`). Reports stay in
   the database.

## Documentation policy (code and tests)

- **Hidden reasons only.** A comment or docstring survives only for a reason the
  code can't show: why something is the way it is, an invariant, or an outside
  fact. Keep it to about two lines.
- **Delete everything that restates code:** Args/Returns/Raises blocks,
  narration, `Attributes:` lists repeating fields, and dated finding or ADR
  references.
- **Long incident histories move to `docs/OPERATIONS.md`,** compressed to their
  lesson.
- **Test names carry the behavior.** Test docstrings and comments go unless they
  explain a non-obvious reason.
- **Not documentation:** MCP tool docstrings become the model's tool
  descriptions, and schema field descriptions are sent to the model. Both are
  runtime content and stay.

## Lint changes

The current rules force much of the bloat, so they change first:

- **Drop ruff `D`** (pydocstyle) in `app/` and `engine/`, so docstrings become
  optional.
- **Raise `PLR0913`** (maximum arguments) from 5 to 8.
- **Raise mccabe `max-complexity`** from 5 to 10.

## Phases

Finish each phase's exit test before starting the next.

### Phase 1: tests and docs

- **Opening PR:**
  - Extend `evaluations/tests/test_code_size_ratchet.py` to also report test
    lines and Markdown doc lines. Production lines keep the ceiling.
  - Make the lint changes.
- **Fidelity apparatus:** remove it (What goes, item 3), and update the Makefile,
  CI, `README.md`, `docs/README.md` and the AGENTS.md files to match.
- **Docs:** keep the AGENTS.md/CLAUDE.md files, READMEs,
  `docs/ARCHITECTURE.md`, `engine/docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`,
  `docs/OPERATIONS.md`, `docs/RUNNING-LOCALLY.md`, `docs/CI.md`, `docs/LAUNCH.md`
  and this file. Delete every other doc unless code or the build reads it.
  Prompt templates under `engine/src` are product, not docs.
- **Tests:** remove the audited waste only:
  - docstrings and comments under the documentation policy
  - redundant tests: the same behavior asserted through several entry points
  - tests of private helpers where a behavior test covers the same path
  - exact-string, prose and route-table snapshots
  - copy-pasted fixtures and fakes, merged into shared conftest helpers
  - hand-written arrange blocks, turned into builders or parametrization

  Keep the MCP study-trace tests. Behavior that must stay tested, and where it
  is tested best today:
  - leases, idempotency and retries: `test_task_worker.py`, `test_task_recovery.py`
  - evidence gates: `test_review_gate.py`, `test_claim_grounding.py`
  - lineage and provenance: `test_checkpoint.py`, `test_evolve_guard.py`,
    `test_engine_drain_provenance.py`
  - spend caps: `test_llm_budget_escalation.py`, `test_llm_attempt_loop.py`
  - auth and ownership: `test_authentication.py`, `test_auth_exchange.py`,
    `e2e/production/launch.spec.ts`
  - URL guards: `engine/mcp_server/tests/test_web.py`
  - sandbox confinement: `test_sandbox.py`, `test_workspace.py`
  - SQLite invariants: `test_engine_drain_hypotheses.py`, `test_persistence_records.py`
- **Bar:** CI green and healthy deploys.
- **Exit:** the fidelity apparatus is gone, docs match the keep list, and every
  audited waste category is done.

### Phase 2: the four remaining removals

- Remove What goes items 1, 2, 4 and 5, one PR each.
- Each PR also takes the feature's tests, docs, routes, config, environment
  variables and Makefile targets.
- **Bar:** Phase 1's bar plus `make e2e`.
- **Exit:** all five removals are done, nothing references them, and no orphaned
  configuration remains.

### Phase 3: redundancy

1. **Production reset, authorized by the owner on 3 October 2026:**
   - Export every production run to a file outside the repo. Never commit it;
     run outputs stay out of git.
   - Verify the export's row counts against production.
   - Only then reset the production store. Old runs need not keep loading
     afterwards.
2. **Apply the documentation policy** to all production code.
3. **Remove over-splitting:** inline single-caller helpers where that reads
   better (1,738 today), collapse wrapper chains, and delete re-export facades
   such as `store/__init__.py`'s 177-name `__all__`.
4. **Collapse duplication.** The audit found:
   - one truncation rule written seven ways across `qa/`, `report/`, `store/`
     and `drain/`
   - eight near-identical lookup blocks in `biomedical_databases.py`
   - ten copies of the `scoped_*` ContextVar pattern
   - seven data structures re-carrying the `PromptRunContext` fields
   - three tool-provider layers
   - three near-identical fan-out executors in `engine_tasks/fanout.py`
   - `errorMessage` defined three times in the frontend
   - run-status sets and tier vocabulary duplicated between backend and frontend
5. **Simplify state and idioms:**
   - replace the chat session's 25-field handler bundle with a reducer
   - derive `to_dict` methods from dataclass fields
   - filter in SQL instead of in Python
   - simplify the store schema now that old data shapes are free to go
- **Bar:** full rigor, including light and dark visual comparison for CSS
  changes.
- **Exit:** the last two themed PRs each removed under 500 production lines.

## Rules

- **Remove code, don't compress it.** Collapsing lines or reformatting to game a
  count is forbidden.
- **Never move content to dodge the count:** no shifting code, prompts or data
  into uncounted file types, `vendor/`, `references/`, or out of git. A file
  counts as a test only if no production code imports it.
- **The ratchet only goes down:** lower the production ceiling in every PR that
  shrinks the count, and never raise it.
- **One theme per PR, sized for throughput:** 2–5k lines for removals and for
  doc and test batches, at least 500 for refactors. Open a smaller PR only when
  it finishes a theme. Run targeted tests while iterating, and the phase's full
  bar before each merge.
- **Invariants:** keep the operational invariants in CLAUDE.md and
  `docs/OPERATIONS.md`. An invariant that exists only for a removed feature
  retires with it; say so in that PR.
- **Deploys:** every merge to `main` deploys production (api and mcp on Railway,
  the frontend on Vercel). After each merge, confirm both deploys are healthy
  using read-only status, logs and `/health`. If one isn't, ship a revert PR
  before anything else.
- **Git and PRs:** follow CLAUDE.md. Never amend, reset, stash, or
  checkout/restore files. Run the app and engine pytest suites one after the
  other, never together. Capture each gate's exit status on its own line.
- **Subagents:** at most two Sonnet subagents at a time, on separate subtrees.
  Brief each one on the forbidden git operations and the ratchet, and have it
  confirm its files are on disk before reporting.
- **Hosting configuration:** never write Railway or Vercel configuration.
  Collect the needed changes for the final report: `DEEPSEEK_API_KEY` and any
  variable of a removed feature.
- **Progress:** keep the campaign's progress in the PR bodies: phase, theme,
  lines removed, new totals.

## Done

Stop when Phase 3's exit test passes, or earlier if production stays unhealthy
after a revert. The final report gives:

- production, test and doc lines at the start and end of each phase
- every removal and the reason for it
- anything that looked removable but proved load-bearing, and why
- the Railway and Vercel changes for the owner to make

## Before launch (owner)

- Stop any other agent trimming this repository.
- Launch from a clean checkout of `main`.

## Previous campaign

The completed external-reference campaign (closed 1 October 2026), with its
source decisions, final observations and immutable evidence links, is preserved
at [`PLAN.md` @ 33ec8984](https://github.com/guy915/Co-Scientist/blob/33ec8984c6f9292a6653cc6a661d32210f55c688/PLAN.md).

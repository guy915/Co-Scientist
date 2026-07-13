# Google Co-Scientist fidelity implementation handoff

**Last reconciled:** 2026-07-13 21:59 Europe/Dublin  
**Repository:** `/Users/guy/Code/Co-Scientist`  
**Branch:** `main`  
**Reconciled implementation HEAD:** `c2ac6c3e26430ca959756652c12a247ebcd128d3`  
**Objective:** Complete the implementation as specified by the fidelity diff and
the self-contained implementation prompt. Do not redefine completion around the
current implementation.

This is the canonical continuation document for a fresh session or a different
coding agent. It records implementation state, evidence, worktree ownership,
runtime state, remaining requirements, and the exact completion protocol. Read
the two controlling artifacts in full before changing code; this handoff does
not replace them.

## 1. Controlling artifacts and evidence order

Use sources in this order when claims conflict:

1. `docs/audits/google-co-scientist-implementation/GOOGLE_CO_SCIENTIST_FIDELITY_DIFF_2026-07-12.md`
   is the audited 232-row behavior-level baseline (A01-M20), uncertainty
   register, difference register, and fidelity-first roadmap.
2. `docs/audits/google-co-scientist-implementation/GOOGLE_CO_SCIENTIST_1_TO_1_IMPLEMENTATION_PROMPT.md`
   is the imperative implementation contract. Its 17 acceptance conditions at
   lines 404-447 are the terminal completion gate.
3. Current executable code and runtime behavior. Names, types, routes, prompts,
   comments, mocks, stubs, and UI shells are not implementation proof.
4. Direct tests/evaluations that exercise the claimed behavior. A broad passing
   suite is not proof of an uncovered requirement.
5. `docs/audits/google-co-scientist-implementation/fidelity_closure_overrides.json`,
   regenerated `docs/audits/google-co-scientist-implementation/IMPLEMENTATION_CLOSURE_MATRIX_2026-07-13.md`, and
   `docs/PARITY.md`. These are trackers, not substitutes for code/runtime proof.
6. Git history, checked-in browser captures, evaluation reports, the durable
   SQLite database, and real-provider soak logs.

Google target evidence is inventoried in the fidelity diff under “Evidence
hierarchy and examined material.” The primary local corpus is
`references/core/google-co-scientist/`, including extracted prompts,
pseudocode, outputs, product screenshots, and live footage. The strongest
external sources are the 2026 157-page Co-Scientist paper/supplement, the 2026
Google DeepMind publication, and the 2025 Google Research announcement. Keep
verified Google behavior separate from evidence-bounded reconstruction. Never
claim that proprietary prompts, thresholds, scheduling distributions, compute
budgets, safety classifiers, or current output-quality distributions are known.

## 2. Non-negotiable implementation rules

- Implement only behavior supported by primary evidence or label the behavior
  as reconstructed/inferred with its basis and confidence.
- Treat extensions, substitutions, simplified flows, and intentional product
  differences as fidelity violations, not advantages.
- Never count mock/demo behavior as live scientific behavior. A requested real
  run must fail truthfully if the engine/provider is unavailable.
- Preserve claim-level provenance. Unsupported or contradicted material must
  not enter Elo ranking or a publishable report as verified science.
- Keep Standard Run and Advanced Run as the only faithful run choices.
- Preserve durable task leases, idempotent effects, restart recovery, and
  scientist feedback propagation.
- Do not assign a numerical fidelity score.
- Follow root `AGENTS.md`: comments describe the *what*, commit natural
  checkpoints, and visually/interactively verify frontend work with the built-in
  browser at desktop 1440x720 and mobile 390x780 (or equivalent 16:9/2:1 and
  1:2 viewports).
- Commit messages use `<type>(<scope>): <subject>` and must not mention an AI
  tool or agent.
- Do not discard unrelated dirty-worktree changes.

## 3. Current completion status

Completion is **not proven**. The working acceptance ledger currently records:

- 6 implemented conditions;
- 8 partial conditions;
- 3 unproven conditions.

This is a condition count, not a fidelity score. The 232-row closure matrix is
still substantially stale: only ten finding overrides have been recorded (eight
implemented, two partial). Reconcile every row before completion.

| AC | Current status | Evidence already recorded | Work still required |
|---|---|---|---|
| 1 | implemented | Durable four-field Agent interview; browser journey; interview tests | Preserve proprietary wording uncertainty |
| 2 | implemented | Exactly Standard/Advanced in faithful UI; 3/1 concurrency tests | Preserve undisclosed compute-envelope uncertainty |
| 3 | implemented | Model-directed Supervisor plus durable queue actions and steering priority | Final real-run orchestration evidence |
| 4 | implemented | Multi-process lease, duplicate completion, crash redelivery tests | Finish current real-provider restart soak |
| 5 | partial | Engine/app specialist tests | Strategy-by-strategy end-to-end closure audit |
| 6 | partial | PubMed/PMC, OpenAlex, ChEMBL, UniProt; ranked merge; private and multimodal provenance | Large-corpus and structured-table real-run proof; evaluate AlphaFold requirement boundaries |
| 7 | partial | Claim extraction, semantic assessment option, support spans, publication gate | Audit every report surface and a successful real-provider report |
| 8 | unproven | Evaluation mechanism exists | Green contradiction recall >=0.80 and larger-panel result artifact |
| 9 | implemented | Durable-task-derived activity/progress; focused tests; desktop runtime inspection | Preserve truthful indeterminate behavior |
| 10 | unproven | Report/share/export/Open Agent components and focused tests exist | Complete permission, revocation, export, report, and follow-up browser journeys |
| 11 | partial | Steering reached Supervisor; manual input paths are durable and tested | One real-provider journey proving message, hypothesis, review, and upload each alter later work/output |
| 12 | partial | Layered safety, held-item adjudication, intended-use and auth paths | Consolidated policy audit and complete adversarial suite/report |
| 13 | implemented | Faithful history filters mocks; real provider cannot fall back to mock | Final contamination audit across reports/evidence/recents |
| 14 | partial | Home and Goal Report captures at both target viewports | Every interview, running, report, dialog, share, download, and error state at both viewports |
| 15 | partial | Last full evidence: engine 1046, app 422, frontend 274, frontend build | Re-run all current suites, Ruff, mypy, lint/build, evaluations, safety, provenance, and browser gates after final edits |
| 16 | partial | Scaling/ablation mechanisms and some historical artifacts | Checked-in Elo calibration, expert review, expanded citation, safety, and failure-recovery reports with honest limitations |
| 17 | unproven | Fidelity diff contains uncertainty register | Final row-by-row documentation reconciliation and no literal-parity overclaim |

The detailed machine-readable version is
`docs/audits/google-co-scientist-implementation/fidelity_closure_overrides.json`.
Regenerate the matrix with:

```bash
python scripts/build_fidelity_closure.py
```

Do not change a row to implemented merely because a similarly named component
exists. Record exact symbols, routes, tests, runtime evidence, consequences, and
remaining proprietary uncertainty.

## 4. Implemented checkpoints since the audit baseline

The audited implementation program begins at `6df6531e`. Inspect the complete
history with:

```bash
git log --reverse --oneline 6df6531e^..HEAD
```

Major implemented groups follow. The referenced commits are evidence locators,
not by themselves proof of acceptance.

### Product journey and report

- `4b0ee376`: faithful Standard and Advanced modes.
- `d97b92cf`: durable four-field Agent interview.
- `7c06e32b`, `cbfd6db3`, `d6b25c94`: Goal Report information architecture,
  persisted sections, and evidence-grounded Knowledge Base topics.
- `a6c78662`, `5589c03a`, `5f71653c`: grounded follow-up/export controls,
  revocable sharing, and durable completion email.
- `4a3b6728`, `bdcb5bfb`: intended-use boundaries and verified researcher
  ownership.
- `77837111`, `2352aef7`, `b0aa2634`, `4f90cbc4`: focused browser/report journey
  tests and responsive captures.

### Durable Supervisor and execution

- `625455a6`: persistent scientific task queue.
- `82588231`: Supervisor decisions from live state.
- `d131d7bd`, `f76a66b4`, `d355f19e`: durable workflow/node/specialist tasks.
- `7a9645af`, `3ebdc3a4`: concurrent fan-out and API event-loop isolation.
- `1602e531`: bounded Supervisor queue controls.
- `63a2a9a1`: multi-process crash/restart and duplicate-delivery tests.
- `33630814`: startup recovery workers reclaim interrupted runs.
- `58ac1b55`: deterministic fallback prevents repeated same-iteration
  maintenance tasks from creating a no-progress loop.
- `c2ac6c3e`: a branch superseded by a newer checkpoint completes
  idempotently instead of exhausting retries as a scientific failure.

### Scientist steering and private context

- `aebc471a`, `618cc8cb`: active-run steering reprioritizes later work.
- `31b0328e`, `a54c0d9c`, `0cc6396d`: private corpus binding, uploads, CSV/JSON
  structure preservation, and image/scanned-PDF figure provenance.
- `dfb22531`, `d3af6142`: completed reports reopen and continue from new
  constraints.

### Retrieval, verification, and release gating

- `6df6531e`: unsupported scientific claims gate publication.
- `955081a1`, `75a22cd9`: provenance-stamped semantic verifier and visible
  supporting passages.
- `3f505ec5`: engine evidence release gate tests.
- `2b6223d2`: ranked/paginated retrieval.
- `6b9adb12`: named biomedical databases.
- `b619ebc0`, `a546dca5`, `8c75bdd3`: retraction quarantine, abstract retention,
  and unique evidence-budget filling.
- `5f5f3fba`: real runs default to semantic claim assessment.
- `15c5be25`: claim gate before Elo ranking in the durable app path.
- `5ba857a7`: default PubMed/OpenAlex retrieval plus ChEMBL/UniProt context.
- `e6f9088e`: deep-verification probes trigger fresh evidence retrieval.
- `b7ff6d6f`: mature full/simulation reflection retrieves fresh evidence.

### Scientific coalition behavior

- `1f5276f6`: meta-review retains all review/debate feedback.
- `515a56cd`: specialist feedback propagates into evolution.
- `f8de3786`, `5eef30d5`: distinct evolution operators with genuinely divergent
  combination, analogy, and out-of-box semantics.
- `4c76ae17`: sequential tournament commits.
- `5baf6be4`: configured Elo K-factor reaches real ranking.
- `59b5e8d8`: durable review scores seed ranking.
- `37486e2c`: debate alternates presentation order and normalizes votes to
  stable identities; invalid output has a balanced deterministic fallback.
- `07475502`, `9c1b997b`: authorized persisted proximity landscape and UI.
- `b4d755da`, `f31554cc`: flawed-idea review gate and unified deterministic
  safety decisions.

### Evaluation and truthful presentation

- `c910729d`: scaling, ablation, and release-gate mechanisms.
- `1c55fc4`, `77ec3b0f`, `4cdab801`: progress and activity derive from durable
  committed work.
- `8c544991`: faithful research statistics.
- `85f3df5c`, `87cfd6d1`: mock history quarantine and no mock fallback.
- `c839bd0d`: generated closure ledger infrastructure.

## 5. Current worktree ownership

At reconciliation, HEAD is clean for the recovery fix, but four pre-existing
files remain modified:

```text
 M app/tests/test_runs.py
 M docs/PARITY.md
 M docs/audits/google-co-scientist-implementation/IMPLEMENTATION_CLOSURE_MATRIX_2026-07-13.md
 M docs/audits/google-co-scientist-implementation/fidelity_closure_overrides.json
```

These edits are intentional work in progress. Do not discard them.

- `app/tests/test_runs.py` adds ownership-aware coverage for the persisted
  proximity landscape endpoint.
- `docs/PARITY.md` updates the durable worker, proximity API/UI, Elo K-factor,
  and incremental proximity rows to match current code.
- `fidelity_closure_overrides.json` records ten finding overrides and the
  current 17-condition ledger.
- `IMPLEMENTATION_CLOSURE_MATRIX_2026-07-13.md` is regenerated output from those
  overrides; regenerate it rather than manually drifting it.

Before the next commit, inspect `git diff`, run the named tests, regenerate the
matrix, and commit related tests/docs at a natural checkpoint. Preserve any
newer edits if another agent has changed the same files.

## 6. Real-provider soak state

The current real-provider durability run is stored in the repository-root
database, **not** `app/coscientist.db`:

```text
Database: /Users/guy/Code/Co-Scientist/coscientist.db
Run id:   95b46092-0006-4673-bf48-1042bf993d8a
Provider: engine (DeepSeek through LiteLLM)
Mode:     Standard
Budget:   max_iterations=2, initial hypotheses=8, evidence target=8
Status at 2026-07-13 21:59: queued
Tasks:    202 completed, 2 failed, 1 leased
Latest checkpoint sequence: 81
```

The two failed tasks are historical evidence of defects now fixed:

- an obsolete ranking task exhausted retries with `specialist task checkpoint
  was superseded`;
- an obsolete mature-reflection aggregate exhausted retries with `reflection
  aggregate checkpoint was superseded`.

Commit `c2ac6c3e` makes future superseded tasks complete with a structured
`{"superseded": true, "reason": ...}` result. The running API process was
started before that commit, so restart it to load the fix. The final leased task
at reconciliation was `engine.node.ranking`, owner
`embedded-recovery:23842:3`. Let the lease expire and the recovery worker reclaim
it; do not mutate task rows by hand merely to make the run appear successful.

The run already exposed and led to fixes for:

1. startup recovery missing unexpired leases (`33630814`);
2. repeated same-iteration reflection/no-progress scheduling (`58ac1b55`);
3. obsolete branch failures (`c2ac6c3e`).

The API was healthy at reconciliation and reported the MCP/PubMed/literature
stack available. Rehydrate services with the correct database:

```bash
# Terminal 1, from repository root. Python 3.12 environment required.
cd mcp_server
../app/.venv/bin/uvicorn mcp_server.server:app \
  --host 0.0.0.0 --port 8888

# Terminal 2, from app/. Explicit root DB path is essential.
cd app
COSCIENTIST_DB_PATH=../coscientist.db \
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8008
```

Then verify:

```bash
curl -sS http://127.0.0.1:8008/health
curl -sS http://127.0.0.1:8008/status
sqlite3 -cmd '.timeout 10000' coscientist.db \
  "select status,count(*) from scientific_tasks where \
   run_id='95b46092-0006-4673-bf48-1042bf993d8a' group by status;"
```

Do not call the soak successful merely because it reaches a terminal state.
Inspect the final run, checkpoints, events, evidence, claim edges, hypotheses,
matches, safety decisions, and report. A truthful blocked report is correct
behavior but does not prove the successful-report acceptance path. If this run
cannot pass the semantic publication gate, start another small real-provider
run after the retrieval fixes and retain both blocked and successful evidence.

## 7. Known material gaps and risks

### Immediate runtime risks

1. Restart the API on `c2ac6c3e` and prove obsolete tasks no longer retry/fail.
2. Confirm `current_iteration` advances after the Supervisor no-progress fix.
3. Confirm the run terminates rather than scheduling recurrent reflection
   indefinitely.
4. PubMed full-text calls have occasionally returned an empty/non-JSON payload.
   The collector records query errors and continues; assess whether source
   fallback and visible degradation are sufficient.
5. Full/simulation reflection now performs fresh retrieval per hypothesis. It
   can create many concurrent searches and model calls. Measure rather than
   hiding the cost or collapsing the disclosed strategy.

### Scientific and architectural gaps

1. The durable app path gates claims before Elo, but verify whether direct
   engine/CLI paths can still rank unsupported hypotheses. The product path is
   primary, yet a shared engine-native invariant is preferable if it does not
   duplicate incompatible policy.
2. Live DOI/URL resolution and source availability validation need a final
   audit. Retraction metadata is implemented, but exact Google verification is
   undisclosed.
3. Retrieval breadth has materially improved but general web/non-biomedical
   scope, AlphaFold invocation, and hundreds-of-documents scale require
   evidence-bounded decisions and honest tests.
4. Published-output reasoning density, novelty, testability, uncertainty, and
   detailed experimental proposals remain quality gates, not structural fields
   to mark complete by presence.
5. Human steering, manual hypotheses, reviews, and uploads have durable paths,
   but all four still need a single real-provider trace showing a later task or
   final artifact changed.
6. Safety policy is present in engine and app layers. Audit for contradictory
   classifications, prove held-item adjudication, and create a complete
   adversarial report. Google's classifier/threshold equivalence remains
   unverifiable.
7. Exact Google Supervisor prompts, task granularity, termination policy,
   worker topology, memory implementation, run compute, concurrency internals,
   and safety controls are proprietary. The final docs must label the closest
   reconstruction rather than assert literal parity.

### Evaluation gaps

Existing mechanisms live in `evaluations/`, and historical results live in
`evaluations/results/`. Do not fabricate experts, wet-lab validation, Google
private data, or unpublished quality labels.

- Citation: current shareable dataset is small and synthetic. Run it, meet the
  required contradiction-recall gate, expand with a legally shareable audited
  panel, and document limitations.
- Elo calibration: produce a checked-in report distinguishing Elo from external
  quality ground truth. Use blinded expert labels only if real labels exist.
- Expert review: `evaluations/expert_review.py` exports/imports blinded panels;
  it is not itself an expert result. A missing recruited panel must remain
  explicitly external/unavailable.
- Scaling and ablation: mechanisms exist. Generate checked-in artifacts from
  real controlled runs with paired goals and honest compute metrics.
- Safety: expand and record adversarial results; do not equate a small lexical
  set with Google's published 1,200-goal evaluation.
- Recovery: check in a failure-injection report including duplicate delivery,
  two restarts, expired leases, superseded work, and terminal artifact identity.

## 8. Strict next-action sequence

Resume in this order unless new runtime evidence changes the priority:

1. Read this handoff, the fidelity diff, and the implementation prompt fully.
2. Inspect `git status`, `git diff`, HEAD, running processes, and the root DB.
3. Restart the API with `COSCIENTIST_DB_PATH=../coscientist.db` so commit
   `c2ac6c3e` is loaded. Preserve the MCP server.
4. Let the real-provider run reclaim naturally. Diagnose and fix every new
   durability/orchestration defect. Commit each verified natural checkpoint.
5. Inspect the terminal run end to end. If blocked by the claim gate, preserve
   that evidence and execute a second real run to prove successful publication.
6. Close AC5 with a specialist-by-specialist behavioral inventory and missing
   end-to-end tests.
7. Close AC6-8 with large/private/structured ingestion evidence, all-surface
   claim auditing, and a green checked-in citation evaluation.
8. Close AC10-14 with real input propagation, safety/adjudication, and complete
   browser journeys at desktop and mobile.
9. Produce every honest evaluation artifact required by AC16. Mark genuinely
   external expert/wet-lab requirements as external rather than fabricating
   results.
10. Reconcile all 232 findings into the override ledger, regenerate the closure
    matrix, and update `docs/PARITY.md` so descriptions match current runtime.
11. Run every full automated gate and visually verify the final built product.
12. Perform a requirement-by-requirement completion audit. Completion requires
    direct evidence for all 17 acceptance conditions and every actionable
    finding; “no obvious failures” is insufficient.

## 9. Verification commands

Use repository environments as configured; do not assume `ruff` is installed in
`app/.venv/bin`. On the reconciled machine it is `/opt/homebrew/bin/ruff`.

```bash
# Focused recovery checkpoint already passed on c2ac6c3e:
cd app
.venv/bin/pytest tests/test_task_worker.py tests/test_engine_tasks.py -q
/opt/homebrew/bin/ruff check \
  app/engine_tasks.py app/task_worker.py tests/test_task_worker.py
.venv/bin/mypy app/engine_tasks.py app/task_worker.py
# Result: 25 passed; Ruff clean; mypy clean.

# Full repository gates before completion:
cd /Users/guy/Code/Co-Scientist
make test-all
make lint
make typecheck
make build

# Direct frontend gates if diagnosing individually:
cd app/frontend
bun run test
bun run lint
bun run build

# Evaluation and ledger gates:
cd /Users/guy/Code/Co-Scientist
python -m pytest evaluations/tests -q
python evaluations/smoke.py
python evaluations/parity_check.py
python scripts/build_fidelity_closure.py
```

Confirm what each Make target actually covers before using it as broad evidence.
Record exact command, environment, date, count, result, and artifact path in the
verification log. A previous full-suite count is historical evidence only after
new edits.

## 10. Browser evidence and required continuation

Checked-in captures currently include:

- `docs/assets/faithful-home-desktop-2026-07-13.png`
- `docs/assets/faithful-home-mobile-2026-07-13.png`
- `docs/assets/faithful-goal-report-desktop-2026-07-13.png`
- `docs/assets/faithful-goal-report-mobile-2026-07-13.png`

These prove selected states, not the whole journey. Use the built-in browser and
inspect interactively, not screenshots alone. At both 1440x720 and 390x780,
cover:

1. new challenge composer;
2. every interview turn and editable four-field plan;
3. Standard/Advanced configuration and concurrency-limit state;
4. queued, running, indeterminate progress, active tasks, recovery, failure,
   blocked, and completed states;
5. Ideas list/buckets, detail, evidence spans, lineage, reviews, debates, Elo,
   and proximity landscape;
6. Knowledge Base, Summary, and Run Specifications;
7. Open Agent and idea-level follow-up streaming;
8. NotebookLM handoff, markdown/PDF download, public sharing, revocation, and
   unauthorized views;
9. safety hold/adjudication and scientific intended-use notices;
10. long text, empty data, loading, network errors, dialogs, focus order,
    keyboard use, clipping, overflow, and accessible labels.

Capture final artifacts with date/state/viewport in their names and link them
from the acceptance ledger.

## 11. Common traps already encountered

- Starting FastAPI from `app/` without `COSCIENTIST_DB_PATH=../coscientist.db`
  silently uses `app/coscientist.db` and makes the soak appear absent.
- Startup reconciliation alone cannot recover an active unexpired lease; an
  embedded recovery cohort must remain alive until it can reclaim the task.
- A superseded task is normal optimistic-concurrency obsolescence, not a retryable
  scientific failure.
- The Supervisor model may repeatedly choose an apparently useful maintenance
  task without advancing an iteration; hard invariants must prevent no-progress
  loops while preserving one adaptive pass.
- Fewer than two claim-gate-eligible hypotheses means ranking must skip
  truthfully; do not inject unsupported ideas to force a report.
- Matching agent names, routes, tabs, schemas, or prompt filenames is not
  behavior proof.
- Historical tests and screenshots become stale after implementation changes.
- The closure matrix defaults to `unproven`; that is intentional. Do not weaken
  the generator or acceptance rules to make the ledger green.
- Do not present the expert-review harness as an expert review result.
- Do not claim Google-equivalent output quality from Elo, self-review, or a
  small synthetic evaluation set.

## 12. Completion protocol

Before declaring the implementation complete:

1. Derive every requirement from the diff, implementation prompt, 232 findings,
   uncertainty register, roadmap, and repository instructions.
2. For every requirement, identify the authoritative evidence that would prove
   it and inspect that current evidence directly.
3. Classify evidence as proving, contradicting, partial, weak/indirect, missing,
   or proprietary/unverifiable.
4. Continue implementation for every actionable gap. Preserve undisclosed
   Google internals in the uncertainty register instead of inventing parity.
5. Ensure every material conclusion links to files, symbols, routes, prompts,
   tests, runtime records, browser captures, or external primary evidence.
6. Ensure the faithful product contains no visible non-faithful extension unless
   isolated behind an explicit developer/reference mode.
7. Ensure all required evaluation reports are checked in with methodology,
   limitations, source references, and no fabricated results.
8. Re-run all software, evaluation, provenance, safety, and browser gates from
   the final worktree.
9. Regenerate the closure matrix and confirm the parity checker accepts every
   `verified` row's named evidence.
10. Commit all intended work at natural checkpoints and confirm no unexplained
    dirty files remain.

Only then may the persistent goal be marked complete. The closest achievable
result will still contain an explicit proprietary/unverifiable register; that
is evidence fidelity, not unfinished engineering.

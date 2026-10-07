# Re-architecture

Restructure the codebase into one package organized by domain, with
boundaries that CI enforces. Behavior does not change: same prompts, same
outputs, same API, same persisted data. This plan only moves, deepens and
deletes.

**Status:** drafted 6 October 2026. It starts after the cuts, shrink and
optimization campaigns (`docs/CAMPAIGNS.md`) are all done. One lead runs it.

## Why

After the three campaigns the code is smaller, but its shape is still the
shape it grew into:

- **Two packages for one product.** `engine/` and `app/` split by history,
  not by domain. Shrink lever 11 merges them, but merging is not organizing:
  about 50 flat modules sit in `app/app/` and 30 packages in the engine.
- **No owner for the research state.** Hypotheses, reviews, evidence, claims,
  matches and lineage are read and written from `store/`, `engine_tasks/`,
  `report/`, `claims/`, `hypothesis/`, `citations/` and the engine agents.
  Kosmos and the Co-Scientist paper both put this state (a "world model" /
  "context memory") at the center, with agents as workers around it.
- **LLM policy in two places.** Admission, budgets, retries and routing live
  in `engine/.../llm/`, but `llm_request.py`, `llm_scope.py`,
  `execution_policy.py`, `byok_models.py` and `free_usage.py` in the app also
  decide them.
- **Workflow and agent code mixed.** Most of the pipeline is a fixed workflow
  (generate → review → rank → evolve → report). Only the supervisor and the
  tool loops are agents. The code does not show that split, so both get the
  same tests and budgets.
- **Rules only in prose.** Layering and invariants live in AGENTS.md files.
  Agents write most of this code; rules that tooling does not enforce decay.
- **A hand-built durable runtime.** `engine_tasks/`, `task_worker/` and the
  task tables re-implement what durable-execution libraries now ship
  (checkpointed steps, durable queues, retries) on the same SQLite file.

## Goals

1. One Python package organized by domain. Each module has a small public
   interface; everything else is private.
2. Layers and module boundaries enforced by `import-linter` in `make lint`
   and CI.
3. One research-state module that is the only writer of the scientific
   tables.
4. An explicit split between the pipeline (workflow) and agent loops.
5. One LLM gateway: every model call goes through one interface that owns
   profiles, admission, budgets, retries and telemetry.
6. A tested decision on the durable runtime: keep it behind one interface,
   or replace it with DBOS.
7. Standard tracing (OpenTelemetry GenAI conventions) at the gateway, the
   node runner and HTTP, off by default.
8. The frontend organized by feature, with boundaries enforced by ESLint.
9. A glossary and ADRs, so names and decisions stay fixed.

## Non-goals

- No microservices, no second replica, no Postgres. The api stays one
  replica on one SQLite file (see AGENTS.md "Production hosting").
- No agent framework (LangGraph, CrewAI) as the core.
- No prompt, schema, scoring or output changes. No new features.
- No API wire changes. The frontend contract stays byte-compatible.
- No renames of persisted names: node keys, task types, checkpoint keys,
  idempotency keys, table and column names, event kinds.
- The MCP server stays a separate package and deploy. It shares only its
  wire contract with the app.

## Target structure

The package name is whatever shrink lever 11 chose (below: `coscientist`).
Layers from top to bottom; a layer may import only layers below it.

```text
coscientist/
  main.py              composition root: builds the app, wires adapters
  api/                 FastAPI only here: routers per domain, SSE, wire models
  orchestration/       the workflow: run lifecycle state machine, node
                       registry, fan-out primitive, durable runtime
                       (queue, leases, worker cohorts, recovery), steering
  science/             one module per agent: generation, reflection,
                       ranking, evolution, proximity, meta_review,
                       supervisor. Each: prompt + schema + run(input) -> output.
                       No database access.
  domains/
    research_state/    the world model: hypotheses, reviews, evidence,
                       claims, matches, lineage, Elo projection. Only writer
                       of those tables. Typed models live here.
    safety/            intake, hypothesis screen, final gate
    reports/           report build, gates, markdown
    chat/              chat sessions, interviews, Q&A
    documents/         ingest, staging, chunking, PDF
    access/            auth, credentials, BYOK, free usage, retention
  platform/            adapters to the outside world
    db/                connection scope, schema, migrations, checkpoints
    llm/               the gateway: profiles, admission, request, attempts,
                       structured output, tool loops, telemetry
    retrieval/         MCP client, search fusion, relevance
    sandbox/           confined workspace and skills
    cache/
    telemetry/         logging setup, OpenTelemetry wiring
  core/                types, errors, ids, config, clock. No I/O.
```

Rules for the structure:

- **Public interface.** Each module exposes its interface in `__init__.py`.
  Other modules import only from there. Names starting with `_` and
  submodules are private.
- **`science/` modules are independent.** No agent imports another agent.
  Shared helpers go to `core/` or a named shared module.
- **`domains/` modules are independent** except through the interfaces
  ADR-001 lists (for example `reports` reads `research_state`).
- **Third-party confinement:** `fastapi` only in `api/` and `main.py`;
  `sqlite3` only in `platform/db/` and domain repositories; provider SDKs and
  `httpx` only in `platform/llm/` and `platform/retrieval/`.
- **`evaluations/`** imports only the public interface of the package.

The map is a target, not a contract. Phase 1 confirms or adjusts it against
the real post-campaign code, and ADR-001 records the final version.

## Phases

### Phase 0: survey (read-only)

Measure the post-campaign state. Write `docs/rearchitecture/survey.md`:

- Line counts per directory; test, CI and `make check` times.
- The import graph (use `grimp`, which `import-linter` installs): cycles,
  fan-in and fan-out per module, cross-layer imports.
- Change hot spots from `git log` (files changed most often since August).
- Shallow modules by the deletion test: if deleting a module only moves its
  complexity to its callers, it is a pass-through.
- What the shrink left undone (typed models, engine move, levers that
  slipped). Those become phases here, not prerequisites.
- Everything that stores or loads a module path by string:
  `importlib.import_module` calls (for example in `llm/__init__.py`), the
  pickle cache (`cache/`), `tools.yaml`, Railway watch paths, Dockerfile
  `COPY` lines, `Makefile` targets, CI path filters, mypy and ruff configs.
  Each is a break point when files move.
- One Express benchmark run as the baseline (see `docs/OPTIMIZATION.md`).

### Phase 1: glossary, ADRs, target map

- `docs/GLOSSARY.md`: one line per domain term (run, cycle, node, task,
  hypothesis, review, match, claim, evidence, citation, steering, cohort...).
  Use these terms in module and type names.
- ADRs in `docs/adr/`, one page each: context, decision, consequences.
  - ADR-001 module map and allowed dependencies.
  - ADR-002 layering and how it is enforced.
  - ADR-003 durable runtime: keep or DBOS (after phase 3).
  - ADR-004 LLM gateway interface.
  - ADR-005 tracing.
- Decide on the recommended option and record it; do not wait for the owner.
  List each decision on the board so the owner can overrule it.

### Phase 2: guardrails first

- Add `import-linter` as a dev dependency and a `make arch` target that
  `make lint` and CI run.
- Write the target contracts now: layers, independence, forbidden imports.
- Record every current violation in an ignore list in the config. The list
  may only shrink: a structural test fails if it grows. Each later PR removes
  the entries it fixes. The campaign ends with an empty list.

### Phase 3: durable runtime prototype (time-boxed, never merged)

Port one fan-out phase (review) to DBOS on SQLite on a throwaway branch.
Go only if every check passes:

1. Kill the worker mid-fan-out; on restart it resumes with no duplicate
   model calls and no lost results.
2. Leases, retry budgets, future-due tasks and steering admission behave as
   `docs/OPERATIONS.md` requires.
3. It shares the one SQLite file safely: one writer, WAL, no write lock held
   over network I/O, no write on every poll tick, no VACUUM or truncating
   checkpoint from the serving process.
4. Startup stays cheap; recovery runs outside the port-binding path.
5. It works with the worker cohorts' separate event loops, sharing no
   asyncio primitive across them.
6. Moving every phase would delete at least 1.5k lines net.
7. In-flight runs have a cutover path: new runs start on the new runtime,
   old runs drain on the old one, then the old one is deleted.

If any check fails: keep the hand-built runtime, put it behind one
`orchestration.runtime` interface and record why in ADR-003. Do not retry
with another library in this campaign.

### Phase 4: moves (mechanical)

- Move one module group per PR with `git mv`. A move PR only moves files and
  fixes imports; no edits. This keeps review easy and rename detection
  intact. Check the diff for rename artifacts before merging.
- No compatibility shims. Fix every importer in the same PR.
- Update every string path phase 0 found, in the same PR. Bump the cache key
  version when pickled types move.
- Order, bottom up, so each PR lands on settled ground: `core` →
  `platform/db` → `platform/llm` → `platform/retrieval`, `sandbox`, `cache`,
  `telemetry` → `domains/research_state` → other domains → `science` →
  `orchestration` → `api` → `main.py`.
- Moves touch nearly every file, so they run one at a time. Nothing else
  merges into the moved folders while a move PR is open.

### Phase 5: deepen

After a module has moved, make its interface small:

- **research_state:** one repository interface per concept; delete direct
  table access elsewhere. Typed models in, typed models out.
- **LLM gateway:** one entry point for a model call (structured or tool
  loop). Move the app-side policy modules into it. App code never sees
  provider details.
- **science:** each agent is `run(input, gateway) -> output` with typed input
  and output. Agents do not touch the database or the queue.
- **orchestration:** one fan-out primitive used by every phase (if shrink
  lever 3 did not finish it); nodes declared in one registry.
- **Delete pass-throughs** the deletion test finds.

One concept per PR. Each removes its ignore-list entries.

### Phase 6: tracing

- OpenTelemetry spans with GenAI semantic conventions at the LLM gateway
  (model, tokens, cache hits, reasoning tokens, retries), at the node runner
  (node key, run id, task id) and at HTTP.
- No exporter unless an env var is set. CI and tests stay hermetic.
- The existing persisted logs and telemetry stay; spans add to them.
- List the exporter account and env vars the owner must create on the board.

### Phase 7: frontend by feature

- `src/features/{chat,runs,report,access,diagnostics}/` and
  `src/shared/{api,ui,hooks}/`. A feature imports only `shared/` and its own
  files.
- Enforce with ESLint (`import/no-restricted-paths` or
  `eslint-plugin-boundaries`).
- Same rules as phase 4: moves first, then edits. Verify light and dark
  themes in `make e2e`.

### Phase 8: docs and deploy config

- Rewrite `docs/ARCHITECTURE.md` from the final structure, with the layer
  diagram and the module map.
- Update root and nested `AGENTS.md` files: point to the glossary, ADRs and
  `make arch`; delete prose rules that a contract now enforces.
- Dockerfiles, `Makefile`, CI path filters, mypy and coverage paths.
- Railway watch paths change with the moves: put the exact new values on the
  board for the owner before the first move PR merges.

## Done when

| Check | Target |
|---|---|
| `import-linter` ignore list | Empty; contracts run in CI |
| Import cycles | 0 |
| Express benchmark | Within the baseline noise floor |
| `make check`, CI time | Not slower than phase 0 |
| Line count | Not larger than phase 0 |
| Docs | `ARCHITECTURE.md`, glossary and ADRs match the code |

## Rules

- **Behavior-preserving.** No prompt, schema, scoring, API or persisted-name
  changes. A test change is allowed only for an import path or a private
  helper that no longer exists; never weaken an assertion.
- **Benchmarks.** Run one Express benchmark after each PR that changes
  `orchestration/`, `science/` or `platform/llm/` behavior (not after pure
  moves). The free model allows about 1,000 requests a day, shared with the
  owner; at most two benchmarks at once.
- **Operational invariants.** Every item in AGENTS.md "Operational
  invariants" and `docs/OPERATIONS.md` holds after every PR.
- **Gates.** Each PR passes `make lint`, `make typecheck`, `make test-all`,
  `make e2e` and `make arch`; record each exit status. Only the lead runs
  full suites, one at a time.
- **Git.** Follow AGENTS.md: commit format, no AI attribution, additive
  commits, no rebase or force-push on shared branches.
- **Production.** Every merge to `main` deploys. After each merge, check the
  deployment statuses and check runs for the merge commit. If a deploy fails,
  ship a revert first. Never change Railway or Vercel settings or touch the
  production database; owner requests go on the board.

## Running it

- **Board.** One issue, `Campaign board: re-architecture`, kept current:
  phase, open PRs, decisions taken, owner requests, blockers.
- **Merging.** Squash-merge with the GitHub merge tool once CI is green on
  the latest commit, as for the earlier campaigns.
- **Lanes.** Three agents on separate accounts. The lead owns the board and
  phases 0–2, 4–6 and 8. Lane F owns `app/frontend/` and `e2e/`: the
  transitions work first, then phase 7. Lane P runs phase 3 on
  `proto/dbos` and reports; the lead writes ADR-003.
- **Subagents.** Sonnet only. Moves are serial; the parallel work is the
  survey, the DBOS prototype, tracing, the frontend and docs. For gateway,
  runtime and research-state work the lead gives small, precise tasks or
  does it itself, and reviews every line.
- **Pacing.** Rolling 5-hour usage limit, unattended: use most of each
  window without reaching it, and keep a recurring 2-hour check-in that
  resumes from the board and the merged PRs.

## Risks

| Risk | Mitigation |
|---|---|
| A move breaks resume of in-flight runs | Persisted names never change; phase 0 lists string paths; recovery tests run on each move PR |
| Pickled cache entries fail after a move | Bump the cache key version in the same PR |
| Deploy breaks on a path change | Dockerfile, watch paths and Makefile change in the same PR as the move; check the deployment after merge |
| Long-lived move PRs conflict | One move at a time, small groups, merge fast |
| DBOS looks good but fails under load | Hard go/no-go list; never merged from the prototype branch |
| Boundaries erode again later | Contracts in CI; the ignore list can only shrink |

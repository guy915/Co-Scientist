# Architecture deepening campaign: handoff

Status as of 2026-10-02 00:15 CEST. Work order for whoever continues the
campaign; delete this file when section 1 and the backlog are done.

## Already on `main`

- #95: `co_scientist.llm` package (28-name interface), one attempt loop
  (`llm/attempts/retry.run_attempts`), one model profile table
  (`llm/profile/`), durable-path reducers read off `WorkflowState`
  annotations (`task_runtime.channel_reducers`), topology declared once
  (`workflow_topology.py`), `app/report/` package, `process_mode.py` seam,
  `claim_verdict.py`, `engine_tasks` runtime seam, `engine_adapter/drain/`
  subpackage, `api/run_lifecycle.ts`, and a fix for the minimal-reasoning
  rung `KeyError`.
- #96: claim-gate roles through `claim_verdict`; the contradiction panel no
  longer calls a published idea "withheld".
- #97: completion backend seam (`llm/request/backend.py`).
- #98: app and evaluations tests fake engine completions through `FakeBackend`.
- #99: `app/engine_tasks/`, `app/claims/`, `app/runs/` packages; CI's app-test
  job ceiling raised to 25 minutes.

## 1. Finish first

1. **#101** (`refactor/app-packages-2`): test-only re-exports removed, plus
   eleven more app packages (`interviews`, `seed`, `demo_seed_data`, `safety`,
   `qa`, `pdf`, `outcome_refinement`, `task_worker`, `run_modes`,
   `hypothesis`, `citations`). Already merged with `main` at #99; app suite
   green. Merge once CI is green.
2. **#100** (`refactor/engine-packages`): engine `constants/`, `models/`,
   `state/`, `cache/`, `mcp_client/`, `offline/` packages; `.gitignore` and
   `.dockerignore` re-include `engine/src/co_scientist/cache`; `Dockerfile.api`
   imports every engine module at build time. It CONFLICTS with `main`. After
   #101 lands: merge `origin/main` into the branch and resolve (its app-side
   edits are path-comment updates; #99 and #101 moved those files). Then search
   for stale engine paths, e.g.
   `rg 'co_scientist\.(offline_|cache_|models_|mcp_client_|mcp_campaign|constants_|state_)'`
   (#98's `app/tests/_llm_fake_backend.py` needed `co_scientist.offline.llm`).
   Run the engine and app suites, mypy x3, parity and the length gates, push,
   confirm CI's docker job builds, then merge.
3. Run `make e2e` on `main`, then check production: read-only
   `railway logs` for the api startup and the health endpoint. The package
   moves changed every startup import path.

Merging: `main` requires a review; the owner's standing instruction is to
merge green work without asking, using `gh pr merge <n> --merge --admin`.

## 2. Backlog, in order

Items marked OWNER DECISION need the owner's answer first; skip them.

1. OWNER DECISION. Tool-call 429s: `call_llm_with_tools` gets no throttle
   backoff or rate-limit park (`AttemptPlan.escalation_only` in
   `llm/attempts/contract.py`). A 429 there fails at once.
2. OWNER DECISION. The app's direct provider path (`app/app/llm_request.py`:
   interview, Q&A, titling, goal restatement, credentials, run announcement)
   bypasses the engine's timeout ceiling, call budget and telemetry, and
   `config_thinking.py` hand-copies the engine's thinking floors. Routing it
   through the engine backend changes spend accounting.
3. Make the free-model catalog injectable: autouse `_free_catalog` fixtures in
   `engine/tests/conftest.py` and `app/tests/conftest.py` patch the private
   `_snapshot` / `_fetch_catalog` (22 sites).
4. Inert patch: `app/tests/test_engine_tasks_dispatch.py` patches
   `execute_finalize`, but `engine_tasks._ENGINE_TASK_DISPATCH` captured it at
   import, so the patch does nothing.
5. Extract evidence gathering from `agents/generation` (12.4k lines):
   `reflection/deep_verification_evidence.py` imports the private
   `literature_review.run_config._get_search_config` and
   `orchestration._phase2_collect_papers` across agents.
6. Frontend wire types: 46 hand-mirrored types in
   `app/frontend/src/api/*_types.ts`. Add backend response models and a
   contract test.
7. Re-run the architecture review (`improve-codebase-architecture`) on the
   new layout.

## 3. How to work here

- Setup: `make setup`; then the venv is `.venv/bin/python`. Run mypy from
  `app/`, `engine/` and `evaluations/` with their own configs.
- Gates: `evaluations/tests/test_file_length.py` (500 lines per file),
  `test_function_length.py` (40 lines per function, TS describe blocks too),
  `python -m evaluations.parity_check`. `docs/PARITY.md` cites test file paths
  and test function names: never move or rename a cited test.
- Moving a module family into a package: `git mv`; `X.py` becomes
  `X/__init__.py` keeping its public names; siblings drop the prefix. Rewrite
  monkeypatch targets (attribute and string form, and logger names) to the
  module whose globals the code reads at call time; a patch on a module that
  only re-exports a by-value import passes and tests nothing. Keep lazy
  imports lazy, and check every module imports first in a fresh interpreter:
  `python -c "import importlib,pkgutil,app; [importlib.import_module(m.name) for m in pkgutil.walk_packages(app.__path__, 'app.')]"`
  (same for `co_scientist`).
- Test reproducibility: write the characterization test first and see it pass
  on the old code before refactoring; reproduce a bug red before fixing it.
- Never judge a gate through `| tail`: capture `$?` on its own line.
- If you work from a git worktree of a checkout whose venv has the engine
  installed editable from elsewhere, 8 subprocess tests in
  `evaluations/tests` import that other engine. Symlink
  `co_scientist -> engine/src/co_scientist` at the root for the run.
- The owner is on a small usage plan: one worker at a time, targeted tests
  per change and the full suites once per PR.
- Commits `<type>(<scope>): <subject>`; no AI attribution anywhere.

## 4. Decisions already made

Do not undo these without new evidence.

- `co_scientist.llm.__init__` is lazy (PEP 562) so `cache`, `mcp` and
  `workspace` cannot hit a half-initialised import. A name read through the
  package is cached there, so patch it on the package, not its defining module.
- The completion backend registry is a module global, not a ContextVar,
  because worker cohorts run on their own threads. The engine-tasks runtime
  seam is bound per task through a ContextVar (`bound()`) to avoid editing
  about 25 handler signatures.
- The `_supports_json_schema_response_format` split is deliberate and pinned:
  read at call time in `llm/request/completion.py`, bound at import in
  `attempts/json_attempt.py`.
- Model profile: an exact route beats its family for `json_schema` (identical
  for every current model; a guard test holds it). `MODEL_PRICING` is an
  import-time snapshot of the table. Free and price lookups stay exact-case.
  Free routes stay pinned, fallback off, zero-price ceiling intact.
- The contradiction panel still lists speculative contradictions (pinned by
  `test_the_withheld_contradiction_panel_ignores_role`) but no longer says they
  were withheld. Whether to list them at all is an open product question.
- The telemetry label `site="safety_semantic.risk_domains"` keeps its old name
  for dashboard continuity, although the module is now `app.safety.semantic`.
- `workflow_topology.py` lists five intentional differences between the graph
  and the durable path, each with a test. Do not unify them.
- Three function-local imports break cycles created by package `__init__`s
  (`report/finalize.py`, `outcome_refinement_lineage.py`, `claims/span.py`);
  each has a comment. Hoisting them re-creates the cycle.

## 5. Risks and cleanup

- If CI's docker job fails at #100's new import step, a module imports
  something the api image lacks: make that import lazy or fix the image. Keep
  the check; it exists because `**/cache` in `.dockerignore` would have
  silently dropped `co_scientist/cache/` from production.
- After #100 and #101 merge, delete the merged remote branches (`refactor/*`,
  `g/codebase-architecture-refactor-9bdd34`).

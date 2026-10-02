# Engine Operation Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the app's remaining dependence on private engine scientific
helpers while preserving graph and durable execution behavior.

**Architecture:** Ranking, Reflection and Evolution expose operations below
their graph nodes. The app owns durable adaptation and commits; the engine owns
scientific work and context assembly. Implement the three independent package
boundaries, then enforce and verify them together.

**Tech Stack:** Python 3.12, LangGraph, FastAPI, SQLite, pytest, strict mypy,
Ruff; existing React/TypeScript/Bun browser checks for integration validation.

**Spec:** [Engine operation boundaries design](../specs/2026-10-02-engine-operation-boundaries-design.md).

**Status:** Completed on 2 October 2026. All task steps below are verified;
the [completion record](../../decisions/2026-10-02-engine-operation-boundaries.md)
contains preserved adaptations, review corrections and full-suite results.

## Global Constraints

- Use Python 3.12, Node.js 22.13+ and Bun 1.3.14 for the full application.
  The standalone engine supports Python 3.10+.
- No new dependencies, dependency-lock edits or vendor changes.
- No SQLite write lock over network I/O. Preserve task keys, leases, retry
  budgets, checkpoint ordering, wire payloads and append-only lineage.
- No asyncio primitive may be shared between worker cohorts' event loops.
- No production environment writes; preserve Railway UID, replica and cache
  placement invariants from root `AGENTS.md`.
- First-party source files remain at most 500 lines; functions at most 40
  executable lines, as enforced by the evaluation gates.
- Commit messages, when used, follow `<type>(<scope>): <subject>`; no tool
  attribution. Current work remains reviewable in the shared working tree.
- Keep the completed second-pass changes and root `PLAN.md` intact. Broader
  provider retry/accounting policy is outside these extraction tasks; Task 4
  only corrects a proven nonterminating escalation cycle.

## Review Focus

1. A resumed ranking wave must preserve scientist criteria and its existing
   omission of preferences; Task 1 captures the judge inputs for both paths.
2. Out-of-order matchup completion must commit Elo in wave order and charge
   actual debate turns; Task 1 uses deferred judges and early consensus.
3. Alternating provider reasoning failures must terminate within the existing
   distinct request shapes; Task 4 uses a finite success sentinel and checks
   that repeated requests cannot reach it.
4. Failed verification must persist `unverified` while siblings survive, and
   platform caps must reach the worker unchanged; Task 2 exercises mixed-result
   aggregation and injects both task-control exceptions.
5. An outcome refinement must cite retained run evidence without receiving
   unrelated sibling/meta-review prompt content; Task 3 inspects its context.

---

## File structure and execution

| Owner | Files and responsibility |
|---|---|
| Ranking | New `ranking/operations.py` owns public context/judge/commit operations; defining lifecycle/matchmaking modules own promoted preparation and pairing logic. |
| Reflection | New `reflection/operations.py` owns single-item adaptation and result validation; defining modules own public gate, selection, observation and mature-review routines. |
| Evolution | New `evolution/context.py` owns `EvolutionContext` and round assembly; `evolution/operations.py` owns selected-parent projection. |
| App | Existing ranking/fanout/outcome modules consume package exports, preserving durable scheduling and persistence. |
| Contract | New `app/tests/test_engine_operation_boundaries.py` rejects private engine imports in production app code and engine-to-app imports. |

All paths below are repository-relative. Use the existing `.venv/bin/python`;
engine commands run from `engine/`, app commands from `app/`. Confirm imported
source resolves to this checkout before testing. Tasks 1–3 share no source
files and may be developed independently; Task 4 is an independent correctness
fix; Task 5 consumes all three boundaries and verifies the corrected bound.
Keep task reports and verification logs outside tracked source. Package exports
and tests are the review artifacts; commits/pushes are not completion criteria.

### Task 1: Public Ranking operations

**Files:**
- Create: `engine/src/co_scientist/agents/ranking/operations.py`.
- Modify: `ranking/__init__.py`, `ranking/ranking.py`,
  `ranking/ranking_lifecycle.py`, `ranking/ranking_matchmaking.py` under the
  same agent source directory; extract a focused pairing module if needed.
- Modify: `app/app/engine_tasks/ranking.py`, `ranking_wave.py`.
- Test: new `engine/tests/test_ranking_operations.py`; existing
  `test_ranking.py`, `test_ranking_matches.py`, `test_ranking_budget.py`,
  `test_ranking_lifecycle_entry.py`; app `test_engine_tasks_ranking.py`,
  `test_engine_tasks_ranking_pause_resume.py`, `test_engine_tasks_fanout_control_flow.py`.

**Interfaces:**
- Public `TournamentGuidance` retains the five named/iterable guidance fields.
- `remaining_ranking_rounds(state: WorkflowState, hypotheses: list[Hypothesis]) -> int`.
- `prepare_ranking_round(state: WorkflowState, hypotheses: list[Hypothesis]) -> tuple[int, TournamentGuidance]` (async).
- `build_tournament_pairings(hypotheses: list[Hypothesis], tournament_rounds: int, research_goal: str, current_iteration: int, judged: set[frozenset[str]] | None = None) -> list[tuple[Hypothesis, Hypothesis]]`.
- `prepare_ranking_prompt_context(state: WorkflowState, *, preferences: str | None = None) -> RankingPromptContext`.
- `prepare_ranking_judging_context(prompt: RankingPromptContext, hypotheses: list[Hypothesis]) -> RankingJudgingContext`.
- `judge_ranking_matchup(pair: tuple[Hypothesis, Hypothesis], context: RankingJudgingContext, matchup_index: int) -> RankingJudgement` (async).
- `apply_ranking_matchup(pair: tuple[Hypothesis, Hypothesis], judgement: RankingJudgement, *, k_factor: int, current_iteration: int) -> RankingMatchResult`.
- `finalize_ranking(state: WorkflowState, hypotheses: list[Hypothesis], matchup_details: list[dict[str, Any]], tournament_rounds: int, total_llm_calls: int) -> dict[str, Any]` (async).
- Frozen result types: `RankingJudgement(winner: str, response: dict[str, Any], budgeted_turns: int)`; `RankingMatchResult(detail: dict[str, Any], llm_calls: int)`.

- [x] Add public-operation contract tests for deterministic excluded pairings,
  preparation progress/admission, graph/durable preferences and criteria,
  early-consensus call counts, confidence knobs and finalization ordering.
- [x] Run the new operation tests before implementation; expect missing public
  exports. Capture the existing wave-order and pause/resume behavior with the
  named app suites before migrating their collaborators.
- [x] Move shared behavior below graph orchestration and implement the listed
  public operations. Capture graph prompt context once per tournament and
  judging context once per match; capture both once per durable wave.
- [x] Migrate app consumers and graph judging/Elo application. Keep the app's
  full-pool skip-budget check, eligible-pool preparation, wave exclusions,
  failure isolation, telemetry, successor keys, checkpoint pool order and commit
  order. Preserve durable peer-review admission. Migrate test
  patch sites to the modules that actually consume the collaborator.
- [x] Run `../.venv/bin/python -m pytest -q tests/test_ranking*.py` from
  `engine/`; run `../.venv/bin/python -m pytest -q
  tests/test_engine_tasks_ranking*.py tests/test_engine_tasks_fanout_control_flow.py`
  from `app/`. Expected: all pass, including new public operation tests.
- [x] Review the scoped diff and record tests and preserved adaptations.

### Task 2: Public Reflection operations

**Files:**
- Create: `engine/src/co_scientist/agents/reflection/operations.py`,
  `verification.py` (context, bounded evidence and shared verification leaf).
- Modify: `reflection/__init__.py`, `review_gate.py`, `review.py`,
  `deep_verification.py`, `verification_freshness.py`, `reflection.py`,
  `comprehensive_reflection.py` in that agent directory.
- Modify: app `engine_tasks/fanout.py`, `fanout_items.py`,
  `fanout_aggregates.py`, `fanout_verification.py`.
- Test: new `engine/tests/test_reflection_operations.py`; existing review-gate,
  deep-verification, reflection and comprehensive-reflection suites; app
  `test_engine_tasks_fanout*.py`.

**Interfaces:**
- `apply_initial_review_gate(hypotheses: list[Hypothesis], reviews: list[HypothesisReview], criteria: list[str] | None = None) -> None`.
- `select_hypotheses_to_verify(hypotheses: list[Hypothesis], model_name: str) -> list[Hypothesis]`.
- `verify_hypothesis(state: WorkflowState, hypothesis: Hypothesis) -> dict[str, Any] | None` (async).
- `has_valid_verification(result: Mapping[str, Any] | None) -> bool`.
- `observe_hypothesis(state: WorkflowState, hypothesis: Hypothesis, *, hypothesis_index: int = 1, total_count: int = 1) -> dict[str, Any] | None` (async).
- `review_hypothesis(state: WorkflowState, hypothesis: Hypothesis, review_type: ReviewType) -> ReviewRun` (async).
- `ReviewRun` is a named/iterable result with `review_type: ReviewType`,
  `result: dict[str, Any] | None`, `ledger: dict[str, Any] | None`.

- [x] Add contract tests for criteria-aware gates, selected verification
  candidates, bounded source evidence plus existing meta-review inclusion,
  invalid/missing verdicts,
  local semaphore ownership, ordinary failures and both task-control exceptions.
  Pin separate review/ledger outputs and observation indices.
- [x] Run `../.venv/bin/python -m pytest -q tests/test_reflection_operations.py`
  from `engine/`; expect missing public exports before implementation.
- [x] Promote gate, selection and mature-review routines at their defining
  owners; implement public single-item verification/observation adaptation and
  verdict validation. Both graph and public operation import the verification
  leaf from `verification.py`; operations must not import graph coordinators.
  Keep graph batch concurrency around the shared leaf work.
- [x] Migrate durable fanout to package exports. Retain missing-literature
  rejection, raw durable verification payloads, markers/fingerprints, sibling
  isolation, worker control-flow errors and aggregate transaction boundaries.
- [x] Run engine review/reflection/deep-verification suites and app
  `../.venv/bin/python -m pytest -q tests/test_engine_tasks_fanout*.py`.
  Expected: all pass, including mixed-success aggregation and park propagation.
- [x] Review the scoped diff and record the graph/durable payload distinction.

### Task 3: Public outcome-refinement context

**Files:**
- Create: `engine/src/co_scientist/agents/evolution/context.py`, `operations.py`.
- Modify: evolution `__init__.py`, `evolve.py`, `evolve_prompt.py` and context
  consumers that annotate the moved type.
- Modify: `app/app/outcome_refinement/context.py`.
- Test: new `engine/tests/test_evolution_operations.py`; existing engine
  `test_evolve*.py`; app `test_outcome_refinement_executor.py`,
  `test_outcome_refinement_gates.py`, `test_outcome_refinement_telemetry.py`.

**Interfaces:**
- `EvolutionContext`: frozen public dataclass preserving every field/default
  currently defined by `evolve_prompt._EvolutionContext`.
- `build_evolution_context(state: WorkflowState, removed_duplicates: list[str], supervisor_guidance: dict[str, Any] | None) -> EvolutionContext`.
- `prepare_outcome_refinement_context(state: WorkflowState, parent: Hypothesis) -> EvolutionContext`.
- Existing `evolve_single_hypothesis_from_outcome(hypothesis: Hypothesis, context: EvolutionContext, outcome_context: str, validation_hypotheses: list[Hypothesis]) -> tuple[Hypothesis | None, dict[str, Any] | None]` (async) retains its behavior.

- [x] Add a contract test with selected parent, sibling, meta-review, supervisor
  guidance, lab constraints, literature and citation sources. Assert only the
  parent enters prompt/ranked state; run guidance/evidence/reference keys remain;
  meta-review/duplicates/supervisor context are empty; original state is intact.
- [x] Run `../.venv/bin/python -m pytest -q tests/test_evolution_operations.py`
  from `engine/`; expect missing public exports before implementation.
- [x] Move the immutable type and round-context builder below prompt/graph
  orchestration, then move the exact selected-parent projection into the public
  operation. Preserve compatibility aliases used inside existing engine tests.
- [x] Make the app context adapter consume the public operation and type;
  leave sibling duplicate validation, safety, action replay and commits with
  their current app owners.
- [x] Run engine `../.venv/bin/python -m pytest -q tests/test_evolve*.py
  tests/test_evolution_operations.py` and the three named app suites.
  Expected: all pass, including lineage, duplicate guard and replay accounting.
- [x] Review the scoped diff and record context/source retention evidence.

### Task 4: Bound escalation-only provider recovery

**Files:**
- Modify: `engine/src/co_scientist/llm/attempts/retry.py`, `contract.py`.
- Test: `engine/tests/test_llm_attempt_loop_tools.py`,
  `test_llm_attempt_loop.py`, `test_llm_tool_loop_budget.py`.

**Interfaces:** Preserve `AttemptPlan.escalation_only(model_name: str)` and
`run_attempts`; `max_attempts=None` still selects escalation-only handling.
The private attempt run tracks rungs visited by that call, starting with
`BudgetEscalation.NONE`. Standard plans retain their configured budgets.

- [x] Add a public-entry regression with alternating reasoning-only responses
  and mandatory-reasoning refusals followed by a success sentinel. Assert the
  tool turn raises the current failure on revisiting a rung, uses at most four
  attempts, and never reaches the sentinel. Assert no sleep, park, throttle
  increment or retry telemetry; preserve every distinct recovery request shape.
- [x] Run the regression before the fix; expect failure because the sentinel
  succeeds after repeated identical requests. Record the finite reproducer.
- [x] In `_AttemptRun._climb`, reject an already visited target rung only for
  escalation-only plans, raising the current error unchanged. Record a new
  rung only when it is actually entered. Keep rejected-response exhaustion
  behavior, ordinary failure reporting and all standard-plan handling intact.
- [x] Add the opposite alternation order and an independent second tool turn
  to prove the guard is call-local and does not suppress legitimate recovery.
- [x] Run the three named suites. Expected: all pass; existing raw throttle,
  no-tool-reexecution, mandatory-reasoning shaping and standard retries remain.
- [x] Document the corrected finite bound separately from the open product
  decisions about tool backoff, parking and app accounting; review the diff.

### Task 5: Enforce the boundary and verify integration

**Files:**
- Create: `app/tests/test_engine_operation_boundaries.py`.
- Modify: `docs/ARCHITECTURE.md`, `app/AGENTS.md`, `engine/AGENTS.md`,
  `docs/README.md`; add a dated completion record after verification.

**Interfaces:** Consumes the package exports from Tasks 1–3; produces an AST
import contract over `app/app/**/*.py` and `engine/src/co_scientist/**/*.py`.

- [x] Add a regression guard rejecting underscore-prefixed symbols imported
  from `co_scientist` by app production modules, including function-local
  imports. Reject engine imports of `app`/`app.*`; include `import` and
  `from ... import ...` forms. Reject shared operation/context modules importing
  their graph coordinators; keep verification leaf below its public adapter.
  No blanket allowlist.
- [x] Run the guard on the pre-migration snapshot to verify it detects the
  fifteen known private-import sites; run on the new tree and expect PASS.
- [x] Update architecture/module guides with ownership, supported operations,
  transaction placement and the characterized graph/durable adaptations.
- [x] Run fresh import-order smoke, `make lint typecheck test-engine test-app
  parity eval-smoke`; expected all pass. Retain the full output in local logs.
- [x] Rebuild the API image and run its default-user import smoke with offline
  mode, temporary DB and no dotenv. Expected: public packages and API import,
  no baked runtime DB, no production configuration changes. If the proxy CA
  is required, use the second pass's temporary BuildKit-secret mount procedure.
- [x] Obtain an independent cross-package review; resolve concrete regressions,
  update this plan's checkboxes and record exact validation in the completion
  record. Run additional frontend/browser checks only if integration changes
  affect their behavior or earlier checks reveal a concern.

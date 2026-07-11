# Cleanup sweep — final report

Branch `refactor/simplify-dead-code`, 6 commits on top of `480a3489`.
Strictly behavior-preserving removal of dead code, duplication, and stale
docs across `app/`, `engine/src/`, and `app/frontend/src/`. As predicted,
yield was modest: the big wins were dead re-export facades in `app/app/` and
stale documentation; the engine source itself came back clean.

**Net delta: 18 files changed, +73 / −574 lines** (−416 deletions excluding
the mechanical `bun.lock` regeneration; every insertion is a docs rewrite or
a kept import block reformatted).

---

## Removals (each with proof, one commit per batch)

### 1. `chore(make)`: dead `COSCIENTIST_TEST_MODE` (43f36a14)
`Makefile:175` set `COSCIENTIST_TEST_MODE=1` for `test-app`, but a repo-wide
grep (`grep -rn COSCIENTIST_TEST_MODE` across Python/TS/docs/Make, excluding
`.venv`/`node_modules`) finds only that single line. Mock mode in tests is
actually forced by the autouse `isolated_db` fixture
(`app/tests/conftest.py:22`, `COSCIENTIST_FORCE_MOCK=1`).
Verified: `make test-app` → 231 passed (identical to baseline), parity OK.

### 2. `refactor(app)`: unreferenced facade re-exports (8d8bfe0f, −318 lines)
Three modules kept large re-export blocks from past module splits. I
enumerated every consumer: all `from app.<module> import …` sites, all
attribute uses (`grep -rho "<module>\.[A-Za-z_]*"`), all string-form
`monkeypatch.setattr`/`mock.patch` targets (none exist for these modules),
and wildcard imports (none exist) across `app/app`, `app/tests`,
`evaluations`.

- `app/app/report_render.py`: kept the six consumed re-exports (`EmitFn`,
  `make_emitter`, `article_stub`, `hypothesis_stub`, `match_stub`,
  `format_deep_verification_critique`); removed the 21 private
  `_render_*`/`_has_*`/`_first`/`_append_if` re-exports and
  `_META_REVIEW_BULLET_SECTIONS` (zero consumers each; they all live on in
  `report_markdown.py`, which uses them internally).
- `app/app/mock_workflow.py`: only `run_mock_workflow` is consumed via this
  path (engine_stream.py, workflow.py, test_mock_workflow.py,
  test_resume.py). The 47-name `__all__` re-export block had zero consumers —
  tests import the split modules (`mock_workflow_stages`/`_seeds`/`_phases`)
  directly (e.g. `test_resume.py:195` imports `_emit_cancelled_if_set` from
  `app.mock_workflow_stages`).
- `app/app/engine_adapter/__init__.py`: exactly five names are consumed via
  the package namespace — `run_workflow`, `select_provider`,
  `system_status`, `_persist_final_state` (test_engine_drain.py),
  `_build_engine_opts` (test_messages.py). The other ~55 private re-exports
  had zero consumers; tests reach submodule helpers via the submodule paths
  (`from app.engine_adapter import provider`, etc.), which are untouched.

### 3. `chore(frontend)`: unused dep + orphan assets (61ce6fa6)
- `react-markdown` was a runtime dependency with zero imports: grep across
  the repo (excluding `node_modules`/`dist`) hits only `package.json` and
  `bun.lock`. Markdown-ish content renders via the app's own
  `sanitize_html.ts` path. Removed with `bun remove`.
- `public/favicon-dark.svg` / `favicon-light.svg`: zero references anywhere
  (index.html, src/, backend, manifest, vercel.json). `index.html` links only
  `/favicon.ico` and `/favicon.svg`; `favicon.svg` self-themes via an
  internal `prefers-color-scheme` media block, superseding the static
  variants.

### 4. `docs(config)`: env vars documented but read nowhere (adb62228)
- `MAX_ITERATIONS`, `INITIAL_HYPOTHESES_COUNT`, `EVOLUTION_MAX_COUNT`
  (root `.env.example`, `app/README.md`): no `os.getenv`/pydantic field reads
  these names anywhere; no engine YAML uses them as `${...}` placeholders.
  They flow only as per-run request params (`app/app/runs_models.py`), so
  setting them in `.env` silently does nothing (the documented values 2/5/2
  didn't even match the code defaults 1/5/3).
- `COSCIENTIST_LIT_REVIEW_PAPERS_COUNT` (`app/README.md`): read nowhere; the
  budget comes from per-run state + `COSCIENTIST_DEV_MODE`
  (`engine .../literature_review/run_config.py:39-45`).
- `VITE_DOMAIN` (`app/frontend/.env.example`, frontend README): never read;
  the frontend reads only `import.meta.env.VITE_API_BASE_URL`
  (`src/api/runs.ts:44`).
- `app/.env.example` comment pointed at `app/store.py` (gone) → now
  `app/store/db.py`.

### 5. `docs`: references to removed modules and superseded routing (a500f4ad)
All verified against the tree before editing:
- `docs/EXPLAINER.md`: every `generator.py:NN` citation pointed at a file
  that no longer exists (split into `generator/{core,graph,streaming,
  availability}.py`); §4 described the removed `after_ranking`/
  `after_proximity` routers (no such functions exist anywhere) — rewritten
  around the current orchestrator loop point (`nodes/orchestrator.py`,
  `scheduling/policy.py`, `generator/graph.py::_route_next_task`), with the
  iteration-increment move (proximity → orchestrator) and the node table's
  next-hop cells corrected. Also `engine_adapter.py` →
  `engine_adapter/provider.py`, `literature_review_helpers.py` →
  `literature_review/` package.
- `docs/ARCHITECTURE.md`: frontend box listed removed routes/components
  (LandingPage, DemoPage, Dashboard, NewRunForm, RunStatusPill, IdeaModal,
  useMessages — none exist in `src/`); replaced with the current route table
  and live hooks; backend labels `engine_adapter.py`/`store.py` → packages.
- `docs/FIDELITY.md`: `mock_workflow._judge` doesn't exist → the real
  pairwise judge `mock_workflow_seeds._judge_pair`.
- `app/frontend/README.md`: dropped `src/md3/`, `src/components/ui/`,
  `src/hooks/use_messages.ts` rows (none exist on disk); stack list, routing
  table, and source map updated to the current chat-workspace surface.
- `engine/docs/DEVELOPMENT.md`: tree named `generator.py`, `schemas.py`,
  `nodes/literature_review.py`, `literature_review_helpers.py`,
  `generation/papers.py` — none exist; node-wiring instructions now point at
  `generator/graph.py`.

### 6. `refactor(app)`: `default_db_path` store-facade re-export (a1a4f99e)
Defined and used inside `app/store/db.py` (the `connect` fallback), but its
re-export via `app.store` had zero consumers (`grep -rnw default_db_path`
across `app/app`, `app/tests`, `evaluations` hits only `store/db.py` and the
facade lines removed).

---

## Candidates deliberately KEPT (with reasons)

**Engine re-export facades (~168 alias lines across 14 modules) — KEPT.**
An AST + grep audit found unconsumed `X as X` re-exports in
`co_scientist.cache`, `config.schema`, `generator/__init__`, `llm`,
`llm_json`, `mcp_client`, `nodes.evolve`, `generation.coordinator`,
`literature_tools.validate`, `literature_review.helpers`,
`literature_review.node`, `nodes.ranking`, `nodes.reflection_helpers`,
`nodes.review`. Removal would be behavior-preserving in the current tree,
but unlike the app facades (whose test-seam rationale was verifiably
vacuous and which the task named directly), these carry explicit docstring
contracts ("compatibility facade", "historical import paths keep working")
that match the repo's documented split convention. Pruning them is a policy
decision for the maintainer, not dead-code cleanup; the module list above is
the exact prune list if that guarantee is ever dropped.

**`_emit_cancelled_if_set` (mock_workflow_stages.py:110) vs
`_emit_cancelled_event` (engine_stream.py:52) — KEPT both.** They share an
identical 4-line pause-vs-cancel persist-and-emit tail; consolidation is
possible but touches cancellation semantics adjacent to the cancel path
owned by a concurrent worktree. Risk > reward under "if in doubt, keep it".

**`_append_if` / `_first` twins (report_markdown.py vs
engine_adapter/opts.py, elo.py) — KEPT.** Same names, different signatures
and behavior (one appends a bare value, the other formats "Label: value"
lines; one defaults to `values[-1]`, the other to `""`). Not duplicates.

**`HumanHypothesisAdmission.to_dict` (app/app/human_input.py:40) — KEPT.**
Referenced only by `app/tests/test_human_input.py:49`; production builds its
response dict by hand. A test reference counts as a reference per the task
rules — flagged for a human glance.

**Frontend exported-but-not-imported symbols (11) — KEPT.** Each is used
2–9× inside its own defining file (`RunTierOption`, `UseRunStreamResult`,
`ComposerAttachment`, `ICON_BUTTON_CLASSES`, …); only the `export` keyword
is arguably redundant, which is a style question, not dead code.

**Ask-flow docs — KEPT.** `docs/ARCHITECTURE.md` item 4 and the frontend
README's message-endpoints section describe `/messages` polling the current
frontend no longer performs, but the ask flow is owned by a concurrent
worktree; left untouched to avoid conflicts.

**Config YAML examples, prompt templates, engine constants/schemas/
exceptions, store/nodes `__all__` surfaces — all verified live.** Every
prompt template is referenced by a literal string name; all 18 schema
constants are wired (17 via `schemas/registry.py`, one used directly);
`CoScientistError` is the live base class of three used exceptions; every
engine package `__all__` name has external references.

---

## Verification (all from the worktree root, after the final batch)

```
make test-all      engine: 961 passed; app: 231 passed;
                   parity: 62 rows (external=6, undisclosed=2, verified=54) — OK
make eval-smoke    evaluations smoke: OK (safety + citation offline evals passed)
make lint          ruff: All checks passed! (app, engine, evaluations)
mypy (engine)      Success: no issues found in 197 source files
mypy (app)         Success: no issues found in 43 source files
frontend           bun run test: 39 files / 254 tests passed
                   bun run lint: clean; bun run build: built in ~719ms
```

Identical to the pre-change baseline (961/231/254 passed, all gates green),
run after every batch as well as at the end.

## Unresolved blockers

None. Two follow-ups intentionally left for the maintainer: (a) decide
whether the engine compat facades' guarantee still pays its way (prune list
above); (b) the ask-flow doc paragraphs above once that worktree lands.

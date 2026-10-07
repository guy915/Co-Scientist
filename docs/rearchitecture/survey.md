# Re-architecture survey (phase 0)

Measured on `main` at `35d68bf`, 7 October 2026, after the cuts, shrink and
optimization campaigns. Read-only. The plan is `docs/REARCHITECTURE.md`; the
decisions this survey feeds are in `docs/adr/`.

## Baseline for "Done when"

| Check | Phase 0 value | How to re-measure |
|---|---|---|
| Python source lines | 72,370 raw / 61,277 non-blank in 325 files | `count.sh` below, `PYSRC` |
| Python test lines | 37,692 raw / 31,382 non-blank in 159 files | `PYTEST` |
| TS/TSX source lines (`app/frontend/src`) | 21,605 raw / 19,988 non-blank in 80 files | `TSSRC` |
| TS/TSX test lines (frontend) | 6,934 raw / 6,173 non-blank in 73 files | `TSTEST` |
| e2e TS lines | 1,496 raw / 1,390 non-blank in 11 files | `E2E` |
| Module import cycles (strongly connected components > 1) | 6 with every import; 0 with top-level runtime imports only | `survey.py` method below |
| Package-level cycles | 4 (18, 8, 2, 2 units); 3 with top-level runtime imports only | same |
| CI wall time, postsubmit on `main` | 2:47–5:24 over the last five pushes (median 4:36) | Actions run list for `ci.yml` on `main` |
| `make lint` / `make typecheck` (local container) | 18 s / 154 s, exit 0 | `time make lint`, `time make typecheck` |
| `make test-all` (local container) | 457 s across five suites; see the suite table | `time make test-<suite>` |
| `make e2e` (local container) | 195 s, 32 passed, exit 0 | `time make e2e` |
| Express benchmark | `rearch-baseline-1`, recorded below | `Benchmark` workflow, `express` |

Lines exclude `vendor/`, lockfiles, prompt templates (42 Markdown files, 2,043
lines), CSS (1,685 lines) and data files. Python counts include `app/app`,
`app/dev`, `engine/src`, `engine/mcp_server`, `evaluations` and
`.github/ci_shard.py`. A test is a path under a `tests/` directory, a
`test_*.py` file or a `conftest.py`; on the TS side `*.test.ts(x)`,
`__tests__/`, the `*_test_support`/`*_test_helpers` files, `test_setup.ts`,
`test_fixtures.ts` and `http_test_support.ts`.

```sh
# count.sh LABEL PATHSPEC... -> "LABEL | files | raw | non-blank"
label=$1; shift
git ls-files -z -- "$@" | xargs -0 awk 'FNR==1{f++} {r++} /[^[:space:]]/{n++} END{print f, r, n}' \
  | { read f r n; echo "$label | $f | $r | $n"; }

count.sh PYSRC ':(glob)**/*.py' ':(exclude)vendor' ':(exclude)**/tests/**' ':(exclude)**/test_*.py' ':(exclude)**/conftest.py'
count.sh PYTEST ':(glob)**/tests/**/*.py' ':(glob)**/test_*.py' ':(glob)**/conftest.py' ':(exclude)vendor'
count.sh TSSRC ':(glob)app/frontend/src/**/*.ts' ':(glob)app/frontend/src/**/*.tsx' \
  ':(exclude,glob)app/frontend/src/**/*.test.ts' ':(exclude,glob)app/frontend/src/**/*.test.tsx' \
  ':(exclude,glob)app/frontend/src/**/__tests__/**' ':(exclude,glob)app/frontend/src/**/*_test_support.ts*' \
  ':(exclude,glob)app/frontend/src/**/*_test_helpers.ts*' ':(exclude,glob)app/frontend/src/test_setup.ts' \
  ':(exclude,glob)app/frontend/src/test_fixtures.ts' ':(exclude,glob)app/frontend/src/http_test_support.ts'
count.sh TSTEST ':(glob)app/frontend/src/**/*.test.ts' ':(glob)app/frontend/src/**/*.test.tsx' \
  ':(glob)app/frontend/src/**/__tests__/**/*.ts' ':(glob)app/frontend/src/**/*_test_support.ts*' \
  ':(glob)app/frontend/src/**/*_test_helpers.ts*' ':(glob)app/frontend/src/test_setup.ts' \
  ':(glob)app/frontend/src/test_fixtures.ts' ':(glob)app/frontend/src/http_test_support.ts'
count.sh E2E ':(glob)e2e/**/*.ts'
```

### Local suite times

One run each, in the cloud container, one suite at a time:

| Suite | Seconds | Result |
|---|---:|---|
| `make test-engine` | 19 | 766 passed, 22 skipped, 1 failed: `test_sandbox.py::TestRealConfinement::test_process_vm_reads_are_denied` |
| `make test-app` | 297 | 853 passed |
| `make test-mcp` | 65 | 102 passed, then strict mypy |
| `make test-evaluations` | 35 | 35 tests passed (`pytest -q` prints dots only) |
| `make test-frontend` | 41 | 63 files, 244 tests passed |

The engine failure is specific to this container: the confined child reads the
virtualenv's `pyvenv.cfg`, which Landlock denies when the interpreter lives in a
`.venv` outside the allowed roots. CI installs into the system
interpreter, where it passes. It fails identically before and after every campaign PR, so PRs record
it as the known local failure rather than a regression.

## Sizes

### Python by area

| Area | Files | Raw | Non-blank |
|---|---:|---:|---:|
| `app/app` | 131 | 30,778 | 26,264 |
| `app/tests` | 93 | 22,491 | 18,808 |
| `engine/src/co_scientist` | 159 | 36,262 | 30,554 |
| `engine/tests` | 51 | 12,730 | 10,496 |
| `engine/mcp_server` source | 21 | 3,544 | 2,972 |
| `engine/mcp_server` tests | 9 | 1,712 | 1,418 |
| `evaluations` source / tests | 11 / 6 | 1,600 / 759 | 1,337 / 660 |

### `app/app` by subpackage (raw lines)

`store` 5,626 · flat modules (39) 5,111 · `engine_tasks` 3,907 · `report` 3,099 ·
`engine_adapter` 2,235 · `claims` 2,163 · `runs` 2,085 · `interviews` 1,368 ·
`qa` 1,321 · `task_worker` 872 · `api_contracts` 862 · `safety` 763 ·
`run_modes` 467 · `hypothesis` 448 · `citations` 338 · `seed` 113.

### `engine/src/co_scientist` by subpackage (raw lines)

`agents` 14,457 · `llm` 4,154 · `schemas` 2,299 · `prompts` 2,097 (plus 42
templates) · `evidence` 1,703 · `workspace` 1,553 · flat modules (11) 1,262 ·
`sandbox` 1,245 · `research` 875 · `scheduling` 827 · `config` 708 · `patch` 686
· `offline` 684 · `mcp_client` 593 · `models` 579 · `skills` 570 · `generator`
533 · `tools` 438 · `research_adapter` 406 · `state` 298 · `constants` 295.

Python is spread thin: about 230 lines per file, no source file above 800
lines. Thirteen `__init__.py` files carry 298–686 lines of real code
(`run_modes`, `citations`, `patch`, `mcp_client`, `skills`, `state`,
`constants`, ...). The largest files are
`agents/generation/literature_tools/validate.py` (800), `store/schema.py`
(748), `report/markdown/hypothesis.py` (735) and `report/markdown/overview.py`
(720). The frontend is about 30% of the Python source; `workbench/pages` alone
is 10.4k lines.

## Import graph

Built with `grimp` 3.17 over the `app` and `co_scientist` packages; every import
statement is classified with `ast` as top-level runtime, function-local (lazy)
or `TYPE_CHECKING`, because grimp reports neither.

**Seven engine directories have no `__init__.py`:** `llm/request`,
`llm/attempts`, `llm/tools`, `llm/admission`, `llm/structured`, `offline` and
`prompts/templates`. grimp, and therefore `import-linter`, cannot see the 15
modules under the first six: 58 import statements and 70 module edges are
dropped or attributed to a parent. Phase 2 adds the six `__init__.py` files
before writing contracts. The numbers below are for the complete graph.

297 internal modules (131 `app`, 166 `co_scientist`), 1,306 module edges, 1,552
import statements (1,313 top-level, 199 lazy, 40 `TYPE_CHECKING`).

### Cycles

| Level | All imports | Without `TYPE_CHECKING` | Without lazy | Top-level runtime only |
|---|---|---|---|---|
| Module | 6: sizes 23, 11, 8, 5, 2, 2 | 3: 23, 11, 2 | 3: 8, 5, 2 | 0 |
| Package (second-level unit) | 4: 18, 8, 2, 2 | 3: 18, 6, 2 | 4: 8, 2, 2, 2 | 3: 6, 2, 2 |

- **App, 23 modules:** `engine_adapter.drain.*`, `engine_tasks.*`, `hypothesis`,
  `report.*`, `safety`, `task_worker.outcomes`. Closed only by 12 lazy edges
  (for example `report.finalize → engine_tasks.runtime`,
  `safety → engine_tasks.support`, `engine_tasks.runtime → safety`).
- **App, 11 modules:** `credentials`, `engine_adapter`, `llm_request`,
  `logging_setup`, `offline_guard`, `process_mode` and five `store` modules.
  Closed by 7 lazy edges; `credentials` (five concerns in one file) is the hub.
- **Engine, 8 / 5 / 2 / 2 modules:** `llm` ↔ `models` ↔ `progress` ↔ `state`,
  `evidence` ↔ `research_adapter`, `llm.tools.loop` ↔ `policy`, and
  `reflection.deep_verification_evidence` ↔ `review_evidence`; all
  `TYPE_CHECKING` or lazy.
- **Package level, top-level runtime only:** engine `constants`, `llm`,
  `mcp_client`, `models`, `tools`, `workspace` (6); `app.free_usage` ↔
  `app.runs`; `app.claims` ↔ `app.store`.

grimp's cycle breakers: 18 app edges, led by `task_worker → engine_tasks`,
`report.finalize → engine_tasks.*`, `safety → engine_tasks.support`,
`credentials → llm_request`/`store.db`, `store.records → claims.gate`; 6
engine edges, led by `constants → llm.profile` and
`research_adapter → evidence.*`.

### Fan-in and fan-out

| Unit | Modules | Fan-in (modules) | Fan-out (modules) |
|---|---:|---:|---:|
| `app.store` | 22 | 57 | 8 |
| `app.config` | 1 | 29 | 2 |
| `app.credentials` | 1 | 23 | 5 |
| `app.async_bridge` | 1 | 19 | 0 |
| `app.engine_tasks` | 11 | 8 | 56 |
| `app.runs` | 9 | — | 42 |
| `app.engine_adapter` | 9 | 13 | 36 |
| `app.main` | 1 | — | 25 |
| `co_scientist.constants` | 1 | 57 | 1 |
| `co_scientist.models` | 3 | 52 | 2 |
| `co_scientist.state` | 1 | 50 | 1 |
| `co_scientist.llm` | 25 | 46 | 8 |
| `co_scientist.exceptions` | 1 | 34 | 0 |
| `co_scientist.agents` | 58 | 11 | 37 |

### Between the packages

- The engine imports nothing from `app` (enforced today by
  `app/tests/test_architecture.py`).
- `app` → engine: 82 module pairs from 17 app units; `engine_tasks` alone has
  44 (`agents` 17, `models` 7, `llm` 5, `checkpoint` 4, `task_runtime` 4, ...).
- App mypy skips the engine (`follow_imports = "skip"` for `co_scientist.*`),
  and `evaluations` mypy skips `app.*`: a stale engine import in the app passes
  `make typecheck`.

### Third-party confinement today

| Library | Modules | Where |
|---|---:|---|
| `fastapi` | 24 | `app.runs` 8, `app.interviews` 4, `auth`, `byok_models`, `diagnostics_api`, `document_ingest`, `documents`, `feedback_api`, `free_usage`, `logs_api`, `main`, `operator_access`, `provider_usage`, `staged_documents` |
| `sqlite3` | 42 | `app.store` 19, `engine_tasks` 5, `engine_adapter` 4, `runs` 3, and one each in `claims`, `credentials`, `free_usage`, `hypothesis`, `logs_api`, `main`, `notifications`, `qa`, `safety`, `seed`, `task_worker` |
| `httpx` | 3 | `app.citations`, `app.pinned_http`, `co_scientist.llm.admission.free_policy` |
| `litellm` | 8 | `co_scientist.llm` (5); lazily in `app.async_bridge`, `app.credentials`, `app.logging_setup` |

The engine has no `sqlite3` or `fastapi` import. Real SQL also runs outside
`store/` in `engine_tasks/finalize.py`, `engine_tasks/support.py`,
`runs/lifecycle.py`, `runs/chat.py`, `free_usage.py`, `credentials.py`,
`provider_usage.py`, `logs_api.py`, `seed/` and `diagnostics.py`.

### What `evaluations/` imports

All function-local: `app.task_worker`, `app.claims` (and `.verifier`),
`app.config`, `app.hypothesis.safety`, `app.run_modes`, `app.store.*`,
`co_scientist.llm` (and `.profile`), `co_scientist.offline.llm`. Two more are
inside strings: `"app.config"` in `_live_config.py` and
`co_scientist.llm.request.backend` in a subprocess script.

## Change hot spots

From a blobless clone, `git log --since=2026-08-01` (1,753 commits), excluding
11 mass commits that touch 150 or more files (the format change, the cut
prunes, package splits). Paths moved during the campaigns split their history.

| Source file | Commits | Directory | Commits |
|---|---:|---|---:|
| `app/app/config.py` | 50 | `engine/.../agents` | 132 |
| `app/app/store/schema.py` | 40 | `app/app/store` | 118 |
| `app/frontend/src/api/runs.ts` | 36 | `app/app` (flat) | 116 |
| `app/app/store/__init__.py` | 33 | `app/frontend/src/workbench/pages` | 102 |
| `app/app/engine_adapter/opts.py` | 30 | `engine/.../schemas` | 54 |
| `app/app/main.py` | 28 | `app/app/engine_adapter` | 50 |
| `app/app/store/tasks.py` | 24 | `app/frontend/src/api` | 47 |
| `engine/.../schemas/synthesis.py` | 22 | `engine/.../llm` | 34 |
| `app/app/store/records.py` | 20 | `engine/.../prompts` | 33 |
| `engine/.../meta_review/research_overview.py` | 20 | `app/app/runs` | 29 |

Churn concentrates in configuration, the store and the engine's schemas and
agents: the store layer has 9 of the top 40 source files.

## Shallow modules (deletion test)

Pure one-call forwarders are rare after the shrink (10 of 1,434 functions in
`app/app`, 27 of 1,742 in the engine). What remains:

| Module | Lines | Verdict |
|---|---:|---|
| `engine/.../llm/precall.py` | 8 | Pass-through: one `replace(...)` used twice |
| `engine/.../tools/__init__.py` | 6 | Pass-through: no importer uses the package name |
| `engine/.../evidence/__init__.py` | 8 | Pass-through: no production importer |
| `app/app/engine_adapter/__init__.py` | 77 | Partly: `select_provider()` can only return `"engine"`; re-exports `offline_mode` |
| `app/app/engine_adapter/drain/__init__.py` | 11 | Pass-through re-export |
| `app/app/process_mode.py` + `offline_guard.py` | 56 + 19 | Three hops for one boolean (offline mode); merge |
| `app/app/execution_policy.py` | 17 | Two tiny functions left after campaign mode was cut |
| `app/app/engine_tasks/runtime.py` | 81 | Test seam: four methods that lazy-import and forward |
| `engine/.../agents/ranking/operations.py` | 96 | Mostly argument carriers and two forwards |
| `engine/.../evidence/retrieval_support.py` | 5 wrappers | One-line function pairs |
| `app/app/staged_documents.py` via `documents.py` | 21 | Lookup plus a 404, re-exported once more |

The agent package `__init__.py` files (`proximity`, `supervisor`, ...) are thin
on purpose: they are the public interfaces the target structure wants.

## What the earlier campaigns left undone

| Item | State in code |
|---|---|
| Shrink lever 3, one fan-out primitive | Not done: 4 item and 4 aggregate handlers plus 4 planners in `engine_tasks/fanout*.py` (1,057 non-blank lines); some machinery is shared |
| Lever 4, ambient connection | Partial: 351 functions in 57 files still declare `db_path` or `conn`; 296 forwarding lines |
| Lever 10, typed models | Claims and matches done; evidence, hypotheses and reviews remain dicts (`dict[str, Any]`: 815 app, 1,051 engine) |
| Lever 11, one package | Not done: two distributions, `app/app/engine_adapter/` (1,930 non-blank lines) and `co_scientist/research_adapter/` (346) translate between them |
| Optimization "not worth the risk" rows (B12–B18, M7–M9, M13, M15) | Unchanged; outside this campaign |

The plan's pickle cache (`cache/`) no longer exists: there is no pickle,
shelve or similar serialization and no cache-key version anywhere. Checkpoints
are plain JSON keyed by `WorkflowState` field names, so moving a class does not
break resume; renaming a field does.

## Duplicate concepts (backend and cross-cutting)

Severity A is the same behavior twice; B overlaps with different behavior.

| # | Concept | Where | Severity |
|---|---|---|---|
| D1 | Bind-and-reset a `ContextVar` | `co_scientist/_context.py` and five hand copies in `app` (`credentials`, `provider_usage`, `logging_setup`, `engine_tasks/runtime`, `llm_scope`) | A |
| D3 | SSRF-screened, IP-pinned HTTP | `app/app/pinned_http.py` (sync) and `engine/mcp_server/safe_http.py` (async); separate deploys | A |
| D7 | Initial Elo | Engine constant, re-aliased in `app/elo.py`, mirrored as a literal in the `hypothesis_state` SQL default | A |
| D16 | `UnsafeUrlError` | Two classes, part of D3 | A |
| MCP HTTP | 12 hand-built `httpx.AsyncClient`s in 7 MCP tool files, per call, with timeouts 30 s (×8), 45 s, 15 s and 10 s + 30 s total; only `web_fetch` is SSRF-screened, only Europe PMC retries | A (one factory) |
| `_strings` | `research/serialization.py` (keeps blanks), `research_adapter/__init__.py` (strips, drops blanks), MCP `biomedical_databases.py` (same as the first) | A for two of three; the stripping copy differs |
| D2 | Fold model usage into the metrics update | `engine_tasks/gate.py`, `engine_tasks/ranking.py`, `drain/final_state.py`, `task_runtime.py` | B (call deltas differ) |
| D6 | `rank_for_publication` | Engine models (on objects) and `app/elo.py` (on dicts) with different tie-breaks | B |
| D8 | Hypothesis title/id/statement helpers | `text_utils.py` and ad hoc copies in `qa/` and `report/` (140 vs 160 characters) | B |
| D9–D10 | Markup cleaning, text clipping | Five variants each, outputs differ | B |
| D15 | Offline-mode decision | `process_mode` → `engine_adapter` → `offline_guard`, plus `config.has_provider_credential` | B |

No second JSON-repair implementation and no second SQLite opener exist.
`docs/rearchitecture/duplication-audit.md`, which the campaign brief cites, is
not in the repository; the board tracks it.

## String paths and deploy paths (break points for moves)

Ranked by how quietly a move would break production:

1. **Railway watch paths and start command** live only in the dashboard. The
   api watches `/engine/src/**`, `/engine/pyproject.toml`, `/app/app/**`,
   `/app/pyproject.toml` (and Dockerfile, locks, licenses, vendored skills);
   its start command overrides the Dockerfile `CMD` with
   `python -m uvicorn app.main:app` (without `--timeout-graceful-shutdown 20`).
2. **CI path filters** (`ci.yml`, `dorny/paths-filter`): a skipped job
   satisfies `required-checks`, so a new directory outside the filters skips
   its tests silently.
3. **`.dockerignore` and `.gitignore`** drop any directory named `cache`,
   `reports`, `build` or `dist` while `COPY` still succeeds. The target names
   `platform/cache` and `domains/reports` are therefore unsafe (ADR-001
   renames them).
4. **`Dockerfile.api`** copies `engine/src/` and `app/app/` separately and
   smoke-imports all of `co_scientist` but only `app.main`'s import closure.
5. **Silent data paths:** `config/registry.py` loads `tools.yaml` beside
   itself (an empty registry on a miss); `seed/` reads
   `resources.files("app")/data/demo_runs.json.gz` and `retraction_set.py`
   reads `data/retractions.txt.gz` beside itself, both logging and continuing.
6. **`document_ingest.py`** starts `python -m app.pdf_worker` with a `cwd`
   derived from its own path; the production image imports `app` only through
   that working directory.
7. **Sandbox launchers:** `python -I -m co_scientist.sandbox.confine_exec` and
   `.cgroup_exec` by string; availability probes do not import them.
8. **`co_scientist/llm/__init__.py`** resolves about 33 exports from dotted
   strings in `_EXPORTS` at first access; mypy does not see them.
9. **Logger names:** `logging_setup.UNPERSISTED_LOGGERS` filters
   `"co_scientist.mcp_client"` by prefix; `main.py` sets the `co_scientist`
   logger level by name; tests match `app.run_stage`, `app.chat_turn` and
   several `__name__`-derived loggers. `logs.logger` stores `__name__` values
   for display only.
10. **Code inside strings:** subprocess scripts in `evaluations/tests/`,
    `app/tests/test_task_queue.py` and `engine/tests/test_llm.py`; 22
    `monkeypatch`/`patch` targets given as dotted strings (14 app, 8 engine).

Also by path, failing loudly: `evaluations/_identity.py` hashes eight engine
files by relative path into the evaluation identity; `_artifacts.py` reads the
prompt directory; `api_contracts/generate.py` names `wire_<module>.ts` after
its modules and finds the frontend two levels up; package data globs
(`prompts/templates/*.md`, `config/*.yaml`, `sandbox/*.sbpl`, `data/*.gz`);
`engine/mcp_server/pyproject.toml` lists its packages explicitly; layout tests
in `app/tests/test_architecture.py`, `engine/tests/test_agents.py` (`_LAYERS`
of `co_scientist.llm`), `test_research_loop.py`,
`test_literature_review_retrieval.py` and `test_llm.py` (globs `agents/**`).

Persisted names that no move may change: task types (`engine.bootstrap`,
`engine.node.<key>`, `engine.fanout.*`, `engine.ranking.*`,
`notification.email`), node keys (`workflow_topology`), idempotency keys,
checkpoint `stage` values, `CHECKPOINT_VERSION`, `WorkflowState` field names,
prompt template names, event kinds, and table and column names.

## Express baseline

`rearch-baseline-1`, `main` at `35d68bf`:
[run 37619174808](https://github.com/guy915/Co-Scientist/actions/runs/37619174808).
Still running when this survey merged; its scores are added here when it
finishes.

The optimization campaign's two Express runs set the noise floor for the
unsupported claim rate at 0.64–0.76 (`docs/optimization/findings.md`).

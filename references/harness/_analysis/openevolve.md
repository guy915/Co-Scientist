# OpenEvolve — engineering analysis for a "Computational Discovery" surface

Target: `references/harness/openevolve` @ `411fb59c886c18704caaffb611e17cf9e7d824d2` (Apache-2.0).
Host: `/Users/guy/Code/co-scientist` (`engine/` LangGraph agents, `app/` FastAPI + SQLite durable queue + React).
Spec being replicated: `references/core/google-co-scientist/media/computational-discovery/*` (screenshots read directly).

All paths below are repo-relative to their own root unless absolute. `path:line` citations are to the pinned commit.
Anything I could not verify in code is marked **unverified**.

---

## 0. One-paragraph shape of the system

OpenEvolve is a **steady-state, island-partitioned MAP-Elites loop** over whole source files. Each "iteration" is: sample
one parent (+ N inspirations) from one island → build a text prompt containing the parent's full code, its metrics, the
last 3 attempts, the island's top programs and the inspirations → ask an LLM for SEARCH/REPLACE diff blocks → apply them
textually → write the child to a temp file → call a **user-supplied Python `evaluate(path)` function in-process** → get a
`Dict[str, float]` of metrics → insert the child into the island's feature grid keeping the better occupant per cell.
Persistence is a directory of JSON files per checkpoint; there is no database and no server. There is no sandbox.

---

## 1. EVOLUTION LOOP — the actual algorithm

### 1.1 Population model: MAP-Elites × islands (a hybrid, not either one)

- `ProgramDatabase` holds every program in one flat dict `self.programs: Dict[str, Program]` (`openevolve/database.py:128`)
  plus **per-island** MAP-Elites feature grids `self.island_feature_maps: List[Dict[str, str]]`
  (`database.py:131`) and per-island membership sets `self.islands: List[Set[str]]` (`database.py:144`).
- Defaults (`openevolve/config.py:321-323`): `population_size=1000`, `archive_size=100`, `num_islands=5`.
- Feature grid: `feature_dimensions=["complexity","diversity"]` with `feature_bins=10`
  (`config.py:337-347`). `complexity` = `len(program.code)`; `diversity` = mean fast-diversity vs a 20-program
  reference set; any evaluator metric name can be a dimension instead (`database.py:846-912`). Bin index comes from
  min-max feature scaling over observed values (`database.py:914-966`, `_scale_feature_value_minmax` at `2289`).
- Cell occupancy rule: a child claims its cell only if the cell is empty or the child's **fitness** beats the incumbent
  (`database.py:277-348`, `_is_better` at `database.py:1111-1139`). Fitness = `combined_score` if present, else the mean
  of numeric metrics *excluding* the feature dimensions (`openevolve/utils/metrics_utils.py:72-118`).
- **Fitness is always maximized** (`database.py:1139`). The Google worked example minimizes MAE; an OpenEvolve port must
  make the evaluator emit `combined_score = -MAE` or `1/(1+MAE)`. There is no "direction" setting anywhere in
  `config.py`.
- A displaced cell occupant that belongs to no island and owns no cell is deleted outright — "orphan" reaping
  (`database.py:1699-1729`). Population overflow evicts non-cell-owners first, worst-fitness-first, protecting cell
  owners and the global best (`database.py:1731-1808`).
- A separate elite `archive` (`database.py:154`, `_update_archive` at `1141`) and a globally tracked
  `best_program_id` (`database.py:157`) that the eviction path explicitly protects.

### 1.2 Selection / parent sampling

Per-iteration parent choice is a three-way random split on `exploration_ratio=0.2` / `exploitation_ratio=0.7` /
remainder `0.1` (`config.py:326-328`; dispatch at `database.py:1290-1298` and, for the parallel path,
`database.py:453-468`):

| roll | branch | behaviour |
|---|---|---|
| `< 0.2` | exploration | uniform random from the island (`database.py:1494-1523`) |
| `< 0.9` | exploitation | uniform random from the elite archive, preferring same-island members (`database.py:1525-1562`) |
| else | weighted / random | fitness-proportional within the island (`database.py:1437-1492`) |

Note the "exploitation" branch is **uniform over the archive**, not greedy — the only fitness-proportional selection is
the 10% tail branch. Inspirations (the diverse examples shown alongside the parent) are sampled separately by
`_sample_inspirations` (`database.py:1564+`), sized by `prompt.num_diverse_programs=2`
(`process_parallel.py:865-868`, `config.py:269`). This is the "double selection" the repo's own CLAUDE.md names.

### 1.3 "Variants per generation" — there are no generations

This is the single most important structural fact for a port. `run_evolution` is a **steady-state async pipeline**, not
a generational batch:

- `batch_size = min(num_workers * 2, max_iterations)`, then `batch_per_island = batch_size // num_islands`, submitted
  round-robin across islands (`process_parallel.py:549-563`).
- The loop polls for any completed future, integrates exactly one child, and submits exactly **one** replacement
  iteration to keep island balance (`process_parallel.py:588-834`, the `break` at `:834`).
- `num_workers = config.evaluator.parallel_evaluations`, default **1** (`process_parallel.py:412`, `config.py:389`).
  So the out-of-the-box run is effectively sequential: 1 variant in flight.
- `Program.generation` exists but is purely `parent.generation + 1` bookkeeping
  (`process_parallel.py:304`); it drives nothing in selection.
- The only thing called a "generation" is `island_generations[i]`, an integer bumped once per accepted child
  (`process_parallel.py:672-674`, `database.py:1822`) whose sole job is scheduling migration.

### 1.4 Island migration

- `should_migrate()` fires when `max(island_generations) - last_migration_generation >= migration_interval`
  (`database.py:1828-1831`); default `migration_interval=50`, `migration_rate=0.1` (`config.py:351-352`).
- Migration is a **ring topology** (`i±1`), copying the top `10%` of each island by fitness as new-UUID clones with
  `parent_id` = the original (`database.py:1844-1926`).
- Two anti-duplication guards, both with incident comments: a program already flagged `metadata["migrant"]` never
  re-migrates (`database.py:1884-1885`, comment at `1867-1883` cites one program reaching 183 descendant copies), and
  migration into an island already holding identical code is skipped (`database.py:1888-1902`).

### 1.5 Termination

Four independent stopping conditions, all in `process_parallel.run_evolution`:

1. `max_iterations` exhausted — default `10000` (`config.py:420`), CLI `--iterations` (`cli.py:32`).
2. `target_score` reached on `combined_score` (`process_parallel.py:737-745`; CLI `--target-score`, `cli.py:36`).
3. Early stopping: `early_stopping_patience` iterations without a `convergence_threshold`-sized improvement
   (`process_parallel.py:748-790`; defaults `patience=None` i.e. **disabled**, `threshold=0.001`, `config.py:441-443`).
   A negative patience switches to event-based "stop when the metric exactly equals the threshold"
   (`process_parallel.py:792-801`).
4. SIGINT/SIGTERM graceful shutdown via `shutdown_event` (`controller.py:319-336`, `process_parallel.py:836-840`).

---

## 2. MUTATION MECHANISM

### 2.1 Diff blocks are the default; full rewrite is a flag

`diff_based_evolution=True` (`config.py:436`). The format is a git-conflict-style SEARCH/REPLACE block, matched by the
regex `r"<<<<<<< SEARCH\n(.*?)=======\n(.*?)>>>>>>> REPLACE"` (`config.py:438`), extracted with `re.findall(..., DOTALL)`
(`utils/code_utils.py:78-92`).

Application is **exact line-sequence matching, first occurrence only, silently skipped on miss**:
`apply_diff` splits both sides into lines and scans for the first index where the search lines match verbatim
(`code_utils.py:56-75`). A SEARCH block that does not match anywhere is dropped with no error and no signal —
`apply_diff` returns the code unchanged. (The newer `apply_diff_blocks` at `code_utils.py:243-260` at least returns an
`applied` count, but the plain code path at `process_parallel.py:263` uses `apply_diff`, which discards it.)
If **zero** blocks parse at all, the iteration returns an error result and **no child program is created**
(`process_parallel.py:224-228`).

Full-rewrite mode extracts the first fenced code block, falling back to any fenced block, falling back to the raw
response text (`code_utils.py:95-120`) — that last fallback will happily store an English paragraph as a program.

Hard cap: a child over `max_code_length=10000` characters is discarded (`process_parallel.py:281-286`, `config.py:437`).

### 2.2 EVOLVE-BLOCK markers do NOT delimit the edit region

The repo's docs say to mark editable regions with `# EVOLVE-BLOCK-START` / `# EVOLVE-BLOCK-END`
(`CLAUDE.md:88-94`, `examples/README.md:11-29`), and `parse_evolve_blocks` exists to parse them
(`code_utils.py:9-37`). **It is never called by the evolution loop.** Grepping the package, the only references are
its own definition and the `utils/__init__.py` re-export (`utils/__init__.py:17,39`); the markers are otherwise only
*inserted* by the convenience API wrappers (`api.py:223-227`, `415-430`, `542-552`) and asserted in tests.

Concretely: `build_prompt` receives `current_program=parent.code` — the **whole file** (`process_parallel.py:182`) —
and diffs are applied to the whole file (`process_parallel.py:263`). The markers are a prompt-level convention the model
may or may not honour, not an enforced boundary. Any port that needs a real protected region has to implement it.

### 2.3 What is in the prompt

Templates load from `openevolve/prompts/defaults/*.txt` with an optional user override dir
(`prompt/templates.py:175-215`); the module-level constants in `templates.py:14-158` are shadowed by those files.
The live `diff_user.txt` user message is:

~~~
# Current Program Information
- Fitness: {fitness_score}
- Feature coordinates: {feature_coords}
- Focus areas: {improvement_areas}
{artifacts}
# Program Evolution History
{evolution_history}
# Current Program
```{language}
{current_program}
```
# Task  … SEARCH/REPLACE instructions + one worked example …
~~~
(`openevolve/prompts/defaults/diff_user.txt:1-46`, assembled at `prompt/sampler.py:156-167`.)

Feedback from past attempts, in order of usefulness:

- **`improvement_areas`** — a fitness delta sentence vs the immediately preceding program
  ("Fitness improved: 0.0440 → 0.0089" / "declined" / "unchanged"), the MAP-Elites region being explored, and a
  "code is too long" nudge past `suggest_simplification_after_chars=500` (`sampler.py:196-254`;
  strings in `prompts/defaults/fragments.json:2-13`).
- **Previous Attempts** — the last **3** programs, each rendered as `changes` (a truncated textual summary of that
  attempt's SEARCH/REPLACE blocks, `code_utils.py:136-166`), its metrics, and an outcome label derived by comparing
  the child's metrics to `metadata["parent_metrics"]` (`sampler.py:270-333`). Note the slice is
  `previous_programs[-3:]` where `previous_programs` = the island's **top-3 by score**
  (`process_parallel.py:169, 185`) — so "Previous Attempts" is really "the island's current leaders", not a
  chronological attempt log.
- **Top Performing Programs** — `num_top_programs=3` full code snippets with scores (`sampler.py:335-375`, `config.py:268`).
- **Inspiration Programs** — `num_diverse_programs=2`, each labelled with a heuristic "type" (High-Performer /
  Alternative / Experimental / Migrant / Random) and "unique approach" line (`sampler.py:469-638`).
- **Artifacts** — the parent's last execution output (stdout/stderr/traceback/timeout flags), capped at
  `max_artifact_bytes=20KB` and passed through a security filter (`sampler.py:651-731`, `config.py:281-283`).
  This is the mechanism that lets a crash inform the next mutation.

Two extras worth knowing: `use_template_stochasticity=True` applies random template variations per call
(`config.py:272`, `sampler.py:639-650`); and `programs_as_changes_description` (`config.py:263`) is a large-codebase mode
where the LLM must *also* diff a maintained natural-language "changes description" and the child is **rejected** if it
doesn't (`process_parallel.py:230-254`). That description is the closest thing OpenEvolve has to the screenshots'
per-variant "insights" — see §6.

---

## 3. EVALUATION / SCORING

### 3.1 How code is executed — there is no sandbox

The candidate is written to a `tempfile.NamedTemporaryFile(suffix=".py", delete=False)`
(`evaluator.py:156-159`) and its **path** is handed to a user-supplied function:

```python
result = await loop.run_in_executor(None, self.evaluate_function, program_path)   # evaluator.py:351
```

`self.evaluate_function` is `module.evaluate` from the user's `evaluator.py`, loaded via
`importlib.util.spec_from_file_location` + `exec_module` **into the worker process**, with the evaluator's directory
pushed onto `sys.path` (`evaluator.py:67-99`). Whether the candidate itself is imported, exec'd, or subprocessed is
entirely the user evaluator's business — OpenEvolve never looks at it.

Consequences, stated plainly because they are the single biggest gap to a hosted product:

- **No sandbox of any kind.** No container, no seccomp, no `setrlimit`, no user separation. Grep for
  `sandbox|docker|seccomp|nsjail|firejail|setrlimit|rlimit` over `openevolve/` returns nothing. The shipped `Dockerfile`
  runs the *whole tool*, not the candidate, and mounts `/app` as a volume.
- **Resource limits are declared but not implemented.** `EvaluatorConfig.memory_limit_mb` and `cpu_limit` carry the
  literal comment `# Note: resource limits not implemented` (`config.py:379-382`). Same for
  `distributed` (`config.py:390-391`).
- The only isolation is that iterations run in `ProcessPoolExecutor` workers (`process_parallel.py:451+`), which is
  crash containment, not security containment.

### 3.2 Timeouts

`asyncio.wait_for(run_evaluation(), timeout=self.config.timeout)` with default `timeout=300s`
(`evaluator.py:354`, `config.py:376`). Because the work runs in a thread-pool executor, **the timeout abandons the
future but cannot kill the thread** — a candidate in a `while True:` keeps burning a CPU for the life of the worker.
The outer belt-and-braces is at the controller: `future.result(timeout=evaluator.timeout + 30)` then `future.cancel()`
(`process_parallel.py:608-610, 803-810`).

### 3.3 Cascade (multi-stage) evaluation

`cascade_evaluation=True` by default with `cascade_thresholds=[0.5, 0.75, 0.9]` (`config.py:385-386`). The evaluator
module may define `evaluate_stage1/2/3`; each stage is run with the same timeout and the run stops at the first stage
whose merged metrics fail `_passes_threshold` (`evaluator.py:360-535`, threshold logic at `668+`). Missing stage
functions silently degrade to `_direct_evaluate` (`evaluator.py:388-389`), which is warned about at load time
(`evaluator.py:101-130`). Every stage failure is caught, converted to metrics (`stageN_passed: 0.0`, `error: 0.0`) plus
artifacts carrying `stderr`/`traceback`/`failure_stage` (`evaluator.py:409-420`, `441-464`, `503-526`).

### 3.4 Crashes and invalid programs

Three distinct outcomes, and only one of them produces a stored variant:

| failure | result | stored? |
|---|---|---|
| LLM call failed / returned `None` / no parseable diff / code too long | `SerializableResult(error=...)`, logged as a warning | **no** (`process_parallel.py:206-228, 281-286, 612-613`) |
| evaluation raised | retried `max_retries=3` times, then metrics `{"error": 0.0}` + artifacts `{stderr, traceback}` | **yes**, as a zero-fitness child (`evaluator.py:267-296`) |
| evaluation timed out | no retry; metrics `{"error": 0.0, "timeout": True}` + timeout artifacts | **yes** (`evaluator.py:252-265`) |

`safe_numeric_average` deliberately excludes bools so `{"error":0.0,"timeout":True}` scores 0.0 not 0.5
(`metrics_utils.py:24-27`) — a nice detail, and a bug class worth remembering.

There is a fourth silent drop: if `database.embedding_model` is configured, `add()` runs a cosine-similarity + LLM
"NOVEL / NOT NOVEL" judge against same-island programs and **returns without inserting** a non-novel child
(`database.py:269-274`, `_is_novel` at `1070-1109`, `_llm_judge_novelty` at `1003-1068`). Off by default
(`embedding_model=None`, `config.py:367`).

### 3.5 Multi-objective

Metrics are an open `Dict[str, float]`. The system collapses them to a scalar in exactly one place —
`get_fitness_score` — which prefers `combined_score` and otherwise averages non-feature numeric metrics
(`metrics_utils.py:72-118`). Both the controller and the parallel loop emit a loud warning when `combined_score` is
absent (`controller.py:288-302`, `process_parallel.py:699-714`). The genuinely multi-objective part is MAP-Elites:
any metric can be a *feature dimension* and is then excluded from fitness, so you get a Pareto-ish grid rather than a
Pareto front. Optional LLM-judged quality metrics (`readability`/`maintainability`/`efficiency`) can be blended at
`llm_feedback_weight=0.1`, hard-coded as 70/30 against accuracy (`evaluator.py:187-214`, `config.py:394-395`).

---

## 4. DATA & ARTIFACT MODEL

### 4.1 What OpenEvolve persists

The record is the `Program` dataclass (`database.py:43-79`):

```
id, code, changes_description, language,
parent_id, generation, timestamp, iteration_found,
metrics: Dict[str,float],
complexity, diversity,
metadata: Dict[str,Any],          # island, migrant, changes, parent_metrics
prompts: Optional[Dict],
artifacts_json, artifact_dir,     # small artifacts inline, large on disk
embedding: Optional[List[float]]
```

Storage is **a directory tree of JSON, not a database**, despite the class name:

- `checkpoints/checkpoint_<N>/programs/<uuid>.json` — one file per program, `json.dump(program.to_dict())`
  (`database.py:815-844`).
- `checkpoints/checkpoint_<N>/metadata.json` — islands, per-island feature maps, archive, `best_program_id`,
  `island_best_programs`, `last_iteration`, `current_island`, `island_generations`, `last_migration_generation`,
  `feature_stats` (`database.py:632-647`).
- `best/best_program.py` + `best/best_program_info.json` (`controller.py:515-564`).
- Artifacts: `< artifact_size_threshold` (32KB) inline as `artifacts_json`, larger written to
  `artifacts/<program_id>/` with a 30-day retention sweep (`database.py:2385-2560`, `config.py:357-361`).
- Optional `evolution_trace.jsonl` — one row per parent→child transition with metrics, deltas, island, prompts and
  optionally code (`evolution_trace.py:25-208`); **disabled by default** (`config.py:406`).

Two structural consequences: (a) rewriting *every* program file at every checkpoint is O(population) per checkpoint;
(b) programs that were never added to an island (parse failures, non-novel children) exist in no file at all, so the
run's own history is lossy.

### 4.2 A SQL schema for this, and how it maps onto the host

The host already has the right shape. The host's `hypotheses` table is append-only with `parent_id`, `parent_ids`,
`generation`, and a **separate mutable** `hypothesis_state` (`app/app/store/schema.py:181-225`) — precisely the
split OpenEvolve does informally between `Program` (immutable-ish) and the database's grid/archive bookkeeping.

Proposed tables for code variants, annotated with the host analogue:

```sql
-- append-only variant record   ← mirrors hypotheses (schema.py:181-200)
CREATE TABLE code_variants (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  parent_id TEXT,                    -- lineage edge; host: hypotheses.parent_id (:184)
  generation INTEGER NOT NULL DEFAULT 0,
  ordinal INTEGER NOT NULL,          -- the "#169" the UI shows; OpenEvolve: iteration_found
  language TEXT NOT NULL,
  code TEXT NOT NULL,                -- OpenEvolve Program.code (database.py:49)
  diff_text TEXT,                    -- the raw SEARCH/REPLACE blocks
  changes_summary TEXT,              -- OpenEvolve metadata["changes"] (process_parallel.py:308)
  insights_md TEXT,                  -- LLM narrative; NOT in OpenEvolve, see §6
  created_by_agent TEXT NOT NULL,    -- 'seed' | 'mutation' | 'migration'
  created_at REAL NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
  FOREIGN KEY (parent_id) REFERENCES code_variants(id) ON DELETE SET NULL
);

-- mutable evaluation state    ← mirrors hypothesis_state (schema.py:206-225)
CREATE TABLE code_variant_state (
  variant_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,              -- queued|running|complete|error|timeout|rejected
  fitness REAL,                      -- the scalar the staircase plots
  objective REAL,                    -- the user-facing metric (MAE); sign-independent
  island INTEGER,                    -- OpenEvolve metadata["island"]
  cell_key TEXT,                     -- MAP-Elites coords; host analogue: cluster_id (:221)
  is_cell_owner INTEGER NOT NULL DEFAULT 0,
  in_archive INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL
);

-- one row per named metric    ← no host analogue; OpenEvolve Program.metrics
CREATE TABLE code_variant_metrics (
  variant_id TEXT NOT NULL, name TEXT NOT NULL, value REAL,
  PRIMARY KEY (variant_id, name)
);

-- execution side-channel      ← host analogue: scientific_tasks.result_json (schema.py:164)
CREATE TABLE code_variant_artifacts (
  variant_id TEXT NOT NULL, key TEXT NOT NULL,
  value_text TEXT, blob_path TEXT,   -- 32KB threshold, cf. config.py:359
  PRIMARY KEY (variant_id, key)
);
```

Mapping table, host ↔ OpenEvolve:

| concept | host today | OpenEvolve | verdict |
|---|---|---|---|
| immutable lineage record | `hypotheses` (`schema.py:181-200`); engine-side `Hypothesis.parent_id`/`parent_ids`/`generation` (`engine/src/co_scientist/models.py:248,252,253`) | `Program` JSON file | **same shape**; host is better (indexed `idx_hyp_parent` at `:202`) |
| mutable score/state | `hypothesis_state` (`schema.py:206-225`) | grid + archive + `best_program_id` in RAM | host is better |
| pairwise comparison record | `matches` w/ Elo before/after (`schema.py:303-319`) | none (no tournament) | host-only |
| similarity/dedup graph | `proximity_edges` (`schema.py:468-487`) | `_is_novel` embedding+LLM judge, off by default | host is better |
| resume point | `checkpoints(run_id, seq, state_json)` (`schema.py:376-387`) | `checkpoint_<N>/` directory | host is better |
| durable work unit | `scientific_tasks` w/ lease, `idempotency_key`, `max_attempts` (`schema.py:148-176`) | in-memory `Future` in a `ProcessPoolExecutor` | **host is far better** |
| named metrics per item | — | `Program.metrics` dict | **new table needed** |
| raw dataset bytes | — (`staged_documents.text` is *extracted text, never raw bytes*, `schema.py:106`) | — | **new subsystem needed** |

### 4.3 Side-by-side: the two evolutionary loops

Both repos run a generate→assess→select→mutate loop with append-only lineage. They disagree on almost every parameter.

| axis | OpenEvolve | host engine |
|---|---|---|
| unit of evolution | whole source file (`database.py:49`) | a prose hypothesis + explanation/experiment (`models.py:239,259,261`) |
| mutation operators | **one** implicit ("improve the fitness score", `prompts/defaults/diff_user.txt:17`) | **seven** named: enhancement, coherence/feasibility, inspiration, combination, simplification, analogy, out-of-box (`agents/evolution/evolution_operators.py:23-32`), dealt from a per-run shuffled deck with round rotation (`:81-110`) |
| multi-parent | no — single `parent_id` | yes — `combination` operator merges up to 2 partners; `parent_ids` list, `parent_id` = primary (`agents/evolution/evolve_results.py:140-144`, partners at `evolve_context.py:114-134`) |
| parents per round | 1 (steady-state) | 5, fixed: `EVOLUTION_PARENT_COUNT` (`agents/evolution/evolve_round.py:33,83`), one LLM attempt each, `asyncio.gather` (`evolve.py:376-379,416`) |
| parent eligibility | any island member | `is_rankable() and not is_undermined()`, then top-5 by Elo (`evolve_round.py:73-83`) |
| selection signal | executed metric → scalar fitness (`metrics_utils.py:72-118`) | LLM-judged pairwise debate → Elo, K=24, init 1200 (`agents/ranking/ranking_debate.py:284-311`, `ranking_elo.py:122-163`, `constants_tournament.py:20,25`) |
| diversity preservation | MAP-Elites cells + islands (`database.py:277-348`, `1833-1930`) | near-duplicate rejection at cosine-free **token coverage** ≥ 0.95 (`constants.py:200`, `evolve_results.py:230-268`) + a proximity clustering pass that *deletes* high-similarity siblings (`agents/proximity/proximity_dedup.py:155-180`) |
| duplicate handling | non-novel child silently not inserted (`database.py:270-274`) | duplicate archived with an audit record naming what was kept instead (`proximity_dedup.py:123-152`) |
| loop control | fixed iteration count / target score (`process_parallel.py:588-834`) | an LLM Supervisor picks the next task each cycle (`agents/supervisor/orchestrator.py:153-189`, `WORK_TASKS` at `supervisor_decision.py:41`) |

Two of these are worth stealing in the *other* direction: OpenEvolve's single free-form operator is weaker than the
host's operator deck, and the host's audit-recorded duplicate handling is better than OpenEvolve's silent drop.

---

## 5. OBSERVABILITY

- **Checkpointing** every `checkpoint_interval=100` iterations (`config.py:421`), writing the whole database plus the
  best program (`controller.py:422-477`, called from `process_parallel.py:725-734`).
- **Resume** by passing `--checkpoint <dir>` (`cli.py:48-51`); `load()` restores programs, islands, feature maps,
  archive, generation counters, and `feature_stats` so the MAP-Elites binning stays stable across restarts
  (`database.py:651-719`, `controller.py:243-248`). Resume is genuinely complete — it is one of the better parts.
- **Visualizer** (`scripts/visualizer.py`) is a Flask app over the newest checkpoint dir. It builds `nodes` from
  `metadata["islands"]` and `edges` from `parent_id` (`visualizer.py:44-89`), and serves a D3 frontend with three
  views: `graph.js` (lineage tree), `list.js` (table), `performance.js` (scatter).
- `evolution_trace.jsonl` (§4.1) is the machine-readable equivalent, off by default.

### 5.1 Against the three screenshot views

| Google view | OpenEvolve equivalent | delta |
|---|---|---|
| **Lineage** — nodes coloured red/yellow/green by score, labelled `#id` + score, `error` nodes shown inline (`solar-forecasting-initial-code.jpg`, `solar-forecasting-lineage-visualization.jpg`) | `graph.js` D3 tree from `parent_id` edges (`visualizer.py:77-82`) | **structurally the same view.** But OpenEvolve's node set is `metadata["islands"]` only, so evicted, orphaned, non-novel and diff-parse-failed variants are absent — it cannot render the red "error" nodes the screenshot shows |
| **Breakthrough Plot** — best-score-so-far staircase vs variant id, breakthrough points annotated `#1 #3 #23 #106 #117 #130 #136 #161 #169 #175` | none | `performance.js` plots metric-on-x vs **generation**-on-y as a scatter with an island toggle (`performance.js:36-60`) — a different chart. The staircase is ~10 lines of running-max over `iteration_found`, but it does not exist |
| **Scatter Plot** | `performance.js` | closest match |

---

## 6. GAP TO THE SCREENSHOTS

Verified by reading the images, then checking the code for a counterpart. Everything here is "OpenEvolve does not have it":

1. **Intake as a conversation.** The Google surface drafts the run from a chat: an "Optimization Task" card carrying an
   **AI DRAFT** badge, an Initial Code card, an Evaluation Requirements card, and an Agent panel that writes a "Run
   Draft" summarising dataset/split/baseline/objective back to the user (`overview.webp`,
   `solar-power-forecasting-run-setup.jpg`, `feature-overview-splash-screen.jpg`). OpenEvolve's intake is
   `openevolve-run.py initial_program.py evaluator.py --config config.yaml` (`cli.py:18-26`). **The evaluator is
   authored by the user in Python; Google appears to synthesise it from "Evaluation Requirements" prose** — unverified,
   but nothing in the screenshots asks the user for an `evaluate()` function.
2. **Dataset upload and a source library.** "Upload data … up to 200GB of files in your source library which are
   available across all of your runs" (`data-upload-panel.jpg`); the worked example reads
   `solar_predictions.parquet`. OpenEvolve has no data plane at all — the evaluator opens whatever path it likes.
3. **Error variants are first-class.** The variants table shows rows with Status `COMPLETE` and Score `Error`
   (Variant 304, 301 in `solar-forecasting-lineage-zoomed-out.jpg`), and error nodes appear in the lineage graph. In
   OpenEvolve, an evaluation error *is* stored (a zero-fitness child) but a **prompt/parse failure is not**
   (`process_parallel.py:225-228`) — the variant id is never allocated. Google's numbering is dense 1..306, which
   implies every attempt gets an id.
4. **Per-variant LLM "insights".** `solar-forecasting-variant-169-solar-geometry-insights.jpg` +
   `solar-forecasting-breakthrough-plot.jpg`: a **Generate insights** button produces prose explaining that #169 beat
   #161 by moving "from purely statistical features to physically-motivated Solar Geometry modeling", with named
   sub-points. OpenEvolve's nearest thing is `metadata["changes"]`, a mechanically truncated dump of the SEARCH/REPLACE
   text (`code_utils.py:136-166`), plus the optional `changes_description` mode (`config.py:263`). Neither is a
   comparative narrative, and neither is generated on demand.
5. **Run-level insights.** The header carries "Agent Insights / Generate insights" beside Best Score and Total Variants
   (`solar-forecasting-lineage-zoomed-out.jpg`) — a run-wide synthesis. No counterpart.
6. **"Copy to new run"** from a variant detail (`solar-forecasting-variant-169-solar-geometry-insights.jpg`) — seed a
   fresh run from any variant. OpenEvolve can resume a *checkpoint* (`cli.py:48`) but cannot fork from one program.
7. **The Breakthrough Plot** (§5.1) and its breakthrough-point annotation.
8. **Minimisation as a first-class objective.** The screenshots plot MAE descending 0.200 → 0.005 and label it
   "Best Score". OpenEvolve maximises unconditionally (`database.py:1139`).
9. **Live status per variant.** The table has a `Status` column (`COMPLETE`); OpenEvolve has no per-variant lifecycle
   state — a program either exists in a checkpoint or does not.
10. **Multi-tenant execution safety** — see §3.1. Google is running arbitrary LLM-written code against user data as a
    hosted service; OpenEvolve's answer to that problem is "it's your machine".
11. **Sortable variants table with a Parent column** (`solar-forecasting-lineage-zoomed-out.jpg`). `list.js` exists but
    is a checkpoint-scoped static table, not a server-paged one.

Not a gap, worth saying: OpenEvolve's **islands + MAP-Elites** machinery is *more* sophisticated than anything visible
in the screenshots. The Google lineage graph shows several long horizontal chains, which is consistent with islands, but
nothing in the images names or exposes them — **unverified**.

---

## 7. WHAT IS WORTH TAKING

Ranked by value-per-unit-effort for this host.

| # | Component | Where | Call |
|---|---|---|---|
| 1 | **SEARCH/REPLACE diff protocol + applier** — the format, the prompt instructions, the "each SEARCH must match exactly" contract | `config.py:438`, `code_utils.py:40-92`, `prompts/defaults/diff_user.txt:21-46` | **[PORT]** ~120 lines. Fix on the way in: return the applied-count and reject a child whose blocks did not all apply (`apply_diff` at `code_utils.py:56-75` swallows misses; `apply_diff_blocks` at `:243` already counts) |
| 2 | **Artifacts side-channel** — stdout/stderr/traceback/timeout captured from the failed run and injected into the *next* prompt | `evaluator.py:174-241`, `sampler.py:651-731` | **[PORT]** This is what turns a crash into a signal. Host has the storage seam already (`scientific_tasks.result_json`, `schema.py:164`) |
| 3 | **Cascade evaluation** — cheap gate, then medium, then full, with per-stage thresholds | `evaluator.py:360-535`, `config.py:385-386` | **[PORT]** Directly maps onto host tiering; it is the cost control for a 306-variant run |
| 4 | **MAP-Elites cell/archive bookkeeping** — feature binning with running min-max stats, cell-owner protection during eviction | `database.py:846-966`, `1731-1808`, `_serialize_feature_stats` at `2304` | **[STUDY]** The idea (keep the best per behaviour niche, don't let fitness collapse diversity) is exactly what the host's proximity/dedup stage half-does. The implementation is entangled with in-RAM sets; re-derive on SQL |
| 5 | **Island model + ring migration with the two anti-duplication guards** | `database.py:1833-1930` | **[STUDY]** Take the guards (they document a real 183-copy incident at `:1867-1883`); the islands themselves only pay off at ≥5× parallelism, which SQLite-single-writer limits (root AGENTS.md) |
| 6 | **Steady-state scheduler** — one child in, one submitted, island-balanced | `process_parallel.py:588-834` | **[STUDY]** The *pattern* is right for the host's durable queue; the `ProcessPoolExecutor`/`Future` mechanics are strictly worse than `scientific_tasks` leases |
| 7 | **`evolution_trace.jsonl`** — parent/child/metrics/delta/prompt per transition | `evolution_trace.py:25-208` | **[STUDY]** Host's `run_events` (`schema.py:134-144`) already is this, better; steal the `improvement_delta` field |
| 8 | **Prompt "evolution history" assembly** — previous attempts w/ outcome labels, top programs, typed inspirations | `sampler.py:256-638` | **[STUDY]** Good structure, but note the bug in §2.3: "Previous Attempts" is fed the island's top-3, not the actual recent attempts (`process_parallel.py:169,185`). Take the shape, not the wiring |
| 9 | **Checkpoint/resume of the whole population incl. feature stats** | `database.py:602-719` | **[SKIP]** Host `checkpoints` table (`schema.py:376-387`) already does this properly |
| 10 | **`ProcessPoolExecutor` worker + snapshot-per-iteration** — full DB snapshot pickled into every worker call | `process_parallel.py:498-526, 852-883` | **[SKIP]** Serialises the whole population per iteration. Actively harmful at 306 variants |
| 11 | **Novelty rejection (embedding + LLM NOVEL/NOT-NOVEL judge)** | `database.py:1003-1109` | **[SKIP]** Off by default, and the host's proximity/dedup records *why* a sibling was dropped and what was kept instead (`engine/.../proximity_dedup.py:123-152`) where OpenEvolve just returns without inserting (`database.py:270-274`). Neither belongs in a code-variant loop unmodified — see §8.2(c) |
| 12 | **Its evaluation "sandbox"** | — | **[SKIP]** There isn't one (§3.1). This is the piece the host must build from scratch |

---

## 8. REUSE vs NEW — the architectural judgment

**Recommendation: reuse the *substrate*, build a new *node*. Concretely — reuse the app's durable task queue,
lineage/state table pair, checkpoint/resume, event log and run shell; add one new engine agent (`agents/code_evolve/`)
and one genuinely new subsystem (a code execution service). Do NOT try to make the existing `evolution`/`ranking`
agents polymorphic over hypotheses-or-code.**

### 8.1 What genuinely transfers (argue: it's the same object)

The host's persistence model is already the right one, and it is the expensive part:

- **Lineage.** `hypotheses(parent_id, parent_ids, generation)` append-only + `hypothesis_state(elo, status, cluster_id)`
  mutable (`app/app/store/schema.py:181-225`) is *structurally identical* to what §4.2 needs for variants. The
  comment at `schema.py:178-180` — "`evolve` inserts a new row with parent_id set rather than mutating the parent" —
  is exactly OpenEvolve's `Program(parent_id=parent.id, generation=parent.generation+1)`
  (`process_parallel.py:298-312`). The engine side agrees: `_build_evolution_child` mints a fresh id and sets
  `parent_id=primary.id`, `parent_ids=[...]`, `generation=primary.generation+1` while never mutating the parent
  (`engine/src/co_scientist/agents/evolution/evolve_results.py:119-162`). The host's lineage model is in fact
  *richer* than OpenEvolve's — it supports multi-parent combination, which `Program` cannot express.
- **Work scheduling.** `scientific_tasks` (`schema.py:148-176`) gives leases, heartbeats, `UNIQUE(run_id,
  idempotency_key)`, `max_attempts`, pause/resume/cancel — every property `ProcessPoolExecutor` +
  `Future` (`process_parallel.py:547-610`) lacks. The existing fan-out pattern
  (`engine.fanout.review.item` → `.aggregate`, dispatch table at `app/app/engine_tasks.py:407-420`) is a **direct
  template**: `engine.fanout.variant.propose` / `.evaluate` / `.aggregate` slot into that dict with no framework
  change.
- **Resume.** `checkpoints(run_id, seq, stage, state_json)` (`schema.py:376-387`) subsumes
  `checkpoint_<N>/metadata.json`.
- **In-graph accumulation.** `state["hypotheses"]` uses a custom reducer with an explicit
  `AppendHypotheses` / `ReplaceHypotheses` op union and id+normalized-text collision dropping
  (`engine/src/co_scientist/state.py:129-160`, ops at `:29-63`). A `state["variants"]` field with the same reducer is a
  copy-paste — and it already solves the exact problem OpenEvolve papers over by pickling the whole population into
  every worker call (`process_parallel.py:498-526`).
- **UI shell.** `/runs/:id/:tab` with a canonical tab table (`app/frontend/src/workbench/run_tabs.ts:7`) is where
  "Code Variants / Visualizations / Run Specifications" lands as three tabs.

### 8.2 Where it genuinely differs (argue: three axes, and all three break the existing agents)

**(a) The selection signal is deterministic, not judged.** The host ranks by an LLM-judged pairwise Elo tournament: a
multi-turn debate produces a winner (`engine/src/co_scientist/agents/ranking/ranking_debate.py:284-311`, verdict parsed
from a literal `better idea: <1|2>` at `ranking_debate_turns.py:77-102`), Elo updates at K=24 from 1200
(`ranking_elo.py:122-163`, `constants_tournament.py:20,25`), persisted as
`matches(winner_id, loser_id, winner_elo_before/after, rationale, tier)` (`schema.py:303-319`). Each match costs an LLM
call with `max_tokens=18000` (`ranking_debate.py:157`), and the budget is ~`3` matches per idea
(`constants_tournament.py:109`). Code variants have a **total order for free**: a float from an executed metric.
Running a debate tournament over 306 variants would be strictly worse *and* astronomically more expensive. So the
ranking agent is not reusable — `hypothesis_state.elo_rating` is replaced by a `fitness` column, and `matches` has no
analogue at all. This is the cleanest evidence that a shared table with a nullable `elo` would be the wrong design: the
two objects disagree about what "better" *means*, not about how it is stored.

**(b) Execution infrastructure does not exist anywhere in the host.** This is the load-bearing argument. A recursive
search of `engine/` for `subprocess`, `exec(`, `os.system`, `Popen`, `shell=True`, `runpy`, `importlib`, `docker` and
`sandbox` returns **zero** real hits — every `compile(` match is `re.compile` or LangGraph's `StateGraph.compile()`
(`generator/configuration.py:84`). The engine's only outbound effects are LLM calls and MCP tool calls. On the app side,
document ingest deliberately stores **"extracted text, never the raw bytes"** (`schema.py:106`) and accepts only
text/markdown/csv/json plus a few image types (`app/app/document_ingest.py:14-19`). The Google surface uploads a
**parquet file** and executes LLM-written Python against it. That is a new service — a job runner with a filesystem, a
data volume, CPU/memory limits and network isolation — and OpenEvolve provides **zero** help here (§3.1: limits are
literally commented "not implemented", `config.py:379-382`). Any plan that says "generalize evolve to carry code" and
stops there has skipped the only part that is actually hard.

**(c) The population model is different in kind.** The host evolves a single pool through two gates that *remove*
members. `_select_evolution_pool` breeds only from `is_rankable() and not is_undermined()` survivors, top-5 by Elo
(`agents/evolution/evolve_round.py:73-83`), and `is_rankable` is false for any of five blocking review dispositions
(`models.py:352-373`, `BLOCKING_REVIEW_DISPOSITIONS` at `:177-185`) — a verdict set once and never revisited (root
AGENTS.md). Then proximity clustering **deletes** all but the best member of each high-similarity cluster
(`agents/proximity/proximity_dedup.py:155-180`, `:214`). MAP-Elites does the opposite on purpose: a low-fitness program
that occupies an unclaimed behaviour cell is *kept* precisely because it is the only occupant of its niche
(`database.py:277-348`), and eviction protects cell owners over higher-fitness homeless programs
(`database.py:1752-1777`). Running code variants through the host's review gate and dedup pass would blackhole exactly
the exploratory variants the algorithm depends on — and the host's own recorded incident is that this gate, applied to
prose, shrank a 22-idea run to a 2-idea tournament. The near-duplicate guard is likewise in the wrong currency: it
rejects a child at ≥0.95 token coverage against a peer (`constants.py:200`, `evolve_results.py:230-268`), whereas two
programs with near-identical text and different fitness is the normal, informative case in code evolution.

### 8.3 The concrete recommendation

1. **New engine agent** `engine/src/co_scientist/agents/code_evolve/` — a sibling of `agents/evolution/`, not a mode of
   it, registered as its own entry in `NODE_REGISTRY` (`engine/src/co_scientist/agents/__init__.py:71-93`). It owns:
   parent sampling (§1.2), prompt assembly (§2.3), diff application (§2.1), and cell/archive bookkeeping (§1.1). Port
   items 1, 2, 3, 8 from §7. Do reuse the host's **operator-deck** idea (`evolution_operators.py:81-110`) — OpenEvolve's
   single implicit "make it better" instruction is the weaker design, and named code operators (vectorize, add feature,
   change model family, tune hyperparameters, simplify) would give the lineage graph legible edge labels.
2. **New execution service** — the piece with no precedent in either repo. Contract: `(code, dataset_ref,
   evaluator_spec) → {metrics: dict[str,float], artifacts: dict, status}` with a hard wall-clock kill (a real
   `SIGKILL`, not `asyncio.wait_for` over a thread — §3.2), memory/CPU limits, no network, and a read-only mount of the
   run's dataset. Take OpenEvolve's *return shape* (`EvaluationResult`, `openevolve/evaluation_result.py`) and its
   cascade staging; take nothing else.
3. **New tables** `code_variants` / `code_variant_state` / `code_variant_metrics` / `code_variant_artifacts` (§4.2),
   mirroring the `hypotheses`/`hypothesis_state` split rather than extending it. Rationale: `hypotheses.title`,
   `statement`, `mechanism`, `expected_effect` (`schema.py:191-195`) are all NOT NULL-ish prose fields with no meaning
   for a program, and `hypothesis_state` carries `novelty_score`, `plausibility_score`, `verification_verdict`
   (`schema.py:213-222`) that a variant will never have. Widening those tables would leave every column nullable and
   every consumer branching on run type — the classic wrong generalization.
4. **New task types**, reusing the queue verbatim: `engine.fanout.variant.propose`, `engine.fanout.variant.evaluate`,
   `engine.fanout.variant.aggregate`, registered in `_ENGINE_TASK_DISPATCH` (`app/app/engine_tasks.py:407-420`).
   Note the host's retry rule applies unchanged: only `UnsupportedTaskError` is permanent (root AGENTS.md), so a
   crashing variant evaluation must return a **scored** result, not raise — same conclusion OpenEvolve reached at
   `evaluator.py:292-296`.
5. **Reuse the run shell wholesale**: `runs`, `run_events`, `checkpoints`, SSE, ownership middleware, the tab router.
   Add the Breakthrough Plot (running max over `code_variant_state.fitness` ordered by `ordinal` — the one chart
   OpenEvolve is missing) and reuse the lineage-graph idea from `scripts/graph.js`, which is already a `parent_id`
   edge list (`visualizer.py:77-82`).

### 8.4 The counter-argument, and why I don't take it

The strongest case for reuse-in-place is that a code variant *is* a hypothesis with a machine-checkable claim, and the
host's evolution + lineage + proximity machinery would then get better for free. It fails on cost of coupling: the three
axes in §8.2 each force a branch inside a shared code path (selection signal, execution vs. LLM review, gate vs.
niche-keeping), and the host's own recorded incidents are overwhelmingly about *one shared path serving two meanings*
(the `idea_count`/`hypothesis_count`/`verified_count` confusion; the two run paths diverging on safety gating). Concrete
test of the claim: `_select_evolution_pool` takes exactly the top 5 by Elo (`evolve_round.py:33,83`) and the operator
deck is 7 prose-specific transformations (`evolution_operators.py:23-32`) — generalizing it means both numbers become
run-type-dependent and every one of the seven operator instruction strings needs a code twin, at which point the "shared"
agent is two agents in a trenchcoat. A parallel agent + parallel tables that reuse the *substrate* — queue, checkpoints,
state reducer, event log, ownership, UI shell — get most of the leverage with none of that coupling. The substrate is the
part that took the host years of production incidents to get right; the agent is a few hundred lines.

The one place the "it's the same object" argument does hold is **the UI**. Code Variants / Visualizations / Run
Specifications is the same information architecture as the host's ideas / learning / details tabs
(`app/frontend/src/workbench/run_tabs.ts:7`), and the lineage graph is `parent_id` edges either way. Build the surface
once over an abstract "run item with a parent and a score".

**One-line answer to Q8:** generalize the *plumbing*, not the *agents* — the host's durable queue, append-only
lineage/mutable-state table pair, checkpointing and run shell carry code variants unchanged, but evolve/rank/proximity
are built around an LLM-judged ordering over prose and must not be stretched over a deterministic executed metric; and
the genuinely missing piece — a sandboxed code execution service — exists in neither repository.

"""Tables for code variants: the Computational Discovery half.

Spliced into ``SCHEMA`` next to the hypothesis tables because it mirrors
their shape deliberately -- append-only lineage beside mutable state --
rather than widening them. A program has no ``statement``, ``mechanism``
or ``expected_effect``, and a hypothesis has no exit code; sharing one
table would leave every column nullable and every consumer branching on
run type.

Three details are not arbitrary.

**The ordinal is dense and includes failures.** Every attempt gets a
number, including one whose diff did not apply and one that crashed on
import. Skipping them makes the sequence lie about how much was tried,
and the breakthrough plot -- running best against attempt number -- reads
as faster progress than actually happened.

**Metrics are rows, not a JSON blob.** A run reports several metrics per
variant and the surface charts one of them across hundreds of variants;
as JSON that is a table scan and a parse per point. The raw value is
stored, never the sign-corrected fitness, so a minimized metric still
reads as itself.

**Artifacts are separate and can be large.** A traceback is what turns a
dead variant into the next prompt, so it is kept -- but off the row that
every list query reads.
"""

CODE_VARIANTS_SCHEMA = """
-- Append-only variant records. A child is a new row with parent_id set;
-- nothing here is ever updated. Mutable state lives in the table below.
CREATE TABLE IF NOT EXISTS code_variants (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_id TEXT,                  -- NULL for the seed program
    generation INTEGER NOT NULL DEFAULT 0,
    -- Dense 1..N within a run, allocated at insert and never reused, so
    -- a variant that failed to parse still occupies a number.
    ordinal INTEGER NOT NULL,
    -- Named code operator that produced this child (vectorize, change
    -- model family, tune hyperparameters, ...). NULL for the seed. This
    -- is what gives the lineage graph legible edge labels.
    operator TEXT,
    rationale TEXT,                  -- why the operator was applied here
    diff TEXT,                       -- the patch applied to the parent
    -- {path: contents} for the whole program at this variant. Stored
    -- rather than replayed from diffs: reconstructing by replay makes
    -- every historical view depend on every intervening patch applying
    -- cleanly, and a single lossy step silently corrupts the rest.
    source_json TEXT NOT NULL,
    created_by_agent TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES code_variants(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_variant_run ON code_variants(run_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_variant_parent ON code_variants(parent_id);

-- Mutable evaluation state for a variant.
CREATE TABLE IF NOT EXISTS code_variant_state (
    variant_id TEXT PRIMARY KEY,
    -- One of code_eval.EvaluationStatus, plus 'pending' before it runs.
    status TEXT NOT NULL DEFAULT 'pending',
    -- Higher-is-better, already sign-corrected by the objective. NULL
    -- when nothing usable was reported -- which is not a score of zero,
    -- and ordering must keep the two apart (see is_best_so_far).
    fitness REAL,
    -- Whether this variant was the best in its run at the moment it was
    -- evaluated. Recorded rather than derived so the breakthrough plot
    -- does not recompute a running maximum over every row on each read.
    is_best_so_far INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL,
    stages_json TEXT,                -- per-stage outcomes, for the detail view
    -- Every objective's sign-corrected score, JSON, in the spec's
    -- declared order; `fitness` is its first entry. Stored rather than
    -- re-derived from the metrics because deriving needs the run's spec,
    -- and the two would then have to agree forever.
    objective_values_json TEXT,
    -- Raw behaviour features, JSON: size, nesting, dependencies, the
    -- operator that produced it. The *cell* is deliberately not stored.
    -- Under an adaptive or CVT grid a variant's cell depends on every
    -- other variant, so a cell written at evaluation time is wrong by
    -- the next generation; storing the measurement and deriving the
    -- cell keeps one source of truth instead of two that drift.
    behaviour_json TEXT,
    updated_at REAL NOT NULL,
    FOREIGN KEY (variant_id) REFERENCES code_variants(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_variant_state_fitness
    ON code_variant_state(fitness DESC);

-- One row per reported metric. Raw values, never the sign-corrected
-- fitness, so a minimized metric still reads as itself in a report.
CREATE TABLE IF NOT EXISTS code_variant_metrics (
    variant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (variant_id, name),
    FOREIGN KEY (variant_id) REFERENCES code_variants(id) ON DELETE CASCADE
);

-- Evidence from a failed evaluation: stderr, a traceback, the stage that
-- failed. Injected into the next proposal prompt, which is what turns a
-- crash into a direction rather than a dead end.
CREATE TABLE IF NOT EXISTS code_variant_artifacts (
    variant_id TEXT NOT NULL,
    kind TEXT NOT NULL,              -- 'stderr' | 'stdout' | 'failed_stage'
    content TEXT NOT NULL,
    PRIMARY KEY (variant_id, kind),
    FOREIGN KEY (variant_id) REFERENCES code_variants(id) ON DELETE CASCADE
);
"""

CODE_DATASETS_SCHEMA = """
-- Read-only input a run's programs open, kept out of both the variant
-- rows and the run's config. Out of the variants because the proposal
-- agent rewrites every file it is handed, so data placed there would be
-- patched like code and stored again in full per variant; out of the
-- config because that row is read by every task of every type.
CREATE TABLE IF NOT EXISTS code_datasets (
    run_id TEXT NOT NULL,
    path TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (run_id, path),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
"""

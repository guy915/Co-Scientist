"""DDL for the durable Supervisor plan and allocation ledger (audit E19).

Split out of ``schema.py`` to keep that module within the size cap; its
``SUPERVISOR_PLAN_SCHEMA`` constant splices in right after
``knowledge_facts``, so the executed script is unchanged from having it
inline. See ``app.store.supervisor_plan`` for the read/write helpers and
``app.engine_adapter.drain`` for where a run's final checkpoint state is
turned into these rows.

Before this table existed, the Supervisor's research plan, its per-cycle
task allocations, the observed statistics behind each decision, and the
terminal termination rationale lived only inside the workflow checkpoint
blob -- and only the newest checkpoint row survives
``prune_superseded_checkpoints``. Once a run finished there was no way to
answer "why did this run do that" without an unpruned checkpoint.
"""

SUPERVISOR_PLAN_SCHEMA = """
-- The Supervisor's research plan and terminal state for a run (audit E19).
-- One row per run, upserted at finalize like `run_metrics` -- a resumed run
-- that finalizes again simply replaces it. `plan_json` carries the six
-- guidance blocks the Supervisor's planning call produced wholesale
-- (research_goal_analysis, workflow_plan, config_synthesis,
-- performance_assessment, adjustment_recommendations, output_preparation);
-- `orchestrator_state_json` is the scheduler bookkeeping snapshot as of the
-- last orchestrator decision (previous top Elo, rank-stability counter, pool
-- sizes, last work task). `decision_provenance` and `termination_reason` are
-- the engine's own explanation of its last allocation source and why the
-- run stopped.
CREATE TABLE IF NOT EXISTS supervisor_plan (
    run_id TEXT PRIMARY KEY,
    plan_json TEXT NOT NULL,
    orchestrator_state_json TEXT NOT NULL DEFAULT '{}',
    decision_provenance TEXT,
    termination_reason TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

-- One row per scheduled task in the Supervisor's adaptive orchestration
-- ledger (a serialized `scheduling.TaskRecord`, audit E19). Bounded growth:
-- one row per orchestrator decision, and the loop terminates on
-- `max_iterations` (1-4 across the run tiers) or a hard budget ceiling --
-- an order of magnitude below a per-task or per-LLM-call table, which
-- AGENTS.md rules out. Rows are replaced wholesale at finalize (see
-- `replace_supervisor_allocations`), matching the `knowledge_facts`/
-- `matches` pattern, so a re-finalized resumed run does not accumulate
-- duplicates. `seq` is the ledger's own append order -- every row from one
-- drain shares a `created_at`, so ordering by timestamp alone cannot
-- recover the sequence.
CREATE TABLE IF NOT EXISTS supervisor_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    iteration INTEGER NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    -- Observable-facts reason built from live scheduler stats (pool size,
    -- reviewed count, committed matches, iteration) -- never a bare model
    -- claim; see `orchestrator._observable_decision_reason`.
    reason TEXT NOT NULL,
    -- The model's own stated rationale, kept for operator audit only -- not
    -- presented as a factual activity summary (see `orchestrator.py`).
    planner_reason TEXT,
    priority INTEGER,
    termination_reason TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sup_alloc_run
    ON supervisor_allocations(run_id, seq);
"""

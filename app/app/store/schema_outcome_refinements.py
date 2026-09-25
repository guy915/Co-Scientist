"""DDL for explicit, owner-authorized outcome-refinement intents."""

OUTCOME_REFINEMENTS_SCHEMA = """
-- Durable outbox for the separate action that authorizes one stored outcome
-- to refine its linked parent. pending_executor is intentionally not a
-- scientific_tasks status: 01c owns the first claimable executor and must
-- preserve this task identity when it materializes work.
CREATE TABLE IF NOT EXISTS outcome_refinement_actions (
    action_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    outcome_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    request_idempotency_key TEXT NOT NULL,
    task_idempotency_key TEXT NOT NULL,
    checkpoint_seq INTEGER NOT NULL,
    context_snapshot TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_executor',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    UNIQUE (run_id, request_idempotency_key),
    UNIQUE (run_id, outcome_id),
    UNIQUE (run_id, task_idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_outcome_refinement_pending
    ON outcome_refinement_actions(run_id, status, created_at);
"""

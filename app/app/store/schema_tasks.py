"""Schema for the durable task queue.

Split out to sit beside ``store/tasks.py``, matching how the other
spliced schema constants pair with the store module that owns them.
The queue is one table and two indexes; the indexes belong in this
constant rather than in ``_run_migrations`` because every column they
cover is created here.
"""

SCIENTIFIC_TASKS_SCHEMA = """
-- Durable global scientific task queue. A unique idempotency key prevents a
-- Supervisor retry or worker redelivery from duplicating scientific effects.
CREATE TABLE IF NOT EXISTS scientific_tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    -- queued | leased | paused | completed | failed | cancelled
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    inputs_json TEXT NOT NULL,
    dependencies_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    budget_json TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_owner TEXT,
    lease_expires_at REAL,
    result_json TEXT,
    error TEXT,
    -- Bounded history of *failed* attempts only (a success is already
    -- captured by result_json): JSON array, newest last, capped at
    -- store.tasks._MAX_STORED_ATTEMPTS entries. Lets a stalled task be
    -- diagnosed instead of only showing the most recent error, which
    -- used to overwrite every earlier attempt's.
    attempts_json TEXT NOT NULL DEFAULT '[]',
    -- When the *current* lease's attempt was claimed -- set once per
    -- lease, alongside `attempt`, in _try_lease_task. Deliberately not
    -- `updated_at`: a long attempt's heartbeat renews its lease through
    -- renew_task_lease, which bumps updated_at on every renewal, so
    -- reading that column as an attempt's start would report only its
    -- most recent renewal for exactly the slow failures this history
    -- exists to diagnose.
    attempt_started_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    UNIQUE (run_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_tasks_ready
    ON scientific_tasks(status, priority DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_tasks_run
    ON scientific_tasks(run_id, created_at ASC);
"""

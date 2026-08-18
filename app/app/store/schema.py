"""SQLite DDL for the app store.

The complete CREATE TABLE/INDEX script executed by ``app.store.db`` on
first connection. Pure data: behavioral code (connections, migrations)
stays in ``db.py``. Inline comments document each table's role and the
compatibility notes behind non-obvious column choices.
"""

from app.store.schema_code_variants import (
    CODE_VARIANTS_SCHEMA as CODE_VARIANTS_SCHEMA,
)
from app.store.schema_knowledge_facts import (
    KNOWLEDGE_FACTS_SCHEMA as KNOWLEDGE_FACTS_SCHEMA,
)
from app.store.schema_supervisor_plan import (
    SUPERVISOR_PLAN_SCHEMA as SUPERVISOR_PLAN_SCHEMA,
)

_SCHEMA_HEAD = """
-- Primary lifecycle record for a single hypothesis-generation run.
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    research_goal TEXT NOT NULL,
    -- short model-generated session heading, distinct from research_goal;
    -- NULL until generated (surfaces fall back to a clause of the goal)
    title TEXT,
    -- canonical run mode; column name kept for legacy clients
    profile TEXT NOT NULL,
    -- draft|queued|running|synthesizing|completed|failed|blocked|cancelled
    status TEXT NOT NULL,
    provider TEXT NOT NULL,          -- 'mock' | 'engine'
    -- JSON: initial_count, iterations, evolution_count, k_factor, ...
    config_json TEXT NOT NULL,
    client_id TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    error TEXT,
    llm_backend TEXT                 -- 'offline' | 'real'
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);

-- Bring-your-own-key credentials (see app/credentials.py). One encrypted
-- credential per run, persisted for the run's lifetime because a run's
-- durable tasks lease independently and may execute later or elsewhere
-- than the request that created the run. `encrypted_key` holds a Fernet
-- token -- never plaintext -- and the row cascades away with its run, so
-- deleting a run deletes its key. `client_id` records the owning
-- identity the key was accepted from.
CREATE TABLE IF NOT EXISTS run_credentials (
    run_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    provider TEXT NOT NULL,          -- one of config.PROVIDER_CREDENTIAL_ENV
    model TEXT NOT NULL,             -- litellm model the credential runs
    encrypted_key TEXT NOT NULL,     -- Fernet token, never plaintext
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

-- Durable pre-run Agent interview. The structured fields are derived from the
-- append-only turn transcript and remain editable until finalized.
CREATE TABLE IF NOT EXISTS interviews (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    status TEXT NOT NULL,             -- active | completed | cancelled
    fields_json TEXT NOT NULL,
    current_question TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_interviews_client
    ON interviews(client_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS interview_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id TEXT NOT NULL,
    role TEXT NOT NULL,               -- user | agent
    content TEXT NOT NULL,
    -- the Agent's chain of thought for this turn; NULL for user turns and
    -- for models that emit none
    reasoning TEXT,
    -- 1 when the deterministic recovery path authored this Agent turn
    -- because no model could be reached (see
    -- interviews_model._fallback_interview_response); 0 for model-driven
    -- turns and every user turn. Per turn, so a mid-session credential
    -- change marks only the turns it affects.
    fallback INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    FOREIGN KEY (interview_id) REFERENCES interviews(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_interview_turns
    ON interview_turns(interview_id, id ASC);

-- Scientist documents uploaded BEFORE any run exists, so an attachment can
-- ground the interview that scopes the goal and can be carried into the run
-- as part of creating it. Owned by client_id and never read across owners.
-- `interview_id` is set when the document is attached to a chat, `run_id`
-- when creating a run copies it into that run's private corpus; a row keeps
-- both so a document is traceable from chat to run. Deliberately not
-- foreign-keyed: a document exists before either row does.
CREATE TABLE IF NOT EXISTS staged_documents (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    interview_id TEXT,
    run_id TEXT,
    title TEXT NOT NULL,
    text TEXT NOT NULL,               -- extracted text, never the raw bytes
    mime_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    extraction_tool TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_staged_documents_client
    ON staged_documents(client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_staged_documents_interview
    ON staged_documents(interview_id, created_at ASC);

-- Revocable capability links for read-only public Goal Reports. Tokens are
-- random and stored only as hashes so a database read cannot disclose links.
CREATE TABLE IF NOT EXISTS report_shares (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_by_client TEXT NOT NULL,
    created_at REAL NOT NULL,
    revoked_at REAL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_report_shares_run
    ON report_shares(run_id, created_at DESC);

-- Append-only timeline of everything that happened during a run. This is the
-- canonical source the SSE endpoint replays on client reconnect or restart.
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,            -- per-run monotonic sequence number
    -- agent name, 'status', 'log', 'metric', ...
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON run_events(run_id, seq);

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

-- Append-only hypothesis records: `evolve` inserts a new row with parent_id
-- set rather than mutating the parent. Mutable fields (Elo, scores, status)
-- live in hypothesis_state below, keyed by hypothesis id.
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_id TEXT,                  -- NULL for generation-0; set by evolve
    -- JSON array of every parent id for multi-parent combination children;
    -- NULL when a single parent_id is the whole lineage. parent_id stays the
    -- primary parent so existing lineage consumers are unaffected.
    parent_ids TEXT,
    generation INTEGER NOT NULL DEFAULT 0,
    category TEXT,                   -- short classification label (breadcrumb)
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    mechanism TEXT,
    expected_effect TEXT,
    experimental_context TEXT,
    created_by_agent TEXT NOT NULL,  -- 'generation' | 'evolution'
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES hypotheses(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_hyp_run ON hypotheses(run_id);
CREATE INDEX IF NOT EXISTS idx_hyp_parent ON hypotheses(parent_id);

-- Mutable state for a hypothesis (Elo, scores, status). Kept separate from the
-- append-only `hypotheses` table so the original record is never overwritten.
CREATE TABLE IF NOT EXISTS hypothesis_state (
    hypothesis_id TEXT PRIMARY KEY,
    -- DEFAULT mirrors app.elo.INITIAL_ELO; rows are always inserted with an
    -- explicit rating, so this is only a belt-and-suspenders fallback.
    elo_rating INTEGER NOT NULL DEFAULT 1200,
    win_count INTEGER NOT NULL DEFAULT 0,
    loss_count INTEGER NOT NULL DEFAULT 0,
    novelty_score REAL,
    -- plausibility_score/testability_score/safety_status/status are reserved
    -- columns: update_hypothesis_state does not currently set them, and the
    -- underlying scores live on reviews instead (see reviews table below).
    plausibility_score REAL,
    testability_score REAL,
    safety_status TEXT DEFAULT 'pending',
    status TEXT NOT NULL DEFAULT 'active',
    cluster_id TEXT,               -- proximity/dedup cluster, set by evolve
    verification_verdict TEXT,     -- deep verification; see store/db.py
    updated_at REAL NOT NULL,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
);

-- Literature/evidence items retrieved for a run; cited by hypotheses via the
-- citations table below.
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT,                     -- 'pubmed' | 'arxiv' | 'mock' | ...
    url TEXT,
    authors_json TEXT,
    year INTEGER,
    abstract TEXT,
    available INTEGER NOT NULL DEFAULT 1,
    mime_type TEXT,
    sha256 TEXT,
    byte_size INTEGER,
    document_version TEXT,
    extraction_tool TEXT,
    doi TEXT,                        -- canonical DOI, when the source has one
    pmid TEXT,                       -- canonical PubMed id, when applicable
    passage_text TEXT,                -- exact text (title + abstract) a
                                       -- claim-evidence span's offsets index
    retrieved_at REAL,                 -- when the engine retrieved this
                                        -- article, distinct from created_at
    retrieval_score REAL,               -- hybrid lexical+semantic score
    retrieval_rationale TEXT,           -- the semantic pass's stated reason
    retriever_version TEXT,             -- method/version that produced the
                                         -- score (see relevance.py)
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ev_run ON evidence(run_id);

-- Links one hypothesis claim to one supporting evidence row, classified by
-- the four-state citation model in app/citations.py (verified/partial/
-- unsupported/unavailable).
CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    -- verified | partial | unsupported | unavailable
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cit_hyp ON citations(hypothesis_id);
-- The per-run listing (store.list_citations) filters on run_id and orders by
-- created_at; without this it scanned the whole table -- every run's rows, not
-- just this one's -- and sorted the survivors in a temp b-tree.
CREATE INDEX IF NOT EXISTS idx_cit_run ON citations(run_id, created_at);

-- Reviewer critiques and scores for a hypothesis; one row per reviewing
-- agent pass (reflection, review, meta_review), never updated in place.
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    reviewer_agent TEXT NOT NULL,    -- 'reflection' | 'review' | 'meta_review'
    summary TEXT NOT NULL,
    critique TEXT NOT NULL,
    novelty REAL,
    plausibility REAL,
    testability REAL,
    overall REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rv_hyp ON reviews(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_rv_run ON reviews(run_id);

-- One row per pairwise tournament match. Elo before/after snapshots are
-- denormalized here so match history stays reconstructable even though
-- hypothesis_state.elo_rating keeps moving forward.
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    winner_id TEXT NOT NULL,
    loser_id TEXT NOT NULL,
    winner_elo_before INTEGER NOT NULL,
    winner_elo_after INTEGER NOT NULL,
    loser_elo_before INTEGER NOT NULL,
    loser_elo_after INTEGER NOT NULL,
    rationale TEXT,
    -- decisiveness class: upset|decisive|clear|narrow
    tier TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_match_run ON matches(run_id);

-- Safety-gate outcomes at the intake and final-output checkpoints (see
-- app/safety.py); one row per gate invocation, kept for audit purposes.
CREATE TABLE IF NOT EXISTS safety_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,             -- 'intake' | 'final'
    decision TEXT NOT NULL,          -- 'allow' | 'redact' | 'block'
    reason TEXT,
    matches_json TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
-- This table had no index at all, so every per-run read of it (the audit
-- listing, the adjudication lookup in safety_stage_is_approved) and every
-- per-run delete scanned it whole.
CREATE INDEX IF NOT EXISTS idx_safety_run
    ON safety_decisions(run_id, created_at);

-- Rendered report snapshots for a run. Multiple rows may accumulate (a
-- report can be regenerated); get_latest_report picks the newest by
-- created_at, so older rows are kept only as history.
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    -- structured report (Overview, Ideas, Tournament, Citations, Safety)
    payload_json TEXT NOT NULL,
    markdown_path TEXT,
    -- full markdown stored in DB for durability across restarts
    markdown_text TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reports_run ON reports(run_id);

-- Chat-style messages for a run: user steering requests and Q&A exchanges.
-- `kind` distinguishes 'steering' (consumed by the workflow, then marked
-- applied) from 'qa' (answered inline, never marked applied).
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    sender     TEXT NOT NULL,
    content    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    created_at REAL NOT NULL,
    applied    INTEGER NOT NULL DEFAULT 0,
    meta_json  TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_run ON messages(run_id, id);

-- Durable workflow checkpoints (Milestone 4). One row per saved checkpoint;
-- get_latest_checkpoint reads the newest by seq. `state_json` is the versioned
-- checkpoint envelope (curated workflow state + provider-specific resume data),
-- `last_event_seq` is the high-water mark a resumed run assigns new event seqs
-- above (idempotent replay), and `schema_version` gates fail-closed restore.
CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,            -- per-run monotonic checkpoint sequence
    stage TEXT NOT NULL,             -- provider stage/boundary label
    schema_version INTEGER NOT NULL,
    last_event_seq INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ckpt_run_seq ON checkpoints(run_id, seq DESC);

-- Final per-run execution metrics (LLM calls, phase timings). One row per
-- run, upserted at finalize; a resumed run that finalizes again replaces it.
CREATE TABLE IF NOT EXISTS run_metrics (
    run_id TEXT PRIMARY KEY,
    metrics_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

-- Pilot feedback submitted from the workspace. Standalone by design: a note
-- is not tied to a run (testers send them from the header at any time), and
-- `audience` records which mode the sender was in when they wrote it.
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  TEXT NOT NULL,
    audience   TEXT NOT NULL,
    -- bug | suggestion | question | praise
    -- (see FEEDBACK_CATEGORIES in app/feedback.py)
    category   TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);

-- Claim-level entailment graph (Milestone 5). One row per atomic claim of a
-- hypothesis, with its assessed entailment label against retrieved evidence and
-- the exact supporting/contradicting passages that drove the verdict. This is
-- the claim-evidence graph the publication gate reads; it is distinct from the
-- document-level four-state `citations` table.
CREATE TABLE IF NOT EXISTS claim_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    -- supports | contradicts | insufficient
    label TEXT NOT NULL,
    -- categorical | speculative (how the source text presents the claim)
    claim_role TEXT NOT NULL DEFAULT 'categorical',
    supporting_json TEXT,            -- JSON list of supporting passages
    contradicting_json TEXT,         -- JSON list of contradicting passages
    assessor TEXT NOT NULL,          -- provenance id of the entailment assessor
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_claim_ev_hyp ON claim_evidence(hypothesis_id);
-- Same reason as idx_cit_run: the publication gate and the report render read
-- this graph per run, and the hypothesis_id index above cannot serve that.
CREATE INDEX IF NOT EXISTS idx_claim_ev_run
    ON claim_evidence(run_id, created_at);
"""

# The knowledge_facts DDL lives in its own module (see there for why) and is
# spliced in here so the executed script is unchanged.
_SCHEMA_TAIL = """
-- Persisted application log records captured from the Python root logger
-- (see app/logging_setup.py). App-wide: run_id is NULL for records emitted
-- outside any run context. Deliberately no FK to runs -- log history
-- survives run deletion. Retention is enforced by store.prune_logs.
CREATE TABLE IF NOT EXISTS app_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    level TEXT NOT NULL,             -- level name: INFO, WARNING, ...
    levelno INTEGER NOT NULL,        -- numeric level for range filtering
    logger TEXT NOT NULL,            -- dotted logger name
    message TEXT NOT NULL,
    run_id TEXT,
    exc_text TEXT,                   -- formatted traceback, when attached
    client_id TEXT                   -- owning client for ingested UI records
);
CREATE INDEX IF NOT EXISTS idx_app_logs_run ON app_logs(run_id, id);
-- NOTE: the index over client_id is created in _run_migrations, not here.
-- CREATE TABLE IF NOT EXISTS is a no-op against an existing table, so on a
-- database from an older build this column does not exist yet when _SCHEMA
-- runs; indexing it here would abort executescript before the migration
-- that adds it could run. See _run_migrations.

-- Explainable hypothesis-proximity landscape persisted from the engine.
CREATE TABLE IF NOT EXISTS proximity_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_hypothesis_id TEXT NOT NULL,
    target_hypothesis_id TEXT NOT NULL,
    similarity REAL NOT NULL,
    degree TEXT,
    cluster_id TEXT,
    method TEXT,
    version TEXT,
    model TEXT,
    updated_at REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (source_hypothesis_id)
        REFERENCES hypotheses(id) ON DELETE CASCADE,
    FOREIGN KEY (target_hypothesis_id)
        REFERENCES hypotheses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_proximity_run ON proximity_edges(run_id);
"""

# Concatenated (not interpolated) so knowledge_facts' CREATE TABLE runs
# right after claim_evidence's -- adjacent in the executed script to the
# table it derives from, matching the story an on-disk schema dump tells.
# supervisor_plan/supervisor_allocations are spliced in right after, for the
# same reason: both are derived at the same finalize drain.
SCHEMA = (
    _SCHEMA_HEAD
    + KNOWLEDGE_FACTS_SCHEMA
    + SUPERVISOR_PLAN_SCHEMA
    + CODE_VARIANTS_SCHEMA
    + _SCHEMA_TAIL
)

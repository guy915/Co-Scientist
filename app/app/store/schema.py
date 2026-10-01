"""SQLite DDL for the app store.

The complete CREATE TABLE/INDEX script executed by ``app.store.db`` on
first connection. Pure data: behavioral code (connections, migrations)
stays in ``db.py``. Inline comments document each table's role and the
compatibility notes behind non-obvious column choices.
"""

from app.store.schema_interviews import (
    INTERVIEWS_SCHEMA as INTERVIEWS_SCHEMA,
)
from app.store.schema_knowledge_facts import (
    KNOWLEDGE_FACTS_SCHEMA as KNOWLEDGE_FACTS_SCHEMA,
)
from app.store.schema_outcome_refinements import (
    OUTCOME_REFINEMENTS_SCHEMA as OUTCOME_REFINEMENTS_SCHEMA,
)
from app.store.schema_retrieval_calls import (
    RETRIEVAL_CALLS_SCHEMA as RETRIEVAL_CALLS_SCHEMA,
)
from app.store.schema_supervisor_plan import (
    SUPERVISOR_PLAN_SCHEMA as SUPERVISOR_PLAN_SCHEMA,
)
from app.store.schema_tasks import (
    SCIENTIFIC_TASKS_SCHEMA as SCIENTIFIC_TASKS_SCHEMA,
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
    execution_policy TEXT NOT NULL DEFAULT 'standard',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    error TEXT,
    llm_backend TEXT,                -- 'offline' | 'real'
    -- freshly synthesized narrative restatement of the goal in different
    -- words (GOAL-RESTATEMENT-001); NULL until a background generator fills
    -- it, and NULL on offline/keyless runs and rows predating this column
    goal_restatement TEXT
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
    model TEXT NOT NULL,             -- litellm worker-tier model
    supervisor_model TEXT,           -- supervisor tier; NULL = model
    encrypted_key TEXT NOT NULL,     -- Fernet token, never plaintext
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

-- Owner-scoped receipts make ambiguous run-create retries replay one run.
-- The digest contains only canonical intent and a keyed fingerprint of any
-- explicit BYOK secret; the raw provider key is never stored here.
CREATE TABLE IF NOT EXISTS run_creation_receipts (
    client_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    PRIMARY KEY (client_id, idempotency_key),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
"""

_SCHEMA_MID = """
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
    -- Authoring-cycle ordinal the engine stamps at creation (0 for the
    -- initial generation, N for a research-expansion/evolution cycle). The
    -- run's true timeline axis; NULL on legacy rows. See EVAL-SCALING-001.
    creation_iteration INTEGER,
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
    -- What kind of source this is (app/citation_metadata.py's SourceType):
    -- 'peer_reviewed' | 'preprint' | 'database' | 'web' | 'document' |
    -- 'unknown'. Reported, never gated on.
    source_type TEXT,
    passage_text TEXT,                -- exact text (title + abstract) a
                                       -- claim-evidence span's offsets index
    retrieved_at REAL,                 -- when the engine retrieved this
                                        -- article, distinct from created_at
    retrieval_score REAL,               -- hybrid lexical+semantic score
    retrieval_rationale TEXT,           -- the semantic pass's stated reason
    retriever_version TEXT,             -- method/version that produced the
                                         -- score (see relevance.py)
    -- The search that found this evidence (retrieval_calls.id), or NULL for
    -- evidence that arrived by another path -- an uploaded document, a
    -- directly fetched corpus paper, or any run predating this column.
    -- Deliberately not a foreign key: the retrieval_calls key is
    -- (run_id, id), and a composite FK cannot be added by ALTER TABLE, so
    -- declaring one here would make a migrated database differ from a fresh
    -- one. Both tables cascade with their run regardless.
    retrieval_call_id TEXT,
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

-- Scientist-recorded experimental observations, distinct from reviews and
-- from engine-derived claim/evidence assessments. Each submission is a new
-- immutable row; identity snapshots preserve its context if replay removes
-- the agent hypothesis/evidence rows it originally referenced.
CREATE TABLE IF NOT EXISTS hypothesis_outcomes (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    method_protocol TEXT NOT NULL,
    conditions TEXT NOT NULL,
    measured_observation TEXT NOT NULL,
    units TEXT,
    controls TEXT NOT NULL,
    interpretation TEXT NOT NULL,
    referenced_evidence_ids_json TEXT NOT NULL,
    hypothesis_snapshot_json TEXT NOT NULL DEFAULT '{}',
    referenced_evidence_snapshots_json TEXT NOT NULL DEFAULT '[]',
    author TEXT NOT NULL,
    recorded_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_outcomes_run_recorded
    ON hypothesis_outcomes(run_id, recorded_at, id);

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
-- app/safety/); one row per gate invocation, kept for audit purposes.
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
    -- full markdown (the single Goal Report document) stored in DB for
    -- durability across restarts.
    markdown_text TEXT,
    -- Legacy from the R14-11 two-document split, reversed 2026-09-04
    -- (docs/PARITY.md's REPORT-DOCUMENT-SPLIT-001 row). Never written by
    -- any code path after the reversal -- kept nullable rather than
    -- dropped because a forward migration cannot be un-run against the
    -- production SQLite volume. A row from the split window has its
    -- second document here; store/reports.py's read path still checks it.
    markdown_text_ranking TEXT,
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
    -- Set together, once, when a steering message is acknowledged
    -- (store.mark_steering_applied): when it happened, and the
    -- orchestrator's next_task decision it fed -- "how it changed the
    -- plan" (HITL-STEERING-001), on the message itself. NULL for every
    -- unapplied message and for one applied before this column existed.
    applied_at       REAL,
    applied_decision TEXT,
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
    verification_method TEXT NOT NULL DEFAULT 'legacy_unknown',
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

# The interview/staged-document DDL lives in its own module (see there for
# why) and is spliced back between the head and the mid, which is exactly
# where it stood before the split -- so the executed script, and any schema
# dump taken from it, is byte-identical to what it was.
#
# Concatenated (not interpolated) so knowledge_facts' CREATE TABLE runs
# right after claim_evidence's -- adjacent in the executed script to the
# table it derives from, matching the story an on-disk schema dump tells.
# supervisor_plan/supervisor_allocations are spliced in right after, for the
# same reason: both are derived at the same finalize drain. retrieval_calls
# has no such adjacency to keep -- it is referenced by evidence.
# retrieval_call_id, which is a plain column rather than a foreign key -- so
# it goes last, before the tail.
SCHEMA = (
    _SCHEMA_HEAD
    + INTERVIEWS_SCHEMA
    + _SCHEMA_MID
    + OUTCOME_REFINEMENTS_SCHEMA
    + KNOWLEDGE_FACTS_SCHEMA
    + SUPERVISOR_PLAN_SCHEMA
    + SCIENTIFIC_TASKS_SCHEMA
    + RETRIEVAL_CALLS_SCHEMA
    + _SCHEMA_TAIL
)

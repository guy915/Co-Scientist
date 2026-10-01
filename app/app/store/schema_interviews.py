"""DDL for the pre-run chat: the goal interview and its attachments.

Split out of ``schema.py`` when that file reached its length ceiling, on
the same per-surface pattern its other extracted modules follow
(``schema_tasks``, ``schema_knowledge_facts``, ...). These three tables are
one surface -- the conversation that scopes a research goal, before any run
exists -- and ``schema.py`` splices this back exactly where it stood, so an
on-disk schema dump still reads in the order the tables were written in.
"""

INTERVIEWS_SCHEMA = """
-- Durable pre-run Agent interview. The structured fields are derived from the
-- append-only turn transcript and remain editable until finalized.
CREATE TABLE IF NOT EXISTS interviews (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    execution_policy TEXT NOT NULL DEFAULT 'standard',
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
    -- interviews.model._fallback_interview_response); 0 for model-driven
    -- turns and every user turn. Per turn, so a mid-session credential
    -- change marks only the turns it affects.
    fallback INTEGER NOT NULL DEFAULT 0,
    -- JSON array of the structured multiple-choice questions this Agent turn
    -- offered the scientist (see interviews/questions.py). NULL for user
    -- turns and for any turn that asked nothing choosable. Per turn, never
    -- cumulative: a question belongs to the turn that asked it, so a reopened
    -- chat re-offers only the one still awaiting an answer.
    questions_json TEXT,
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
"""

"""DDL for retrieval provenance: which query found a piece of evidence.

Split out of ``schema.py`` to keep that module within the size cap; its
``SCHEMA`` constant splices ``RETRIEVAL_CALLS_SCHEMA`` in last, since
this table is pointed *at* by ``evidence.retrieval_call_id`` rather than
pointing anywhere itself. See ``app.store.retrieval_calls`` for the
read/write helpers and ``app.research_provenance`` for how a row is
derived from a research run's ledger.

Nothing in this store recorded the *question* a search was serving or the
*query* it was issued as. Evidence carried a score, a rationale and a
retriever version, but not what was asked -- so a citation could be
audited for quality and never for relevance to the thing it was fetched
to answer, and no run could be replayed against what its sources actually
returned. This table is that missing half.
"""

RETRIEVAL_CALLS_SCHEMA = """
-- One search: one query, against one source, serving one question. Written
-- by the deep-research capability (co_scientist.research) through
-- app.research_provenance, after the network work returns -- never across
-- it, since a transaction spanning outbound I/O freezes every other writer
-- for its duration (see the store gotchas in AGENTS.md).
CREATE TABLE IF NOT EXISTS retrieval_calls (
    -- Content id from co_scientist.research.artifacts: a hash over
    -- (source, question, query), so re-issuing the same search re-derives
    -- the same id and a resumed run recognizes work it already paid for.
    -- Deliberately NOT unique on its own: the id carries no run, so two
    -- runs asking the same question of the same source share it, and a
    -- bare primary key would let one run's delete cascade take the other
    -- run's provenance with it. The key is (run_id, id).
    id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    -- The question this search was serving, and its content id. Kept apart
    -- from `query` on purpose: a query is a lossy, source-shaped rendering
    -- of a question, and when it is broadened or retried the question it
    -- was serving has to survive.
    question TEXT NOT NULL,
    question_id TEXT NOT NULL,
    query TEXT NOT NULL,
    source TEXT NOT NULL,            -- 'pubmed' | 'openalex' | 'corpus' | ...
    -- Level of the descent this call was made at, from 1. Without it the
    -- ordering of a replay cannot be reconstructed: a follow-up search and
    -- the first-level search that provoked it are otherwise indis-
    -- tinguishable rows.
    depth INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,            -- ok | empty | failed
    -- The ranked result set exactly as the source returned it, including
    -- its own ordering and scores. A replay has to reproduce the ranking,
    -- not just the winners.
    hits_json TEXT NOT NULL DEFAULT '[]',
    -- Locators the evidence budget funded, and the ones it refused. These
    -- partition hits_json: "we saw it and did not read it" and "we never
    -- saw it" are different facts about a run, and only the second is a
    -- coverage problem.
    admitted_json TEXT NOT NULL DEFAULT '[]',
    dropped_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,                      -- failure text, when status is failed
    duration_seconds REAL,
    created_at REAL NOT NULL,
    PRIMARY KEY (run_id, id),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_retrieval_calls_run
    ON retrieval_calls(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_retrieval_calls_question
    ON retrieval_calls(run_id, question_id);
"""

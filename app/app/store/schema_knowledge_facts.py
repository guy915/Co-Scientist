"""DDL for the durable structured facts/contradictions table (audit G14).

Split out of ``schema.py`` to keep that module within the size cap; its
``SCHEMA`` constant splices ``KNOWLEDGE_FACTS_SCHEMA`` in right after
``claim_evidence``, so the executed script is unchanged from having it
inline. See ``app.knowledge_facts`` for how a row is derived from a run's
claim-evidence graph and ``app.store.knowledge_facts`` for the read/write
helpers.
"""

KNOWLEDGE_FACTS_SCHEMA = """
-- Durable, structured facts and contradictions (audit G14). claim_evidence
-- above is the only structured claim table, but its `claim` column is free
-- text and its `label` a bare supports/contradicts/insufficient tag --
-- nothing normalized or queryable as a "fact" or a "contradiction" on its
-- own. One row here is derived per settled (supports/contradicts)
-- claim_evidence edge when a run's report is finalized (`insufficient`
-- edges assert nothing either way and are not carried over); `entities_json`
-- names the biomedical entities the statement mentions, so the knowledge
-- base is queryable by entity, not only by hypothesis. Scoped per-run like
-- every other run-scoped table: FINDINGS.md records per-run context memory
-- as the faithful model and cross-run "Ideation Memory" as invented by the
-- reference corpus, so this table never mixes rows across runs.
CREATE TABLE IF NOT EXISTS knowledge_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    -- Deliberately NOT a foreign key to evidence(id). A claim-evidence span's
    -- evidence_id is assessor provenance, not guaranteed to be a resolvable
    -- evidence row (e.g. a synthetic passage id from a non-store-backed
    -- assessor input) -- enforcing the FK would abort persisting an
    -- otherwise-valid fact whenever that id does not resolve.
    evidence_id TEXT,
    -- fact | contradiction
    kind TEXT NOT NULL,
    statement TEXT NOT NULL,
    entities_json TEXT NOT NULL DEFAULT '[]',
    -- the claim_evidence label this row was derived from (supports |
    -- contradicts), kept for traceability back to its source edge
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_kf_run ON knowledge_facts(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_kf_hyp ON knowledge_facts(hypothesis_id);
"""

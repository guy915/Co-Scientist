# ADR: Remove the audience/affiliation feature

**Status:** Accepted · 2026-08-27
**Removes:** the self-declared audience (`general` | `google` | `sbi_ucd`), the
SBI/UCD paper corpus, the pilot feedback form, and the proposals graph
**Supersedes:** [2026-07-18](2026-07-18-audience-context-tiers.md),
[2026-07-21](2026-07-21-group-bibliography-corpus.md)

## Context

Every visitor was asked, once per page load, which of three audiences they
belonged to. The answer was unverified, persisted in one localStorage key, and
sent to the server on run creation, the goal interview, and run Q&A. It was
not decoration: it selected which of three controls occupied the header slot,
which suggestions the home stage offered, whether the "Lab papers" connector
appeared, whether a 610k-token bibliography's catalog was injected into every
prompt the run built, and whether the `fetch_paper` MCP tool and the
disk-backed corpus search source were registered at all.

That made the audience a hidden third input to a run, alongside the goal and
the configuration. Two runs with identical goals could take different research
paths, and reproducing a run meant reproducing a browser preference. It also
put a per-audience gate in front of retrieval, which is the one place in the
system where a silently withheld source reads as "nothing found" rather than
as an error.

The three audiences had stopped earning that cost. `google` served a static
team note and a link to the proposals graph — a pitch page whose argument had
already been made. `sbi_ucd` served one lab's library to one lab. `general` is
what the product is.

## Decision

Remove the concept, not merely its two non-default values. There is no
audience field on the wire, no gate dialog, no affiliation section in
Settings, and no per-audience branch anywhere. The Logs control is now
unconditionally the header's control.

Removed with it, because each existed only to serve an audience:

- **The paper corpus.** `corpus/` (3.3 MB of sanitized full text plus its
  catalog), `app/app/paper_corpus.py`, the `fetch_paper` MCP tool, the engine's
  disk-backed `LocalCorpusRetrieval` source, `SBI_CORPUS_DIR` in both images
  and both compose files, and the offline ingest tooling under `app/dev/`.
- **The pilot feedback form.** Its endpoint, its store module, its client, and
  its table. The account-export endpoint that shared its module was extracted
  to `app/app/account_export.py` first — it was never part of the feature.
- **The proposals graph.** The `/proposals` route, its module, and its
  stylesheets. The self-contained HTML was retired from the checkout during
  the 2026-10-02 file cleanup. Recover it from Git if needed:
  `git log --all -- docs/archive/proposals.html proposals.html`.

## Consequences

**A run with no reachable search source now has no floor.** The degradation
notice used to report the corpus as a last resort when every network source
was down; `retrieval_degradation.py` now reports `run_attachments` or `none`.
That floor only ever existed for one audience, so this is a change of
description rather than of behaviour for everyone else.

**Existing databases keep an unused `interviews.audience` column.** It is
dropped from the schema for fresh databases and no longer read or written, but
production runs on a populated SQLite volume where an `ALTER TABLE ... DROP
COLUMN` buys nothing and can fail. The `feedback` table *is* dropped, by
migration.

**A stray `audience` field on a run request is ignored, not rejected.** The
frontend and the api deploy independently, so a cached tab can post the retired
field for a few minutes after the api redeploys. Pydantic's `extra="ignore"`
already covers this; `test_runs_models.py` pins it so a later `extra="forbid"`
cannot turn a stale tab into a 422.

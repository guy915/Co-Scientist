# Deeper research inside Co-Scientist — stage-2 plan

Supersedes the open questions in `SCOPE.md`. Grounded in the three teardowns
in `_analysis/`, and in claims re-verified against this repo (noted inline).

Acceptance is not a demo. It is the deletion of the "Residual gap / owner"
text on two `docs/PARITY.md` rows: `GEN-TECHNIQUES-001` and
`REFLECT-TYPES-001`.

---

## 0. Build status (2026-08-20)

Stages A, B and C are built: the capability, its provenance, and both of
its owners. Stage D is what remains. Everything below ships with tests;
the engine and app suites, `ruff`, strict `mypy` and `make parity` are
green with them in.

| Item | Stage | State | Where |
| --- | --- | --- | --- |
| Content-addressed artifacts | A | **done** | `research/artifacts.py` |
| Budget with decaying breadth + quotable ceiling | A | **done** | `research/budget.py` |
| Retrieval and model ports | A | **done** | `research/ports.py` |
| Admission and finding provenance | A | **done** | `research/admission.py` |
| The loop (levels, clamping, guards, containment) | A | **done** | `research/loop.py` |
| Offline test suite (18 cases, fakes only) | A | **done** | `engine/tests/test_research_loop.py` |
| Provenance tests + migration test | B | **done** | `app/tests/test_store_retrieval_calls.py` |
| `REFLECT-TYPES-001` corrected | A | **done** | `docs/PARITY.md` |
| `retrieval_calls` table + `evidence.retrieval_call_id` | B | **done** | `app/store/schema_retrieval_calls.py`, `app/store/retrieval_calls.py` |
| Ledger-to-rows mapper | B | **done** | `app/research_provenance.py` |
| Adapters over MCP and `llm.py` | C | **done** | `research_adapter/retrieval.py`, `model.py`, `budget.py` |
| Five prompts + their schemas | C | **done** | `prompts/templates/research_*.md`, `schemas/research.py` |
| Result round-trip through a checkpoint | C | **done** | `research/serialization.py` |
| Assigned to Generation (phase 6 of the review) | C | **done** | `literature_review/research_phase.py` |
| Tier gate, engine-side single source of truth | C | **done** | `research_adapter/budget.py`, `generator/run_setup.py` |
| Provenance written end to end | C | **done** | `app/engine_adapter/drain_research.py` |
| Owner chosen | C | **decided 2026-08-20** | Generation first, then Reflection on the same adapter |
| Assigned to Reflection (full + simulation) | C | **done** | `reflection/research_evidence.py`, `review_evidence.py` |
| Cross-level follow-up dedup | C | **done** | `research/loop.py` |
| Degradation + the three metrics | D | not started | — |

Three things to know before picking this up:

**1. The package imports nothing from this repo but itself.** That is
the property the whole staging rests on, and it is easy to lose in one
convenient import. `research/` may not reach for `mcp_client`, `llm.py`,
a run tier, or the store; anything provider-shaped arrives through
`ports.py`. If a future edit needs one of those, it belongs in the
adapter, not here. `test_the_package_depends_on_nothing_in_this_repo_but_itself`
walks the package's imports and fails on the first one that reaches
outside it.

**2. The identity scheme is frozen from the first persisted row.** A
finding is `(locator, span, question)` and a call is `(source, question,
query)`, both hashed. Change either after Stage B and every existing row
becomes unreferenceable.
`test_a_finding_is_identified_by_the_question_that_found_it` is the pin.

**3. The thread bound is linear, not exponential.** Follow-ups are
pooled per level and clamped, rather than each finding recursing on its
own, so `ResearchBudget.max_threads()` is a number a caller can quote
before spending anything: 8 + 4 + 2, not 8 x 4 x 2. Restoring per-result
recursion would silently reintroduce an unbounded loop.

## 1. What the three sources actually settled

**Delegation should be bounded by arithmetic, not by a model's judgement.**
`open_deep_research` lets the supervisor emit N `ConductResearch` tool calls
and caps N at execution time; `gpt-researcher` fixes breadth and depth up
front and halves breadth at each descent. Both work. The second is the one
this host can afford: constraint #4 in `SCOPE.md` — agentic tool-calling
generation is already the largest single line in an express run's token
budget — argues against the least-bounded option. We take arithmetic
recursion, and take from `open_deep_research` only its overflow discipline:
a thread that cannot run gets an answer explaining why and what budget to
retry against, never a dropped thread and never an exception.

**Coverage is planned before it is searched.** STORM generates perspectives
first, then one question-asking conversation per perspective. Ported off its
Wikipedia framing, the perspectives are scientific stances — mechanism,
clinical evidence, contradicting findings, methodology, prior art. This is
what makes the first round of a run wide on purpose rather than wide by
accident, and it is the mechanism `GEN-TECHNIQUES-001` is missing.

**Direction comes from what was read.** `gpt-researcher`'s recursion builds
its next query from the previous research goal plus the follow-up questions
that reading raised — not from the original goal re-planned. That single
property is the difference between our current `research_expansion` (another
meta-review-informed generation pass) and an exploration program.

**Evidence needs an identity that includes why it was fetched.** STORM hashes
`(url, sorted(snippets), "Question: … , Query: …")`. Same URL, two questions,
two objects. We have the better *columns* already; we do not have the
question, the query, or a stable id derived from them.

**Compression is a node with its own model role.** `open_deep_research`
compresses each researcher's transcript before it reaches the supervisor, and
treats a token-limit error as control flow (drop the oldest turn, retry, cap
at three, then return an error string rather than raising).

## 2. Five claims re-verified in this repo

1. **The evidence table is already good.** `app/app/store/schema.py:207`
   persists `passage_text`, `retrieved_at`, `retrieval_score`,
   `retrieval_rationale`, `retriever_version`, `sha256`, `doi`, `pmid`. The
   survey's "persist raw retrieval artifacts" advice is largely already taken.
2. **The query and the question are nowhere.** Grepped across all five
   `app/app/store/schema*.py` files: no column holds either. This is the whole
   of the provenance gap, and it is why replay reproducibility is currently
   unmeasurable for us.
3. **Tier-resolved budgets already have a precedent.**
   `literature_review/run_config.py::_resolve_papers_to_read_count` reads a
   per-run count out of `WorkflowState`, resolved once at the generator
   boundary (`generator/run_setup._resolve_dev_mode_flag`), specifically so
   the budget is visible in run state rather than in process env. New ceilings
   follow that path exactly; they do not become a second config system.
4. **The MCP gate is server-level and fails the node, not the run.**
   `literature_review/node.py:215` checks server reachability before spending
   any LLM calls, and returns `make_failure_result("literature source service
   unavailable")`. The always-available local corpus is a source *behind* that
   gate — so today an unreachable remote server suppresses a corpus that was
   never unavailable.
5. **`REFLECT-TYPES-001` is stale on the point that matters here.** The row
   says "full" and "simulation" reviews receive empty `domain_context` and do
   no retrieval. The code disagrees:
   `reflection/comprehensive_reflection.py::_review_evidence_for` generates
   hypothesis-specific queries and retrieves for exactly those two types, and
   `review_prompt_context.py` formats the result into the prompt; deep
   verification runs its own targeted probes
   (`deep_verification_evidence.py`). So reviews are not blind. What no review
   does is *follow up* — read, notice what is unanswered, search again. The
   row needs correcting; it is machine-checked, and a wrong row is worse than
   a missing one. Left alone pending a decision.

## 3. Staging

**Revised 2026-08-20, on direction from the repo owner.** The earlier version
of this section wired the loop straight into generation and then into
reflection. That is not how the harness cycle worked and not what we want
here: there, the capability (`sandbox/`, `workspace/`, `code_eval/`) was built
as a standalone package first and *assigned* to a caller afterwards — which is
why assigning it to the simulation review was a small change rather than a
rewrite. Deep research gets the same treatment. Build the capability; decide
its owner later.

### Stage A — The capability (`engine/src/co_scientist/research/`)

A standalone package, on the `code_eval/` model: typed request in, typed
result out, no knowledge of which agent called it.

- The recursive loop itself: stances → questions → queries → read → findings
  + follow-ups → descend with `breadth // 2` (floor 2) and `depth - 1`.
- A budget object carrying depth, breadth and concurrency, plus the decay
  rule. Nothing in the package reads a run tier or an env var.
- Content-addressed artifacts: a search call identified by
  `(source, question, query)`, a finding identified by `(locator, span,
  question)` — so the same paper read for two questions is two findings, per
  STORM. **This is the one irreversible decision in the package**; everything
  else can be refactored after rows exist, an id scheme cannot. The dataclasses
  are therefore designed against the columns Stage B will need, including the
  ranked result set and what the budget dropped.
- Clamps are reported, never silent: threads declined, the reason, and the
  budget to retry against travel in the result (`open_deep_research`'s
  overflow discipline), and a descent stopped by an empty level is a recorded
  outcome, not a log line (`gpt-researcher`'s guard).

**Four things must not enter this package**, or the swap-it-anywhere property
is gone: MCP client imports (retrieval arrives through a port), `llm.py`
imports (the model port returns typed results; JSON repair is the adapter's
problem), any tier→budget mapping, and any store write.

Ports the caller supplies: one retrieval port (`search`, `read`) and one model
port (plan stances, ask questions, turn a question into a query, extract
findings and follow-ups, compress a thread).

Tests are offline fakes only — CI is hermetic, with no network and no keys.

### Stage B — Persistence (resolves D4, D7) — **built 2026-08-20**

The in-memory ledger from Stage A becomes rows: a `retrieval_calls` table
(question, query, source, status, timings, the ranked result set including
what the budget dropped) with `evidence.retrieval_call_id` pointing at it. The
volume worry raised in `SCOPE.md` does not survive contact with the repo —
the log-capture thread already writes a row per emitted record. The
single-writer rules still hold: the call row is written after the network work
returns, never across it.

Three things settled while building it, each of which would have been a bug
found late:

**The key is `(run_id, id)`, not `id`.** A call's content id is a hash over
`(source, question, query)` and carries no run, so two runs asking the same
question of the same source derive the *same* id. Every sibling table is
per-run with `ON DELETE CASCADE`; under a bare primary key one run's deletion
would take another run's provenance with it, and an `INSERT OR IGNORE` would
silently attach the second run's evidence to the first run's row. The content
id itself is untouched — it is the table's key that gains the run.

**`evidence.retrieval_call_id` is deliberately not a foreign key.** A
composite FK cannot be added by `ALTER TABLE`, so declaring one would make a
migrated database differ from a fresh one — exactly the divergence the
migration tests exist to catch. Both tables cascade with their run anyway.

**The old literature-review path is not retrofitted here, and that is a
decision rather than an omission.** `Article` carries no query, so threading a
question and a query through the engine's existing search path and the drain
is a separate change of its own size. Stage B gives the capability somewhere
to write; Stage C's adapter is the first thing that writes. Until then the
column is NULL for every row, which is what it means: nothing recorded what
was asked.

### Stage C — Assignment (resolves D1, D5, and D3 at the boundary) — **Generation built 2026-08-20**

One adapter, shared by every caller: `research_adapter/` implements the two
ports over the MCP client and `llm.py`, and `budget_for_tier` turns a run
tier into a `ResearchBudget`. Generation calls it as phase 6 of the
literature review (`literature_review/research_phase.py`), seeded from the
gaps Phase 3's per-paper analysis already recorded.

Five things settled while building, none of them obvious from the plan:

- **The adapter is top-level, not under `agents/generation/`.** Two callers
  were decided from the start, so it cannot live inside one of them. It is
  also exactly where the four imports `research/` refuses belong.
- **The tier is passed verbatim, not as a yes/no.** The app sends
  `research_tier` and `research_adapter.budget` alone decides what it buys.
  A boolean would have put the tier list on both sides of the boundary,
  which is how the two drift.
- **The offline backend is not a refusal.** Unlike the tool loops, all five
  model calls are ordinary schema-constrained completions, which the offline
  responder answers deterministically — so the whole path, search included,
  runs in tests without a key.
- **The result round-trips.** `WorkflowState` is checkpointed as JSON and the
  artifacts are frozen dataclasses holding enums, so `research/serialization.py`
  writes the ledger as plain data and reads it back with the ids re-derived
  rather than stored.
- **The extraction schema names documents by index.** Echoing titles back
  would make the reply scale with the number of documents read, which is the
  silent-truncation failure the proximity node already paid for once.

Stage C's own definition of done was an offline run whose evidence rows carry
a `retrieval_call_id` resolving to a `retrieval_calls` row. That holds:
`app/tests/test_engine_drain_research_provenance.py`.

Settled while building the second owner:

- **One ledger channel, many researchers.** `research_ledger` was a single
  dict, which was correct while Generation was the only writer and silently
  wrong the moment Reflection became the second: the later node's update
  replaced the earlier one and its searches left no record. It is
  `research_ledgers`, a list with an accumulating reducer — declared on the
  state *and* mirrored in `task_runtime._CHANNEL_REDUCERS`, since a reducer
  missing from that table falls through to last-write-wins on the only path
  production runs.
- **A per-hypothesis budget bounds nothing on its own.** The review
  researches once per hypothesis, so cost is a product. Both factors are
  capped: `review_budget_for_tier` (4 threads on extended, 5 on ultra) and
  `reviewed_hypothesis_limit` (the 3 or 5 best-ranked by Elo). Ceiling per
  run: 12 threads on extended, 25 on ultra, against Generation's 6 and 11.
- **Selection is computed, not passed.** The funded set is derived from the
  whole pool inside the module, so the in-process node and a durable
  per-hypothesis task — which never sees the batch — choose identically.
- **Research is additive to the probe round, and failing it is not fatal.**
  A funded review keeps the articles its first search found and gains the
  researched ones; research that raises degrades to the probe round rather
  than failing the review item.
- **The ledger travels beside the review, not inside it.** Stamped on the
  review it would ride into every later checkpoint through `enrichments`.
- **The literature-review node being off is no longer a refusal.** With two
  owners, the reviews resolve the run's sources from its tool registry
  themselves; only MCP being unreachable refuses the tier now.
- **The tier keys the review cache.** A cached literature review from a tier
  that did not research must not answer for one that did.

**Decided 2026-08-20: Generation first, then Reflection, on the same
adapter.** Both get it; the order is what the owner chose, and it is also the
cheap order — the second caller writes no new adapter, only a budget and a
seed-question policy.

Candidate owners, in the order they make sense:

1. **Generation** — **done.** The largest win, and the owner's own instinct.
   Deepens what `literature_review/` already does well.
2. **Reflection** — **done**, for the `full` and `simulation` reviews, which
   share one gathering per hypothesis. They now get *follow-up* rather than
   first-time retrieval. Deep verification is the natural next one, since it
   already decomposes a claim into assumptions, and is deliberately not in
   this change: it is a third caller with a third multiplicity.
3. **Supervisor** — not taking it. Not a reader: It is a deterministic scheduler over
   `SchedulerStats` and a budget; the model only advises it. There is nothing
   for a research loop to plug into. What it could take is a new *signal* to
   schedule on — thin evidence on a thread, unresolved questions outstanding —
   which is a stat, not a capability, and a separate piece of work.

The in-node-vs-durable-task question (D1) is answered per assignment, not
once: the discriminator is provider spend across a restart, and Stage B is
what makes an in-node loop resumable without re-paying for retrievals.

One behaviour was left for the first real caller and is now decided.
Follow-ups were deduplicated *within* a level but not against questions
already researched at earlier levels, so a question the reading kept raising
could be researched once per level. Reflection is where that bites — its
budget is 4 threads, so one repeat is a quarter of it — and re-asking was
judged waste rather than a legitimate second look. `_follow_up_questions`
now excludes every question already opened, at any level.

### Stage D — Degradation and evaluation (resolves D6, D8)

- The MCP-down path stops being silent. The local corpus is a floor, not a
  casualty of the server gate; a degraded run says so in its state and in the
  workbench rather than quietly becoming LLM-only.
- Three metrics into `evaluations/`, in this order because the third depends
  on Stage B: **unsupported-claim rate**, **citation usefulness** (does the
  cited span support *this* claim — distinct from the existing four-state
  classifier), and **replay reproducibility** (rerun against persisted
  retrieval calls; measure evidence-set stability).
- Explicitly not adopted: BrowseComp, GAIA, FRAMES. General-web browsing
  benchmarks measure a capability that is not this system's job.

## 4. Sequencing and risk

Stage B before any assignment writes evidence, because provenance is the one
thing that cannot be retrofitted — evidence written without the question that
fetched it has to be re-fetched to be understood.

Stage C's first owner before its second, because the second reuses the first
adapter rather than writing its own.

Stage D's degradation work could move earlier if a credentialed run shows the
MCP gate firing often; the evaluation half cannot move earlier than Stage B.

The three risks worth naming:

- **Token spend.** A depth-3 run multiplies searches and readings. Mitigation
  is the tier gate plus per-thread compression, and the honest check is a
  measured express-vs-ultra token delta before this is default-on anywhere.
- **A second budget system.** If the new ceilings are configured beside the
  tier rather than derived from it, the two will disagree and the run will
  obey whichever is read last. Claim 3 above is the guard.
- **Silent degradation getting worse.** Recursion over an unreachable source
  fails deeper and quieter than a single search does. The empty-level guard
  and Stage D's visible-degradation work are one mitigation split across two
  stages; the guard shipped in Stage A, so no assignment can ship without it.

## 5. Decided and still open

**Decided:** arithmetic recursion over model-chosen delegation (D2);
perspective-planned first round (D2); in-node with incremental persistence
rather than a new task type, revisited on measurement (D1); ceilings derived
from the tier at the generator boundary (D3); a `retrieval_calls` table rather
than widening `evidence` (D4); question and query as separate artifacts (D7);
the three custom metrics, and no general-web benchmarks (D8).

**Open, and needing a human call:** which caller gets the capability first,
and how far a Reflection assignment goes (D5) — per-assumption retrieval for
the top-K hypotheses is the requirement `REFLECT-TYPES-001` states, and it is
also the largest new spend in this plan. Stage B can proceed while that is
decided; Stage C cannot.

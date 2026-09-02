# ADR: Draining the peripheral chat-interface reference

**Status:** Accepted · 2026-08-23
**Drains reference:** `references/peripheral/ai-chatbot-interface/`
**Companion:** [`2026-06-21-chat-first-foundations.md`](2026-06-21-chat-first-foundations.md),
which drained the *core* reference of the same name.

This record preserves what the last peripheral reference was worth, so that its
32 KB report and the sixteen codebases it recommends can be closed out without
losing the conclusions. It stands alone: a reader who never sees the report
should understand every decision below.

## Context

The reference is a single document — "Best Open-Source Foundations for a
Chat-First AI Co-Scientist" — surveying seventeen projects and recommending
either forking LibreChat (fastest) or building fresh on CopilotKit + AG-UI
(cleanest long-term), on a twelve-week, three-to-four-engineer roadmap.

It was written **before this product existed**, so its build advice is spent:
the shell, the engine, the citation pipeline and the export path it proposes
building are all shipped. What survives is its design thesis — *the thread owns
the product; show intermediate work; the conversation continues after the run* —
and the codebases themselves, which were read for mechanisms rather than for
adoption.

Sixteen of the seventeen were cloned shallow (single branch, no submodules, no
dependency installs; 2.5 GB) to `/Users/guy/Code/co-scientist-refs/`, a sibling
of the repository so nothing lands in git or in the deployed images. The
seventeenth was already vendored at `vendor/science-skills/`. That directory
is disposable; this ADR is what outlives it.

**Correction (2026-09-02).** This paragraph originally named that vendored
bundle `K-Dense-AI/scientific-agent-skills`. That is wrong, and it matters
because `NOTICE` is a license-attribution file. The bundle's own metadata
identifies it unambiguously as Google DeepMind's: `plugin.json` declares
`"author": {"name": "Google"}` and `"repository":
"https://github.com/google-deepmind/science-skills"` at version 1.1.0,
matching `NOTICE`'s pinned revision and plugin version; `README.md` and
`CONTRIBUTING.md` both point at that same repository. `NOTICE` and
`AGENTS.md` were right all along. Whether a K-Dense-AI project was
separately among the sixteen surveyed is not established by this evidence
either way -- only that it is not what is vendored here.

## Decisions

### 1. Keep the stack. Again.

We do not fork LibreChat or Open WebUI, do not adopt CopilotKit or AG-UI as the
event spine, and do not take on docling, citation-js, quarto, nbconvert or
qdrant as dependencies. This repeats the June decision and the study confirmed
it on new evidence rather than by deferring to it:

- **AG-UI is weaker than what we have on the axis it exists for.** Its SSE
  parser discards `id:` and `retry:`, there is no protocol-level replay, and
  `connectAgent` throws `AGUIConnectNotImplementedError` by default — resumption
  is left to each integration. Its `STATE_DELTA` JSON-patch sync drops a failed
  patch with a `console.warn`, with no sequence numbers and no gap detection, so
  a missed delta silently desynchronizes the client until the next snapshot. Our
  `?after=<seq>` replay-then-tail is one contract that works for every run and
  every client.
- **Each declined dependency costs more than it returns.** docling pulls a
  torch/transformers/onnxruntime chain; citation-js is JavaScript plus ~200 KB of
  CSL data; quarto needs Deno, Pandoc and LaTeX; nbconvert drags in traitlets;
  qdrant is a stateful vector service, which contradicts the single-replica
  SQLite deployment.

### 2. Take mechanisms, not products.

The study's value is a register of specific, located mechanisms. The ones worth
acting on are recorded in "Findings worth keeping" below, each with the file it
lives in, so a later session can implement from the idea without re-cloning.

### 3. The licence picture was wrong and is now corrected.

The GitHub API reports `NOASSERTION` for Open WebUI, Dify, quarto-cli and
Flowise, and two of the study's own agents concluded from that that Dify and
Flowise code "may not be copied verbatim". Reading the actual licence files:

| Project | Actual licence | What it means for us |
| --- | --- | --- |
| quarto-cli | Plain **MIT**, in `COPYING.md` (which is why the API could not classify it) | Freely usable |
| Flowise | **Apache-2.0**, except `packages/server/src/enterprise/` and files carrying an explicit notice | Freely usable outside that directory |
| Dify | **Apache-2.0** plus two conditions — one on multi-tenant hosting, one requiring Dify's branding to stay in *Dify's own frontend*, explicitly inapplicable to uses that do not involve it | Freely usable |
| Open WebUI | BSD-3-Clause **plus a clause-4 branding-preservation term**, with an exemption below fifty end users | Treat as read-only; reimplement from the idea |

Three of the four apparent blockers are permissive. Only Open WebUI carries a
real restriction, and even that one is about branding rather than about the code.

### 4. Anything the reader sees goes to the owner first.

The user interface is finished as far as its owner is concerned. Every finding
that changes what an end user sees or notices is recorded below as a proposal
awaiting sign-off, not as work to be executed. This is why the register
distinguishes *build* from *propose* at all.

## Findings worth keeping

Verdicts: **build** = invisible to the reader, may proceed. **propose** =
user-visible, needs the owner's sign-off. **learn** = recorded, not acted on.
**have** = already covered. **decline** = considered and rejected.

### Retrieval and ranking

| # | Finding | Located in | Verdict |
| --- | --- | --- | --- |
| D1 | **Reciprocal Rank Fusion** — `score = Σ 1/((rank+1)/weight + k - 1)` over each source's *own* ranked list. Ignores raw scores entirely, so lists on incomparable scales fuse without cross-scale arithmetic | qdrant `lib/segment/src/common/reciprocal_rank_fusion.rs`; ~20 lines of Python | **propose** — see "The ranking defect" below |
| D5 | Distribution-based fusion (z-score per list, then sum) as the alternative when raw scores *are* comparable | qdrant `score_fusion.rs` | learn — sibling of D1, unnecessary if D1 lands |
| D7 | Filter-cardinality query planning: estimate selectivity first and *change strategy*, rather than filtering post-hoc | qdrant `hnsw/read_view/search.rs` | learn — the principle transfers, the HNSW mechanics do not |
| R7 | MMR diverse retrieval, to stop near-duplicates crowding a fixed evidence budget | paper-qa `docs.py:456` | decline — needs a vector index we deliberately do not run; the MOME archive solves the same problem better and is measured |

### Generation and evidence handling

| # | Finding | Located in | Verdict |
| --- | --- | --- | --- |
| R1 | Strip inline citations out of evidence text *before* it reaches the writer prompt, so the writer cannot copy a chunk's own citation and mis-attribute it | paper-qa `src/paperqa/core.py:178` `_map_fxn_summary` | **propose** — changes generation input, so it changes what is written |
| R2 | A bundled offline Retraction Watch DOI dataset as a **second, independent** retraction check | paper-qa `src/paperqa/clients/retractions.py` | **propose** — ours (`app/app/citation_resolver.py`) marks a paper retracted only when the source API already flagged it, so it misses whatever upstream missed. Flips visible badges |
| R3 | Coerce malformed structured output at every LLM JSON boundary (list / `{"queries": [...]}` / bare string / None → clean list) | gpt-researcher `actions/query_processing.py::_normalize_sub_queries` | **build** — same failure class we have been burned by; audit the boundaries still unguarded |
| R4 | A reviewer→reviser loop over the **rendered report** before it publishes | gpt-researcher `multi_agents/agents/{editor,reviewer,reviser}.py` | **propose** — genuinely absent here: our reflection critiques hypotheses, never the final overview prose |
| R5 | A wall-clock timeout as a hard backstop around any open-ended agentic tool loop | paper-qa `agents/tools.py:405` + `settings.agent.timeout` | learn — confirm ours has one before building |
| R6 | Breadth-halving recursive research tree (`max(2, breadth // 2)` per level) | gpt-researcher `skills/deep_research.py:377` | have — `research/` already computes its whole cost arithmetically before the first call |
| R8 | Downward model-fallback ladder (smaller `max_tokens`, then a cheaper model) | gpt-researcher `query_processing.py` | decline — a model swap does not fix a token-budget failure; `BudgetEscalation` targets the actual `finish_reason="length"` cause |

### Document handling and export

| # | Finding | Located in | Verdict |
| --- | --- | --- | --- |
| D2 | Heading-hierarchy inference by heuristic cascade: PDF bookmarks → outline/legal numbering regex → font size/weight/case ranking. Pure stdlib, no ML | docling `models/stages/heading_hierarchy/` | **build** (~200 lines) — closes the "no section hierarchy" gap without docling's dependency chain |
| D3 | Run docling **offline, once**, to re-extract the 211-paper corpus, whose extraction quality is known to be poor | docling `pipeline/standard_pdf_pipeline.py` | **build** (offline tool) — the original PDFs exist outside the repo; torch never ships to production |
| D4 | DOI → CSL-JSON is one HTTP call: `GET https://doi.org/<doi>` with `Accept: application/vnd.citationstyles.csl+json` | citation-js `packages/plugin-doi/src/api.js` | learn — ~10 lines if formatted references are ever wanted, still gated by the fidelity register's "implement one truthful format" rule |
| D6 | Ordered-preprocessor-then-template report rendering | nbconvert `exporters/exporter.py` | learn — a good shape, but our report renderer is not currently painful |
| C9 | Server-side PDF export (client posts messages, receives a rendered blob) | open-webui `apis/utils/index.ts` | learn — server-side is the right side, and matches our existing server-rendered Markdown |

### The chat surface

| # | Finding | Located in | Verdict |
| --- | --- | --- | --- |
| C1 | **Block-split markdown memoization** — parse a message into top-level mdast blocks; only the last, growing block re-parses per token, earlier blocks frozen by `React.memo` on source-slice equality. Unclosed fences stay "last" until closed | LibreChat `client/src/components/Chat/Messages/Content/splitMarkdown.ts` (MIT) | **build** — `markdown_message.tsx` re-parses the whole message on every token. The reader only ever notices the flicker it removes |
| C2 | Syntax highlighting, copy button and language label on code blocks | LibreChat `CodeBlock.tsx`, `useCopyCode.ts` (MIT) | **propose** — visible chrome, one dependency |
| C3 | **Backend cancel on stop** — a dedicated abort endpoint so generation halts server-side, rather than relying on the closed connection | LibreChat `data-provider/SSE/mutations.ts`; anything-llm `models/workspace.js` | **propose** — our interview stream has no abort at all, so a turn cannot be interrupted and keeps burning tokens |
| C4 | Resumable stream: server holds state keyed by `streamId`, client reconnects with `?resume=true` | LibreChat `hooks/SSE/useResumableSSE.ts`; open-webui via Socket.IO task ids | learn — our *run* stream's replay-from-seq is stronger; our *interview* stream has neither. Worth closing with our own design |
| C5 | `@microsoft/fetch-event-source` as a drop-in for hand-rolled SSE parsing | anything-llm | decline — `readSseFrames` works on both paths; the real gap is a missing `AbortController`, about five lines |
| C6 | Structured tool-call rendering: `{toolCallId, name, args, output, runStepStatus, runStepDurationMs}`, collapsed by default with a live progress label, auto-expanding only when there is output | LibreChat `ToolCall.tsx`, `useToolCallsMap.ts` (MIT) | **propose** — pairs with U1; add open-webui's idea of collapsing *consecutive* calls into one summary |
| C7 | Artifact side panel opened by detecting a closing code fence, needing no special model syntax | open-webui `ContentRenderer.svelte` (read-only licence — reimplement from the idea) | learn |
| C8 | Progressive row mounting instead of virtualization: below forty messages mount everything; above, mount sixteen rows around the anchor and widen in chunks of thirty-two inside `startTransition`. Nothing unmounts | LibreChat `useProgressiveRowMount.tsx` (MIT) | learn — **none of the three shells virtualize the chat list**, so our plain `.map()` is the industry default rather than a gap |

### Product proposals from the reference's own thesis

These three do not come from a codebase; they are what the survey argues a
research-conversation product must do, checked against what we ship. They were
promised as proposals when this work was scoped, and are recorded here so none
is lost.

| # | Finding | State today | Verdict |
| --- | --- | --- | --- |
| P1 | **The conversation continues after the run.** The composer disables the moment a run starts, so the thread ends there | `POST /api/runs/{id}/messages/ask` is fully built — it persists the question, gathers run context, streams, handles BYOK, falls back offline and persists the answer with its sources — and has **zero frontend callers**. Audit row D4 | **propose** — the document's whole thesis, and frontend-only. *Note for whoever builds it:* the existing `disabled={Boolean(startedSession)}` lock is not an oversight, it is the fix for audit row A17. A post-run composer must route to `askRunQuestion`, never to interview turns |
| P2 | **Approve or edit the plan in the thread.** The survey's wireframe has an explicit "user edits or approves?" gate | No interview-progress rail; the only in-flight signal is "Thinking…" (audit row A1). Plan fields are read-only and `editInterviewFields` is exported with no caller (audit row A3) | **propose** |
| P3 | **Say which sources were actually consulted** | `retrieval_calls` records question, query and source per search, but only on `extended`/`ultra`, and it has no endpoint and no frontend type. The ordinary MCP literature path records nothing | **propose** — the proportionate fix mirrors `skills_used` into the report's "Data sources"; audit row A5 ("do not stream raw reasoning") is closed as a deliberate choice and stays closed |

### Agent-to-UI protocol

| # | Finding | Located in | Verdict |
| --- | --- | --- | --- |
| U1 | Tool-call status union `InProgress → Executing → Complete` carrying `{name, toolCallId, args, status, result}`, with args parsed incrementally by a partial-JSON parser while they stream | CopilotKit `react-core/src/v2/hooks/use-render-tool-call.tsx` | **propose** — the exact prop shape for a "what is the agent doing" card, and it fits our existing events without adopting their transport |
| U2 | Interrupt as a first-class terminal run outcome: `RunFinished{outcome: interrupt, interrupts: [{id, reason, responseSchema, expiresAt}]}`, resumed by a `resume[]` array keyed on `interruptId` | ag-ui `docs/concepts/interrupts.mdx` | **propose** — we have no human-in-the-loop. It maps cleanly onto the leased-task queue: an interrupt is a task row blocking on a resume row |
| U3 | Snapshot-before-pause: emit full state immediately *before* any terminating event, so any resume strategy works | ag-ui | have — checkpoint-per-node gives this for free |
| U4 | An `activityType` discriminator on progress events (`"PLAN"`, `"SEARCH"`, …) so a client renders per-kind icons instead of parsing free-text stage names | ag-ui `ActivitySnapshot`/`ActivityDelta` | **propose** (small) — `run_events` payloads are flat `type + dict` with no such field |
| U7 | Frontend tools: the agent calls a function that runs in the browser | CopilotKit `use-frontend-tool.tsx` | decline — no UI-side actions exist for hypothesis generation to trigger |

The honest trade-off: our replay design beats theirs on every resumption axis,
and we pay for it with no tool-call, shared-state or generative-UI surface at
all. U1 and U2 are precisely that cost.

### Orchestration and operations

| # | Finding | Located in | Verdict |
| --- | --- | --- | --- |
| O1 | **Per-attempt retry snapshot** — store each failed attempt whole (inputs, outputs, error, timing), not merely a counter | Dify `api/core/app/workflow/retry_history.py` | **build** — `task_worker.py` tracks `attempt`/`max_attempts` only. This turns "attempt 2/3, still failing" into "here is what attempt 1 returned", aimed squarely at the retry-budget-strand failure AGENTS.md documents |
| O2 | A Prometheus `/metrics` endpoint with run started/completed/failed counters and a node-latency histogram | Flowise `packages/server/src/metrics/` | **build** — there is no ops-facing metrics surface outside app logs and `run_events` |
| O3 | Structured per-chunk citation metadata (document id, segment, score, position), deduped and renumbered, carried in a channel *separate* from the generated text | Dify `workflow/nodes/knowledge_retrieval/retrieval.py` | learn — our `[Cn]` `ReferenceIndex` already separates keys from text; per-segment granularity is the delta |
| O4 | `GraphEngineLayer` — tracing and persistence as listeners on an event stream, so the engine core never calls out to them | Dify `core/app/workflow/layers/` | learn — cleaner than baking event-writes into node code, but not worth engine surgery now |
| O5 | Human-in-the-loop as a **typed pause reason any node can raise**, serializing runtime state into a pause row, rather than a dedicated node type | Dify `workflow/nodes/human_input/boundary.py`, versus Flowise's `humanInputAgentflow` node | learn — the more general shape, and the right one if U2 is ever scoped |
| O6 | `json_repair` as a last-resort parse tier | Dify `llm_generator/output_parser/structured_output.py` | have — `engine/src/co_scientist/llm_json_repair.py` already strips fences and repairs unterminated strings, truncated array entries and partial field names, targeted at the truncation patterns we actually see |

## The ranking defect the study found

`literature_review/search_support.py::_retrieval_score` ranks the merged
multi-source candidate pool as:

    source_quality + min(citations, 1000) / 1000 + recency

with `source_quality ∈ {1.0 arXiv, 1.5 anything else, 2.0 OpenAlex, 3.0 PubMed}`
— a span of 2.0 — against two terms spanning 1.0 each. There is **no
query-relevance term at all**. Relevance arrives later, in
`relevance.py::apply_semantic_relevance`, but only the top
`min(budget × 3, 24)` candidates *by that popularity score* are ever judged.
Everything below keeps a lexical-only score and is dropped.

The consequence is a weighted sum over incomparable scales — the exact trap
AGENTS.md already forbids for evolution objectives ("Never collapse several
objectives into one score"), unnoticed on this path. Concretely, at the time of
writing:

- **Web results score exactly 1.5** — source `"web"` is absent from the quality
  table, web providers return no citation count and no publication year — and
  `normalize_lexical`'s floor *is* 1.5, so every web result normalizes to
  exactly **0.0**. Web search is registered, keyed, enabled by default and
  structurally last in every ranking; it can never enter the semantic pool that
  would notice it.
- **Europe PMC scores at most 2.5** against PubMed's 5.0, because it declares no
  literal source and falls through to its `source_type` of `"literature"`, which
  is also absent from the table.
- The citation term is live for **exactly one source**, OpenAlex, the only one
  that emits `cited_by_count`.

`search_budget.py:87` already describes the symptom without naming the cause: a
source can "lack [citations and recency] entirely rather than score poorly on"
them. `reserved_slots` exists to force such a source in, and now has no user —
the group's corpus stopped being a search source when its whole catalogue began
arriving in run context instead.

RRF (D1) fixes this at the root: each source returns results in its own
relevance order, preserved through `merge_search_results`, and fusing ranks
needs no cross-source arithmetic. A source with no citation metadata still has a
rank-1 result. **This changes which papers reach a report, so it is a proposal,
not a build.**

## Two live defects found while verifying the above

Both were introduced by `3438c33c` (2026-08-22) and both are fixed in the same
commit as this ADR.

1. **Europe PMC search crashed the literature review node.** The tool answers
   with an envelope — `{"source": …, "query": …, "records": [...]}` — not the
   `{paper_id: metadata}` map the pipeline consumes, and its tool config named
   no `results_path`. The three envelope keys were therefore taken for paper
   ids, every real record was discarded, and `merge_search_results` was handed a
   bare string where it expected metadata, raising `AttributeError` out of Phase
   2. Nothing in the collection chain catches it, so the node failed and spent
   its whole retry budget on the identical failure. Fixed by naming
   `results_path: "records"` and having the tool emit a stable `source_id`
   (Europe PMC's own `source`/`id` pair — a DOI is absent from many preprints,
   and without a stable id the re-key falls back to list position, so a second
   query's results overwrite the first's).

2. **`preprint_search` silently returned nothing.** Same envelope, same missing
   `results_path`, but on the validation path, which skips a titleless article
   instead of raising — so every preprint query reported zero results and
   novelty claims about the last eighteen months went unchecked. Fixed the same
   way.

A third, smaller alignment shipped with them: Europe PMC emitted its citation
count as `citation_count` while the ranker reads `cited_by_count`, so a heavily
cited Europe PMC paper scored zero on that axis. Renamed to match OpenAlex.

## Where the study found us ahead

Recorded so a later session does not regress these by copying a reference.

- **Loop control.** `scheduling/policy.py::decide_next_task` is a pure
  deterministic function. Open Deep Research, gpt-researcher and paper-qa all
  let an LLM decide when to stop, capped by a counter.
- **Citation grounding.** PaperQA2 — built *for* citation-grounded answers —
  only checks that a cited key exists among the retrieved contexts. It never
  checks that the source supports the claim. `claim_verifier.py` does LLM
  entailment with a coverage fallback.
- **Context management.** Our transcript ageing evicts proactively by policy;
  Open Deep Research catches the token-limit exception and truncates after the
  failure.
- **Retrieval provenance.** None of the three research backends persist it;
  `retrieval_calls` records question, query and source per search.
- **Goal scoping.** Open Deep Research's `clarify_with_user` and
  `write_research_brief` are a single structured-output call each.
  `app/app/interviews.py` is a multi-turn streamed interview producing a
  verified five-field contract behind readiness gates, persisted and editable.

### The namesake, head to head

`The-Swarm-Corporation/AI-CoScientist` was read in full — one 1993-line file,
synchronous, in-memory, no durability.

| Aspect | Theirs | Ours |
| --- | --- | --- |
| Elo initialization / K | 1200 / 24 | 1200 / 24 — independently the same numbers |
| Match selection | Uniform-random pairs, `n * 3` rounds, **no dedup on repeated pairs** | Matchmaking plus dedup on `(pair, pre-match ratings)` — theirs has no guard against the "tournament collapsed to one repeated pair" bug we hit in production |
| Proximity / diversity | Tags a `similarity_cluster_id`; nothing is ever removed, though its own docstring implies otherwise | Actually dedupes and archives near-duplicates |
| Evolution lineage | Evolved text **overwrites** the hypothesis in place; no parent/child ids | Append-only; children carry `parent_id`, parents stay and compete |
| Durability | Fully in-memory; a crash loses the run | Leased idempotent task per node plus SQLite checkpoints, resumable |
| Safety | A free-text `safety_ethical_concerns` field that nothing gates on | Intake gate, pre-ranking screen, final gate |
| Review dimensions | Six named 1–5 scores (soundness, novelty, relevance, testability, clarity, impact) | Rubric-banded thresholds mirroring the prompt — comparable, though theirs names its dimensions more explicitly in the schema |

## Consequences

- `references/peripheral/` is now empty of undrained material; this was the last
  of the four categories, after the coding harness (`ffe49d50`), deep research
  (`b461f5ca`) and the science skills (`1398298d`, `65c28899`).
- Two live literature-search defects are fixed, with tests.
- **Six** findings are cleared to build without further sign-off: R3, D2, D3,
  C1, O1, O2.
- **Twelve** await the owner's decision, because each changes what a reader sees.
  Thirteen entries above carry the *propose* verdict — D1, R1, R2, R4, C2, C3,
  C6, U1, U2, U4, P1, P2, P3 — of which C6 and U1 are one decision (tool-call
  rendering), giving twelve. **Eight were put to the owner directly**: D1, P1,
  C3, R2, R1, P3, R4, and C6/U1. The remaining four — **P2** (approve or edit
  the plan mid-interview), **C2** (code-block highlighting), **U2** (interrupt as
  a run outcome) and **U4** (typed activity icons on progress events) — are
  recorded here and were not raised, on the judgement that eight decisions is
  already a long ask. Raising them is a sentence away.
- The clone directory outside the repository can be deleted at any time; every
  mechanism worth keeping is named above with the file it lives in.

## Outcome — all eighteen built (2026-08-25)

Every finding above was approved and is on `main`. Four were built to a
different shape than the row that proposed them, and the reasons are recorded
here rather than only in the commits, because in three of the four the
proposal's own premise turned out to be wrong.

- **U2 — no generic interrupt framework was built.** The row's premise, "we
  have no human-in-the-loop", is false. A complete one already exists and is
  specific to safety: a hold parks the boundary task rather than completing it,
  leaves a `requires_review` decision, and approval releases the parked
  boundary through the resume path. What was missing was that a run waiting on
  a person was indistinguishable from one someone had paused, and that
  `adjudicate` had no caller in the frontend at all — so a held run could only
  be released by hand. Both are now closed (`awaiting_decision_count` on the
  run payload, plus approve/reject with a confirmation step). A second
  mechanism with one consumer would have been an interface with a single
  implementation.

- **C6/U1 — no per-tool-call events.** The proposal's `{toolCallId, name,
  args, output}` shape has no counterpart in our data: run events are node and
  task lifecycle records, and one event row per MCP call would put that write
  on the single SQLite writer this system is already bottlenecked on. The card
  was built on the typed `activity` discriminator U4 added, with consecutive
  same-activity events collapsed into one counted, expandable group.

- **C3 — no dedicated abort endpoint.** The row asked for one "rather than
  relying on the closed connection". A client disconnect already reaches the
  generator; what it did not do was pass the cancellation on to the detached
  task it had started. One `finally` was the whole server-side fix.

- **P2 — no interview-progress rail.** Only the read-only-fields half (A3) was
  built. The rail is a separate visual invention that was not specified.

Two further notes for whoever picks this up next. The `D3` re-extraction
covered the fourteen papers we hold original PDFs for, out of roughly fifty
corpus files carrying full text — the rest have no PDF on this machine and are
unchanged. And the ranking defect this study found (`_retrieval_score` flooring
every web result) is fixed by rank fusion, which registers as a new retriever
method rather than redefining the existing one.

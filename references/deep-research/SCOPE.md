# Deeper research inside Co-Scientist — stage 1 scoping

Status: **stage 1 (data collection)**. This file frames the problem and lists
the decisions the stage-2 plan must resolve. It is deliberately not an
implementation plan.

Reading order: this file, then `MANIFEST.md` for what was cloned and under
what licence, then the three `_analysis/` write-ups. The survey that started
this cycle is `references/peripheral/deep-research-agent/README.md`.

## What we are actually building

**Not** a deep-research product. That option was considered and declined: a
standalone "produce a long cited report" mode would be a second output surface
beside the ranked hypothesis pool, duplicating plumbing rather than deepening
it.

What we are building is the closure of two parity rows, both currently
`partial` and both attributed to an owner label (`P1.9`) that has no plan
document anywhere in the repo:

- **`GEN-TECHNIQUES-001`** — literature exploration disappears entirely when
  MCP is unavailable, assumptions generation is reserved to the no-literature
  path, and "research expansion" is a meta-review-informed generation pass
  rather than an independent exploration program.
- **`REFLECT-TYPES-001`** — "full" and "simulation" reviews run on the single
  top hypothesis with empty `domain_context`/`tool_instructions`; no
  retrieval of their own.

These are one problem seen twice: the system searches once, shallowly, at
generation time, and never searches *because of something it read*.

## Why this is not a bolt-on, and not a rewrite either

The host is further along than the survey assumes. It already has multi-source
literature review with query generation, budgets, semantic relevance and
synthesis (`agents/generation/literature_review/`, 20 modules); an MCP tool
surface covering PubMed, OpenAlex, the SBI corpus, ChEMBL/UniProt, INDRA and
web search; a four-state citation model with claim-level grounding; and an
offline evaluation harness. The `evidence` table already persists
`passage_text`, `retrieved_at`, `retrieval_score`, `retrieval_rationale`,
`retriever_version`, `sha256` and canonical `doi`/`pmid`.

So the work is depth, not foundations. Precisely three things are missing:

1. **Recursion.** Nothing turns what a reading raised into the next search.
2. **The question behind the query.** `evidence` records the score and the
   retriever version but not the query that found the row, and not the
   question that query was serving. No column in any table holds either. This
   is why replay reproducibility is not currently measurable for us.
3. **Retrieval at verification time.** Reflection reviews consume evidence
   gathered for generation; they cannot go and look.

Four host constraints any design must respect (each is a documented past
outage or data-loss bug — see `AGENTS.md` "Gotchas"):

1. **One SQLite writer, and never across network I/O.** A recursive research
   loop multiplies both retrievals and writes. The assess-then-persist split
   in `claim_grounding.py` / `engine_adapter/drain.py` is the pattern to copy.
2. **No process-global asyncio primitives.** Each cohort runs its own event
   loop; a fan-out concurrency limiter must be per-loop or per-cohort, never a
   module-level semaphore.
3. **Durable tasks are leased, idempotent and restartable**, capped at 3
   attempts, with only `UnsupportedTaskError` permanent. A research thread
   that can run for minutes is a task-shaped thing, not a nested await.
4. **Token cost is already the largest line in an express run.** Agentic
   tool-calling generation was measured as the biggest single cost and is
   opted into by tier, not by toggle (`engine/AGENTS.md`). Anything recursive
   inherits that scrutiny.

## Decisions the stage-2 plan must resolve

| # | Decision | Why it is contested |
| --- | --- | --- |
| D1 | **Where the deeper loop lives** — inside the existing `literature_review` node, as a new subgraph, or as durable task fan-out | A subgraph is the cheapest and matches `open_deep_research`, but a research thread that runs for minutes inside one node is invisible to the leased-task model and dies with a restart. Task fan-out is restart-safe and costs a new task type. |
| D2 | **How threads are chosen** — model-chosen delegation (`ConductResearch` tool call), arithmetic recursion (breadth/depth with decay), or perspective-planned fan-out (personas → questions) | Each of the three upstreams picked a different one. They are combinable but the combination is not free: model-chosen is the most adaptive and the least bounded; arithmetic is bounded by construction and blind; perspective-planned buys coverage and costs a planning round-trip. |
| D3 | **Where budgets live and how they map to tiers** | The run already has express/extended/ultra tiers and a token budget. A new set of ceilings (concurrent threads, depth, tool calls per thread) has to be derived from the tier, not configured beside it, or the two budget systems will disagree. |
| D4 | **Evidence provenance schema** — extend `evidence` with the query/question, or add a `retrieval_calls` table the evidence rows point at | Extending is one migration and loses the result set (what ranked above what, what was dropped). A call table is the addressable-artifact answer the survey argues for and is more rows in a single-writer store. |
| D5 | **Whether reflection gets its own retrieval, or reuses generation's** | Reuse is nearly free and does not close `REFLECT-TYPES-001`; independent retrieval per assumption is the actual requirement and doubles the search volume. Possibly tier-gated. |
| D6 | **Degradation when MCP is down** | Today literature exploration vanishes and the run silently becomes LLM-only. Deeper recursion makes that failure bigger. The pre-flight gate already checks server reachability, not per-source health; the local corpus is always available and could floor the degradation. |
| D7 | **Question/query separation** | STORM keeps them as separate artifacts; we collapse goal→query in one step, which is why `query_broadening.py` loses the question a query was serving. Splitting them touches prompts, schemas and the broadening path. |
| D8 | **Evaluation** — which metrics gate this work | The survey's benchmarks (BrowseComp, GAIA, FRAMES) are general-web and a poor fit. Its three custom metrics — unsupported-claim rate, citation usefulness, replay reproducibility — fit `evaluations/` directly, but the third is unmeasurable until D4 lands. |

## What is settled

- **All three sources are permissively licensed**, verified firsthand in the
  clones: `open_deep_research` MIT, `gpt-researcher` Apache-2.0, `storm` MIT.
  No field-of-use rider of the kind that made `pi_agent_rust` off-limits last
  cycle. See `MANIFEST.md`.
- **Only one file group is a copy candidate**: the provider token-limit
  detection and message-trimming helpers in `open_deep_research/utils.py`
  (MIT, self-contained). Everything else is a shape to port, not code to
  lift — `gpt-researcher`'s valuable parts are wrapped in its own config and
  progress objects, and `storm` is DSPy-coupled throughout.
- **DSPy is not entering this repo.**
- **No new output surface.** The terminal artifact stays the ranked
  hypothesis pool with grounded claims.
- **`docs/PARITY.md` rows `GEN-TECHNIQUES-001` and `REFLECT-TYPES-001` are the
  acceptance criteria**, and their "Residual gap / owner" columns are what the
  plan must be able to delete.

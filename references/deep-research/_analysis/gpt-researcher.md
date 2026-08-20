# `assafelovic/gpt-researcher` — analysis

Clone pinned at `5d84d2f5` (Apache-2.0, last commit 2026-07-14). Much larger
than the other two — a full product with a frontend, a Docker stack, an MCP
server and a multi-agent side-tree. Only `gpt_researcher/` matters here.

**Why it is on the list:** it is the reference implementation of recursive
depth-limited research, and of binding a finding to its source at the moment
the finding is extracted. Both are things our literature-review path does not
do.

## What to read, and what to skip

Read: `skills/deep_research.py` (the recursion), `skills/curator.py` (LLM
source curation), `actions/query_processing.py` (query decomposition),
`context/compression.py` (embedding-based context reduction).

Skip: `frontend/`, `backend/`, `multi_agents/`, `deep_agents/`, `terraform/`,
`skills/image_generator.py`. Skip the 21 retriever adapters under
`retrievers/` too — we reach every source through MCP and are not adopting
another provider abstraction.

## The three ideas worth taking

### 1. Depth and breadth are separate budgets, and breadth decays

`DeepResearchSkill.deep_research()` (`skills/deep_research.py:377`) takes
`breadth` (queries at this level) and `depth` (levels remaining). At each
level it generates `breadth` queries, runs them under an
`asyncio.Semaphore(concurrency_limit)`, and for each result that warrants
going deeper recurses with `breadth // 2` (floored at 2) and `depth - 1`
(`:532-545`).

Two properties fall out that we want. Total work is bounded by construction
rather than by a loop counter, and the search naturally spends its budget wide
first and narrow later — the "breadth-first decomposition" Anthropic reports
gains from, expressed as arithmetic rather than as prompt instruction.

Note the guard at `:496`: if *every* branch at a level failed, it stops the
descent instead of generating follow-ups from empty learnings. That bug
(their issue #1579) is one we would otherwise have written ourselves — an
offline MCP server is exactly the condition that produces it, and our
literature path already degrades to LLM-only in that case.

### 2. Each level produces "learnings" plus follow-up questions, and the
follow-ups become the next query

`process_research_results` returns `{learnings, followUpQuestions}`, and the
recursion's next query is literally the previous research goal plus its
follow-up questions (`:537-541`). Research direction is therefore *derived
from what was read*, not re-planned from the original goal each time.

This is the substantive difference from our current `research_expansion`,
which re-enters generation informed by the meta-review rather than by the
unresolved questions a specific reading raised. It is the concrete mechanism
behind the `GEN-TECHNIQUES-001` residual gap.

### 3. A finding is bound to its source when it is extracted

`citations: Dict[str, str]` maps each learning to the URL it came from, built
inside result processing (`:150-171`), carried through every recursion level,
and re-attached at write time as `f"{learning} [Source: {citation}]"`
(`:611-618`).

The binding point is right; the representation is not. Keying a dict by the
free text of the finding means two identically-worded findings collide, a
reworded finding loses its source, and nothing records *where in* the source
it came from, when it was fetched, or what query found it.

Our `store.citations` + claim-grounding path is already better on
representation. What we lack is the discipline of binding at extraction time
rather than assessing after the fact — which is what makes an unsupported
claim impossible rather than merely detectable.

## What we should not take

- **`SourceCurator`** (`skills/curator.py`) — an LLM pass that ranks and drops
  sources by prompt. We already have `relevance.py` with semantic relevance
  scoring inside a budget, and the survey's own warning about source-quality
  ranking argues for explicit primary/secondary weighting, not a second LLM
  opinion.
- **`trim_context_to_word_limit`** (`:213`) — word-count truncation of a
  context list. Crude next to ODR's token-limit-driven compression, and
  crude next to what our token accounting already knows.
- **The retriever and scraper layers** — 21 search adapters and 8 scrapers.
  Our MCP server is this layer, and it already covers PubMed, OpenAlex, the
  SBI corpus, ChEMBL/UniProt, INDRA and web search.
- **The `Dict[str, str]` citation shape** — see above.

## Reuse verdict

**Copy with attribution (Apache-2.0 — the file must keep a provenance header
and the licence/NOTICE must travel with it):** nothing, on current reading.
The valuable parts are 30-line control-flow shapes wrapped in this project's
config, progress-printing and prompt-family objects; lifting them would drag
more coupling than rewriting costs.

**Port the shape, write our own code:** the depth/breadth budget pair with
decaying breadth, the empty-level descent guard, follow-ups-become-the-next-
query, and extraction-time claim→source binding.

**Learn only:** everything else.

## One caution

This repo carries a lot of in-flight work in its root (`ISSUE_BACKLOG.md`, two
`PR_pr_*.md` files, `CURSOR_RULES.md`). Treat what is in `gpt_researcher/` as
the product and the rest as a working tree — it is not a curated release.

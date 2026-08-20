# `stanford-oval/storm` — analysis

Clone pinned at `fb951af7` (MIT, last commit 2025-09-30 — quiet for about
eleven months). Two systems in one repo: STORM (`knowledge_storm/storm_wiki/`)
generates a Wikipedia-style article from scratch; Co-STORM
(`knowledge_storm/collaborative_storm/`) adds a human-in-the-loop discourse
with a shared mind map.

**Why it is on the list:** it is the only one of the three that treats
*evidence* as a first-class object with an identity, and the only one that
plans coverage by generating perspectives before generating questions. Both
map onto gaps our system has.

**The hard constraint up front:** STORM is built on DSPy — modules, signatures
and its own `lm.py`/`rm.py` provider layer. Our engine is LangGraph with our
own dispatch, JSON repair and bounds in `llm*.py`. Nothing here can be lifted
as code without importing DSPy, which we will not do. This is a design source,
not a dependency.

## The three ideas worth taking

### 1. `Information` is content-addressed, and its identity includes the
question that produced it

`interface.py:41` — an evidence object is `{url, title, description, snippets,
meta}`, and its hash is the MD5 of `(url, sorted(snippets), meta_str)` where
`meta_str` is literally `f"Question: {...}, Query: {...}"`.

Three consequences worth having:

- The same URL read twice for two different questions is two objects, not one
  deduplicated one — so *why* a source entered the run survives.
- Identity is derived from content, not assigned, so the same evidence found
  twice collapses without a registry.
- `citation_uuid` is assigned late (`-1` until numbering), which keeps the
  evidence object stable while its rendering changes.

This is the shape the survey argues for — "provenance as a data model, not a
rendering choice" — and it is the piece our literature path most visibly
lacks. We persist what a search returned only as far as it survives into a
citation row; the query, the question behind it, and the retrieved span are
not addressable afterwards, which is why `replay reproducibility` is not
currently measurable for us.

### 2. Coverage is planned by perspective, not by query

`persona_generator.py` reads related Wikipedia articles' tables of contents to
derive a set of *personas* for a topic, then `knowledge_curation.py` runs one
question-asking conversation per persona in a `ThreadPoolExecutor`
(`:317-330`), each bounded by `max_conv_turn`, with `max_perspective` capping
the fan-out.

The mechanism generalizes past its Wikipedia framing: decide *whose questions
matter* before deciding what to search, and you get coverage that a single
query-generating prompt does not produce. For a scientific run the personas
are not writers but stances — mechanism, clinical evidence, contradicting
findings, methodology, prior art — and that maps directly onto the
`REFLECT-TYPES-001` gap, where "full" and "simulation" reviews currently run
with empty domain context and no retrieval of their own.

Note the four-signature decomposition in `knowledge_curation.py`:
`AskQuestion` → `QuestionToQuery` → (retrieve) → `AnswerQuestion`. Question
and query are separate artifacts. Our `queries.py` goes from goal to query in
one step, which is why a broadened query loses the question it was serving.

### 3. The knowledge base is an explicit tree that evidence is inserted into

`dataclass.py:86-290` — `KnowledgeNode` (children, parent, `information_index`
list, path-from-root) and `KnowledgeBase` (embeddings over the structure,
`to_dict`/`from_dict`). Co-STORM inserts each new piece of information into
the tree as it arrives (`information_insertion_module.py`) and periodically
re-summarizes it (`knowledge_base_summary.py`).

This is the blackboard the survey recommends, made concrete and — importantly
— serializable. It is also the part we are least likely to want wholesale: our
run already has a durable store with lineage, and a second tree structure
alongside it would be two sources of truth. The idea to keep is that inserting
evidence into an organized structure *as it arrives* is what makes coverage
and contradiction visible before the writing stage, rather than after it.

## What we should not take

- **DSPy.** See above. This is the reason nothing here is a copy candidate.
- **The Wikipedia framing.** `get_wiki_page_title_and_toc`, FreshWiki
  evaluation, article polish — the target artifact is an encyclopedia entry.
  Ours is a ranked hypothesis pool.
- **`ThreadPoolExecutor` fan-out.** Our cohorts run one event loop per thread
  with no process-global asyncio primitives; thread-pool parallelism inside a
  node is the wrong shape here and the gotcha list already says why.
- **Simulated-user conversation as the retrieval driver.** Co-STORM's
  `simulate_user.py` is a research device for studying collaborative
  curation. We have real human checkpoints designed already (`HITL-*`).

## Reuse verdict

**Copy with attribution:** nothing. DSPy coupling makes every candidate file a
rewrite.

**Port the shape, write our own code:** the content-addressed evidence object
with the originating question and query in its identity; the
question→query→answer separation; perspective-planned coverage with a capped
fan-out.

**Learn only:** the knowledge-base tree, and the collaborative-curation
machinery around it.

## Freshness caveat

Eleven months without a commit. Nothing in what we are taking depends on the
project staying alive — but do not plan on upstream fixes, and do not cite it
as a maintained option in `docs/`.

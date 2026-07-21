# ADR: Two-tier audience context, and no retrieval over the lab corpus yet

**Status:** Accepted · 2026-07-18 · partially superseded (see below)
**Code:** `app/app/audience.py`, `app/app/content/sbi_ucd_context.md`

> **Superseded in part by later corpus work.** Two decisions below were
> reversed; the record is kept as history of why they were tried.
>
> - **The two-tier split is gone.** The ~775-token profile was a paraphrase
>   written from a model's understanding of the group, and it dropped the
>   people, the mathematics, and the collaborators. The group's full
>   reference document now ships verbatim as the single
>   `sbi_ucd_context.md`, served to every surface;
>   `audience_chat_context()` is a plain alias of `audience_context()`,
>   there is no `sbi_ucd_reference.md`, and no size-bounding test exists.
>   `audience.py`'s module docstring carries the rationale.
> - **Passage search over the corpus was replaced by catalog injection.**
>   No `search_paper_corpus` MCP tool is registered: the whole catalog
>   (title + abstract of every paper) is injected into the run's context up
>   front, and the agent reads any paper in full with `fetch_paper`. The
>   sanitation pipeline, the committed corpus, the audience gate, and
>   `fetch_paper`'s untrusted-id handling below still stand.

The SBI/UCD audience needed real lab context instead of the placeholder
written from the institute's name. This record explains why that context is
split in two, and why the group's paper corpus is not wired in.

## Context

`audience_context()` rides `run_setup_guidance` into twelve modules:
supervisor, generation, debate, literature review, reflection, review,
ranking, evolution, meta-review, and research overview. Breadth was never the
problem — the plumbing already reaches everything.

Frequency is the problem. Tournament ranking is roughly quadratic in the
hypothesis count and top matchups run multi-turn debates, so a run makes far
more LLM calls than it makes hypotheses. Whatever sits in that file is paid
for on every one of them, and competes with the user's stated research goal
for the model's attention.

The source material was a 19k-token group overview and fifteen PDFs.

## Decision

**Tier by call count, not by topic.**

| File | Size | Reaches |
|---|---|---|
| `sbi_ucd_context.md` | ~775 tokens | every audience-tagged call |
| `sbi_ucd_reference.md` | ~2,440 tokens | chat Q&A only |

The profile carries what changes behaviour: the methods the group owns
(MRA/BMRA, cSTAR, STV/DPD), the assays that decide whether a hypothesis is
testable here, the model systems, and an explicit statement of what makes a
hypothesis useful to this group. The reference carries depth that only helps
a surface making one call per question.

`audience_chat_context()` joins both for chat. Everything on the run path
takes `audience_context()` alone. A test bounds the run-path file's size so
that pasting a document into it fails loudly.

**Grounding was split rather than relaxed.** The Q&A prompt previously said
"answer ONLY from this run's artifacts — do not draw on outside knowledge",
which would have discarded the injected background entirely: "what is a DPD?"
is correctly refused under that rule. Claims about the run remain confined to
run artifacts and numbered citations; field background may come from the
background section but is never citable as `[n]`.

**Maintainer comments are stripped on load.** These files carry notes about
injection sites and token budgets. Those address whoever edits the file, not
the model, and shipping them wasted roughly 100 tokens per call explaining
the cost of the very call they rode in.

## The paper corpus: retrieval, not injection

Fifteen PDFs extract to about **331k tokens**. Sanitation removes roughly a
third — references alone are 21% — leaving **~223k tokens**, still some 250×
the run-path budget and larger than most context windows. Injection was never
on the table; the only question was how retrieval reaches an agent.

**Sanitation.** `app/app/corpus_ingest.py` extracts with `pdftotext` and
strips references, back matter, repeated page furniture, and figure debris.
Two cases needed more than a heading match: journals vary the wording
("REFERENCES AND NOTES"), and PNAS prints no heading at all — the
bibliography simply starts as a numbered list. The latter is detected by
citation density, then walked *backwards* to the first entry, because long
entries wrap onto continuation lines that dilute any forward window and leave
the opening references behind. Two citation lines survive across the corpus.

**Chunks are documents.** A whole paper is ~22k tokens, so retrieving one is
no better than injecting it. Splitting papers into ~450-token passages makes
each a `CorpusDocument`, which the existing `KeywordCorpusRetriever` already
scores — chunking was the only missing piece, not retrieval. Oversized
paragraphs are split on sentence boundaries so one flattened table cannot
produce a passage that crowds out a prompt.

**Keyword scoring, not embeddings.** No vector infrastructure exists anywhere
in the repo, so RAG means a new dependency and a store. It also would not
obviously win: this corpus is jargon-dense (STV, DPD, BMRA, trametinib,
SH-SY5Y) and queries share that vocabulary, which is where term-frequency
scoring is strongest and vocabulary mismatch is mildest. `CorpusRetriever`
remains the seam, so a vector backend can replace this without touching
callers.

**Three access paths, each querying at a moment when a query exists:**

| Surface | Query | Passages |
|---|---|---|
| Chat Q&A | the user's question | 6 |
| Run planning | the research goal | 4, via `user_inputs["literature"]` |
| `search_paper_corpus` MCP tool | whatever the agent asks | agent's choice |

The run path deliberately uses the literature channel rather than
`run_setup_guidance`: literature reaches planning and query generation, while
setup guidance reaches every tournament comparison.

The MCP side makes retrieval genuinely agentic — `call_llm_with_tools` lets
generation, validation, and reflection agents query mid-reasoning rather than
receiving a fixed set chosen up front. It is a **pair**, mirroring
`pubmed_search` → `pubmed_fulltext`: `search_paper_corpus` returns passages
with a `paper_id`, and `fetch_paper` reads that paper in full.

The pair exists because passages are the right unit for *finding* a paper and
the wrong one for *reading* it. Chunking is what makes scoring discriminate —
term-frequency over 15 whole documents blurs every paper together, while over
627 passages it locates the paragraph. But a passage that raises a question
cannot answer it, and papers here run 8k–24k tokens against a 1M-token model
window, so reading one in full costs about 2% of the context. An earlier
design offered only search, which left an agent able to find a promising
passage and unable to read the rest.

Both tools carry a small self-contained scorer instead of importing the
viewer's, because `mcp_server` is separately installable and must not depend
on the web application; the alternative, a network hop back into the app,
would make literature search depend on its own caller. That duplication has
already drifted once — the viewer split oversized paragraphs and the server
did not, so a paper whose body was one long line came back as a single
passage covering all of it. Both sides now split, and a test pins it.

`fetch_paper` treats its `paper_id` as untrusted: it is model output, so the
resolved path is checked to be inside the corpus directory.

**Retrieved passages are not run evidence.** Chat renders them under their
paper title with an explicit instruction not to cite them as `[n]` and not to
present them as findings this run produced. `[n]` must keep resolving to the
numbered manifest.

## Constraints

**Extract text; never hand an agent PDF binary.** Engine calls go through
LiteLLM as text prompts and there is no PDF input path, so binary is not
merely wasteful here — it does not work.

**The corpus is committed in full.** These are published papers from the
group's own body of work, so a clean checkout gets working retrieval with no
setup and deployments that ship the repository tree need no extra
configuration. The location stays configurable via `SBI_CORPUS_DIR` for
deployments that mount it elsewhere, and an absent or partial corpus is not
an error: retrieval returns nothing and every surface falls back.

**Retrieval is audience-gated.** One group's library is never served to
another audience.

Quality notes from `pdftotext`: body prose comes out clean with column order
preserved, but **figure labels and equations fragment** into isolated glyphs,
which is why short unpunctuated lines are dropped. The maths largely does not
survive — for MRA and cSTAR the equations *are* the contribution, so the
group's overview document (clean LaTeX) remains the better source for
notation, and the papers are the better source for findings prose.

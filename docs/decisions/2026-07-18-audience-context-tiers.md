# ADR: Two-tier audience context, and no retrieval over the lab corpus yet

**Status:** Accepted · 2026-07-18
**Code:** `app/app/audience.py`, `app/app/content/sbi_ucd_*.md`

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

## Rejected: retrieval over the paper corpus

Fifteen PDFs extract to about **336k tokens** of text — seventeen times the
overview, and the smallest single paper still exceeds the entire run-path
budget. Nothing near that can be injected, so using the corpus means building
extraction, chunking, embeddings, a store, and a retrieval tool.

We did not build it, because the papers are published with DOIs and PubMed
IDs and the literature-review agent already searches PubMed. Instead the
profile names the methods (cSTAR, MRA, BMRA, STV, DPD) and the reference
lists the canonical papers, so those names shape the queries literature
review generates and the real papers come back through the existing channel.
Literature review is query-driven and accepts no seed references, which is
why the route is indirect.

Revisit when runs demonstrably cite adjacent literature while missing the
group's own work. That is the signal; absent it, this is speculative
infrastructure.

## Constraint for whoever builds it

**Extract text; never hand an agent PDF binary.** Engine calls go through
LiteLLM as text prompts and there is no PDF input path, so binary is not
merely wasteful here — it does not work.

Quality notes from extracting the corpus with `pdftotext`:

- Body prose comes out clean, with column order preserved.
- **Figure labels and equations fragment** into isolated glyphs ("ST", "V",
  "Hyperplane" on separate lines). Any ingestion needs to drop short
  fragmented lines, and must not treat that noise as content.
- The maths largely does not survive. For MRA and cSTAR the equations *are*
  the contribution, so the group's own overview document — which carries them
  as clean LaTeX — is the better source for notation, and the papers are the
  better source for findings and method prose.

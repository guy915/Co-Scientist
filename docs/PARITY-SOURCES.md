# Primary sources and their divergences

`docs/PARITY.md` and `docs/CORPUS-EXTRACTION.md` cite "the paper" as if
Google published one document. It did not. Two separate publications exist,
and they disagree on facts in at least three confirmed places. A citation
that just says "the paper" or "Nature paper" without saying which one is
ambiguous — this note exists so a reader (and a future parity wave
re-sourcing citations) can tell the two apart and knows to check when the
distinction might matter.

## The two publications

- **arXiv** — Gottweis et al., *Towards an AI co-scientist*, arXiv:2502.18864.
  Local copy: `references/core/google-co-scientist/research/papers/
  towards-an-ai-co-scientist.md`.
- **Nature SI** — the Supplementary Information accompanying the peer-reviewed
  Nature 2026 publication *Accelerating scientific discovery with
  AI co-scientist* (Gottweis et al.). Local copy: `references/core/
  google-co-scientist/research/supplements/accelerating-scientific-
  discovery-with-co-scientist-supplementary-information.md`.

Most content is shared near-verbatim between the two (the SI is often a
"parallel source" for a passage the arXiv also carries — see the extraction
notes throughout `docs/CORPUS-EXTRACTION.md`). Where `docs/PARITY.md` cites
`SSR §n` / `TE §n` / `ARCH §n` / `RGV §n` (the local `references/core/
google-co-scientist/*.md` consolidations) it is not citing either paper
directly, and this note does not apply to those shorthands. It applies to a
bare **"the paper"** or **"Nature paper"** citing Google's own text without
saying which of the two above.

## Three confirmed factual divergences

These were found by direct comparison during the corpus extraction (corpus
row R10-11) and are not exhaustive — only these three are confirmed; there
may be others neither audit happened to compare.

1. **Selinexor expert-study panel size and experience.** The arXiv reports
   **6 raters, mean 8 years experience**
   (`specific-aims/selinexor-colon-cancer.md:5-7`). The Nature SI reports
   **9 raters, mean 6.7 years experience**, and titles the example
   differently ("Selinexor monotherapy...") in its Section 4.1.2.

2. **OCT4/AlphaFold validation tool set.** The arXiv states the modification
   was independently validated using **"ESM-2 and RoseTTAFold"** — two
   tools — and attributes the "similar pLDDT" result to ESM-2
   (`tool-use/alphafold-oct4-protein-design.md:11-16`). The Nature SI
   Supplementary Note 11 adds a **third tool, ESMFold**, and reassigns the
   "similar pLDDT" result from ESM-2 to ESMFold: "validated ... using
   ESM-2, ESMFold, and RoseTTAFold. ESM-2 predicted an increased
   log-likelihood ratio, ESMFold predicted a similar pLDDT, and RoseTTAFold
   predicted a similar GDT."

3. **Inter-rater agreement statistic.** The Nature SI Supplementary
   Information (`...supplementary-information.md:111-115`) reports that two
   independent rater groups agreed at **Spearman's rho = 0.745, p < 0.001**.
   The arXiv does not carry this statistic at all — it is not a differing
   number, but a result present in one publication and entirely absent from
   the other.

## Using this note

When a `docs/PARITY.md` row's Source column says "Nature paper" or "the
paper" without naming arXiv or Nature SI specifically, and the exact wording
of the cited claim matters (not just its substance), check both documents
before treating the citation as settled — do not assume they say the same
thing. Where a row already names a specific document (arXiv or Nature SI),
no ambiguity exists and this note does not apply.

This note is a record of a fact about the sources, not a proposal to change
any implementation. It carries no PARITY row of its own; see corpus row
`R10-11` in `docs/CORPUS-EXTRACTION.md` for the extraction that found it.

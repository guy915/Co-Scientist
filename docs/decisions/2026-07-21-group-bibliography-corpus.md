# ADR: The lab corpus is the group's whole bibliography, injected in two tiers

**Status:** Accepted · 2026-07-21
**Code:** `corpus/sbi_ucd/`, `app/app/paper_corpus.py`, `app/dev/harvest_group_pubmed.py`, `app/dev/build_catalog.py`
**Supersedes in part:** [2026-07-18](2026-07-18-audience-context-tiers.md), which sized the corpus at fifteen papers.

The corpus was fifteen hand-curated papers. The ask was to make it the
group's complete published record. This records what "complete" was scoped to
and why the catalog had to change shape to hold it.

## Context

The corpus reaches a run two ways: the app injects a catalog (title +
abstract of every paper) into the run's context, and the `fetch_paper` MCP
tool reads any one paper in full when the agent asks. There is **no search
over the corpus** — the `search_paper_corpus` tool the earlier ADR envisioned
was removed, leaving `fetch_paper` as the only route in. So a paper the
catalog does not name cannot be reached at all: the catalog is both the
index and the access list.

That was fine at fifteen papers. It does not survive the whole bibliography.

## Decision

**Scope: papers a principal investigator authored.** A PubMed harvest of all
eleven people associated with the group returns 500 unique papers, but the
group is defined by its two PIs. Keeping only papers with Kholodenko or
Rukhlenko on them yields **210** (1972–2026). The 290 dropped are almost all
Walter Kolch's solo work — he is SBI's director and a constant co-author, but
his own body of work is not this group's, and the group's own reference
document says as much. The junior members add almost nothing distinct on
their own (Borodin 0 group papers on PubMed, Carmody 1, Nemati 3); the two
PIs are the corpus.

**Depth: full text where a publisher releases it.** 94 of the 210 are open
access in PubMed Central; 53 of those return usable structured XML (the rest
are publisher-restricted or scanned). PMC full text is cleaner than the PDF
path — JATS marks up sections and the reference list, so there is no page
furniture to strip and no equations fragmented into single glyphs. The
remaining ~150 papers are title and abstract; 17 of the oldest have no
abstract in PubMed at all and are title-only.

**Shape: a two-tier catalog.** Injecting 210 abstracts costs about 66k tokens
on *every* injected call, and the catalog rides `run_setup_guidance` into
every tournament comparison, which is roughly quadratic in the hypothesis
count. So:

| Tier | Count | In the injected catalog |
|---|---|---|
| Core | 15 | Title + full abstract |
| Rest | 195 | One line: title, year, `paper_id` |

The core are the flagship methods and findings (MRA, cSTAR, the drug-
resistance work) whose substance bears on almost any hypothesis in the
group's field. The rest are named — not summarised — because `fetch_paper` is
the only way in and the catalog is the only place a `paper_id` is advertised,
so a title index is the minimum that keeps all 210 reachable. This costs
about 14k tokens per call against 66k for full injection.

This is a middle path between the two the earlier ADR set up. That ADR first
tiered the audience context by call frequency, then a later change reversed it
and injects the group's full 19k-token reference document on every call,
valuing fidelity over token cost. The abstract catalog is too large to follow
that all the way (66k dwarfs the 19k document and lands on quadratic calls),
so it keeps the core in full and indexes the tail.

**Correcting attribution.** Three of the fifteen committed papers are not the
group's own work: two are Borg, Colinge and Ravel's independent papers on the
*limits* of Modular Response Analysis — the group's signature method — and one
is Imoto's work from before he joined. The old catalog prompt called all
fifteen "the group's own papers", which for the Borg pair presented a critique
of the method as the group's own finding. Entries now carry an `attribution`
(`group`, `external`, `member prior work`) and the injected catalog labels the
non-group ones so the model credits their real authors.

## Build tooling

The corpus is committed in full, but two committed dev scripts reproduce and
extend it:

- `dev/harvest_group_pubmed.py` — searches PubMed per member (common surnames
  intersected with an institutional clause so "Robertson S" does not return
  2,973 unrelated authors), keeps PI-authored papers, drops errata and
  superseded preprints, pulls PMC full text, and writes one markdown file per
  paper. Adding the next member is one line in its `MEMBERS` list.
- `dev/build_catalog.py` — rebuilds `catalog.json`. It holds the 15
  hand-verified core abstracts inline (their PDF-extracted `.md` files carry
  no clean abstract to parse) and reads every other paper's metadata back out
  of its harvested header, so there is one source of truth per paper. It
  refuses to write if the catalog and the corpus directory disagree in either
  direction.

## Constraints carried forward

The corpus stays committed in full and audience-gated to `sbi_ucd`; an absent
or partial corpus is not an error. Text only, never PDF binary. These are
unchanged from the earlier ADR.

## What this does not do

No search over the corpus was added. With a title index every paper is
reachable, so search is an optimisation (cheaper injection, fuzzy discovery),
not a correctness fix. The `CorpusRetriever` seam already exists in
`app/app/run_corpus.py`; wiring a keyword search over the corpus files behind
a new MCP tool, and shrinking the injected catalog back toward the core, is a
clean follow-up if the injected index proves too heavy on tournament calls.

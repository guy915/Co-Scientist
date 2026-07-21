# Paper corpora

Sanitized full text and metadata of a research group's own papers, read by
the audience-gated corpus retriever.

The corpus is committed in full, so a clean checkout has working retrieval
with no setup and a deployment that ships the repository tree needs no extra
configuration.

An absent or partial corpus is still not an error. Retrieval returns nothing,
the MCP tool reports an empty result, and every surface falls back to its
previous behaviour.

## What is in `sbi_ucd/`

The Kholodenko/Rukhlenko group's bibliography: every PubMed paper with Boris
Kholodenko or Oleksii Rukhlenko as an author (210 papers, 1972–2026). Each is
one markdown file. About a quarter carry full text; the rest are title and
abstract, because their publishers release no machine-readable body.

`catalog.json` is the manifest the app reads. It is two-tier, because the
injected catalog rides into every tournament comparison and ranking is
roughly quadratic in the hypothesis count:

- **Core papers** (15) carry their abstract into the run's context. These are
  the group's flagship methods and findings, hand-curated from PDFs.
- **The rest** (195) appear as a one-line title index — enough for the model
  to recognise a paper and read it in full with `fetch_paper(paper_id)`.

Injecting every abstract would cost about 66k tokens per call; the two-tier
arrangement costs about 14k. See `app/app/paper_corpus.py` for the renderer
and `docs/decisions/2026-07-21-group-bibliography-corpus.md` for the rationale.

A few catalog entries carry an `attribution` other than `group` (`external`,
`member prior work`): they sit in the corpus for context but are not the
group's own findings, and the injected catalog labels them so they are not
miscredited.

## Building the corpus

Two paths write markdown files into `sbi_ucd/`; run `build_catalog.py` after
either to rebuild the manifest.

**From PubMed (the bulk of the corpus).**

```bash
python app/dev/harvest_group_pubmed.py
python app/dev/build_catalog.py
```

`harvest_group_pubmed.py` searches PubMed for each group member, keeps the
papers a PI actually authored, drops errata and superseded preprints, pulls
PubMed Central full text where the publisher releases it, and writes one file
per paper. Add a new member to its `MEMBERS` list to extend the corpus. It
never overwrites the hand-curated core files.

**From PDFs (the hand-curated core).**

```bash
cd app
python dev/corpus_ingest.py /path/to/Papers --out ../corpus/sbi_ucd
```

Requires `pdftotext` (`brew install poppler`). Subdirectories of the source
are skipped, so an `External Papers` folder alongside the group's own work is
left out. The step extracts each PDF, strips references, back matter,
repeated page furniture, and fragmented figure/equation glyphs, then writes
one markdown file per paper. Expect roughly a third of the raw extraction to
be discarded; read a few outputs before trusting them.

**Rebuilding the manifest.** `build_catalog.py` reads the 15 hand-verified
core abstracts (inline, checked against the publisher PDFs) plus the metadata
in each harvested file's header, and refuses to write if the catalog and the
corpus directory disagree in either direction — a file with no entry, or an
entry with no file.

## Where it is read

| Consumer | Path | Configuration |
|---|---|---|
| Chat Q&A and run planning | `app/app/paper_corpus.py` | `SBI_CORPUS_DIR`, default `corpus/sbi_ucd` |
| `fetch_paper` MCP tool | `engine/mcp_server/tools/lit_review/` | `SBI_CORPUS_DIR`, no default |

The MCP server has no default because it is deployed separately: point
`SBI_CORPUS_DIR` at a mounted copy, or the tool stays inert. The corpus is
reached only by `fetch_paper(paper_id)`; there is no search over it, so the
catalog must name every paper for it to be reachable.

## Adding another group's corpus

Retrieval is gated on the audience so one group's library is never served to
another. To add a second corpus, write it to its own subdirectory and extend
`CORPUS_AUDIENCE` in `app/app/paper_corpus.py` into an audience-to-directory
mapping.

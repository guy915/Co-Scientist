# Paper corpora

Sanitized full text of a research group's own papers, searched by the
audience-gated corpus retriever.

The corpus is committed in full, so a clean checkout has working retrieval
with no setup and a deployment that ships the repository tree needs no extra
configuration.

An absent or partial corpus is still not an error. Retrieval returns nothing,
the MCP tool reports an empty result, and every surface falls back to its
previous behaviour.

## Building the SBI/UCD corpus

```bash
cd app
python -m app.corpus_ingest /path/to/Papers --out ../corpus/sbi_ucd
```

Requires `pdftotext` (`brew install poppler`). Subdirectories of the source
are skipped, so an `External Papers` folder alongside the group's own work is
left out. The step extracts each PDF, strips references, back matter,
repeated page furniture, and fragmented figure/equation glyphs, then writes
one markdown file per paper with the title as an `# ` heading.

Expect roughly a third of the raw extraction to be discarded. Read a few
outputs before trusting them: `pdftotext` handles body prose well but
fragments equations, and papers whose bibliography is not detected keep an
unusually high share of their characters.

## Where it is read

| Consumer | Path | Configuration |
|---|---|---|
| Chat Q&A and run planning | `app/app/paper_corpus.py` | `SBI_CORPUS_DIR`, default `corpus/sbi_ucd` |
| `search_paper_corpus` MCP tool | `engine/mcp_server/tools/lit_review/` | `SBI_CORPUS_DIR`, no default |

The MCP server has no default because it is deployed separately: point
`SBI_CORPUS_DIR` at a mounted copy, or the tool stays inert.

## Adding another group's corpus

Retrieval is gated on the audience so one group's library is never served to
another. To add a second corpus, write it to its own subdirectory and extend
`CORPUS_AUDIENCE` in `app/app/paper_corpus.py` into an audience-to-directory
mapping.

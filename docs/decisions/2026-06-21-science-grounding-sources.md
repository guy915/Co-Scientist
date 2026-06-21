# ADR: Science grounding sources (OpenAlex + catalog)

**Status:** Accepted · 2026-06-21
**Drains reference:** `references/peripheral/antigravity-science-skills/`

Records what we take from the Antigravity science-skills bundle (Google
DeepMind) — a collection of ~36 skills wrapping science databases (PubMed,
ChEMBL, UniProt, Ensembl, ClinicalTrials, AlphaFold, OpenAlex, bioRxiv,
Reactome, STRING, gnomAD, …). Stands alone so the bundle can be deleted.

## Context

The co-scientist grounds hypotheses through a **YAML-driven MCP tools layer**:
`config/tools.yaml` declares tools (field/parameter mappings) that resolve to
tools on an MCP server; the reference server exposes PubMed search/fulltext and
INDRA CoGex knowledge-graph tools. A new grounding source = an MCP server tool
+ a YAML config entry + workflow wiring.

The Antigravity skills are **not portable** to this layer. They are
Claude-skill format — prose `SKILL.md` + `uv`-run Python CLIs with file-based
JSON I/O — with no typed tool manifest. Each would need bespoke
reverse-engineering into an MCP tool (the bundle's own estimate: 2–12 h each).
Porting all 36 is out of scope, and **Co-Scientist is the main character**: we
want grounding breadth that serves hypothesis generation, not 36 integrations.

## Decisions

1. **Do not port the skills wholesale.** The format is incompatible and the
   volume is out of scope. The bundle's value is its *catalog* of grounding
   sources, captured below.

2. **Build the single highest-leverage source: OpenAlex.** It is broad
   (all-field, not just biomedicine — matching the co-scientist's
   general-purpose nature), needs **no API key**, and fits the existing
   search-tool pattern cleanly. (Built; see below.)

3. **Record the rest as a grounding-source roadmap** (catalog below) — future
   MCP tools following the OpenAlex pattern, prioritized by grounding value.

## What was built

- **OpenAlex MCP tool**: `engine/mcp_server/tools/lit_review/openalex_search.py`
  (`search_openalex`, httpx, self-contained; reconstructs OpenAlex's inverted-
  index abstracts; degrades to `{}` on any transport error). Registered in
  `mcp_server/server.py`.
- **YAML config**: `engine/src/co_scientist/config/examples/openalex_grounding.yaml`
  wires a **multi-source** literature review (PubMed fulltext + OpenAlex). Point
  the engine at it via `TOOLS_CONFIG`.
- **Tests**: `engine/mcp_server/tests/test_openalex.py` (6 tests: normalization,
  abstract reconstruction, capping, garbage tolerance, mocked search, graceful
  HTTP-error degradation). mcp_server mypy clean; engine registry loads the
  config as a verified multi-source workflow.

Verification note: end-to-end live grounding requires the reference MCP server
running (a separate Python 3.12 service); it is unit-tested + config-load
verified here rather than exercised against the live OpenAlex API.

## Grounding-source roadmap (catalog)

High-value sources from the bundle, by grounding type, as future MCP tools:

| Source | Type | Value | Notes |
| --- | --- | --- | --- |
| PubMed / PMC | Literature | built | already in the reference MCP server |
| INDRA CoGex | Mechanisms / KG | built | gene-disease, pathways, statements |
| **OpenAlex** | Literature (all-field) | **built (this ADR)** | no key |
| bioRxiv / medRxiv | Preprints | high | cutting-edge, no key |
| Europe PMC | Literature | medium | OA fulltext |
| ChEMBL | Chemistry (bioactivity) | high | IC50/Ki/mechanism; distinct modality |
| UniProt | Protein metadata | high | annotations, ID mapping |
| Ensembl | Genomics (variant→consequence) | high | VEP |
| Reactome | Pathways | high | mechanistic enrichment |
| Open Targets | Target–disease | high | drug-target evidence |
| gnomAD | Population genetics | high | variant constraint |
| ClinicalTrials.gov | Clinical | medium | trial landscape |

## Consequences

- The co-scientist gains a broad, no-key literature source (OpenAlex) and a
  documented roadmap for richer science grounding.
- The Antigravity bundle can be deleted at cleanup; this ADR preserves its
  actionable catalog.
- Adding the next source (e.g. ChEMBL or bioRxiv) follows the OpenAlex pattern:
  MCP tool + YAML entry + workflow wiring + tests.

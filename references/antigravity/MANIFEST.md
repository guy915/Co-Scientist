# MANIFEST — Antigravity Science Skills

What the vendored bundle contains, and what of it this repository already has.

## Provenance

| | |
| --- | --- |
| Upstream | [`google-deepmind/science-skills`](https://github.com/google-deepmind/science-skills) |
| Pinned revision | `0b42509800f49e6eb7809505d96e20a890ef99bd` (2026-07-07) |
| Release | plugin `science` v1.1.0 |
| Vendored at | `vendor/science-skills/` |
| Size | 234 files, 3.6 MB |
| Licence | Apache-2.0 (code), CC-BY 4.0 (non-software material) |

Re-pin with:

```bash
git clone --depth 1 https://github.com/google-deepmind/science-skills vendor/science-skills && \
  git -C vendor/science-skills fetch --depth 1 origin <sha> && \
  git -C vendor/science-skills checkout <sha> && rm -rf vendor/science-skills/.git
```

**The tree is never reformatted.** A repo-root `ruff format` sweep in commit
`5821d4fc` rewrote 63 files of the earlier reference copy as a side effect of
an unrelated change, which is how a tree pinned to an upstream revision
silently stops matching it. The root `.ruff.toml` now excludes `vendor/` and
`references/` for exactly that reason, and the copy vendored here was taken
fresh from upstream rather than moved from the reformatted one.

## What changed between v1.0.4 and v1.1.0

The reference copy examined at stage 1 was v1.0.4. Three differences matter:

- **`scienceskillscommon` is gone.** The shared stdlib-only HTTP client with
  cross-process `fcntl` rate limiting no longer ships in the repository; it
  was extracted to the PyPI package **`polite-http`**, which 51 scripts now
  import. `fcntl` appears in zero skills.
- **Dependencies are declared, not vendored.** 63 scripts carry PEP 723 inline
  metadata (`# /// script`) naming packages `uv run` resolves at execution
  time: `polite-http` (51), `python-dotenv` (14), `alphagenome` (6), `pandas`
  (5), `numpy` (3), and one each of `jax`, `pyarrow`, `matplotlib`,
  `predictingthepast`. **The bundle alone is therefore not a runnable
  artifact** — the dependency closure is part of what has to be shipped. See
  `Dockerfile.api` for how that closure is resolved and why `uv run` itself
  cannot be used inside the sandbox.
- **Two new skills.** `credentials` defines a protocol for checking whether an
  API key is present *without reading its value into the agent's context*, and
  `predictingthepast` wraps Aeneas/Ithaca for ancient-text restoration — the
  first skill in the bundle outside the life sciences.

## Shape of the bundle

38 directories under `skills/`:

- **35 science skills** — the table below.
- **2 infrastructure skills** — `uv` (checks for and installs the `uv` package
  manager, which every other skill's instructions name as a prerequisite) and
  `credentials` (the safe key-handling protocol above).
- **1 meta-skill** — `workflow_skill_creator`, which distils a completed
  interaction into a new skill. Analysed in
  [`_analysis/science-skills.md`](_analysis/science-skills.md).

Each skill directory is `SKILL.md` + optional `scripts/` + optional
`references/`. The frontmatter carries exactly two keys, `name` and
`description`; everything else is prose.

**`SKILL_LICENSES.md` is a separate obligation from the code licence.** It maps
each skill to the terms of use of the *data source* it queries — 35 rows, and
UniProt, gnomAD, GTEx, HPA, Open Targets, Reactome and openFDA each publish
their own. Some skills enforce it themselves: `uniprot_database` will not
proceed until it has told the user to check the UniProt licence terms and
written a `LICENSE_NOTIFICATION.txt` recording that it did. Apache-2.0 says
nothing about the data behind the endpoint.

## Coverage against this repository

"Covered" means an engine tool id in
`engine/src/co_scientist/config/tools.yaml` backed by a tool in `_MCP_TOOLS`
(`engine/mcp_server/server.py`). "Reachable" means that tool is also declared
in the **default** `tools.yaml` rather than only in a `config/examples/` pack —
the distinction matters because production does not set `TOOLS_CONFIG`.

| Skill | Domain | Covered here | By what |
| --- | --- | --- | --- |
| `pubmed_database` | Literature | yes, reachable | `pubmed_search`, `pubmed_fulltext` → `search_pubmed`, `pubmed_search_with_fulltext` |
| `literature_search_openalex` | Literature | yes, reachable | `openalex_search` → `search_openalex` |
| `chembl_database` | Chemistry | yes, reachable | `chembl_search` → `search_chembl` |
| `uniprot_database` | Proteins | yes, reachable | `uniprot_search` → `search_uniprot` |
| `literature_search_europepmc` | Literature | partial | PMC full text arrives through `pubmed_search_with_fulltext`; Europe PMC's own search, citation lists and OA PDF route do not exist |
| `reactome_database` | Pathways | partial, unreachable | INDRA `query_pathways`, `run_enrichment_analysis` — a knowledge-graph view, not Reactome's Analysis Service; declared only in `config/examples/indra_*.yaml` |
| `string_database` | Networks | partial, unreachable | INDRA `query_mechanistic_statements`, `query_causal_subnetwork` — different provenance model (literature-mined statements vs STRING confidence channels) |
| `opentargets_database` | Target–disease | partial, unreachable | INDRA `query_gene_disease_network`, `query_drug_info` |
| `clinical_trials_database` | Clinical | partial, unreachable | INDRA `query_clinical_trials` — a KG projection, not the ClinicalTrials.gov APIv2 |
| `literature_search_arxiv` | Literature | no | `config/examples/arxiv_*.yaml` declare `search_arxiv`, but no such tool is registered — see the caution below |
| `literature_search_biorxiv` | Preprints | no | on the 2026-06-21 ADR roadmap, unbuilt |
| `ensembl_database` | Genomics | no | on the ADR roadmap, unbuilt |
| `gnomad_database` | Population genetics | no | on the ADR roadmap, unbuilt |
| `alphafold_database_fetch_and_analyze` | Structure | no | deliberately excluded — fidelity finding G13 |
| `alphagenome_single_variant_analysis` | Regulatory variants | no | needs `ALPHAGENOME_API_KEY` |
| `clinvar_database` | Clinical variants | no | |
| `dbsnp_database` | Variants | no | |
| `gtex_database` | Expression | no | |
| `encode_ccres_database` | Regulatory elements | no | |
| `jaspar_database` | TF motifs | no | |
| `unibind_database` | TF binding sites | no | |
| `ucsc_conservation_and_tfbs` | Conservation | no | |
| `human_protein_atlas_database` | Protein expression | no | |
| `interpro_database` | Protein domains | no | |
| `pdb_database` | Structure | no | |
| `foldseek_structural_search` | Structure search | no | needs a coordinate file as input |
| `protein_sequence_similarity_search` | Homology | no | MMseqs2 / BLAST |
| `protein_sequence_msa` | Alignment | no | EBI Clustal Omega |
| `pymol` | Visualisation | no | the only science skill with no scripts — pure instruction |
| `predictingthepast` | Ancient texts | no | new in v1.1.0; needs `jax`, outside the baked closure |
| `ncbi_sequence_fetch` | Sequences | no | |
| `pubchem_database` | Chemistry | no | |
| `openfda_database` | Regulatory | no | 28 endpoints |
| `quickgo_database` | Ontology | no | |
| `embl_ebi_ols` | Ontology | no | 250+ ontologies |

Tally over the 35 science skills: **4 covered and reachable, 5 partial (4 of
those unreachable by default), 26 absent.**

## Caution carried forward

`config/examples/` already declares tools the reference server does not
register — `search_arxiv`, `google_scholar_search`, `search_nvd_cves`,
`read_pdf`, `find_pdf_links`, `analyze_pdf_for_research`,
`generate_queries_hypotheses`. A config naming a missing tool is reconciled
away silently at registry load (`registry._apply_disabled_tools`), so those
packs run with fewer sources than they read as declaring. Any source added
from this bundle lands in the **default** `tools.yaml`, or it is shelfware in
the same way.

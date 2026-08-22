# MANIFEST — Antigravity Science Skills

What is in `references/peripheral/antigravity-science-skills/`, and what of it
this repository already has.

Source: [`google-deepmind/science-skills`](https://github.com/google-deepmind/science-skills),
plugin `science` v1.0.4, cloned verbatim. 192 files, 3.1 MB, ~19.5k lines of
Python across the skill scripts.

Unlike the deep-research clones, this tree is **committed** (all 192 files are
tracked). Two provenance facts to carry:

- **The clone has no `LICENSE` file.** `SKILL_LICENSES.md` is not a code
  licence — it maps each skill to the terms of use of the *data source* it
  queries, 34 rows of them (UniProt, gnomAD, GTEx, HPA, Open Targets, Reactome
  and openFDA each publish their own). Reusing any skill's code means
  establishing the upstream code licence first; reusing any skill's *source*
  means reading that row.
- **Some skills enforce attribution themselves.** `uniprot_database` will not
  proceed until it has told the user to check the UniProt licence terms and
  written a `LICENSE_NOTIFICATION.txt` recording that it did, and requires the
  attribution to appear in the first response containing UniProt data. Any
  port inherits that obligation; it does not travel with the endpoint URL.

## Shape of the bundle

37 directories under `skills/`:

- **34 science skills** — the table below.
- **2 infrastructure skills** — `uv` (checks for and installs the `uv` package
  manager; every other skill declares it as a prerequisite) and
  `scienceskillscommon` (a shared stdlib-only HTTP client; explicitly "not a
  standalone agent skill, do not invoke directly").
- **1 meta-skill** — `workflow_skill_creator`, which distils a completed
  interaction into a new skill. Analysed in
  [`_analysis/science-skills.md`](_analysis/science-skills.md).

Each skill directory is `SKILL.md` + optional `scripts/` + optional
`references/`. The frontmatter carries exactly two keys, `name` and
`description`; everything else is prose.

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
| `pymol` | Visualisation | no | the only skill with no scripts — pure instruction |
| `ncbi_sequence_fetch` | Sequences | no | |
| `pubchem_database` | Chemistry | no | |
| `openfda_database` | Regulatory | no | 28 endpoints |
| `quickgo_database` | Ontology | no | |
| `embl_ebi_ols` | Ontology | no | 250+ ontologies |

Tally: **4 covered and reachable, 5 partial (4 of those unreachable by
default), 25 absent.**

## Caution carried forward

`config/examples/` already declares tools the reference server does not
register — `search_arxiv`, `google_scholar_search`, `search_nvd_cves`,
`read_pdf`, `find_pdf_links`, `analyze_pdf_for_research`,
`generate_queries_hypotheses`. A config naming a missing tool is reconciled
away silently at registry load (`registry._apply_disabled_tools`), so those
packs run with fewer sources than they read as declaring. Any source added
from this bundle lands in the **default** `tools.yaml`, or it is shelfware in
the same way.

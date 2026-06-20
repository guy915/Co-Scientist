# 06 — Retrieval, Grounding, and Verification

> **Purpose.** The scientific-grounding backbone: which databases to query and how (rate limits, MCP), hybrid search, the knowledge/evidence graph layer, the multi-stage citation-verification engine, evidence grading (GRADE), novelty/overclaiming detection, contradiction handling, and the safety/biosecurity pipeline. *Agent roles* in file `04`; *evaluation rubrics* in file `05`.
>
> Consolidates: `Scientific_Retrieval_and_Verification_Layer_Architecture.md`, `Knowledge_and_Evidence_Graph_Layer_Architecture.md`, `Systems_Design_Multi-Agent_Orchestration_and_Claim_Verification.md`, and the grounding/safety sections of `Interactive_Multi-Agent...`, `Context_Engineering_Spec...`, `Distributed_Multi-Agent_Discovery_Harness...`, `Technical_Analysis...`.

> **Design principle.** A scientific discovery platform must prioritize **factual precision and biological safety over creative, ungrounded generation**, and allocate the *majority* of compute to verification. Grounded data is injected directly into generation prompts so every candidate is anchored in empirical evidence.

---

## 1. Bibliographic / scholarly sources

| Database | Content | Use-case | Access & rate limits | Integration strategy |
|---|---|---|---|---|
| **PubMed / MEDLINE** | 40M+ biomedical citations | MeSH-expanded search, PMID validation | E-utilities REST; **3 req/s unkeyed, 10 keyed**; requires email header | `ESearch`→MeSH expand, `EFetch`→abstracts, `ESpell`→spelling |
| **Europe PMC** | 40M+ (PubMed + patents + agri) | full-text JATS XML, text-mined entities | open REST; no key; ~30 req/min heavy | `/textMinedTerms` for chemical-protein associations; preprint aggregation (30+ servers) |
| **Semantic Scholar** | 200M+ STEM | citation tracing, SPECTER embeddings | Graph REST; free key; 1 req/s; batch endpoints | `/paper/batch`, `/recommendations`, 768-d SPECTER vectors |
| **OpenAlex** | 250M+ scholarly works | proximity search, high-volume filtering | freemium REST; keyed 100 req/s | 8KB proximity queries, quarterly snapshots |
| **Crossref** | 180M+ DOIs | DOI resolution, retraction status | open REST; no key; 50 req/s polite pool | `mailto` header → polite pool; `/works/{doi}` |

**Preprints (bioRxiv / medRxiv):** essential in fast fields (AMR, viral epidemiology) where peer review lags ~160–178 days. Concordance is high (96.2% identical interpretations, 97.6% concordant endpoints) but ~13.6% show sample-size changes and ~18.9% numeric outcome differences during review. Strategy: **dual-stream extraction** → **version/peer-review tracking** (match preprint to published pair via Europe PMC daily; import Sciety / Early Evidence Base evaluations) → **claim verification on discrepancies** (Reflection prioritizes the journal article; flag "mutated during peer-review" and lower confidence).

---

## 2. Chemical / structural / pathway sources

| Database | Content | Use-case | Access | Integration |
|---|---|---|---|---|
| **ChEMBL** | small-molecule structures, target affinities, IC50/Ki, ADME | compound bioactivity, target validation | REST or DB download; **1 req/s** | high-throughput SQL on a **local SQLite mirror**; reserve API for small lookups |
| **UniProt** | curated protein sequences, annotations, taxonomy | gene→protein mapping, motifs | REST + bulk TSV; `rest.uniprot.org/uniprotkb/search` | query by gene/accession; UniProt accessions key into AFDB |
| **AlphaFold DB** | 200M+ predicted 3D structures | models for uncharacterized proteins | REST/FTP/BigQuery | parse pLDDT (B-factor field); mmCIF/bCIF/PDB |
| **RCSB PDB** | experimental macromolecular structures | experimental structures, binding pockets | REST/GraphQL | concurrency 3–5 (429 under load) |

Pathway/systems: **Reactome** (pathways/reactions), **KEGG** (metabolic), **Gene Ontology + NCBI Gene** (functional annotation), **ClinicalTrials.gov** (translational/clinical validation). Structural confidence: $\text{pLDDT}\in[0,100]$; >90 highly reliable backbone, <50 disordered/ungrounded.

### Deterministic identifier validation (ingestion layer)
LLMs transpose characters in molecular formats — validate deterministically:
- **Chemicals:** verify SMILES via **RDKit** → canonical form, InChIKey, MW, Lipinski Rule of 5.
- **Proteins/genes:** validate amino-acid chains via **Biopython** → sequence integrity, isoelectric point, stability.
- **Trials/patents:** regex-match NCT numbers / patent registrations against registries.

### Cross-referencing pipeline
Gene symbol → (HGNC) → UniProt accession → (key) → AlphaFold structure + ChEMBL bioactivity, with deterministic ID resolution at each hop (the consolidated database-lookup skill in file `03` performs this routing).

---

## 3. Hybrid search + multi-hop retrieval

### Two-stage hybrid index
Vector chunks alone lack precision for scientific identifiers. Combine **lexical (BM25/tsvector)** for exact matches (PMIDs, gene symbols, chemical codes) with **semantic (SPECTER/dense)** for conceptual alignment, fused via **Reciprocal Rank Fusion (RRF, k=60)**:

```text
Query → ┌ Lexical (exact match) ┐
        ├ Semantic (SPECTER)    ┤ → RRF unified scoring → consolidated context → Agent core
        └ Text-to-SQL (struct.) ┘
```

For structured DBs, translate NL → Text-to-SQL against relational backends while concurrently vector-searching unstructured PDFs.

### Knowledge graphs for multi-hop
Model facts as typed triples $\mathcal{T}=(h,r,t)$ (head, relation, tail) to traverse relationships across papers. Use **Leiden community detection** to partition the graph into sub-domains for high-level summaries.

### Hierarchical Citation Graph ($G_C$)
Structure papers into three layers to keep context bounded:
$$\text{Layers}(G_C)=\{\text{Foundation (seminal)},\ \text{Development (methods)},\ \text{Frontier (emerging)}\}$$
Retrieval does **horizontal** search within a layer (related papers) and **vertical** traversal across layers (trace concept evolution), passing only multi-aspect summaries to generation agents.

### Pivot/Refine self-healing loop
On API failure (429, timeout, zero hits): parse the error, adjust params (ESpell typo fix, MeSH expansion), and retry.

---

## 4. The knowledge / evidence graph layer

### Evidence-centric schema
Collapsing literature into binary triples `(Drug, INHIBITS, Protein)` loses context. Make the **Evidence Node** the primary unit — an intermediate node carrying conditions (p-value, cohort, dose):

```text
Entity (Drug: Cetuximab) ─LINKED_TO→ Evidence (Trial: p=0.002, CRC cohort) ─LINKED_TO→ Entity (Protein: EGFR)
                                          │ SUPPORTS / CONTRADICTS
                                          ▼
                                     Other Evidence (In-vitro lab)
```

### Node classes (ontology-grounded)
`Paper` (PubMed/Crossref), `Claim` (NL parser), `Gene` (HGNC), `Protein` (UniProt), `Pathway` (GO/Reactome), `Disease` (MedDRA/MeSH), `Drug` (ChEBI/ChEMBL/PubChem), `Assay` (BAO), `Mechanism` (GO Causal), `Hypothesis` (internal), `Critique` (internal), `Experiment` (Python runtime), `Evidence` (EvidenceNet). Relationships trace provenance: `(Paper)→(Claim)→(Evidence)→(Drug)→(Mechanism)→(Protein)`, `(Hypothesis)→(Claim)`, `(Critique)→(Hypothesis)`, `(Experiment)→(Hypothesis)`.

### Evidence strength, contradiction, novelty (math)

**Evidence strength** integrates statistical + bibliometric properties:
$$S_E(e)=w_1\ln(N_e)+w_2(-\log_{10}p_e)+w_3\ln(FC_e+1)+w_4\ln(IF_e+1)+w_5\ln(C_e+1)$$
($N$=sample size, $p$=p-value, $FC$=fold change, $IF$=impact factor, $C$=citation count; $w_i$ domain-normalized.)

**Logical contradiction** — write a hard `CONTRADICTS` edge when joint rules are unsatisfiable:
$$(A_1\land C_1)\land(A_2\land C_2)\models\text{unsat}$$

**Semantic contradiction (CO-GAT confidence masking)** — for context-dependent conflicts, compute a node confidence relative to hypothesis $H$ and mask low-confidence attention:
$$c_i=\sigma(\mathbf{W}_c[\mathbf{h}_i \parallel \mathbf{h}_H]),\qquad M_i=\begin{cases}1 & c_i\ge\tau\\0 & \text{otherwise}\end{cases}\;(\tau\approx0.70)$$
If $c_i<\tau$, $M_i=0$ severs attention updates, preventing contradictory information from propagating.

**Hypothesis novelty** — penalize popular paths, reward cross-domain links:
$$Pop(s,o)=\sum_{p\in P_{s\to o}}\prod_{e\in p}\frac{\text{Weight}(e)}{\sum_{e'}\text{Weight}(e')},\qquad
N(H)=-\log_{10}(Pop(s,o)+\epsilon)\cdot\big(1+\gamma\,\mathbb{I}[\text{Comm}(s)\ne\text{Comm}(o)]\big)$$
($P_{s\to o}$ = paths of length ≤3; communities via SLPA; $\gamma$ weights cross-domain; $\epsilon=10^{-6}$.)

### Hierarchical Markdown wiki memory
The graph is mirrored as a navigable Markdown wiki (per-target directories with supporting-evidence records and explicit "conflicting statements & contradictions" sections), giving a tri-level abstraction and human-auditable provenance.

---

## 5. The citation-verification engine

> **Motivation:** unguided LLM output has a **95.9% Type II citation hallucination rate** — citing real papers that don't support the claim.

### VaaS (Validation-as-a-System)
At report synthesis, parse all citations → query DBs for canonical metadata → run an **NLI model** scoring alignment between claim and retrieved abstract → reject if score < **0.85**, triggering a correction loop. Full VaaS reduces Type I + Type II errors to **0.0%**.

### DeepSciVerify two-stage pipeline (+ CiteGuard)

```text
Claim + citation → LLM parser (DOI/title/arXiv) → multi-source retrieval cascade (OpenAlex/PubMed/S2/Crossref)
  Phase 1 — Abstract-level verifier f_a → {SUPPORTS, CONTRADICTS, NEI}
     ├─ decisive → early exit (resolves 67% of tasks)
     └─ NEI → Phase 2 — full-text RAG (512-tok chunks, 32 overlap, SPECTER2 embed)
             → top-k passages → verifier f_p → final {SUPPORTS|CONTRADICTS|NEI}
             → isotonic-regression calibration to align with human judgment
```

**CiteGuard multi-dimensional axes:** **Link Works** (URL/HTTP validity), **Relevant Content** (LLM-judge topical alignment vs first 5000 chars), **Fact Check** (numerical/temporal/entity assertion verification).

### Tiered citation grounding (the clone's storage contract)
Maps to `citations.verification_tier` (file `03`): **tier1** external_id resolves → **tier2** title/authors fuzzy-match the claim → **tier3** snippet grounded in abstract via NLI. Fidelity target: ≥80% reach tier-2, ≥50% reach tier-3.

---

## 6. Research-integrity auditing (Retraction Watch)

Crossref **natively integrated Retraction Watch (Jan 2025)**. For each candidate DOI, `GET https://api.crossref.org/v1/works/{DOI}`; parse `updated-by`/`update-to`. The `source` field distinguishes `"publisher"` vs `"retraction-watch"`; `record-id` cross-references a local Retraction Watch CSV mirror for the reason.

**Deterministic claim-disposition state machine:**
- **YES (Verified)** — active, no retraction, semantically confirmed → approve + clickable link.
- **NO (Rejected)** — matches a retracted work → purge; **recursively invalidate all derivative claims** built on it; force Generation/Evolution to rebuild those branches with verified sources.
- **BORDERLINE (Warning)** — valid but secondary-source or minor metadata discrepancy → append a warning label, log it, route to human review.

---

## 7. Evidence grading (Pollock-GRADE) and novelty/overclaiming

### Algorithmic GRADE (URSE-style)
Initialize certainty: **High** for RCTs, **Low** for observational. Apply programmatic up/downgrades for I-C-O triads:

| Factor | Metric | Action |
|---|---|---|
| Imprecision | cumulative $n$ | −1 if $100\le n<1000$; −2 if $n<100$ |
| Risk of bias | % in low-risk trials | −1 if 30–75%; −2 if <30% |
| Inconsistency | heterogeneity $I^2$ | −1 if $30<I^2<75$; −2 if $\ge75$ |
| Methodology | AMSTAR % | −1 if 3/4; −2 if ≤2/4 |
| Indirectness | population similarity | −1 surrogate outcomes; −2 extreme drift |

Upgrades (observational): large effect (RR>2 or <0.5 → +1; >5 or <0.2 → +2), dose-response (+1), confounding inversion (+1). The sum sets certainty → modulates recommendation strength (strong vs weak) in the Goal Report.

### Feature-level novelty / overclaiming detection (OpenNovelty / PANORAMA)
Move beyond cosine similarity. **(I)** decompose hypothesis into independent features → patent/NPL queries; **(II)** high-coverage retrieval (170M+ patents, 220M+ literature); **(III)** feature-level overlap mapping — **Full (Red)** explicitly disclosed, **Partial (Yellow)** present but different mechanism/host/environment, **None (Green)** absent; **(IV)** novelty = Green / Total features, with per-feature justifications.

### Epistemic uncertainty taxonomy
Every claim is classified **Established Fact / Plausible Inference / Theoretical Speculation / Proposed Experiment** with mandated phrasing per level (file `08`).

---

## 8. Temporal staleness & contradiction reconciliation

Knowledge is dynamic — once-valid findings get superseded. The **ReSSERAct**-style typed hybrid state treats freshness and contradictions as first-class control variables, with state $S_t=(b_t, L_t)$ (belief + ledger) so the system can reconcile stale/conflicting evidence rather than silently averaging it. *(Discovery heuristics for exploiting contradictions are in file `05`.)*

---

## 9. Safety, biosecurity, and dual-use enforcement

A multi-layered safety pipeline runs throughout the lifecycle (the Safety agent, file `04`):

1. **Adversarial input filtering (scoping)** — audit the user goal against a catalog of prohibited domains (CBRN threat profiles); immediately reject dual-use/hazardous pathways.
2. **Planner–Talker safety isolation (generation/evolution)** — a dual-agent architecture (clinical-grade): a background **Planner/Guardian** continuously monitors the active **Talker** agent's outputs and DB requests. If the agent begins drafting hazardous-compound synthesis or restricted biological protocols, the guardian **overrides the Supervisor state, halts execution, and records the block in the Git audit history**.
3. **Observation-based review (reflection)** — hypotheses are evaluated for safety hazards; risky proposals are flagged and require additional safety justification before proceeding.

Classifiers: a fast **pre-classifier** (fastText CBRN keyword/topic gate) + an LLM-as-judge **post-classifier** with WMDP-style probes; sanitization tiers L1/L2/L3; full audit log. Fidelity target: **100% rejection** on CBRN/hazardous queries, with benign biology false-positive rate ≤5% (file `09`).

> **Note for this clone's build context:** the development models used (e.g. Mythos-class) themselves fall back to a safer model on cyber/bio/chem prompts. The platform's *own* safety layer is still required and independent of model-level safeguards.

---

## 10. Architectural recommendations (retrieval layer)

Structure the retrieval layer as a **modular, resilient** design: MCP servers per source (local mirrors for rate-limited DBs like ChEMBL), hybrid lexical+semantic index with RRF, an evidence-centric knowledge graph for multi-hop reasoning and provenance, deterministic ID validation at ingestion, and the VaaS/DeepSciVerify + Retraction Watch verification stack gating every claim before it enters the tournament or the final report.

# Technical Architecture and Design Specification for the Knowledge and Evidence Graph Layer of an AI Co-Scientist System

## Unified Platform Architecture and Relational-Vector-Graph Integration

Implementing a highly capable, multi-agent scientific hypothesis-generation and experiment simulation system requires moving away from traditional single-model reasoning architectures. High-throughput biological data, unstructured medical literature, and clinical metadata are fundamentally fragmented, inconsistent, and prone to rapid conceptual evolution. Simple semantic similarity searches using dense vector representations fail to capture the multi-hop relational dependencies, strict clinical boundaries, and causal biological pathways that define genuine scientific discovery.

To overcome these limitations, the platform utilizes a multi-representational storage and retrieval architecture. This framework integrates a relational database for structured metadata, a vector database for semantic chunk retrieval, and a graph database to map complex multi-hop scientific associations.

```
                 +--------------------------------------------------+
                 |               Supervisor Agent                   |
                 |       (LangGraph Adaptive Planner / Orchestrator) |
                 +----------------+-----------------+
                                                  |
                         +------------------------+------------------------+
                         |                                                 |
                         v                                                 v
        +----------------+----------------+               +----------------+----------------+
        |     Retrieval & Grounding Agents |               |      Hypothesis Ranking Agents  |
        +----------------+----------------+               +----------------+----------------+
                         |                                                 |
                         | (Hybrid Retrieval)                              | (Elo debates / pairwise)
                         v                                                 v
+--------------------------------------------------+     +--------------------------------------------------+
|           Multi-Representational Storage         |     |             Tournament Engine                    |
|                                                  |     |                                                  |
|  +------------------+      +------------------+  |     |  +------------------+      +------------------+  |
|  |  Relational DB   |      |   Vector DB      |  |     |  | Proximity Agent  |      |  Ranking Agent   |  |
|  |  (PostgreSQL)    |      |   (pgVector)     |  |     |  | (Clustering/     |      |  (Multi-Turn     |  |
|  |  - Study design  |      |   - Chunk-level  |  |     |  |  Diversity)      |      |   Elo Debates)   |  |
|  |  - Bibliometrics |      |     embeddings   |  |     |  +--------+---------+      +--------+---------+  |
|  +--------+---------+      +--------+---------+  |     |           |                             |            |
|           |                         |            |     |           +--------------+--------------+            |
|           +------------+------------+            |     |                          |                               |
|                        |                         |     |                          v                               |
|                        v                         |     |              +-----------+-----------+                   |
|              +---------+---------+               |     |              |    Evolution Agent    |                   |
|              |    Neo4j /        |               |     |              | (Iterative Refinement)|                   |
|              |    Memgraph       |               |     |              +-----------------------+                   |
|              |  (Knowledge Graph)|               |     +--------------------------------------------------+
|              +-------------------+               |
+--------------------------------------------------+
```

The coordination of these database layers is managed by an orchestration framework utilizing a "retrieval-first" generation policy. The supervisor agent dynamically translates natural language scientific inquiries into coordinated sub-queries across all three storage layers. The relational layer filters publications by study design metadata and bibliometric indices. Concurrently, the vector layer retrieves candidate text chunks via embedding similarity, while the graph layer traverses relational paths to enforce structured biological constraints.

By merging these streams, the generation agent can construct highly grounded prompts that prevent hallucination and maintain absolute contextual accuracy during the hypothesis creation cycle.

|**Storage Domain**|**Database Implementation**|**Primary Representation Schema**|**Primary System Function**|**Inter-Database Synchronization Linkages**|
|---|---|---|---|---|
|**Relational Metadata**|PostgreSQL (`co_scientist.db`)|Relational tables, Foreign Key integrity constraints|Stores execution run statistics, user configuration files, study design categories, and publication metadata (PMIDs, DOIs, impact factors).|Graph nodes contain foreign-key references (`pmid`, `study_id`) linking directly to relational metadata rows to facilitate fast transactional lookups.|
|**Semantic Embeddings**|`pgVector` extension in PostgreSQL|Dense float vector embeddings, Hierarchical Navigable Small World (HNSW) indices|Conducts high-performance cosine similarity searches across chunked literature abstracts, clinical trials, and full-text scientific papers.|Vector identifiers are stored as property parameters on corresponding Evidence and Text Chunk nodes in the graph database.|
|**Relational Topology**|Neo4j / Memgraph|Labeled Property Graphs, declarative Cypher syntax|Tracks biological pathways, multi-hop mechanisms, disease phenotypes, trial design structures, and evidence dependencies.|Graph nodes represent normalized biological entities and evidence records, pointing to text passages and vectors in the other layers.|

The platform organizes its computing budget into distinct run configurations to support different stages of research. Standard runs optimize resource usage for initial scoping, while Advanced runs scale processing power to perform deeper graph explorations and larger pairwise tournaments.

|**Operational Run Dimension**|**Standard Run Configuration**|**Advanced Run Configuration**|
|---|---|---|
|**Primary Computational Focus**|Rapid ideation, initial scoping, and broad conceptual mapping.|Exhaustive hypothesis generation, deep verification, and multi-turn tournaments.|
|**Max Graph Traversal Depth**|Cap-limited to $2$ hops from seed entities to avoid path explosion.|Dynamic scaling up to $4$ hops to trace distant biological mechanisms.|
|**Tournament Strategy**|Localized pairwise debates, lower candidate count ($N \le 8$).|Full-scale Elo tournament, parallel debate engines ($N \ge 32$).|
|**Evolution Branching Factor**|Single-lineage mutation, simple hypothesis merging.|Multi-lineage branching, non-destructive parallel evolution.|
|**Verification Depth**|Basic literature cross-checking, surface-level contradiction screening.|Deep verification, text-based experiment simulation, and full-text parsing.|

## Multi-Layered Ontological Schema and Entity-Relationship Blueprint

In scientific domains, collapsing literature assertions into binary triples like `(Drug, INHIBITS, Protein)` introduces a severe loss of context. Biological findings are rarely absolute; they are highly dependent on specific experimental conditions, cellular contexts, dose ranges, and patient cohorts.

To capture this complexity, the platform uses an "evidence-centric" schema. In this paradigm, the primary unit of the graph is not a direct entity-to-entity edge, but rather an explicit, intermediate _Evidence Node_.

```
+--------------------+               +-----------------------+               +--------------------+
|    Entity Node     |               |     Evidence Node     |               |    Entity Node     |
|   (e.g., Drug)     | LINKED_TO     |  (e.g., Trial Result) | LINKED_TO     |   (e.g., Protein)  |
|  - Name: Cetuximab |-------------->|  - p-value: 0.002     |-------------->|  - Name: EGFR      |
|  - ChEBI: 50204    |               |  - Cohort: CRC Patients|               |  - UniProt: P00533 |
+--------------------+               +-----------------------+               +--------------------+
                                                 |
                                                 | SUPPORTS / CONTRADICTS
                                                 v
                                     +-----------------------+
                                     |   Other Evidence Node |
                                     |  (e.g., In Vitro Lab) |
                                     +-----------------------+
```

To resolve terminology fragmentation and ensure strict entity resolution, the entity nodes ($V_T$) are mapped directly to industry-standard ontologies. Resolving synonym variance (e.g., mapping "imatinib," "STI-571," and "Gleevec" to a single chemical entity node) is critical to prevent graph fracturing and allow agents to successfully trace pathways.

Furthermore, standard large language models are highly susceptible to character transpositions and hallucinations when extracting complex molecular formats. To eliminate this issue, the ingestion pipeline implements a deterministic validation layer:

- **Chemical Identifiers:** Extracted SMILES strings are verified using RDKit to compute canonical representations, InChIKeys, molecular weights, and Lipinski's Rule of 5 parameters.
    
- **Protein and Gene Sequences:** Extracted amino acid chains are parsed via Biopython to validate sequence integrity, isoelectric points, and thermodynamic stability.
    
- **Clinical Trials and Patents:** Clinical trial identifiers (e.g., NCT trial numbers) and patent registrations are validated through regex patterns matching global registry databases.
    

|**Labeled Node / Relationship Class**|**Representational Category**|**Key Semantic Attributes**|**Mandated Ontological Grounding / Target Database**|**Functional Role in Multi-Agent Execution**|
|---|---|---|---|---|
|`Paper`|Document Anchor|`pmid`, `doi`, `journal`, `impact_factor`, `citation_count`, `publication_date`, `authors`|PubMed, CrossRef, Web of Science|Establishes the primary grounding source; maintains publication weightings used in evidence scoring.|
|`Claim`|Extracted Assertion|`claim_text`, `subject_entity`, `predicate_relation`, `object_entity`, `extraction_confidence`|Internal Natural Language Parsing Engine|Represents individual assertions extracted from literature before verification.|
|`Gene`|Biological Entity|`hgnc_id`, `symbol`, `name`, `chromosome_band`, `synonyms`|HGNC (Hugo Gene Nomenclature Committee)|Anchors upstream genetic interactions, regulatory mechanisms, and expression targets.|
|`Protein`|Biological Entity|`uniprot_id`, `name`, `amino_acid_sequence`, `molecular_weight`, `stability_index`|UniProt KB (Knowledgebase)|Maps drug targets, receptor sites, and metabolic enzymes involved in disease pathways.|
|`Pathway`|Biological Entity|`go_term_id`, `pathway_name`, `reactome_id`, `category_type`|Gene Ontology (GO), Reactome|Contextualizes molecular cascades and multi-protein interactions.|
|`Disease`|Clinical Entity|`meddra_id`, `mesh_heading_id`, `preferred_name`, `disease_class`|MedDRA, Medical Subject Headings (MeSH)|Models clinical indications, patient group profiles, and pathological outcomes.|
|`Drug`|Chemical Entity|`chebi_id`, `smiles_string`, `canonical_inchikey`, `molecular_weight`, `rule_of_five_pass`|ChEBI, ChEMBL, PubChem|Represents therapeutic agents, active chemical ligands, and drug candidates.|
|`Assay`|Experimental Entity|`assay_type`, `experimental_system`, `target_analyte`, `protocol_reference_id`|BioAssay Ontology (BAO)|Represents validation frameworks, molecular testing kits, and screening methods.|
|`Mechanism`|Relational Entity|`causal_type`, `directionality`, `activation_state`, `binding_affinity_kd`|Gene Ontology Causal Relations|Connects biological entities, capturing functional changes like activation or inhibition.|
|`Hypothesis`|Cognitive Entity|`hypothesis_id`, `proposed_linkage`, `aims_description`, `elo_rating`, `validation_status`|Internal Multi-Agent Proposal Schema|Represents a proposed scientific relationship generated by the system.|
|`Critique`|Cognitive Entity|`critique_id`, `assessed_weakness`, `novelty_score`, `correctness_score`, `safety_score`|Internal Evaluation Schema|Stores virtual peer-review assessments generated by the Reflection agent.|
|`Experiment`|Actionable Entity|`experiment_id`, `python_code_snippet`, `sandboxed_execution_status`, `observed_outcome`|Python Runtime Environment Schema|Models simulated experiments run within sandboxed execution environments.|
|`Evidence`|Grounding Entity|`evidence_id`, `p_value`, `hazard_ratio`, `fold_change`, `sample_size`, `experimental_context`|EvidenceNet Schema|Links biological claims to their original experimental and clinical contexts.|

These nodes are connected by relationships that capture the provenance and flow of scientific reasoning:

- **Document to Assertion Linkages:** `(Paper)-->(Claim)` tracks the specific publication source for each parsed assertion.
    
- **Assertion Contextualization:** `(Claim)-->(Evidence)` grounds extracted claims in specific quantitative parameters.
    
- **Entity Linkages:** `(Evidence)-->(Drug)` connects experimental outcomes directly to the physical agents involved.
    
- **Mechanistic Integration:** `(Drug)-->(Mechanism)-->(Protein)` traces the detailed causal pathway.
    
- **Hypothesis Composition:** `(Hypothesis)-->(Claim)` represents the structured assertions that form the generated proposal.
    
- **Review Loop Traceability:** `(Critique)-->(Hypothesis)` links virtual peer-review assessments directly to their target proposals.
    
- **Experimental Verification Loop:** `(Experiment)-->(Hypothesis)` connects simulated or physical assay steps back to the parent hypothesis.
    

## Mathematical Formalization of Evidence Strength, Contradiction, and Novelty

To ensure that the multi-agent system does not propagate false positives or escalate errors embedded in the scientific record, the platform must quantitatively score the strength of supporting evidence and dynamically flag contradictions. The strength score of a given evidence node, denoted as $S_E(e)$ for an evidence record $e$, is computed by integrating both statistical parameters from the study and bibliometric properties of the publication :

$$S_E(e) = w_1 \cdot \ln(N_e) + w_2 \cdot (-\log_{10}(p_e)) + w_3 \cdot \ln(FC_e + 1) + w_4 \cdot \ln(IF_e + 1) + w_5 \cdot \ln(C_e + 1)$$

Where:

- $N_e$ represents the experimental or clinical sample size.
    
- $p_e$ represents the reported p-value of the finding.
    
- $FC_e$ is the fold change of the biological effect.
    
- $IF_e$ represents the journal impact factor.
    
- $C_e$ represents the citation count of the parent publication.
    
- $w_1, w_2, w_3, w_4, w_5$ are normalized weighting parameters adjusted according to the specific scientific domain.
    

Contradiction detection is modeled using a dual-layered pipeline containing logical constraint checking and neural-based attention masking. Logical contradictions are evaluated by extracting assertion rules from the graph and assessing their joint satisfiability. Let an antecedent rule derived from evidence $e_1$ be denoted as $A_1$, with its consequent action or state labeled as $C_1$. If a second evidence node $e_2$ proposes an antecedent $A_2$ and consequent $C_2$, the system evaluates the conditional logic constraint :

$$C_{\text{logical}} = (A_1 \land C_1) \land (A_2 \land C_2)$$

If the combined propositional rule resolves as unsatisfiable:

$$(A_1 \land C_1) \land (A_2 \land C_2) \models \text{unsat}$$

A hard `CONTRADICTS` edge is written between the two corresponding Evidence Nodes.

In cases where contradictions are semantic and context-dependent rather than strictly logical (e.g., conflicting drug efficacy across distinct tissues), the system utilizes a Confidential Graph Attention Network (CO-GAT) to prevent the propagation of noisy, conflicting facts. The node confidence score $c_i$ for an evidence node $v_i$ relative to a proposed target hypothesis $H$ is computed as :

$$c_i = \sigma\left(\mathbf{W}_c \left[\mathbf{h}_i \parallel \mathbf{h}_H\right]\right)$$

Where $\mathbf{h}_i$ is the graph-embedded vector representation of the evidence node, $\mathbf{h}_H$ is the semantic vector representation of the target hypothesis, $\parallel$ denotes vector concatenation, $\mathbf{W}_c$ is a learned weight parameter matrix, and $\sigma$ is the sigmoid activation function.

The classic graph attention coefficients $\alpha_{ij}$ representing the information flow between node $v_i$ and neighboring node $v_j$ are then dynamically scaled using a threshold-based confidence mask :

$$\tilde{\alpha}_{ij} = \frac{\exp\left(\text{LeakyReLU}\left(\mathbf{a}^T \left\right)\right) \cdot M_i}{\sum_{k \in \mathcal{N}_i} \exp\left(\text{LeakyReLU}\left(\mathbf{a}^T \left\right)\right) \cdot M_k}$$

Where the confidence mask $M_i$ is defined as :

$$M_i = \begin{cases} 1, & \text{if } c_i \ge \tau \\ 0, & \text{otherwise} \end{cases}$$

Here, $\tau$ is a highly calibrated validation threshold (typically set to $0.70$). If the relevance or confidence score of an evidence node falls below $\tau$, the mask $M_i$ becomes $0$, completely severing the attention updates and preventing erroneous or contradictory semantic information from flowing to adjacent nodes in the reasoning chain.

Hypothesis novelty estimation measures the topological uniqueness of a proposed link relative to the current scientific knowledge graph. Let a generated hypothesis $H$ propose a novel biological link between a starting entity (source, $s$) and an ending target (object, $o$). The historical popularity and path density connecting these nodes is computed using path-based topological analysis :

$$Pop(s, o) = \sum_{p \in P_{s \to o}} \prod_{e \in p} \frac{\text{Weight}(e)}{\sum_{e' \in E} \text{Weight}(e')}$$

Where $P_{s \to o}$ is the set of all existing paths of length $\le 3$ connecting $s$ and $o$ in the graph, and $\text{Weight}(e)$ corresponds to the frequency of literature co-occurrence of edge $e$. The overall novelty score $N(H)$ is then calculated by combining this path popularity score with a community transition penalty :

$$N(H) = -\log_{10}\left(Pop(s, o) + \epsilon\right) \cdot \left(1 + \gamma \cdot \mathbb{I}\left(\text{Comm}(s) \neq \text{Comm}(o)\right)\right)$$

Where:

- $\gamma \ge 0$ is a scalar weight prioritizing cross-domain connections.
    
- $\mathbb{I}$ is an indicator function returning $1$ if the source and target belong to different topological communities (detected via Speaker–Listener Label Propagation Algorithms, SLPA) and $0$ otherwise.
    
- $\epsilon$ is a small smoothing constant ($10^{-6}$) to prevent log evaluation errors.
    

This mathematical framework enables the system to penalize ideas that rely on popular scientific pathways while prioritizing highly novel, cross-disciplinary hypotheses.

## Hybrid GraphRAG and Agentic Retrieval Mechanics

The platform's retrieval layer operates as a hybrid search engine, combining dense semantic embeddings with deterministic graph traversals to provide a robust reasoning framework. Standard vector-only RAG systems suffer from structural blindness, often failing to trace transitive connections across separate documents. By layering a Cypher-based graph retrieval step over the vector search, the system can execute multi-hop reasoning, retrieving contextually rich answers that pure vector databases cannot reproduce.

```
User Query ---> ---> Generates Cypher + Vector Search
                                                  |
                         +------------------------+------------------------+
                         |                                                 |
                         v (Cypher Traversals)                             v (Cosine Vector Search)
           +---------------------------+                     +---------------------------+
           |       Memgraph / Neo4j    |                     |         pgVector          |
           |   (Multi-hop path trace)  |                     |  (Chunk semantic search)  |
           +-------------+-------------+                     +-------------+-------------+
                         |                                                 |
                         +------------------------+------------------------+
                                                  |
                                                  v (Hybrid Fusion / Rank)
                                      Synthesized Context Prompt
                                                  |
                                                  v
                                     [Generation Agent Output]
```

To optimize execution speed and simplify multi-agent tool usage, the retrieval architecture supports "Atomic GraphRAG" and "Agentic GraphRAG" paradigms :

- **Atomic GraphRAG:** Rather than separating vector search and graph querying into distinct, high-latency network operations, the platform executes the entire pipeline—vector distance calculation, path traversal, node filtering, and prompt generation—as a single, atomic database execution inside Memgraph.
    
- **Agentic GraphRAG:** Not all user questions require the same traversal depths. The system's Supervisor agent dynamically selects the retrieval strategy per query, generating tailored Cypher scripts depending on the task type :
    

Cypher

```
// Text2Cypher Strategy: Quantifying specific relational frequencies across the corpus
MATCH (d:Drug)-->(e:EvidenceRecord)-->(p:Protein)
WHERE e.study_design = 'Randomized Controlled Trial' AND e.p_value < 0.05
RETURN d.name, COUNT(p) AS LinkedTargetCount
ORDER BY LinkedTargetCount DESC LIMIT 10
```

Cypher

```
// Pivot Search + Relevance Expansion: Extracting localized pathways for drug repurposing
MATCH (d:Drug {name: 'Silmitasertib'})-->(e:EvidenceRecord)-->(p:Protein)
MATCH path = (p)--(target:Protein)
RETURN d.name, e.p_value, p.name, type(r), target.name
```

Cypher

```
// Query-Focused Summarization: Fetching global thematic contexts using BERTopic nodes
MATCH (t:TopicNode {theme: 'Liver Fibrosis Therapeutics'})-->(e:EvidenceRecord)
MATCH (e)-->(ent:EntityNode)
RETURN e.source_passage, ent.name
```

To further refine search accuracy, the platform runs unsupervised topic modeling (BERTopic) on extracted literature passages during ingestion, storing the resulting topic classifications directly as nodes within the Neo4j/Memgraph database. High-salience thematic terms from the dominant topic clusters are dynamically injected into the vector-search prompts, sharpening semantic constraints and ensuring that retrieved evidence strictly aligns with the scientific domain of the session.

## Graph-Supported Hypothesis Generation, Tournament Ranking, and Evolution

The core loop of the multi-agent system uses the graph database as an active reasoning sandbox to generate, evaluate, and iteratively evolve scientific hypotheses. The workflow progresses through three distinct, graph-supported phases :

```
+--------------------+
|  Research Goal     |
+---------+----------+
          |
          v
+--------------------+      Link Prediction
| Candidate Triples  |------------------------+
|    Generation      |                        |
+---------+----------+                        v
          |                             (Pruning)
          v                                   |
+--------------------+                        v
| Proximity Agent    |                  (Pairwise)
| (Clustering Graph) |                        |
+---------+----------+                        v
          |                             
          v                                   |
+--------------------+                        v
|  Evolution Agent   |               [Evolution Loop]
| (Refinement Loop)  |                        |
+--------------------+                        v
                                       Final Proposals
```

### Link Prediction and Hypothesis Inception

Initially, the system models hypothesis generation as a link prediction task over the existing scientific knowledge graph. Using the _ResearchLink_ methodology, the system identifies top-tier biomedical entities within the local subgraph and programmatically generates candidate triples $(s, p, o)$ that do not currently exist in the database.

To prevent hypothesis overload and exclude biochemically impossible assertions, these candidate triples are subjected to a fast, local classifier named _SciCheck_. This classifier uses a combination of path-based topological features, text chunk embeddings, and graph embeddings (KGE) to calculate a baseline probability of biological validity. Triples falling below a score of $0.50$ are immediately pruned from the candidate queue.

### Top-k Compressive Subgraph Extraction

The remaining highly-rated triples are expanded into descriptive hypotheses. Passing complete, global graphs to LLM agents is computationally prohibitive and causes context window saturation.

To optimize token efficiency, the system implements the _Compressive KG_ pattern: it extracts compact, highly dense top-$k$ subgraphs centered around the target entities. These localized, structurally rich subgraphs preserve essential pathway logic, providing the Generation agent with sufficient scientific context while reducing input token volume.

### Proximity Clustering and Diverse Selection

To prevent the generation of redundant concepts, the _Proximity Agent_ computes pairwise similarities across the generated hypotheses, constructing a local "graph of ideas" where edges represent semantic similarity. Using community detection algorithms, the system clusters related hypotheses, allowing the Supervisor agent to select diverse representative concepts from distinct topological regions and ensure a comprehensive exploration of the research space.

### Pairwise Elo Tournaments

The selected hypotheses are entered into a competitive tournament orchestrated by the _Ranking Agent_. The agent initiates pairwise, multi-turn simulated debates where agents represent opposing hypotheses, utilizing retrieved graph evidence to argue for correctness, novelty, and experimental testability. Each hypothesis is assigned a dynamic Elo rating based on these win/loss outcomes. High Elo ratings strongly correlate with scientific validity and proposal quality.

### Non-Destructive Evolution

The _Evolution Agent_ selects the highest-rated hypotheses and iteratively refines them. This refinement includes combining complementary ideas, simplifying overly complex biological assumptions, and incorporating negative feedback generated during the tournament debates. To prevent the loss of valuable core concepts, the agent performs non-destructive evolution, maintaining parent-child tracking relationships within the hypothesis graph.

## UX Design, Visual Abstraction, and Hierarchical Wiki Memory

Representing thousands of interconnected biological entities, evidence records, and experimental outcomes inevitably leads to extreme cognitive overload for human scientific directors. If the user interface merely displays a standard "hairball" node-and-edge visualization, the graph becomes unusable.

To resolve this visual complexity, the platform's user interface incorporates several advanced navigation and visual abstraction design patterns:

### Mechanical Connections as Independent Nodes

Rather than representing scientific relationships as basic lines, connections are rendered as collapsible, parameter-rich nodes containing their own internal parameters. This design allows users to visually inspect quantitative metrics (such as p-values, sample sizes, and trial IDs) directly on the node, keeping the canvas organized and minimizing edge crossings.

### Dynamic Hierarchy and Tri-Level Abstraction

The UI enforces three predefined abstraction levels to help users manage detail :

- **Level 1 (Overview Mode):** Displays high-level thematic clusters (such as topic nodes and primary disease phenotypes) generated via community detection algorithms.
    
- **Level 2 (Subsystem Mode):** Reveals key biological pathways, primary drug candidates, and central target proteins when the user clicks a cluster.
    
- **Level 3 (Full Detail Mode):** Expands the view to show individual Evidence Nodes, patient cohorts, exact citation snippets, and biological assay protocols.
    

```
[Overview Mode]     ===> Click Topic Cluster ===>     ===> Expand Evidence Node ===>
- Topic: Fibrosis                                - Protein: TGFB1                                     - p-value: 0.004
- Topic: AML                                     - Drug: Silmitasertib                                - Assay: Western Blot
```

### Contextual Navigation Anchors

To assist users in navigating deep subgraphs, the interface features a persistent breadcrumb trail reflecting the hierarchical pathway. A small minimap displays the user's position relative to the global graph structure, while an interactive "Focus Mode" dims unrelated nodes and highlights direct upstream and downstream neighbors during traversal. Users can choose to expand node parameters directly in the same viewport or open them in separate side-by-side tabs to facilitate comparisons.

### The Hierarchical Markdown Wiki Layer

To bridge the gap between complex graph databases and natural language interfaces, the platform maintains a parallel, human-readable _Hierarchical Markdown Wiki_ (inspired by the LLM Wiki concept). This wiki structures the underlying graph data into organized Markdown documents, serving as a transparent, version-controlled repository :

# Target Directory: Epigenetic Targets for Liver Fibrosis

## Epigenetic Target: HDAC4

- **ID:** UniProt:P56524
    
- **Biological Context:** Expressed in activated hepatic stellate cells.
    

### Supporting Evidence Records

#### Evidence-942 (FIRE-3 Trial Context)

- **Sample Size ($N$):** 150 (in vitro primary human organoids)
    
- **P-Value ($p$):** 0.004
    
- **Finding:** HDAC4 knockdown significantly blocks 91% of the scarring-linked collagen deposition response.
    
- **Citation:** Gottweis et al., Nature, 2026.
    
- **Validation Status:** Verified via Playwright-based automated assay modeling.
    

### Conflicting Statements & Contradictions

- **Evidence-102:** HDAC4 inhibition shows no anti-fibrotic effect in standard 2D cell cultures (p = 0.42).
    
    - _System Note:_ Discrepancy is resolved by tissue-specificity constraints (3D organoids preserve cell-matrix interactions).
        

This dual-layer representation provides significant advantages: human scientists can review complex graph data through clean, structured documents, while the AI agents can parse and update the Markdown files directly using standardized file-system tools, bypassing the need for computationally expensive graph rendering pipelines.

## System Safety, Verification, and Evaluation Harness

Operating an autonomous scientific hypothesis engine introduces significant safety risks, particularly the potential for generating dual-use technologies or violating Chemical, Biological, Radiological, and Nuclear (CBRN) safety protocols. To mitigate these risks, the platform implements a multi-tiered safety and validation layer before writing new proposals to the knowledge base.

```
User Research Goal ---> ---> Fails ---> Reject & Terminate Run 
                                  |
                               Passes
                                  v
                    [Multi-Agent Loop Execution]
                                  |
                        Produces Hypothesis Graph
                                  |
                                  v
               ---> Fails ---> Prune Node 
                                  |
                               Passes
                                  v
                  ---> Fails ---> Flag Simulation Failure 
                                  |
                               Passes
                                  v
              
```

### Safety Agent and CBRN Assessment

Before initializing a research run, the _Safety Agent_ evaluates the user's research goal against a repository of 1,200 adversarial prompts spanning 40 scientific domains, including chemical toxins and biological pathogens. If any dual-use or harmful concepts are detected, the agent immediately terminates the execution, records the violation in the relational database, and blocks write access to the graph database to prevent the propagation of unsafe hypotheses.

### Fidelity Evaluation Harness

To measure system performance, the platform implements a metric-based evaluation harness that tracks three key operational dimensions :

- **Component Extraction Fidelity:** Measures the accuracy of parsed entities, normalized linkages, and semantic relations against curated control data.
    
- **Factual Consistency Scoring:** Evaluates generated hypotheses using a Paraphrased Hallucination Consistency Score (PHCS) to measure the stability of agent outputs across semantically equivalent prompts :
    

$$PHCS = \sqrt{\frac{1}{M-1} \sum_{i=1}^{M} (H_i - \bar{H})^2}$$

Where $H_i$ is the factual consistency score of paraphrased query version $i$, and $\bar{H}$ represents the average consistency score across all $M$ paraphrased query variations.

- **Latency and Operational Costs:** Tracks token consumption, graph write latency, and agent execution times across Standard and Advanced runs to prevent processing bottlenecks.
    

|**System Evaluation Dimension**|**Evaluation Metric**|**Baseline Target**|**High-Performance Target**|**Operational Diagnostic Value**|
|---|---|---|---|---|
|**Extraction Fidelity**|Field-level extraction accuracy|$\ge 90.0\%$|$\ge 98.3\%$|Ensures correct schema extraction before graph updates.|
|**Grounding Accuracy**|Entity-link normalization score|$\ge 95.0\%$|$100.0\%$|Prevents graph fragmentation from spelling variations.|
|**Relational Accuracy**|Semantic relation-type correctness|$\ge 80.0\%$|$\ge 90.0\%$|Confirms that directed edges capture real-world causality.|
|**Response Stability**|Paraphrased Consistency (PHCS)|$\le 0.15$|$\le 0.05$|Measures model resilience against prompt variation.|
|**Run Replay Trace**|Step-by-step verification rate|$100.0\%$|$100.0\%$|Guarantees that every transition is fully auditable.|

### Sandboxed Experiment Simulation

To verify correctness before final proposal generation, the platform passes the proposed hypothesis to an isolated, Docker-based Python sandbox.

The system writes and executes targeted computational scripts (e.g., using RDKit for structural validation or Biopython for protein structure modeling), interacting with the environment through Playwright-based testing to verify that the proposed biological interactions are physically and chemically viable.

### Run Replay and Event Sourcing

To ensure reproducibility, all intermediate states, agent decisions, retrieved text passages, and debate transcripts are written as historical, timestamped transaction events linked to their corresponding nodes.

By storing this complete logical derivation in the database, researchers can replay any session step-by-step, auditing the exact evidence paths and agent reasoning chains that led to a final hypothesis.
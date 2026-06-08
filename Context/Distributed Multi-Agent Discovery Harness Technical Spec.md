# Architectural Blueprint and Technical Specification for an AI Co-Scientist Clone: A Distributed Multi-Agent Scientific Discovery Harness

The acceleration of computational and biological discovery requires a departure from linear, chat-centric language model interactions toward stateful, verification-centric multi-agent systems. Building a high-fidelity clone of Google DeepMind’s AI Co-Scientist entails constructing a distributed cognitive architecture that automates the entire lifecycle of hypothesis generation, peer-reviewed debate, evolutionary optimization, and empirical code execution. This system operates not as a passive literature retrieval tool, but as an active scientific collaborator designed to interact with human researchers, refine objectives, query heterogeneous biomedical databases, execute simulation code, and output verifiable, auditable research proposals.

The system architecture combines a modern web interface, an event-driven serverless backend, a standardized Model Context Protocol (MCP) data-access layer, and an execution harness that enforces scientific discipline through Git-based pre-registration and sandboxed computational coding. This blueprint details the complete system specification, outlining the exact operational loop, the multi-agent coalition topology, the division between stateless MCP tools and stateful agent skills, and the verification pipelines required to prevent hallucinated claims and biosecurity violations.

## The Core Hypothesis-Generation and Experiment-Simulation Loop

The functional pipeline of the Co-Scientist clone is engineered around an iterative, closed-loop discovery cycle that mirrors the scientific method. This core loop progresses through eight distinct phases, systematically moving from initial natural-language goals to verified, execution-ready research protocols :

```
 ──► ──► ──► [Hypothesis Gen]
                                                                                      │
 ◄── [Hypothesis Evolution] ◄── ◄────┘
```

The cycle begins with the intake of a high-level research goal specified in natural language. The system initiates an interview-style scoping phase via a conversational agent, prompting the scientist to define parameters, prioritize target domains, identify known constraints, and submit initial seed ideas or relevant datasets.

Once the objective is scoped, the system enters the literature and data grounding phase. Here, the retrieval layer executes parallel queries across multiple open-access citation indexes and specialized biochemical databases, building a contextual repository of historical methodologies, target structures, and experimental baselines.

Based on this grounded context, the generation phase formulates distinct, chemically and logically viable research hypotheses. To ensure a comprehensive search of the target scientific domain, these hypotheses are mapped into a high-dimensional vector space where proximity-clustering algorithms identify and prune redundant ideas, enforcing structural diversity.

The candidate hypotheses then undergo critique and reflection. Specialized reviewer agents act as hostile peer reviewers, systematically testing each idea against established physical laws, experimental protocols, and clinical trial histories to identify logical flaws or biological contradictions.

Survival of the fittest is quantified through an automated tournament of ideas. Hypotheses are matched in head-to-head debates, where defender and critic agents argue their viability. The outcomes are processed by a ranking engine that calculates updated Elo ratings for each proposal.

The top-ranked ideas are passed to the hypothesis evolution phase, where they are recombined, mutated, and refined to resolve the criticisms raised during the tournament. This evolutionary cycle continues until the hypotheses meet pre-defined confidence and validation thresholds.

Finally, the system compiles the evolved hypotheses, analytical models, and simulated protocols into a comprehensive research proposal, providing the human researcher with an actionable, peer-reviewed blueprint for wet-lab validation.

The user interacts with this core loop through Google’s "Gemini for Science" product workflow. This interface supports two distinct run configurations:

|**Parameter / Capability**|**Standard Run Configuration**|**Advanced Run Configuration (Test-Time Compute Scaling)**|
|---|---|---|
|**Search Space Depth**|Shallow literature sweep across major abstracts; 1-hop citation tracing.|Deep multi-hop bibliographic path tracing; full-text retrieval and parser integration.|
|**Database Breadth**|Core PubMed and ChEMBL REST API indexing only.|Simultaneous queries across PDB, UniProt, Reactome, STRING, and ClinicalTrials.gov.|
|**Tournament Intensity**|10 to 50 pairwise debate cycles; static reviewer agents.|Up to 1,000 parallel Elo-rated tournament matches with dynamic, adaptive critics.|
|**FUTS Iterations**|Short-depth Flat UCB Tree Search; baseline code generation.|High-depth tree search; thousands of parallel sandboxed code iterations and metrics-driven pruning.|
|**Resource Allocation**|Moderate compute footprint; quick turnaround (minutes to hours).|Scaled test-time compute; long-running job queues over days.|
|**User Interaction**|Static final report; basic research proposal markdown output.|Dynamic follow-up; interactive knowledge base exploration; post-hoc simulation execution.|

## System Architecture and Multi-Agent Coalition Topology

Executing long-running, computationally intensive scientific workflows requires a robust, decoupling backend architecture. The system's infrastructure is built on an event-driven, serverless framework.

A responsive React and Tailwind CSS web interface acts as the primary user dashboard, communicating with a backend API Gateway. This gateway routes incoming tasks to an event-driven message queue, such as RabbitMQ or AWS SQS, which orchestrates execution across a cluster of serverless workers.

A persistent relational database (such as PostgreSQL) manages system state, while a high-capacity vector database (such as Milvus or pgvector) indexes embedding vectors for the scientific retrieval layer.

A centralized hypothesis store logs all candidate ideas, debate transcripts, and tournament histories. This store is connected to a fidelity evaluation harness that continuously benchmarks the generated scientific code against historical baselines.

```
 ◄──► [API Gateway] ──► [Event Queue] ──►
                                                        │
                      ┌─────────────────────────────────┤
                      ▼                                 ▼
              (pgvector)          (PostgreSQL)
                      
```

At the core of this runtime infrastructure is the multi-agent coalition. A Supervisor agent manages this coalition, acting as an adaptive, non-linear planner.

Instead of executing code or retrieval tasks directly, the Supervisor parses the research objectives, breaks them down into task-specific DAGs, schedules them in the worker queue, and monitors the progress of twelve specialized worker agents :

- **Supervisor**: Orchestrates the coalition by managing system state, planning tasks dynamically, and allocating queue resources based on real-time execution feedback.
    
- **Intake/Interview Agent**: Manages the scoping workspace, asking targeted, domain-specific questions to clarify the user's objectives and establish key constraints.
    
- **Literature Retrieval Agent**: Formulates queries and manages data retrieval across open literature search engines and citation networks.
    
- **Generation Agent**: Combines retrieval inputs with domain-specific knowledge to propose candidate hypotheses, ensuring all assertions are linked to valid literature sources.
    
- **Reflection Agent**: Evaluates hypotheses by analyzing experimental feasibility, identify potential confounding variables, and assessing statistical validity.
    
- **Proximity/Clustering Agent**: Clusters candidate hypotheses in high-dimensional vector spaces, calculating semantic similarity to filter out redundant variations.
    
- **Ranking Agent**: Runs head-to-head debates between hypothesis pairs, updating Elo ratings based on argument strength and factual backing.
    
- **Evolution Agent**: Refines and combines top-performing hypotheses, mutating structural parameters to resolve flaws identified during debate.
    
- **Meta-Review Agent**: Analyzes tournament transcripts and Elo histories to identify unresolved contradictions, sending feedback to the Supervisor to trigger targeted research cycles.
    
- **Citation Verification Agent**: Parses cited references, validates unique identifiers (DOIs, PMIDs), and retrieves full text to confirm claim-citation alignment.
    
- **Safety Agent**: Enforces security protocols by scanning inputs and outputs for dual-use biological, chemical, or radiological risks.
    
- **Report Synthesis Agent**: Compiles the final verified hypotheses, literature contexts, and simulated protocols into structured, human-ready research proposals.
    

## Model Context Protocol (MCP) Integration Layer

Connecting language models to highly specialized, heterogeneous scientific databases is historically bottlenecked by brittle, ad-hoc API integrations. The Model Context Protocol (MCP) solves this integration challenge by establishing a standardized, host-client-server architecture using JSON-RPC 2.0 communication over standard input/output (stdio) or streamable HTTP transports. By encapsulating complex analytical functions and database interfaces within stateless, containerized MCP servers, the Co-Scientist clone enables its agents to dynamically discover, query, and combine data from diverse scientific sources through a single, unified protocol.

```
[Agent Client] ──(JSON-RPC 2.0 over stdio/HTTP)──► [Unified MCP Host]
                                                        │
                      ┌─────────────────────────────────┤
                      ▼                                 ▼
                          
             • search_articles                 • search_compounds
             • get_article_metadata           • search_activities
```

The data access layer of the Co-Scientist clone is composed of a network of production-ready MCP servers, written in Python or TypeScript, and configured with Zod schema validation :

- **PubMed MCP Server**: Exposes NCBI's Entrez utilities. Rather than retrieving unformatted text, it provides structured JSON payloads containing PMIDs, titles, abstracts, MeSH terms, and publisher URLs. Key tools include `search_articles` (using Boolean logic) and `get_pubmed_article_metadata`.
    
- **OpenAlex MCP Server**: Interfaces with the OpenAlex open catalog of over 240 million scholarly works. It features tools like `openalex_resolve_name` to resolve ambiguous author or institution names to unique entities, and `openalex_get_citation_graph` to trace backward and forward citation networks.
    
- **ChEMBL MCP Server**: Connects directly to the European Bioinformatics Institute (EMBL-EBI) ChEMBL chemical database. It exposes tools like `search_compounds`, `search_activities` to retrieve bioactivity measurements ($IC_{50}$, $K_i$), and `calculate_descriptors` to evaluate chemical properties and Lipinski drug-likeness rules.
    
- **ClinicalTrials.gov MCP Server**: Accesses clinical trial data using either API v2 or the AACT PostgreSQL database. It provides tools like `clinicaltrials_search_studies` for geographic and phase-specific trial mapping, and `read_query` to execute SQL queries for competitive landscape analysis.
    
- **BioContextAI Knowledgebase MCP Server**: Functions as an integrated lookup layer, wrapping genomic, pathway, and protein network endpoints including UniProt, Reactome, STRING, and Open Targets. It translates high-level requests into specific cross-resource API calls (such as fetching a UniProt accession number and querying its related pathway network in Reactome).
    
- **AnnData MCP Server**: Retrieves metadata and matrix slices from AnnData files using the Python `anndata` package, enabling direct agent-driven analysis of single-cell RNA sequencing datasets.
    

|**MCP Server Identifier**|**Host Endpoint & Transport**|**Exposed Tool Definition**|**Primary Input Schema (Zod)**|**Data Output Payload Schema**|
|---|---|---|---|---|
|**`pubmed-mcp`**|`localhost:stdio` / `node build/index.js`|`search_articles` , `get_pubmed_article_metadata`|`{ query: z.string(), max_results: z.number().optional() }`|Array of article objects containing PMID, title, authors, abstracts, and MeSH terms.|
|**`openalex-mcp`**|`localhost:stdio` / `bun run start:stdio`|`openalex_resolve_name` , `openalex_get_citation_graph`|`{ seed_id: z.string(), direction: z.enum(["cites", "cited_by"]) }`|Citation network nodes and edges with metadata including publication years and citation counts.|
|**`chembl-mcp`**|`docker run -i chembl-mcp-server`|`search_compounds` , `search_activities` , `calculate_descriptors`|`{ chembl_id: z.string(), activity_type: z.string().optional() }`|Canonical SMILES, molecular descriptors, and bioactivity arrays ($IC_{50}$, EC50).|
|**`clinicaltrials-mcp`**|`localhost:stdio` / `node build/index.js`|`clinicaltrials_search_studies` , `clinicaltrials_find_eligible`|`{ condition: z.string(), phase: z.enum() }`|Active trials array with NCT IDs, study designs, enrollment sizes, and recruitment sites.|
|**`biocontext-kb`**|`mcp.biocontext.ai` / `http`|`get_uniprot_annotation` , `get_reactome_pathway`|`{ accession: z.string().regex(/^[OPQ][0-9][A-Z0-9]{3}[0-9]$/) }`|Functional annotations, pathway descriptions, and STRING interaction networks.|
|**`anndata-mcp`**|`localhost:stdio` / `uvx anndata-mcp`|`read_lazy` , `get_obs_names`, `get_var_names`|`{ filepath: z.string(), obs_keys: z.array(z.string()).optional() }`|Dimensions of AnnData objects, observation/variable listings, and targeted matrix slices.|

## Statefulness, Cognitive Division, and the Science Superpowers Skills Standard

A key architectural design choice in building the Co-Scientist clone is the distinction between stateless _MCP tools_ and stateful _agent skills_. MCP tools are external resources—they are stateless, standardized, and execution-focused, functioning as the model's access points to the physical world.

Conversely, Skills are internal resources—they are stateful, cognitive, and process-oriented. Written in Markdown using the YAML-frontmatter "Agent Skills" standard, Skills provide the structural guidelines and cognitive workflows that govern how agents interact with MCP tools, execute reasoning steps, and manage context.

```
                    
             (e.g., framing-research-questions)
                             │
            (Instructs Agent on Logic & Process)
                             │
                             ▼
                   
                     (e.g., pubmed-mcp)
```

To enforce rigorous scientific thinking and prevent common LLM reasoning errors like post-hoc data fitting and confirmation bias, the runtime environment implements the "Science Superpowers" skills framework.

This framework is built around an "Iron Law": _no confirmatory scientific claim can be made without an explicit, pre-registered prediction committed beforehand_. This protocol is managed across ten modular agent skills, utilizing Git commits to create timestamped, frozen records of predictions before any data is loaded or executed :

- **Framing Research Questions (`framing-research-questions`)**: Translates vague research objectives into structured, falsifiable hypotheses, specifying the required datasets and success metrics.
    
- **Surveying Prior Work (`surveying-prior-work`)**: Contextualizes hypotheses using historical literature, identifying standard experimental parameters, potential confounders, and prior baseline effect sizes.
    
- **Designing the Analysis (`designing-the-analysis`)**: Details the quantitative variables, covariates, exclusion rules, and statistical power calculations to be used, preventing post-hoc model modifications.
    
- **Pre-Registering Analysis (`preregistering-analysis`)**: Enforces the "Iron Law" by writing the hypotheses, analytical model designs, and decision rules to a structured markdown file, which is committed to a local Git repository to create a frozen, timestamped baseline.
    
- **Setting up Reproducible Workspace (`setting-up-reproducible-analysis`)**: Deploys a standardized research environment, specifying pinned dependencies, fixed random seeds, and immutable raw data structures.
    
- **Executing Analysis (`executing-analysis` / `subagent-driven-analysis`)**: Spawns independent sub-agents to run the pre-registered analysis plan, using intermediate review checkpoints to prevent execution drift.
    
- **Investigating Anomalous Results (`investigating-anomalous-results`)**: Triggers root-cause analysis when anomalous data is encountered, preventing the system from ignoring or deleting results that contradict the initial hypothesis.
    
- **Verifying Results Before Claiming (`verifying-results-before-claiming`)**: Runs statistical robustness checks and mathematical assumption tests to ensure the data supports the generated claims.
    
- **Requesting Red-Team Review (`requesting-red-team-review` / `receiving-critical-review`)**: Deploys an independent, critical reviewer agent to challenge the analysis, requiring the main agent to address criticisms with empirical evidence rather than performative agreement.
    
- **Reporting and Archiving Findings (`reporting-and-archiving-findings`)**: Formulates final research proposals, compiles reproducibility metrics, and archives the execution environment, code, and raw tables.
    

## Verification-Centric Claim Extraction and Contradiction Resolution

To ensure reliability, the Co-Scientist clone dedicates approximately 80% of its test-time compute to verifying claims and identifying contradictions rather than simply generating new content.

This verification is handled by the Citation Verification Agent and the Reflection Agent, which run a multi-stage validation pipeline.

The pipeline begins with claim extraction, where the agent processes generated text to isolate specific assertions (such as technical metrics, version details, and causal statements) while ignoring subjective content or introductory prose.

```

          │
          ▼
 (Isolate factual and causal assertions)
          │
          ▼
 (Extract DOIs, PMIDs, OpenAlex IDs)
          │
          ▼
 (DeepSciVerify / SemanticCite)
          │
          ├──► [Confirmed] ──► Log with High Confidence
          │
          ▼ (Inconclusive or Complex Evidence)
 (Full-text retrieval and parser integration)
          │
          ▼
 (Resolve contradictions and compile audit report)
```

During citation verification, the agent extracts unique identifiers (such as DOIs, PMIDs, or OpenAlex IDs) and validates them against external registries like Crossref or OpenAlex to retrieve the paper's abstract.

Abstract-level analysis then compares the extracted claim against the retrieved abstract using semantic alignment models (such as DeepSciVerify or SemanticCite). If the abstract provides clear support or refutation, the status is logged, avoiding further compute costs.

If the abstract-level analysis is inconclusive, the system escalates to passage-level escalation. It retrieves the full-text XML or PDF (e.g., via PubMed Central or publisher APIs) and searches the text for granular evidence.

The final step uses a hybrid NLI-LLM verification model to analyze the retrieved passages. While traditional Natural Language Inference (NLI) models offer high recall, they often suffer from poor precision, misclassifying minor contextual differences as direct contradictions. Conversely, LLM-based evaluations provide strong contextual analysis but can suffer from limited coverage.

The hybrid approach integrates their strengths :

$$\text{Verdict} = \text{LLM}_{\text{eval}}\left(\text{Claim}, \text{NLI}_{\text{filter}}\left(\text{Passage}_{1\dots N}\right)\right)$$

The NLI model acts as a first-stage filter to identify potential contradictions, and then the LLM evaluates the filtered text to verify the claim.

The agent compiles these evaluations into an audit-ready verification report, flagging valid references, identifying broken or hallucinated citations, and highlighting direct contradictions to ensure scientific integrity.

## Sandbox Code Optimization and Experiment Simulation

To test and validate hypotheses empirically, the Co-Scientist clone integrates Google Research’s Empirical Research Assistant (ERA) framework directly into its multi-agent workflow.

The ERA framework combines language models with a specialized tree-search algorithm, Flat UCB Tree Search (FUTS), to write, execute, and optimize empirical software against target scientific metrics.

```
                
                            │
               (Propose Code Modification)
                            │
                            ▼
              
                            │
               (Evaluate & Assign Score)
                            │
                            ▼
                (Update Search Tree Nodes)
```

The FUTS algorithm guides the search process using two main functions:

- **`generate_fn`**: Prompts the underlying LLM to propose code modifications, such as introducing new analytical components or swapping algorithms.
    
- **`execute_fn`**: Executes the proposed code variants within a secure, sandboxed environment, scoring their performance against the target scientific metrics.
    

The tree search runs for a configured number of iterations, expanding promising code branches based on their historical performance and exploratory value, and ultimately converges on optimized software solutions :

$$a^* = \arg\max_{a \in A} \left( Q(s, a) + C \cdot \frac{P(s, a)}{1 + N(s, a)} \right)$$

Here, $Q(s, a)$ represents the expected performance score of code variant $a$ at search state $s$, $N(s, a)$ is the number of times that branch has been visited, $P(s, a)$ is the prior probability score generated by the model's policy, and $C$ is a scaling constant balancing exploration and exploitation.

This optimization framework has demonstrated the ability to generate high-quality empirical software across several scientific disciplines :

|**Research Domain**|**Computational Target**|**Baseline Benchmark**|**Execution Scale**|**Key Performance Outcome**|
|---|---|---|---|---|
|**Epidemiological Forecasting**|State-level hospital admission modeling up to four weeks in advance.|CDC Ensemble Models.|Parallel iterations over a few hours.|Generated 14 hospitalization models that consistently ranked near the top of public CDC leaderboards.|
|**Transcriptomic Alignment**|Multi-dataset single-cell RNA sequencing integration.|Human-designed state-of-the-art bioinformatics tools.|Iterative tree search across thousands of configurations.|Discovered 4 new dataset integration methods that beat top human-designed approaches.|
|**Zebrafish Neuroscience**|Modeling calcium-imaging activity across 70,000 active brain neurons.|Manual parameter tuning of complex model structures.|Automated hyperparameter tuning and model synthesis.|Assembled and tuned complex neuron-modeling libraries in hours, a task that typically requires weeks of manual calibration.|
|**Hydrological Forecasting**|Seasonal water runoff forecasting across California river basins.|Traditional, static physical hydrology software packages.|Continuous code refinement loops.|Synthesized deep learning models that improved spatial prediction accuracy.|

Integrating ERA's code optimization loops with the Co-Scientist tournament framework enables a closed-loop discovery cycle.

The Supervisor agent can formulate high-level hypotheses and design specifications, and then deploy the FUTS search tree to write, test, and optimize the code required to run the virtual experiments, returning the quantitative results to the agent coalition for final evaluation.

## Safety Guardrails, Dual-Use Risks, and Managed Access Systems

Deploying autonomous scientific research agents introduces significant safety risks, particularly regarding the potential misuse of biological and chemical design tools.

Computational chemistry and protein-design models can be repurposed to design toxic substances or dangerous pathogens.

For example, the MegaSyn model—originally developed to optimize drug safety and avoid toxicity—was repurposed by researchers to generate 40,000 potential chemical weapon compounds, including VX-like neurotoxins, in under six hours.

Similarly, security evaluations of un-safeguarded bio-agents have demonstrated their capability to design over a thousand novel toxic proteins and thousands of toxic small molecules with high predicted lethality.

```
[User / Agent Input Query]
          │
          ▼
 (Ensembles, Keyword Lists, Bio-Regex)
          │
          ├──► ──►
          │
          ▼ (Input Approved)
 (Local FS Blocked, Traversal Blocked)
          │
          ▼
 (DNA Sequence Matching, Token Check)
          │
          ├──► ──► [Halt & Human Checkpoint]
          │
          ▼ (Verification Approved)
 ──►
```

To mitigate these biosecurity risks, the runtime harness implements a multi-layered security framework :

- **Layer 1: Input Threat Screening**: The system screens input queries and intermediate prompt states against biosecurity threat lists and keyword filters to identify terms related to controlled pathogens, toxins, and CBRN weapons.
    
- **Layer 2: Runtime Sandbox Isolation**: Agent execution environments are sandboxed to isolate the runtime system. This sandboxing blocks access to the local filesystem and uses path validation to prevent directory traversal attacks (e.g., when retrieving skill-related files). Git command chains must be strictly managed to prevent remote code execution (RCE) vulnerabilities.
    
- **Layer 3: Output Synthesis Screening**: Generated protein sequences, small molecule structures, and experimental designs are screened against DNA synthesis databases and toxic chemical registries. If a designed molecule or protein matches a restricted toxin (e.g., ricin or diphtheria toxin structures), the workflow is halted.
    
- **Layer 4: Cryptographic Metadata Signing**: All approved biological design outputs are cryptographically signed with metadata detailing the user's credentials, intent, and authorization history. This signature must be provided to downstream DNA synthesis providers to verify the legitimacy of the order.
    

## Unified System Integration Blueprint and Implementation Roadmap

To build a high-fidelity clone of Google DeepMind's Co-Scientist, the stateless database connectors (MCP servers), the structured cognitive protocols (Skills), and the empirical search engines (ERA) must be integrated into a unified runtime environment.

In this unified architecture, the Supervisor agent acts as the central coordinator, dynamically invoking MCP servers to gather literature context, executing tree-search-driven sandboxes to optimize code, and utilizing the pre-registration skill to maintain scientific rigor.

```
                
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
              
  • framing-questions       • PubMed MCP             • FUTS Tree Search
  • preregistering          • OpenAlex MCP           • execute_fn Validation
  • anomaly-investigation   • ChEMBL / AACT          • Pinned Environments
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  ▼
                   
                      • Pairwise Debate (Reflection)
                      • Mathematical Elo Ranking
                                  │
                                  ▼
                  
                      • Structural Toxicity Check
                      • Cryptographic Metadata Sign
                                  │
                                  ▼
                    
```

Implementing this system is divided into six progressive development sprints:

|**Sprint ID**|**Phase Objective**|**Architecture Target**|**Verification Tests**|**Operational Exit Criteria**|
|---|---|---|---|---|
|**Sprint 1**|Dynamic Multi-Agent Foundation|Build the core Supervisor and agentic worker queue configurations.|Mock task execution DAG routing.|Successful parallel task routing across mock worker agents.|
|**Sprint 2**|MCP Infrastructure Integration|Deploy literature and chemical MCP servers (PubMed, OpenAlex, ChEMBL).|Automated entity lookup and citation queries.|End-to-end data retrieval with query execution times under 500ms.|
|**Sprint 3**|Rigorous Pre-Registration|Implement the Git-based pre-registration and critical review skills.|Mock pre-registration Git file locking.|Zero data exploration allowed before timestamped pre-registration.|
|**Sprint 4**|Verification & Fact-Checking|Build the claim verification and hybrid contradiction resolution engine.|Verification scoring across SciFact benchmarks.|Contradiction classification accuracy exceeding 85%.|
|**Sprint 5**|Empirical Code Sandbox|Integrate the ERA FUTS tree search within an isolated execution sandbox.|Automated code optimization runs.|Successful execution and scoring of code variants against target metrics.|
|**Sprint 6**|Safety & Deployment|Integrate biosecurity filters, path validation, and managed access.|Simulated prompt injection and dual-use design attacks.|100% blocking of unauthorized dual-use designs and directory traversals.|

This comprehensive specification delivers an actionable blueprint for implementing a robust AI Co-Scientist clone.

By establishing a clear division of labor between stateless data interfaces (MCPs) and stateful cognitive workflows (Skills), and securing the runtime environment with layered safety filters, the system functions as a trusted, verifiable scientific partner capable of advancing biological and computational research.
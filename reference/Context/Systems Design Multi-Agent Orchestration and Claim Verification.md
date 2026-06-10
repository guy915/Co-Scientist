# Architectural Blueprint for a High-Fidelity AI Co-Scientist Clone: Systems Design, Multi-Agent Orchestration, and Scientific Claim Verification

The integration of artificial intelligence into the scientific discovery cycle has progressed from retrieval tools to autonomous multi-agent networks capable of generating novel hypotheses and planning laboratory validations. However, the practical utility of these systems is heavily constrained by empirical observation: unguided language models exhibit substantial logic drift, ignoring experimental data in 68% of operational sequences, and successfully revising their beliefs in response to contrary findings in only 26% of cases. To address these vulnerabilities, the system architecture of a 1:1 clone of Google DeepMind’s Co-Scientist must allocate the majority of its computational and execution resources to rigorous claim verification, evidence grading, and source auditing. This blueprint outlines the end-to-end design for a highly reliable, multi-agent scientific discovery engine, matching the product flow and rigorous performance benchmarks of advanced platforms.

## Technical Architecture and Product Workflow

To ensure parity with Google’s Hypothesis Generation and Gemini for Science environments, the cloned platform is designed around a dual-loop framework. The outer loop manages human-in-the-loop interaction, scoping, and final proposal synthesis, while the inner loop manages multi-agent task execution, competitive debate, and hypothesis evolution.

The user interface operates as an interactive research workstation. The user enters a high-level technical prompt, which the Intake agent translates into structured parameters during a conversational scoping session. The backend, built on a robust FastAPI framework and a long-running SQLite-backed task queue, coordinates the agents asynchronously to preserve state, enforce token budgets, and manage rate limits.

### The Gemini for Science Product Flow

|**Workflow Phase**|**Visible Product Element**|**Core Technical Mechanism**|**Underlying Data Artifact**|
|---|---|---|---|
|**Intake & Scoping**|Interactive Scoping Widget|Multi-turn interview to extract constraints, target parameters, and boundaries.|Run Specifications & Scoping Metadata|
|**Run Selection**|Standard / Advanced Toggle|Standard allocates lower compute-scaling; Advanced triggers deep test-time compute scaling.|Budget and Wall-Clock Allocations|
|**Agent Execution**|Live htmx/SSE Dashboard|Asynchronous scheduling via a transactional queue with lease-time logic.|SQLite Task State & Agent Logs|
|**Retrieval Layer**|Knowledge Base Connector|Model Context Protocol (MCP) literature search over PubMed, arXiv, and databases.|Normalized JSON Metadata & Vector Index|
|**Reporting & Export**|Report Generator & Export Tools|Synthesis of tournament results, claim states, and evidence grades into markdown.|Final Research Proposal & Clickable Citation Maps|
|**Downstream Synergy**|NotebookLM Integration Button|Semantic document parsing to enable follow-up interactive querying and sharing.|Markdown Package & Shared URL|

### The System Execution Loop

The underlying computational lifecycle systematically advances through the following structured sequence:

$$\text{Research Goal} \longrightarrow \text{Goal Refinement} \longrightarrow \text{Literature Grounding} \longrightarrow \text{Hypothesis Generation} \longrightarrow \text{Critique \& Reflection} \longrightarrow \text{Tournament Ranking} \longrightarrow \text{Evolution} \longrightarrow \text{Proposal Synthesis}$$

The setup is initiated when the user submits an open-ended challenge. The scoping agent refines this into an operational template, identifying the exact variables, pathways, or material properties of interest. The Literature Retrieval agent queries external corpora to build a local vector database of evidence. The Generation agent parses this knowledge to formulate initial candidates, which are immediately projected into a semantic coordinate space by the Proximity agent to identify clusters and ensure diverse exploration.

The Reflection agent acts as a virtual peer reviewer, checking each candidate for logical consistency and physical plausibility. The Ranking agent then pairs these candidates in an Elo-based tournament, conducting simulated debates to construct a real-time leaderboard. Top-ranked candidates are selected by the Evolution agent, which applies specific combination or simplification operations to optimize their quality. Finally, the Meta-Review agent compiles the entire evaluation trail, writing synthesized guidance back to the supervisor and outputting the final proposal.

## Agentic Roster and Orchestration Topology

To execute this lifecycle with high fidelity, the architecture organizes twelve distinct, role-specific agents under the control of a Supervisor coordinator. The Supervisor manages the execution flow using a transactional, SQLite-backed task queue that enforces bounded concurrency, lease-time verification, and dead-letter queue routing to survive transient API rate limits and execution failures.

```
                               ┌─────────────────┐
                               │   Supervisor    │◄──────────────────────────┐
                               └────────┬────────┘                           │
                                        │                                    │
                  ┌─────────────────────┼─────────────────────┐              │
                  ▼                     ▼                     ▼              │
         ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐     │ Append-Only
         │Intake/Scoping   │   │Lit Retrieval    │   │   Generation    │     │ Feedback
         └─────────────────┘   └─────────────────┘   └─────────────────┘     │ (Learning)
                  │                     │                     │              │
                  ▼                     ▼                     ▼              │
         ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐     │
         │   Proximity     │   │   Reflection    │   │ Citation Verify │     │
         └─────────────────┘   └─────────────────┘   └─────────────────┘     │
                  │                     │                     │              │
                  ▼                     ▼                     ▼              │
         ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐     │
         │  Elo Ranking    │   │    Evolution    │   │     Safety      │     │
         └─────────────────┘   └─────────────────┘   └─────────────────┘     │
                  │                     │                     │              │
                  └─────────────────────┼─────────────────────┘              │
                                        ▼                                    │
                               ┌─────────────────┐                           │
                               │   Meta-Review   │ ──────────────────────────┘
                               └────────┬────────┘
                                        │
                                        ▼
                               ┌─────────────────┐
                               │Report Synthesis │
                               └─────────────────┘
```

### The Twelve-Agent Orchestration Matrix

|**Agent Identity**|**Input Channels**|**Tool Integrations & Protocols**|**Target Outputs**|
|---|---|---|---|
|**Supervisor**|User goals, active queue status, and real-time run metrics.|Transactional task queue, state trackers, and SQLite database drivers.|Task-scheduling triggers, model configurations, and resource limits.|
|**Intake / Interview**|Natural language targets and conversational user responses.|Interactive progress tracker, scoping checklists, and interview templates.|Formal run specifications, parameter boundaries, and target variables.|
|**Literature Retrieval**|Search parameters, target genes, chemicals, or materials.|Model Context Protocol, PubMed API, Crossref API, and Semantic Scholar.|Normalized bibliographic JSON payloads and reference libraries.|
|**Generation**|Scoping specifications and retrieved literature databases.|Web search tools, specialized database connectors, and structure parsers.|Grounded initial hypotheses with indexed reference associations.|
|**Reflection**|Unreviewed hypotheses and target evaluation criteria.|Database cross-checkers, biological simulators, and logic rule-engines.|Comprehensive critiques, target gaps, and logical consistency ratings.|
|**Proximity / Clustering**|Active hypothesis coordinate sets and vector embeddings.|FAISS index, Voyage/OpenAI text embedders, and semantic clusterers.|Pairwise distance tables, cluster boundaries, and diversity mappings.|
|**Ranking**|Hypotheses sets, peer-review critiques, and debate logs.|Pairwise matchup schedulers, debate simulations, and Elo math engines.|Updated Elo ratings, leaderboard standings, and tournament traces.|
|**Evolution**|High-Elo hypotheses and structured reflection feedback.|Hypothesis combiners, simplifiers, and mutation prompts.|Optimized daughter hypotheses preserving tournament-tested properties.|
|**Meta-Review**|Complete tournament histories, debate transcripts, and reviews.|Logic aggregators, system performance profiling tools, and synthesis scripts.|System optimization guidelines and prompt directive updates.|
|**Citation Verification**|Candidate claims and linked raw citation strings.|Parsing models, full-text extractors, and dense semantic search engines.|Authenticity verdicts with passage grounding and confidence logs.|
|**Safety**|Generated hypotheses, evolved candidates, and database searches.|Red-teaming engines, chemical checkers, and biosecurity lists.|Compliance decisions, biosecurity logs, and execution block triggers.|
|**Report Synthesis**|Highly ranked hypotheses, verified citations, and audit logs.|Markdown compiler, layout engines, and visualization modules.|Consolidated Goal Reports and interactive HTML dashboard components.|

### Parallel Execution and Asynchronous Task Schedulers

The system relies on an asynchronous scheduler to manage long-running research tasks. When a run is initiated, the Supervisor decomposes the high-level goal into parallel tasks, pushing them to the SQLite queue with bounded concurrency levels to stay within API limit envelopes.

To achieve continuous system optimization without updating neural weights, the Meta-Review agent evaluates the debate logs and tournament matchups from the active cycle. It distills specific logic failures, repeating patterns, and strategic shortcuts, converting these observations into structured guidelines.

These guidelines are written directly back to the database and appended to the system prompt of the Supervisor for subsequent cycles. This loop allows the multi-agent system to adapt its search criteria dynamically, improving hypothesis quality as the run progresses.

### Dynamic Stopping Criteria

The Supervisor periodically evaluates the queue state and active database parameters to determine when to trigger run termination. The run is stopped when any of the following programmatic conditions are satisfied:

- **Budget Exhaustion**: The total cumulative execution cost hits the defined threshold:
    
    $$\text{USD}_{\text{spent}} \ge \text{USD}_{\text{limit}}$$
    
- **Wall-Clock Expiration**: The elapsed running time passes the defined deadline:
    
    $$\text{Time}_{\text{elapsed}} \ge \text{Time}_{\text{limit}}$$
    
- **Elo Stabilization**: The Elo rating of the top-$K$ hypotheses remains stable within a variance threshold of $\epsilon$ over the last $N$ tournament matchups:
    
    $$\max(\text{Elo}_{top\text{-}K}) - \min(\text{Elo}_{top\text{-}K}) \le \epsilon$$
    
- **Queue Starvation**: The SQLite queue returns empty, indicating all exploration paths and follow-up validation iterations have run to completion.
    
- **Operator Interruption**: The user triggers an external pause or abort command through the API or htmx dashboard.
    

## The Multi-Layered Citation and Claim Verification Engine

A major bottleneck of using generative language models in scientific workflows is citation fabrication. Unguided LLM output exhibits a 95.9% Type II citation hallucination rate, generating wrong-topic citations that point to real papers but do not support the claimed scientific context.

To guarantee research integrity, the clone implements a two-stage verification pipeline named DeepSciVerify, augmented with CiteGuard’s multi-agent checking logic.

```
Raw Claim and Associated Citation String
                  │
                  ▼
┌──────────────────────────────────┐
│      LLM Citation Parser         │ ──► Structured Fields (DOI, Title, arXiv)
└─────────────────┬────────────────┘
                  │
                  ▼
┌──────────────────────────────────┐
│ Phase 1: Abstract-Level verifier │ ──► Fetch Abstract via Retrieval Cascade
└─────────────────┬────────────────┘
                  │
                  ├─────────────────────────┐
                  ▼ (Verdict!= NEI)        ▼ (Verdict == NEI)
┌──────────────────────────────────┐   ┌──────────────────────────────────┐
│   Early Exit (Save & Continue)   │   │ Phase 2: Passage-Level Escalation│
└──────────────────────────────────┘   └─────────────────┬────────────────┘
                                                         │
                                                         ▼
                                       ┌──────────────────────────────────┐
                                       │   RAG Full-Text Extraction       │ ──► Parse PDF/HTML into Chunks
                                       └─────────────────┬────────────────┘
                                                         │
                                                         ▼
                                       ┌──────────────────────────────────┐
                                       │    Final LLM-as-a-Judge          │ ──► SUPPORTS | CONTRADICTS | NEI
                                       └──────────────────────────────────┘
```

The process begins when the Citation Verification agent intercepts a generated claim and its linked reference string. The agent uses a parser to convert the citation into structured fields, including the DOI, arXiv ID, URL, and paper title. These fields guide a multi-source retrieval cascade across OpenAlex, PubMed, Semantic Scholar, and Crossref to fetch the paper's metadata and abstract.

### Phase 1: Abstract-Level Early Exit

The Abstract-Level verifier $f_a$ compares the target claim $c$ against the retrieved abstract $e_a$ to output an initial classification label $y_a \in \{\text{SUPPORTS}, \text{CONTRADICTS}, \text{NEI}\}$. If $y_a$ is decisive—meaning the abstract provides sufficient context to support or refute the assertion—the engine executes an early exit. This stage successfully resolves 67% of citation verification tasks, protecting system resources and avoiding unnecessary full-text extraction costs.

### Phase 2: Passage-Level Escalation

If $f_a$ returns `NEI`, indicating the abstract does not contain sufficient details to verify the claim, the engine escalates the task to Phase 2. The system retrieves the full-text paper via open-access links, parses the document, and passes the text to a dense semantic retrieval workflow. The text is divided into chunks of $512$ tokens with a $32$-token overlap using Tiktoken encoding, which are then embedded using SPECTER2 to capture domain-specific semantic properties.

A cosine similarity search extracts the top-$k$ passages, which are evaluated by a secondary verifier model $f_p$ to output the final label. To align this evaluation with human expert judgment, the final verdict score is calibrated using isotonic regression, transforming the raw model probabilities into reliable confidence indicators.

### CiteGuard Multi-Dimensional Citation Evaluation

|**Evaluation Axis**|**Target Metric**|**Core Verification Technique**|**System Disposition**|
|---|---|---|---|
|**Link Works**|URL Accessibility and Response State.|Programmatic URL validation checking for HTTP errors (e.g., 404, 403), timeouts, or paywalls.|Failure ($0$) triggers immediate flag; Success ($1$) allows transition.|
|**Relevant Content**|Topical Alignment with Claim.|LLM-as-a-Judge comparison of the citation context against the first $5000$ characters of the document.|Non-relevant topics generate a rejection and require a new search.|
|**Fact Check**|Empirical and Quantitative Support.|Step-by-step verification comparing numerical, temporal, and entity assertions.|Discrepancies generate a contradiction label, weakening the claim.|

By implementing this structured, multi-dimensional audit trail, the clone ensures that no scientific claim enters the tournament or final report unless it has been explicitly validated against its cited sources.

## Research Integrity Auditing and Retraction Watch Integration

A core requirement for a high-fidelity scientific engine is the detection of retracted or compromised literature. Since 2024, the volume of papers containing invalid, AI-generated, or fabricated references has risen significantly, making continuous integrity auditing essential.

The system implements this safeguard by querying the production Crossref REST API, which acquired and natively integrated the Retraction Watch database in January 2025, deprecating previous Labs endpoints.

### Production API Query and Schema Parsing

For every candidate citation parsed by the verification engine, the system extracts the DOI and issues a REST call to the production Crossref endpoint :

`GET https://api.crossref.org/v1/works/{DOI_STRING}`

If the queried work has been modified, corrected, or formally retracted, the API returns a structured JSON response containing the `updated-by` or `update-to` array. The parser evaluates this array to determine the status and origin of the update :

JSON

```
"updated-by":],
      "date-time": "2019-07-26T00:00:00Z",
      "timestamp": 1564101600000
    },
    "record-id": 44124
  }
]
```

The system evaluates the `source` field, which distinguishes between retractions issued directly by the `"publisher"` and those curated by `"retraction-watch"`. If a match is detected, the `record-id` is used to cross-reference a local SQLite database compiled from the Retraction Watch CSV master, identifying the specific reason for the retraction (such as data manipulation, structural error, or ethical violations).

### Deterministic Claim Disposition State Machine

```
              Candidate Citation Extracted
                           │
                           ▼
             ┌───────────────────────────┐
             │   Production Crossref API │
             │      Retraction Check     │
             └─────────────┬─────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼ (No Retraction) ▼ (Retracted)     ▼ (Uncertain Metadata)
┌────────────────┐ ┌───────────────┐ ┌────────────────┐
│   YES State    │ │   NO State    │ │BORDERLINE State│
│(Verify & Save) │ │(Purge & Pivot)│ │(Warning Label) │
└────────────────┘ └───────────────┘ └────────────────┘
```

The system processes candidate citations through three distinct operational states, applying automated routing based on retraction status:

- **YES (Verified)**: The citation is active, has no retraction history, and is confirmed by the semantic verifiers. The claim is approved, and the reference is indexed with a clickable link in the final proposal.
    
- **NO (Rejected)**: The citation matches a retracted work in the Crossref payload. The reference is immediately purged from the active hypothesis workspace. The system activates a recursive correction mechanism: it traces all derivative claims built on this reference, invalidates their logical support, and forces the Generation and Evolution agents to rebuild those branches using verified sources.
    
- **BORDERLINE (Warning)**: The citation points to a valid work, but is flagged as a secondary review source rather than primary literature, or exhibits minor metadata discrepancies. The system appends a prominent `` label to the citation, records the event in the session audit log, and routes the claim to the researcher interface for manual approval.
    

## Algorithmic Evidence Grading and Synthesis

Generating high-Elo hypotheses requires evaluating the underlying strength of the supporting scientific evidence. To eliminate subjective bias, the engine automates the Grading of Recommendations Assessment, Development, and Evaluation (GRADE) framework.

Following the algorithmic approach of the URSE system, the engine parses literature abstracts and study designs to grade the certainty of evidence for targeted Intervention-Comparison-Outcome (I-C-O) triads.

The evidence certainty is initialized at a baseline level—set to `High` for randomized controlled trials (RCTs) and `Low` for observational studies. The system then runs a series of programmatic checks, applying downgrades of one or two levels if specific criteria are met.

### Pollock-GRADE Algorithmic Grading Model

|**Grading Factor**|**Underlying Quality Vulnerability**|**Programmatic Evaluation Metric**|**System Action**|
|---|---|---|---|
|**Imprecision**|Limited sample size or participant volume.|Total cumulative participants ($n$) across the evaluated studies.|Downgrade $1$ level if $100 \le n < 1000$; Downgrade $2$ levels if $n < 100$.|
|**Risk of Bias**|Methodological flaws in study design.|Percentage of study participants enrolled in low-risk trials.|Downgrade $1$ level if low-risk ratio is $30\%\text{--}75\%$; Downgrade $2$ levels if $<30\%$.|
|**Inconsistency**|High heterogeneity of outcomes.|Statistical heterogeneity index ($I^2$) reported in meta-analyses.|Downgrade $1$ level if $30\% < I^2 < 75\%$; Downgrade $2$ levels if $I^2 \ge 75\%$.|
|**Methodology Quality**|Poor reporting standard compliance.|Percentage of positive indicators on the AMSTAR checklist.|Downgrade $1$ level if AMSTAR score is $3/4$; Downgrade $2$ levels if score is $\le 2/4$.|
|**Indirectness**|Mismatches in study populations or settings.|Semantic similarity between the studied population and target goal.|Downgrade $1$ level for surrogate outcomes; Downgrade $2$ levels for extreme population drift.|

If the initial body of evidence consists of observational studies (starting at `Low`), the grading engine can apply upgrades of one or two levels :

- **Large Magnitude of Effect**: Upgrade $1$ level if the observed relative risk is $> 2.0$ or $< 0.5$ in the absence of systematic bias; Upgrade $2$ levels if the relative risk is $> 5.0$ or $< 0.2$.
    
- **Dose-Response Gradient**: Upgrade $1$ level if the source papers demonstrate a clear dose-response relationship across treatment cohorts.
    
- **Confounding Inversion**: Upgrade $1$ level if all plausible confounding factors would reduce the observed treatment effect, or suggest a spurious effect where none was observed.
    

The final sum of downgrades and upgrades determines the certainty level assigned to the hypothesis. This rating is compiled into the final Goal Report, modulating the recommendation strength.

A strong recommendation suggests the hypothesis is backed by high-certainty evidence with minimal downside, while a weak recommendation indicates that further shared validation or experimental exploration is required due to low underlying certainty.

## Feature-Level Novelty Assessment and Overclaiming Detection

A persistent issue with generative scientific models is "overclaiming"—proposing hypotheses as radically novel when they are merely incremental variations of existing literature.

To enforce rigorous novelty detection, the clone moves away from simple vector cosine similarity. It implements a feature-level comparison pipeline based on the OpenNovelty and PANORAMA frameworks, evaluating technical claims against patent databases and academic literature.

```
              Candidate Hypothesis Abstract
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Phase I: Claim Decomposition                           │
│ • Deconstruct hypothesis into independent features.     │
│ • Formulate target queries for patent/NPL databases.   │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Phase II: High-Coverage Retrieval                      │
│ • Query 170M+ patents and 220M+ literature records.     │
│ • Extract passage-level prior art candidates.          │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Phase III: Feature-Level Overlap Mapping               │
│ • Cross-examine each feature against prior art.        │
│ • Assign Overlap: Full (Red), Partial (Yellow), None.   │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Phase IV: Novelty Score Calculation                    │
│ • Compute final metric: Uniqueness = Green / Total.    │
│ • Output structured report with feature justifications.│
└────────────────────────────────────────────────────────┘
```

The system first parses the hypothesis, extracting its primary components, mechanisms, target variables, and materials. These are used to generate search queries that run against global patent databases (spanning over 170 million documents) and non-patent literature databases (spanning over 220 million articles).

Once the candidate documents are retrieved, the system compares the extracted hypothesis features against passage-level evidence in the prior art, assigning an overlap status :

- **Full Overlap (Red)**: The feature is explicitly disclosed in the prior art, indicating it lacks patentable or conceptual novelty.
    
- **Partial Overlap (Yellow)**: The feature is conceptually present but utilizes a different operational mechanism, host, or environment.
    
- **No Overlap (Green)**: The feature is completely absent from the prior art, representing a genuinely novel technical step.
    

The system synthesizes these evaluations into a structured Novelty Report. The final novelty score is computed as the ratio of green features to total features, ensuring that any claims of originality are fully traceable to gaps in existing patent and academic databases.

## Temporal Staleness and Contradiction Reconciliation

Scientific knowledge is dynamic, meaning once-valid discoveries can be superseded or contradicted by newer findings over time.

To handle the complexity of stale and conflicting evidence, the system architecture incorporates a typed hybrid state representation based on the ReSSERAct framework, treating data freshness and contradictions as first-class control variables.

The current system state at any time step $t$ is modeled as a tuple:

$$S_t = (b_t, L_t)$$

Here, $b_t$ is the posterior probability belief over the validity of the active hypothesis, and $L_t$ represents four structured ledgers that manage state information over time :

$$L_t = (u_t, v_t, r_t, c_t)$$

The **Uncertainty Ledger** ($u_t$) tracks the mathematical entropy of agent beliefs. The **Temporal Validity Ledger** ($v_t$) monitors the chronological age and freshness of retrieved papers, flagging when a citation has been superseded by newer studies.

The **Replay Ledger** ($r_t$) logs previous execution paths to prevent the agents from getting stuck in repetitive logical loops. The **Control Ledger** ($c_t$) coordinates real-time corrections when inconsistencies are detected.

When the verifiers return conflicting claims, the system uses a formal Abstract Argumentation Framework (AF) to resolve the dispute. The AF is constructed as a directed graph where nodes ($A, B, C$) represent scientific claims extracted from the literature, and edges represent attack or support relations.

```
                     Claim A: Kinase Inhibitor Blocks Pathway
                                    ▲
                                    │ (Attacks)
                                    │
                     Claim B: Mutation Causes Drug Resistance
                                    ▲
                                    │ (Attacks)
                                    │
                     Claim C: Western Blot Assay Verification
```

The system evaluates the graph to identify stable, conflict-free extensions, ensuring that the final proposals are logically consistent with the broader body of literature.

If a contradiction is detected during a run, the system triggers the Self-Healing Executor loop from AutoResearchClaw, allowing the Supervisor to pivot the exploration path or refine the hypothesis parameters rather than terminating the run.

## System Safeguards and Biosecurity Enforcement

The deployment of autonomous multi-agent systems in the life sciences introduces critical biosecurity and physical safety risks. High-capacity agents capable of writing code and orchestrating biological models (like protein-design networks) can make dangerous biological information more accessible, and accelerate the design of dual-use biological materials.

To prevent these risks, the clone implements a multi-layered safety and biosecurity defense architecture.

```
               Goal / Query Input
                       │
                       ▼
         ┌───────────────────────────┐
         │    Red-Teaming Layer      │ ──► Automated Adversarial Testing
         └─────────────┬─────────────┘
                       │
                       ▼
         ┌───────────────────────────┐
         │   Internal Safety Agent   │ ──► Monitors Inter-Agent Communication
         └─────────────┬─────────────┘
                       │
                       ▼
         ┌───────────────────────────┐
         │ External Boundary Filters │ ──► Deterministic CBRN & Synthesis Blocks
         └───────────────────────────┘
```

The **Red-Teaming Layer** uses automated adversarial testing to simulate attacks (such as safety filter evasion or requests for hazardous protocols), using these test runs to harden the core language models.

The **Internal Safety Agent** acts as an active supervisor within the agent network, monitoring all inter-agent communication to identify and intercept unauthorized biological or chemical pathways.

The **External Boundary Filters** serve as a deterministic guardrail, intercepting all outbound API requests, tool calls, and final outputs. This layer enforces strict, rule-based blocks to prevent:

- The generation of step-by-step protocols for creating, obtaining, or dispersing chemical, biological, radiological, or nuclear (CBRN) weapons.
    
- The design of pathogens optimized for immune evasion, enhanced transmission, or environmental stability.
    
- Actionable instructions for ordering regulated genetic materials or synthetic DNA.
    

This multi-layered approach allows the system to accelerate beneficial scientific workflows while blocking the automated generation of actionable hazard protocols.

## System Implementation and Evaluation Synthesis

To build and evaluate the AI Co-Scientist clone, developers should implement a dual-phase deployment strategy focused on system similarity and empirical validation.

```
┌────────────────────────────────────────────────────────┐
│ Phase 1: Infrastructure Integration                    │
│ • Build SQLite-backed task queue with lease logic.    │
│ • Configure LiteLLM to orchestrate core models.       │
│ • Deploy PubMed and arXiv MCP search servers.         │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Phase 2: Claim Verification Pipeline                   │
│ • Integrate production Crossref API retraction checks. │
│ • Deploy DeepSciVerify and CiteGuard verifier agents.  │
│ • Set up ReSSERAct typed hybrid state engine.          │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Phase 3: Benchmarking and Calibration                 │
│ • Run parallel vs direct single-model evaluations.     │
│ • Track Elo rating trajectories over 100+ runs.       │
│ • Calibrate verifier scores using isotonic regression. │
└────────────────────────────────────────────────────────┘
```

The infrastructure is built on a transactional SQLite database queue, utilizing LiteLLM to handle connections across multiple model providers. To enable literature-aware reasoning, developers must deploy Model Context Protocol (MCP) servers connected to PubMed and arXiv, allowing the agents to query and retrieve papers in real-time.

### Evaluation Metrics and Similarity Benchmarks

To ensure the clone matches the performance of the baseline system, developers must evaluate the platform across five core axes:

- **Product Flow Similarity**: Verify that the system follows the correct sequence from interactive interview-style scoping to final report synthesis.
    
- **Elo Tournament Trajectory**: Monitor the Elo rating distribution over sliding windows of 100+ tournament runs to verify that competitive debates produce clear leaderboards without rating stagnation.
    
- **Citation Accuracy**: Target a link validity score of $> 94\%$ and factual claim support of $> 80\%$ using the DeepSciVerify and CiteGuard pipelines.
    
- **Retraction Compliance**: Ensure the system instantly identifies and purges retracted papers from the active workspace by querying the production Crossref API.
    
- **Safety & Biorisk Enforcement**: Confirm that all requests for dangerous chemical synthesis or pathogen design are successfully blocked by the multi-layered biosecurity filters.
    

By building the platform around a highly distributed, verification-heavy multi-agent architecture, developers can deliver a scientific discovery engine that generates novel, high-Elo hypotheses backed by structured, fully auditable evidence.
# Architecture and Context Engineering Specification for a Multi-Agent AI Co-Scientist System

## System Design Paradigm and the Scientist-in-the-Loop Workflow

The development of a multi-agent automated scientific discovery platform demands a transition from linear, single-prompt chat systems to a decentralized, asynchronous, and collaborative computational ecosystem. Built on advanced frontier models, this architecture mirrors the iterative rigor of the scientific method. By scaling test-time compute, the system allocates extensive processing budgets to explore multiple hypothesis paths in parallel, executing deep literature reviews, peer debates, and simulated validations. Wet-lab validations have demonstrated the real-world efficacy of this approach, uncovering non-obvious therapeutic mechanisms in oncology, identifying anti-fibrotic targets, and predicting bacterial evolutionary trajectories.

For a project director aiming to build a high-fidelity clone of DeepMind's Co-Scientist, the primary engineering objective is establishing a structured, automated workflow. The platform must operate under a "scientist-in-the-loop" paradigm, allowing human experts to guide, steer, and validate the automated process without requiring manual context-passing or coding. The visible product target maps a complete user-facing lifecycle:

```
  +-------------------------------------------------------------+
  |                   RESEARCH-GOAL SETUP                       |
  |  - Scientist enters objective in natural language           |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |                 INTERVIEW-STYLE SCOPING                     |
  |  - Intake/Interview Agent elicits constraints & parameters  |
  +-------------------------------------------------------------+
                                 |
              +------------------+------------------+
              |                                     |
              v (Standard Run)                      v (Advanced Run)
  +------------------------+            +------------------------+
  |      STANDARD RUN      |            |      ADVANCED RUN      |
  |  - Capped token budget |            |  - Max compute scaling |
  |  - Accelerated reviews |            |  - Deep simulations    |
  +------------------------+            +------------------------+
              |                                     |
              +------------------+------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |              DYNAMIC KNOWLEDGE BASE & SUMMARY               |
  |  - SQLite & Vector stores update real-time execution stats  |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |                 FINAL PROPOSAL GENERATION                   |
  |  - System synthesizes proposal in NIH Specific Aims format   |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |                  FOLLOW-UP INTERACTION                      |
  |  - Conversational feedback loops & targeted mutations       |
  +-------------------------------------------------------------+
```

1. **Research-Goal Setup:** The user inputs a high-level scientific goal in simple natural language.
    
2. **Interview-Style Scoping:** A specialized intake agent conducts an interactive dialog, clarifying boundaries, preferred drug classes, target biological pathways, and budget limitations.
    
3. **Run Configuration:** The system translates these parameters into a structured Run Specification document. The user selects either a Standard Run (optimized for rapid exploration and lower cost) or an Advanced Run (which scales test-time compute through deep tournament rounds, extensive citation audits, and physical simulations).
    
4. **Iterative Execution Queue:** The system executes the plan via a concurrent, asynchronous job queue, writing intermediate states to a centralized data store.
    
5. **Knowledge Base and Summary Dashboard:** A web-based interface displays progress, active task states, and real-time tournament standings.
    
6. **Final Proposal Generation:** The system synthesizes the top-ranked, evolved hypotheses into a structured research proposal, matching the format of grant applications such as the NIH Specific Aims template.
    
7. **Follow-up Interaction:** The user provides targeted conversational feedback (e.g., directing the system to focus on specific pathways), which initiates further mutation and refinement cycles.
    

|**Parameter**|**Standard Run**|**Advanced Run**|
|---|---|---|
|**Primary Objective**|Rapid conceptual mapping and lower API spend.|High-fidelity scientific discovery with maximum novelty.|
|**Compute Scaling**|Bounded iterations; shallow peer-review rounds.|Unbounded iterations; multi-tiered deep reviews.|
|**Database Grounding**|Text retrieval from basic search and PubMed.|Direct API querying of ChEMBL, UniProt, and AlphaFold.|
|**Review Complexity**|Initial and Full Reviews only.|Deep Verification, Observation, and Simulation Reviews.|
|**Evolution Method**|Simple concept merging and pruning.|Multi-agent self-evolution (IDE, IVE, ESE modules).|
|**Typical Wall-Clock Limit**|10 to 30 minutes.|12 to 48 hours (prolonged reasoning).|
|**Target Output**|Basic conceptual overview and summary.|NIH-formatted grant proposals with verified citations.|

## Decentralized Agent Coalition and Task Orchestration

To run this complex workflow without human intervention, the system delegates tasks across twelve specialized agents. Rather than relying on a single model with a complex system prompt, this architecture separates responsibilities into distinct modules. This design allows the system to scale compute efficiently and prevents context window degradation.

The coordination of this coalition is managed by a Supervisor agent, which acts as an adaptive planner. Unlike linear execution scripts, this supervisor translates the research goals into dynamic tasks, schedules them in a SQLite-backed queue, manages parallel executions, and tracks token budgets.

```
                  +--------------------------------+
                  |        SUPERVISOR AGENT        | <---+
                  |  - Manages SQLite Task Queue   |     |
                  +--------------------------------+     |
                                  |                      |
            +---------------------+---------------------+|
            |                     |                     ||
            v                     v                     v|
  +------------------+  +------------------+  +------------------+
  | INTAKE/INTERVIEW |  | LIT RETRIEVAL    |  |  SAFETY AGENT    |
  | - Scopes goals   |  | - Queries PubMed |  | - CBRN filters   |
  +------------------+  +------------------+  +------------------+
            |                     |                     |
            +---------------------+---------------------+
                                  |
                                  v
  +-------------------------------------------------------------+
  |                       HYPOTHESIS LOOP                       |
  |  - Generation -> Reflection -> Proximity -> Ranking -> Evolve|
  +-------------------------------------------------------------+
                                  |
                                  v
  +-------------------------------------------------------------+
  |                        OUTPUT LAYER                         |
  |  - Citation Verification -> Report Synthesis                |
  +-------------------------------------------------------------+
```

- **Supervisor Agent:** Parses high-level objectives, schedules tasks in a SQLite database, manages parallel threads, and tracks execution budgets.
    
- **Intake/Interview Agent:** Conducts the initial scoping dialogue with the user, extracting specific experimental constraints and parameters.
    
- **Literature Retrieval Agent:** Queries external databases (such as PubMed, Web Search, ChEMBL, and UniProt) to compile raw scientific papers and dataset records.
    
- **Generation Agent:** Uses simulated scientific debates to formulate novel hypotheses, grounding them in established literature foundations.
    
- **Reflection Agent:** Simulates a peer-review panel, running five distinct review tiers to verify correctness, testability, and logical coherence.
    
- **Proximity/Clustering Agent:** Computes semantic vector embeddings of hypotheses, grouping related ideas to eliminate duplicates and organize tournament pairings.
    
- **Ranking Agent:** Runs head-to-head Elo tournaments, using simulated debates between hypotheses to determine relative scientific strength.
    
- **Evolution Agent:** Refines top-performing hypotheses by combining related concepts, applying cross-disciplinary analogies, and addressing critiques from the Reflection agent.
    
- **Meta-Review Agent:** Consolidates tournament statistics, identifies conceptual patterns, and provides feedback to optimize subsequent generation rounds.
    
- **Citation Verification Agent:** Performs strict semantic audits on all generated citations, verifying claims against retrieved source documents to prevent hallucinations.
    
- **Safety Agent:** Scans inputs and generated hypotheses for chemical, biological, radiological, and nuclear (CBRN) hazards.
    
- **Report Synthesis Agent:** Compiles the final ranked hypotheses, validation histories, and experimental designs into a structured, publication-grade proposal.
    

|**Agent Name**|**Core Inputs**|**Primary Outputs**|**Context Footprint & Memory Management**|
|---|---|---|---|
|**Supervisor**|User goals, run configurations, system metrics.|Task assignments, queue schedules, run stats.|Minimal footprint; reads and writes metadata to SQLite; does not ingest raw text.|
|**Intake/Interview**|Raw user prompts, scoping template.|Run Specifications, parameter boundaries.|Bounded by dialogue history; summarizes user preferences into a persistent JSON schema.|
|**Lit Retrieval**|Search keywords, database queries.|Raw abstracts, paper metadata, API payloads.|High external I/O; writes raw data to a vector store, passing only IDs to other agents.|
|**Generation**|User parameters, literature abstracts, past ideas.|Initial hypothesis nodes, experimental plans.|Highly focused; utilizes summarized literature contexts to prevent window bloat.|
|**Reflection**|Hypothesis nodes, verification queries.|Structured review logs, validation scores, critiques.|Local scratchpad; pulls targeted literature sections to verify specific assumptions.|
|**Proximity**|Hypothesis text strings.|Cosine similarity vectors, cluster mappings.|Zero conversation history; processes single text strings to compute vector embeddings.|
|**Ranking**|Pairs of hypotheses, review records.|Debate transcripts, winner decisions, Elo updates.|Private scratchpad; matches are run in isolated contexts, appending only ratings to KSDS.|
|**Evolution**|Top hypotheses, critique logs, analogies.|Mutated, higher-quality hypothesis nodes.|Structured prompt inheritance; tracks parent-child lineage in the database.|
|**Meta-Review**|Historical tournament statistics, critique trends.|Optimization directives, system feedback.|Consolidates tournament and critique histories into highly compressed summaries.|
|**Citation Verification**|Hypothesis citations, reference documents.|Alignment verdicts, corrected citations.|Bounded to the evaluated claim and the matching section of the source document.|
|**Safety**|Hypotheses, target biological entities.|Safety scores, hazard warnings, halt signals.|Fast classification; uses structured templates to scan for known dangerous agents.|
|**Report Synthesis**|Evolved hypotheses, tournament logs, citations.|Final publication-grade research proposal.|High capacity; processes the structured KSDS tree to build the final markdown document.|

## Multi-Tier Memory Hierarchy and State Synchronization

Managing context in a long-running, multi-agent scientific platform requires addressing memory as a systems architecture challenge. Simply appending raw logs to model inputs quickly leads to context bloat, attention degradation, and incorrect claims. To maintain performance, the system must deploy a structured, multi-tier memory hierarchy.

```
  +-----------------------------------------------------------------+
  |                       I/O & TOOL BUFFER                         |
  |  - Web Search, PubMed, ChEMBL, UniProt, AlphaFold               |
  +-----------------------------------------------------------------+
                                  |
                                  v
  +-----------------------------------------------------------------+
  |                     WORKING SEMANTIC CACHE                      |
  |  - Isolated Agent Scratchpads (A-T-O sequences)                 |
  |  - Ephemeral conversation and debate histories                  |
  +-----------------------------------------------------------------+
                                  |
                                  v
  +-----------------------------------------------------------------+
  |                  PERSISTENT CONCURRENT STORE                    |
  |  - Relational SQLite Queue (Run parameters, task execution metadata) |
  |  - Structured KSDS JSON (Durable, version-controlled state)     |
  |  - Vector Document Store (Embedded papers and abstracts)        |
  +-----------------------------------------------------------------+
```

### The Hybrid Shared-Distributed Memory Paradigm

To balance collaboration with computational efficiency, the platform uses a hybrid shared-distributed memory paradigm.

- **Shared Memory (The Blackboard):** Enforced via a central relational database and a structured, version-controlled JSON document known as the _Knowledge State Data Structure (KSDS)_. This central repository ensures a single source of truth, tracking task updates, active hypotheses, and tournament standings.
    
- **Distributed Memory (Agent Scratchpads):** Individual agents run their step-by-step reasoning, external tool calls, and initial drafts in isolated, local caches. This prevents messy, intermediate computational traces from cluttering the central blackboard, protecting the context windows of other agents.
    

Once an agent completes a task, it compiles and compresses its findings, persisting only the structured update to the global KSDS.

### The Knowledge State Data Structure Schema

The KSDS is a structured JSON document that tracks the evolving state of the research session. This format enforces consistent data structures, allowing agents to reliably read, update, and validate information across the entire lifecycle.

JSON

```
{
  "session_id": "session_microbiome_2026_06",
  "run_specifications": {
    "research_goal": "Identify hypotheses about microbiome-driven inflammation",
    "budget_usd": 2.00,
    "wall_clock_limit_seconds": 600,
    "scoping_constraints": {
      "excluded_taxa":,
      "focus_pathways":
    }
  },
  "hypothesis_nodes": [
    {
      "id": "hyp_node_001",
      "parent_ids":,
      "author_agent": "GenerationAgent",
      "claim": "Segmented filamentous bacteria drive Th17 differentiation via serum amyloid A induction",
      "proposed_experimental_protocol": "Aerosolized administration of anti-SAA antibodies in murine models...",
      "vector_embedding_id": "vec_hyp_001",
      "elo_rating": 1245.5,
      "tournament_match_history": [
        {"match_id": "m_001", "opponent_id": "hyp_node_002", "verdict": "win", "elo_delta": 16.2}
      ],
      "reflection_critiques":
        }
      ],
      "grounding_citations":
    }
  ],
  "system_statistics": {
    "total_tokens_consumed": 450120,
    "current_queue_status": "active_ranking",
    "active_concurrency_count": 3
  }
}
```

This structured format allows parallel agents to access the same state safely. For example, while the Ranking agent updates Elo scores, the Proximity agent can read the active hypothesis nodes to re-calculate similarity matrices without risking data corruption or state conflicts.

## Trajectory Compression and Context Engineering Protocols

Sustaining accuracy across long-running multi-agent sessions requires active context management. Simply relying on large context windows is insufficient, as models naturally degrade when processing long, uncompressed histories. The platform addresses this by implementing three complementary compression and retrieval protocols.

### Trajectory Compression and Code-to-Language Abstraction

As agents execute searches and generate draft code, their working memory accumulates verbose, unstructured traces. Left unmanaged, this noise leads to attention failures like the "lost-in-the-middle" effect. To prevent this, the platform uses a code-to-language abstraction protocol.

A specialized summarization pipeline intercepts the raw Action-Thought-Observation (A-T-O) sequences of active agents. It strips out raw JSON payloads, terminal logs, and repetitive steps, distilling the entire trajectory into a concise, natural-language summary.

This abstract captures only the key actions, parameters, and outcomes, preserving the logical flow while reducing token consumption by up to 90%.

### Epistemic State Summarization via Persistent Memories

To prevent agents from repeating mistakes or executing redundant search queries, the system implements a dual-module persistent memory architecture. Managed by an automated manager, this architecture separates conceptual findings from functional code patterns:

- **Ideation Memory ($M_I$):** Tracks successful scientific directions and, crucially, logs failed directions and invalid assumptions identified during critiques. Before starting a generation task, the system retrieves these historical failures and appends them to the agent's prompt, preventing the model from exploring previously refuted concepts.
    
- **Experimentation Memory ($M_E$):** Stores successful data-processing routines, code templates, and API configuration scripts. When an engineering agent is tasked with running a simulation, it retrieves these proven code blocks, significantly increasing code execution success rates over time.
    

### Hierarchical Citation Graphs

To prevent literature reviews from overwhelming model context windows, the platform structures paper databases into a Hierarchical Citation Graph ($G_C$). In this graph, nodes represent individual papers, and edges capture citation dependencies and semantic similarity. The graph is organized into three distinct layers:

$$\text{Layers}(G_C) = \{\text{Foundation}, \text{Development}, \text{Frontier}\}$$

The Foundation layer holds classic, seminal works; the Development layer tracks subsequent methodologies and incremental changes; and the Frontier layer maps emerging papers and active discussions.

```
  +-------------------------------------------------------------+
  |                        FRONTIER LAYER                       |
  |  - Active preprints, emerging discussions, recent findings   |
  +-------------------------------------------------------------+
                                 ^
                                 |  Vertical Traversal
                                 v
  +-------------------------------------------------------------+
  |                      DEVELOPMENT LAYER                      |
  |  - Subsequent methodologies, incremental improvements       |
  +-------------------------------------------------------------+
                                 ^
                                 |  Vertical Traversal
                                 v
  +-------------------------------------------------------------+
  |                      FOUNDATION LAYER                       |
  |  - Classic, seminal works and fundamental theories          |
  +-------------------------------------------------------------+
```

To extract relevant context without pulling massive document sets, the retrieval agent uses a graph traversal mechanism. It performs horizontal searches within layers to find closely related papers, and vertical depth traversals across layers to trace how a concept evolved from its foundation to the frontier.

The agent compiles these findings into multi-aspect summaries. By passing only these structured, highly-focused summaries to the generation agents, the system preserves deep, multi-level scientific context while keeping token usage minimal.

## Tournament Mechanics and Elo-Driven Evolution

To continuously improve hypothesis quality, the platform uses an Elo-based self-evaluation tournament. By pitting generated proposals against each other in structured, pairwise debates, the system leverages test-time compute to identify the strongest conceptual leads.

```
  +-------------------------------------------------------------+
  |                     HYPOTHESIS PAIRING                      |
  |  - Proximity Agent clusters similar hypotheses              |
  |  - Selects diverse pairs to avoid redundant debates         |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |                     SIMULATED DEBATE                        |
  |  - Challenger & Defender debate feasibility and novelty      |
  |  - Panel of LLM judges evaluates arguments                  |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |                      ELO RATING UPDATE                      |
  |  - Calculates expected outcomes & updates node ratings       |
  |  - Writes tournament standings back to KSDS                 |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |                   EVOLUTIONARY MUTATION                     |
  |  - Selects high-Elo parents                                 |
  |  - Applies mutation operators (analogy, simplification)     |
  |  - Routes mutated offspring back to tournament pool         |
  +-------------------------------------------------------------+
```

### Pairing Strategy and Debate Protocols

Running unstructured, random matches across a large pool of hypotheses is computationally inefficient and can lead to repetitive debates. To address this, the system uses the Proximity agent's clustering statistics to guide pairings.

The Proximity agent embeds all active hypotheses and groups them into clusters based on cosine similarity. The Ranking agent then selects pairs from different clusters to ensure conceptual diversity, preventing highly similar ideas from competing against each other early in the process.

Once a pair is selected, the Ranking agent initiates an isolated debate session. One hypothesis is designated as the defender, and the other acts as the challenger.

Specialized debating models argue the relative feasibility, novelty, and safety of their respective hypotheses. A panel of independent model judges reviews the arguments and issues a final verdict.

### Mathematical Models for Elo and Probability Distributions

Let $R_A$ and $R_B$ be the current Elo ratings of hypothesis $A$ and hypothesis $B$. The expected probability $P(A > B)$ that hypothesis $A$ wins the debate is calculated using a logistic distribution :

$$P(A > B) = \frac{1}{1 + 10^{(R_B - R_A)/400}}$$

Once the judges declare a winner, the ratings are updated :

$$R'_A = R_A + K \cdot (S_A - P(A > B))$$

$$R'_B = R_B + K \cdot (S_B - P(B > A))$$

where $K$ represents the rating volatility factor (typically set to 32), and $S$ represents the actual outcome score ($S = 1$ for a win, $S = 0$ for a loss, and $S = 0.5$ for a draw).

The updated Elo ratings are written directly back to the KSDS. This metric serves as an automated evaluation score. Systematic tests show that higher Elo ratings correlate strongly with accuracy on challenging benchmarks like the GPQA diamond set.

### The Evolutionary Mutation Loop

Top-performing hypotheses (those with the highest Elo ratings) are selected as parents for the next generation. The Evolution agent retrieves these parent nodes, reads their historical critique logs from the KSDS, and applies targeted mutation operators :

- **Analogical Mapping:** Applies a successful mechanism from a different biological domain to the parent hypothesis (e.g., adapting an oncology target mechanism to fight liver fibrosis).
    
- **Simplification and Pruning:** Strips away over-engineered steps to make the proposed experimental design more feasible and cost-effective.
    
- **Critique Patching:** Directly addresses specific vulnerabilities flagged by the Reflection agent, strengthening the hypothesis's logical grounding.
    

The resulting mutated hypotheses are saved back to the KSDS as new nodes, linking back to their parent IDs to preserve lineage. This self-improving loop allows the platform to iteratively scale test-time compute, driving the pool toward higher-quality, more innovative proposals.

## Grounding, Citation Auditing, and Safety Controls

To ensure that generated hypotheses are both scientifically valid and safe, the platform implements a multi-tiered verification and safety architecture. This pipeline acts as a critical filter, catching hallucinations and blocking hazardous research designs before they reach the final proposal.

### The Multi-Tier Peer-Review Pipeline

The Reflection agent evaluates hypotheses through five distinct review tiers, scaling the depth of evaluation based on the run configuration :

1. **Initial Review:** A fast, low-cost critique designed to quickly flag and discard structurally flawed, non-novel, or biologically impossible proposals.
    
2. **Full Review:** An in-depth evaluation that pulls target literature and searches external databases to verify the foundational assumptions of the hypothesis.
    
3. **Deep Verification Review:** A granular audit designed to detect subtle errors, physical contradictions, or mathematical inconsistencies in complex proposals.
    
4. **Observation Review:** An empirical check that evaluates whether a hypothesis can account for unexplained, long-tail observations from historical wet-lab experiments.
    
5. **Simulation Review:** A physical sanity check that leverages specialized external models (such as molecular dynamics, docking tools, or structural prediction networks like AlphaFold) to test physical viability.
    

### Citation Auditing and Entailment Checks

To prevent models from citing non-existent or irrelevant literature, the Citation Verification agent audits every citation generated within the system.

For each cited claim, the agent retrieves the actual source paper's abstract or full text via APIs. It then runs a semantic entailment audit to evaluate the alignment between the generated claim and the source text.

Let $C$ be the generated claim, and $S$ be the retrieved source text. The agent calculates an entailment score $E(C, S) \in $. If the score falls below a strict threshold (typically 0.85), the citation is rejected.

The system then either searches for an alternative, valid reference or flags the hypothesis node for adjustment. This audit ensures that all final proposals are grounded in verifiable, peer-reviewed literature.

### CBRN Safety Controls and Adversarial Testing

Given the platform's ability to automate biological and chemical research designs, robust safety guardrails are essential. The Safety agent acts as an independent gatekeeper, scanning all incoming prompts and generated proposals for chemical, biological, radiological, and nuclear (CBRN) hazards.

```
  +-------------------------------------------------------------+
  |                     HYPOTHESIS GENERATION                   |
  |  - Generation Agent proposes drug target/chemical pathway  |
  +-------------------------------------------------------------+
                                 |
                                 v
  +-------------------------------------------------------------+
  |                        SAFETY SCAN                          |
  |  - Safety Agent reviews proposal against CBRN catalogs     |
  |  - Identifies dual-use hazards or toxic synthesis designs   |
  +-------------------------------------------------------------+
                                 |
              +------------------+------------------+
              |                                     |
              v (No Hazard Detected)                v (Hazard Flagged)
  +------------------------+            +------------------------+
  |    APPROVE FOR QUEUE   |            |     TRIGGER LOCKOUT    |
  |  - Node cleared for    |            |  - Task halted         |
  |    active tournament.  |            |  - Incident logged     |
  +------------------------+            +------------------------+
```

To validate this safety layer, the platform uses an adversarial testing database consisting of over 1,200 malicious, dual-use prompts across 40 scientific domains. The Safety agent must achieve a zero-bypass record during these adversarial tests, successfully identifying and blocking toxicological synthesis paths or viral engineering proposals before they can be scheduled in the queue.

## System Evaluation and Fidelity Metrics

To build a high-fidelity clone of DeepMind's Co-Scientist, the system must be systematically evaluated against the original platform's behaviors, latency profiles, and output quality. The table below defines the evaluation metrics and target criteria for the clone:

|**Evaluation Dimension**|**Metric / Target State**|**Core Verification Protocol**|
|---|---|---|
|**Product Flow & Terminology**|High similarity in scoping prompts, Run Specifications, Standard vs. Advanced execution, and user feedback directives.|Complete a full walkthrough of the interview-style scoping workflow, verifying that the system generates a structured JSON Run Specification matching the user's constraints.|
|**Report Structure**|Match the format of professional proposals, aligning with standard structures like the NIH Specific Aims template.|Verify that the final synthesized document contains clear sections for Hypotheses, Background Evidence, and Detailed Experimental Protocols.|
|**Agent Behavior & Coordination**|Asynchronous scheduling, SQLite task queue persistence, and concurrent execution under bounded budgets.|Run parallel execution tests, verifying that agent states and task transitions are reliably logged in the relational database without race conditions.|
|**Tournament Behavior**|Proximity-guided pairing, simulated peer debates, and stable Elo rating updates.|Run a 50-candidate tournament, verifying that Elo ratings stabilize across iterations and that pairing rules prevent redundant matches.|
|**Evidence & Citation Grounding**|Integration with databases like PubMed, ChEMBL, and UniProt; zero hallucinated citations.|Audit generated proposals using the Citation Verification agent, verifying that 100% of references map to valid, peer-reviewed articles with high entailment scores.|
|**Safety Behavior**|Multi-tier critiques; zero bypasses on adversarial CBRN tests.|Test the safety layer against the 1,200 adversarial prompt database, confirming that 100% of hazardous requests are intercepted and blocked.|
|**Progress & Latency Tracking**|Real-time SSE/htmx updates, active task counts, and tracking run latency under budget constraints.|Verify that the dashboard accurately streams progress indicators, current Elo standings, and active queue counts.|
|**Final Output Quality**|High novelty and impact ratings from domain experts; positive correlation with GPQA diamond accuracy.|Benchmark the system against known scientific breakthroughs, verifying that the clone can replicate documented findings (such as identifying anti-fibrotic target candidates).|

### Validating Elo Ratings and Compute Scaling

A critical test of the platform's alignment is verifying that its Elo-based self-evaluation matches objective scientific accuracy. Systematic benchmarks demonstrate that higher Elo scores correlate positively with accuracy on the GPQA diamond set :

```
  GPQA Diamond Accuracy (%)
   100 |                                                 /
    80 |                                               /
    60 |                                             /
    40 |                       /
    20 |                     /
     0 +--------------------+-----------------------+------------
                         1000                    1400         Elo Rating
```

This positive correlation confirms that the internal tournament is not just selecting for superficial text alignment or model biases. Instead, as test-time compute scales (through more tournament rounds and deeper peer critiques), the system's ratings correlate with actual scientific validity.

For the project director, this correlation is the ultimate measure of fidelity. It proves that the clone can reliably rank, refine, and deliver novel, high-quality scientific proposals that are ready for wet-lab validation.
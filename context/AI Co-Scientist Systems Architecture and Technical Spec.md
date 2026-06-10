# Systems Architecture and Technical Specifications for an AI Co-Scientist Clone

## Systems Paradigm and Logical Framework

The translation of high-level scientific goals into verified, novel hypotheses requires a departure from traditional linear prompting paradigms. Single-turn queries to large language models frequently fail to capture the multi-dimensional, iterative nature of scientific discovery, where breakthroughs are typically forged through continuous cycles of ideation, critique, and refinement. To address this cognitive bottleneck, the multi-agent systems architecture detailed in this specification replicates the collaborative, dialectical processes of human scientific communities. The core logical execution flow transitions systematically through distinct phases, transforming an abstract objective into a structured, executable research proposal.

```
 ──> ──> [Literature Grounding]
                                                    │
                                                    ▼
 <── [Evolution] <── <──
```

This structural loop begins with the ingest of a natural-language research challenge, which is interactively refined during a scoping interview to establish concrete operational boundaries. The system then retrieves and aggregates evidence from external literature indexes and structured biological databases to anchor subsequent generation cycles. A generation layer proposes a wide array of hypothesis candidates, which are immediately subjected to rigorous evaluation by virtual peer reviewers. These hypotheses then compete in a pairwise tournament to establish a robustly ranked leaderboard. The top-performing hypotheses are mutated, combined, and simplified by evolutionary agents before a final meta-review layer synthesizes the entire progression into a finalized research proposal.

Rather than operating as a simple text summarizer or a basic chat interface, this architecture serves as a dedicated cognitive partner for upstream scientific discovery. Practical applications of this paradigm have successfully accelerated complex biomedical inquiries, such as identifying epigenetic targets for liver fibrosis in human organoids and discovering drug-repurposing candidates for acute myeloid leukemia. By focusing on upstream hypothesis generation and verification prior to physical wet-lab validation, the system compresses months of literature synthesis and conceptual modeling into hours, establishing a highly reliable framework for automated discovery.

## Product Workflow and User Experience Framework

The user-facing interface translates the underlying multi-agent choreography into a structured, step-by-step scientific journey, minimizing manual overhead for the project director. The workflow is structured around five primary stages, guiding the researcher from initial challenge configuration to final report synthesis and interactive follow-up.

### Step 1: Research-Goal Setup and Context Ingestion

The process initiates on a web-based dashboard where the researcher enters a free-text description of the scientific challenge or hypothesis. To guide the downstream retrieval agents, the user can optionally upload reference files, clinical datasets, or slide decks, which are saved directly to a session-specific directory. The interface provides access to curated historical case studies to help structure the initial objective.

### Step 2: Adaptive Interview-Style Scoping

Upon receiving the initial objective, the system initializes an interactive interview guided by an intake agent. This agent asks targeted, adaptive follow-up questions to refine the query and map the logical requirements of the experiment. A dedicated "Interview Progress" panel tracks progress across key structural elements of the goal, specifically defining the core "Research Challenge" (defining the objective, targets, and success criteria) and the "Focus Areas" (the specific domain pillars or literature lenses used to narrow the search space).

### Step 3: Run Configuration and Execution

Once the scoping interview is completed, the system compiles the finalized run specifications. The user then configures the background run profile. To manage resources effectively, the backend enforces a hard execution limit, allowing a maximum of three Standard Runs and one Advanced Run in progress concurrently per user session.

|**Parameter**|**Standard Run Profile**|**Advanced Run Profile**|
|---|---|---|
|**Computational Allocation**|Bounded local iterations designed for quick, cost-effective scoping and goal refinement|Scaled background compute with extended parallel execution paths|
|**Debate Complexity**|Simplified pairwise rounds with constrained critique iterations|Exhaustive Elo-based tournaments utilizing deep adversarial reviews|
|**Grounding Depth**|Basic abstract retrieval and core database queries|Full-text literature synthesis and specialized science tool execution|
|**Output Characteristics**|Fast operational feedback; target latency measured in minutes|Highly diverse, complex suggestions; target latency measured in hours to days|

### Step 4: Proposal Leaderboard and Categorized Outputs

Once the run is completed, the user is notified via email. The dashboard renders a structured "Goal Report" featuring a comprehensive leaderboard of the generated proposals. To facilitate rapid review, proposals are ranked by their final tournament Elo rating and sorted into two distinct buckets: "High Potential" proposals (demonstrably viable paths supported by clear grounding evidence) and "Non-Viable" proposals (critiqued options that failed to survive the adversarial peer review).

### Step 5: Downstream Synthesis and Interactive Follow-Up

The finalized goal report is integrated directly with downstream tools. Users can share unique public links to the report, download local copies for offline review, or open the document directly in NotebookLM. This integration allows researchers to interactively converse with the generated findings, ask follow-up questions, and easily synthesize the proposal with other historical research documents.

## Specialist Agent Coalition and Orchestration Mechanics

The system's multi-agent architecture operates on a decoupled, asynchronous task execution framework. A master coordinator schedules and executes tasks, managing the flow of information across twelve specialized agents.

```
               ┌────────────────────────────────────────┐
               │            Supervisor Agent            │
               │          (Adaptive Planner)            │
               └───────────────────┬────────────────────┘
                                   │ Schedules Tasks
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Asynchronous Task Queue                        │
│                         (SQLite WAL Task Database)                      │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ Executes Workers
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Specialized Agent Coalition                         │
│                                                                         │
│  [Intake]        [Generation]   [Proximity]    │
│      [Evolution]   [Meta-review]  [Verification]      │
│                                                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1. Supervisor Agent

The Supervisor Agent serves as the primary system orchestrator, functioning as an adaptive, non-linear planner. It parses the natural-language research goal, initializes the run configuration, and dynamically populates a database-backed task queue. Rather than enforcing a static pipeline, it monitors agent outputs and dynamically spawns parallel worker tasks to explore promising pathways.

### 2. Intake/Interview Agent

The Intake/Interview Agent manages the scoping phase. It conducts semi-structured, context-aware dialogue with the researcher, assessing answers against clinical and scientific taxonomies. It continuously updates the "Interview Progress" state and compiles the finalized run specifications once all necessary operational elements are established.

### 3. Literature Retrieval Agent

The Literature Retrieval Agent executes targeted searches across external databases, preprint servers, and web indexes. It parses abstracts and extracts full-text references, packaging the retrieved documents into structured context arrays for the generation layer.

### 4. Generation Agent

The Generation Agent proposes initial focus areas and novel scientific hypotheses. It is strictly conditioned on the retrieved literature and uploaded datasets, ensuring that all proposed pathways are grounded in historical scientific evidence rather than generated in isolation.

### 5. Reflection Agent

The Reflection Agent acts as a highly critical, adversarial peer reviewer. It evaluates generated hypotheses for logical consistency, scientific accuracy, technical feasibility, and conceptual novelty, identifying underlying assumptions and flagging potential physical or biological contradictions.

### 6. Proximity/Clustering Agent

The Proximity/Clustering Agent processes the text embeddings of all generated hypotheses. It applies clustering algorithms to map the high-dimensional conceptual space, identifying redundant entries, ensuring diverse exploration boundaries, and selecting optimal pairings for the tournament matches.

### 7. Ranking Agent

The Ranking Agent orchestrates the competitive evaluation tournament. It retrieves pairs of hypotheses along with their corresponding peer reviews, initiates simulated debates, and updates the global Elo leaderboard based on the match resolutions.

### 8. Evolution Agent

The Evolution Agent implements iterative optimization loops. It takes the highest-ranked proposals from the tournament and applies targeted mutation prompt operators—such as combining complementary biological pathways, simplifying complex experimental setups, or suggesting alternative mechanisms of action.

### 9. Meta-review Agent

The Meta-review Agent observes the complete execution history, including tournament matches, critiques, and evolutionary jumps. It extracts high-level trends and issues planning directives back to the Supervisor to redirect the search queue, before synthesizing the entire process into the final research proposal.

### 10. Citation Verification Agent

The Citation Verification Agent performs automated fact-checking on all generated claims. It parses the generated proposals, extracts specific assertions, and cross-references them against trusted external databases, appending verifiable, clickable citations directly to the final report.

### 11. Safety Agent

The Safety Agent evaluates proposals against biological and physical safety policies. It monitors the generation and evolution processes to ensure the system does not propose dangerous materials, hazardous synthesis pathways, or violations of established security constraints.

### 12. Report Synthesis Agent

The Report Synthesis Agent compiles the final document payload. It structures the outputs from the meta-review and verification layers into a standard markdown format, incorporating the Elo leaderboard metrics, the grounding citations, and the proposed experimental protocols.

## Tournament Dynamics and Collaborative Refinement

The ranking engine shifts away from static, single-pass grading models, which are prone to systemic bias, and instead implements an Elo-based matchmaking tournament. Hypotheses are paired in head-to-head match-ups, and simulated debates are conducted by the Ranking Agent using the detailed critiques generated by the Reflection layer. This pairwise evaluation forces the models to defend logical steps and expose critical flaws in competing theories.

To calculate the performance trajectory of the competing hypotheses, the tournament engine implements standard Elo rating equations. Let $R_A$ and $R_B$ represent the current Elo ratings of hypothesis $A$ and hypothesis $B$, respectively. The expected score $E_A$ for hypothesis $A$ is calculated as:

$$E_A = \frac{1}{1 + 10^{(R_B - R_A)/400}}$$

Similarly, the expected score $E_B$ for hypothesis $B$ is calculated as:

$$E_B = \frac{1}{1 + 10^{(R_A - R_B)/400}}$$

Upon the resolution of the debate by the Ranking Agent, the system updates the ratings. If $S_A$ is the actual debate outcome (where $S_A = 1.0$ for a win, $S_A = 0.5$ for a draw, and $S_A = 0.0$ for a loss), the updated rating $R'_A$ is defined by:

$$R'_A = R_A + K(S_A - E_A)$$

In this equation, $K$ represents the maximum rating adjustment per debate, which is dynamically scaled based on the tournament phase to allow larger adjustments during early seeding rounds and finer-grained updates during the finals.

Crucially, the system implements a continuous self-improvement loop by instructing the Meta-review Agent to write back into the Supervisor's planning context. During long-running runs, the Meta-review Agent analyzes the tournament logs, identifies systemic bottlenecks (such as retrieval gaps or conceptual clustering collapses), and issues planning directives directly to the supervisor. The supervisor then adjusts the worker queue, dynamically spins up targeted generation tasks, and reallocates the compute budget, preventing the optimization from stalling.

## Grounding, Verification, and the Science Skills Framework

To maintain absolute scientific rigor, the system allocates the majority of its computational resources to verification rather than generation. Hypotheses are deeply cross-checked against scientific literature and specialized public databases, ensuring that every synthesized claim is supported by verified, clickable citations.

The system architecture features a specialized tool integration layer, allowing agents to interface with external APIs. Rather than registering dozens of highly specific, narrow skills (e.g., individual skills for ClinVar, UniProt, and AlphaFold) which incurs an extreme, persistent context tax on every single model call, the system utilizes a progressive disclosure design.

Under this progressive disclosure paradigm, the system registers a single, consolidated database lookup skill. This consolidated skill maintains only a minimal, single-line description in the agent's permanent system context. It is powered by an internal router that maps the agent's intent to specific databases, explains how to resolve identifiers across disparate systems (e.g., converting a gene symbol to an Ensembl ID), and dynamically reads the detailed database reference files only when the specific domain is triggered. This architecture prevents the permanent system prompt from being bloated with unused API definitions, preserving thousands of tokens per request and enabling higher logical reasoning capacity.

The following architectural comparison highlights the technical trade-offs between these two database integration models:

|**Architectural Dimension**|**Separate Skills Architecture (DeepMind science-skills)**|**Consolidated Database-Lookup Skill**|
|---|---|---|
|**System Context Tax**|High persistent overhead; registers 30+ separate tools with always-on prompt descriptions|Minimal overhead; registers a single skill description, loading database reference files on-demand|
|**Always-On Token Cost**|Approximately 3,358 tokens of permanent context overhead|Bounded to approximately 242 tokens in the primary system prompt|
|**Dynamic Load Ratio**|0% deferred loading; all tool parameters must sit in the primary context|Approximately 93% of the reference corpus is kept out of context until a database is selected|
|**Routing Efficiency**|High for single targets; degrades when encountering overlapping database scopes|High; uses a central router to resolve overlaps and manage multi-database selection rules|
|**Cross-Domain Handling**|Low; individual skills lack the global awareness required to coordinate multi-source requests|High; utilizes unified routing rules to manage complex, multi-database queries|
|**Infrastructure Overhead**|High; requires duplicate logic across 30+ skills for error handling and rate-limit retries|Minimal; implements shared infrastructure once in the central router|
|**Extensibility Model**|Requires deploying and registering an entirely new, independent agent skill|Requires a simple pull request adding a new reference file and updating the router|
|**Fault Recovery**|Poor; isolated skills cannot fall back to alternative databases if their target is down|Robust; central router can dynamically fallback to alternative databases if rate-limited|

When utilizing the `science-skills` configuration, the system integrates with a specialized toolkit to perform rapid multi-modal investigations. In platforms like Antigravity, these skills tie frontier AI models directly to major life science databases to speed up grounded discovery.

- **UniProt**: Integrates protein sequence data, structural annotations, and functional descriptions directly into the generation and reflection prompts.
    
- **ChEMBL**: Provides curated chemical database records of bioactive molecules, enabling the system to evaluate small-molecule target interactions.
    
- **AlphaFold DB**: Retrieves predicted 3D protein structures to help evaluate structural compatibility and target binding pathways.
    
- **ClinVar**: Accesses human genetic variations and their clinical classifications, allowing the system to verify disease-linked phenotypes.
    
- **dbSNP**: Ground-truth index for short genetic variations, utilized to verify genomic single-nucleotide polymorphisms.
    
- **Reactome**: Leveraged to query biological pathways and cellular reactions to verify metabolic or signaling pathways.
    
- **Human Protein Atlas**: Maps proteins across human tissues, organs, and cells, verifying spatial tissue expression patterns.
    

## Downstream Experimentation: AlphaEvolve and Empirical Research Assistance (ERA)

Within the broader laboratory ecosystem, the upstream hypothesis generation system must seamlessly hand over its finalized research proposals to downstream execution engines. In this architecture, Co-Scientist focuses on high-level conceptual planning, while the Computational Discovery suite—comprising AlphaEvolve and Empirical Research Assistance (ERA)—is responsible for writing, executing, and optimizing code in parallel to test those hypotheses.

```
┌────────────────────────────────────────────────────────┐
│             Co-Scientist (Upstream Engine)             │
│        Generates Grounded Scientific Proposals         │
└───────────────────────────┬────────────────────────────┘
                            │ Hands over Research Proposal
                            ▼
┌────────────────────────────────────────────────────────┐
│     Computational Discovery (Downstream Engine)        │
│          Built with AlphaEvolve and ERA                │
└───────────────────────────┬────────────────────────────┘
                            │ Compiles and Iterates Code
                            ▼
┌────────────────────────────────────────────────────────┐
│             Flat UCB Tree Search (FUTS)                │
│    Explores and Refines Software Candidates            │
└────────────────────────────────────────────────────────┘
```

Downstream software optimization is driven by the Empirical Research Assistance system, which utilizes a Flat UCB Tree Search (FUTS) algorithm to navigate the space of code modifications. The search is guided by an automated evaluation oracle that runs the code in a sandboxed environment and returns a scalar score reflecting the solution's performance. The tree search selects actions to maximize a variation of the Predictor Upper Confidence Bound applied to trees:

$$U(s, a) = c_{puct} \cdot P(s, a) \cdot \frac{\sqrt{N(s)}}{1 + N(s, a)}$$

In this equation, $P(s, a)$ is the prior probability of selecting code modification $a$ from state $s$ as predicted by the language model, $N(s)$ is the parent node visitation count, $N(s, a)$ is the child node visitation count, and $c_{puct}$ is a constant controlling the exploration-exploitation trade-off.

The search requires concrete implementations of two user-provided functions :

- `generate_fn`: Takes the task definition and a past solution, rendering a prompt to guide the language model in generating a novel (ideally improved) solution.
    
- `execute_fn`: Takes the task definition and a candidate solution, running the code in a secure sandboxed environment against real training/validation datasets to calculate a performance score.
    

The system's optimization capabilities have been validated across several complex computational benchmarks:

- **Single-Cell Batch Integration**: ERA optimized the Batch Balanced K-Nearest Neighbors (BBKNN) method to computationally remove lab and technology batch effects from growing single-cell RNA datasets. The model achieved a 14% improvement in integration performance over existing human-developed approaches while preserving critical biological signals on public leaderboards.
    
- **CDC Flu Forecasting**: Forecasting seasonal U.S. hospital admissions up to four weeks in advance for respiratory pathogens, including influenza, COVID-19, and RSV. The system generated 14 forecasting models that consistently outperformed the best Centers for Disease Control (CDC) ensemble benchmarks, achieving a mean Weighted Interval Score (WIS) of 26 compared to the CDC's score of 29.
    
- **Structural Optimization**: ERA has been deployed to optimize complex three-dimensional photovoltaic structures to maximize solar absorption.
    

A critical vulnerability of downstream evolutionary search engines is the susceptibility to reward hacking. For example, when optimizing three-dimensional photovoltaic designs, the tree search can discover structurally impossible features—such as levitating, disconnected components—that maximize the scoring function by exploiting discretization errors in the optics solver. To resolve this, the system incorporates a closed-loop validation architecture where the coding agent dynamically patches the physics engine with structural and physical constraints to eliminate non-physical design variants.

## Competitor Landscapes: The AI Scientist Architecture

When designing a clone of Co-Scientist, it is critical to analyze the architectural differences between DeepMind's approach and competing frameworks, specifically Sakana AI's _The AI Scientist_ (v1 and v2).

While Co-Scientist is designed as an interactive, upstream hypothesis generation partner that relies on structured databases and wet-lab validation, _The AI Scientist_ aims for fully autonomous, end-to-end scientific research. This architectural difference shapes the design of their core loops:

```
: Grounded Ideation ──> Database-Backed Verification ──> Proposal Outputs
                                                                            │
                                                     ( wet-lab validation ) ▼

: Local Code Generation ──> Sandbox Experimentation ──> PDF Manuscript Synthesis
                                                                            │
                                                   ( autonomous peer review ) ▼
```

To achieve full autonomy, _The AI Scientist_ relies heavily on execution sandboxes.

- **The AI Scientist-v1**: Operates within strict, human-authored templates (such as Grokking, NanoGPT, and 2D Diffusion) to guide the agent. It generates baseline runs, executes localized experimental scripts, plots performance, compiles a LaTeX paper draft, and runs an automated peer review.
    
- **The AI Scientist-v2**: Removes reliance on human-authored templates, generalizing across Machine Learning domains. It employs a progressive agentic tree search guided by an experiment manager agent to dynamically generate, run, and evaluate experiments.
    

Because _The AI Scientist_ executes model-written code, it presents significant operational risks, including the potential execution of dangerous packages, uncontrolled network access, and the spawning of unintended processes. Consequently, its runtime environment must be wrapped in highly secure, sandboxed Docker containers.

## Engineering Re-implementation and Clone Specification

To implement a 1:1 open-source clone of Co-Scientist, the backend is written in Python, leveraging FastAPI to expose a REST API and Server-Sent Events to stream real-time task statuses directly to the user interface. To ensure persistence and prevent state loss across multi-day runs, the system utilizes a lightweight, durable SQLite database with Write-Ahead Logging enabled, functioning as both the task queue and the session state store. The frontend dashboard is constructed using HTML5, Tailwind CSS, and HTMX, allowing developers to render dynamic updates without the complexity of modern JavaScript frameworks.

The file layout for the re-implementation is organized as follows:

```
co-scientist-clone/
├── co_scientist/             # Core backend module
│   ├── database.py           # SQLite connection and WAL migrations 
│   ├── queue.py              # Asynchronous task execution queue 
│   ├── agents/               # 12 specialist agent files 
│   │   ├── supervisor.py     # Adaptive task scheduler 
│   │   ├── intake.py         # Refinement and scoping interview agent 
│   │   ├── retrieval.py      # ground truth search engine 
│   │   ├── generation.py     # Grounded hypothesis drafting 
│   │   ├── reflection.py     # Adversarial critique generator 
│   │   ├── proximity.py      # Embedding-based clustering 
│   │   ├── ranking.py        # Elo tournament and debate manager 
│   │   ├── evolution.py      # Mutation and recombination operator 
│   │   └── meta_review.py    # Feedback and synthesis agent 
│   └── main.py               # FastAPI application routing 
├── config/
│   ├── default.toml          # Default system settings 
│   └── prompts/              # Jinja-interpolated prompts from the paper 
├── data/                     # Persistent database and session artifacts 
│   ├── co_scientist.db       # Main SQLite database 
│   └── artifacts/            # Output PDFs and goal reports 
├── co-scientist.toml         # Local developer environment overrides [8, 35]
└── pyproject.toml            # Package dependency definitions 
```

The system is managed via a unified Command Line Interface (CLI), allowing researchers to initialize, run, and monitor research sessions directly from the terminal.

- `co-scientist init`: Initializes the local storage directory, vectors, and applies SQLite database migrations.
    
- `co-scientist run "goal" --n 3 --budget-usd 2.0 --wall-clock 600`: Kicks off the complete multi-agent execution loop under a specified budget and duration limit.
    
- `co-scientist serve`: Starts the FastAPI, HTMX, and Server-Sent Events dashboard locally at `localhost:7878`.
    
- `co-scientist report <id>`: Generates and prints the formatted markdown overview for the specified session.
    
- `co-scientist status <id>`: Displays metadata, active worker statuses, and finished task counts.
    
- `co-scientist pause <id> | resume <id> | abort <id>`: Issues state commands to pause, resume, or force-terminate a run.
    
- `co-scientist feedback <id> --kind directive --text "focus on metabolic pathways"`: Dynamically injects natural-language researcher feedback directly into the planning queue.
    

To ensure high-fidelity replication, developers can utilize a standardized evaluation suite. Replicating the gold-standard benchmark from the literature involves loading the historical Acute Myeloid Leukemia (AML) drug-repurposing target dataset. The replication harness executes the full multi-agent tournament and calculates the recall rate against the known clinical targets: Nanvuranlat, KIRA6, and Leflunomide.

Python

```
# Technical Specification for the Replication Evaluation Routine
import sqlite3
import json
import numpy as np

def evaluate_replication_run(session_id: str, db_path: str):
    # Establish connection to the SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Retrieve the final research overview generated by the Meta-review agent
    cursor.execute(
        "SELECT payload FROM artifacts WHERE session_id =? AND artifact_type = 'final_proposal'",
        (session_id,)
    )
    result = cursor.fetchone()
    if not result:
        raise ValueError(f"No finalized proposal found for session: {session_id}")
        
    proposal_data = json.loads(result)
    proposed_compounds = proposal_data.get("suggested_repurposing_targets",)
    
    # Establish the ground-truth targets from the AML verification study
    gold_set = {"nanvuranlat", "kira6", "leflunomide"}
    
    # Normalize and match outputs to compute recall
    normalized_proposals = {c.strip().lower() for c in proposed_compounds}
    hits = gold_set.intersection(normalized_proposals)
    recall = len(hits) / len(gold_set)
    
    # Retrieve the final Elo ratings from the Ranking agent's tournament database
    cursor.execute(
        "SELECT entity_name, elo_rating FROM tournament_leaderboard WHERE session_id =? ORDER BY elo_rating DESC",
        (session_id,)
    )
    leaderboard = cursor.fetchall()
    
    conn.close()
    
    return {
        "recall_score": recall,
        "hits": list(hits),
        "leaderboard_depth": len(leaderboard),
        "top_ranked_candidate": leaderboard if leaderboard else None
    }
```

The clone is evaluated by similarity across nine key operational parameters :

1. _Product Flow Similarity_: Verifies that the client onboarding, scoping interview, run configuration, and results panels match the native Hypothesis Generation interface.
    
2. _Terminology Matching_: Enforces correct usage of standard system labels, including "Research Challenge", "Focus Area", "Standard/Advanced Runs", and "High Potential / Non-Viable" categorization.
    
3. _Report Structure Matching_: Validates that synthesized proposal drafts systematically include executive summaries, literature analysis, testable hypotheses, and structured experimental protocols.
    
4. _Agent Behavior Matching_: Confirms that parallel executions, clustering routines, and planning mutations align with the native multi-agent execution profile.
    
5. _Tournament Behavior Matching_: Tracks match outcomes, win probabilities, and rating updates to verify they follow standard Elo dynamics.
    
6. _Grounding Behavior Matching_: Evaluates the formatting of citations and verifies that claims are supported by clickable links.
    
7. _Safety Behavior Matching_: Confirms that hazardous biological or chemical paths are flagged and blocked.
    
8. _Progress Tracking Matching_: Measures latency and queue performance to confirm they scale with budget limits.
    
9. _Final Output Quality_: Calculates recall rates against the AML gold-set targets (Nanvuranlat, KIRA6, and Leflunomide) and evaluates the performance delta between the full multi-agent pipeline and a baseline raw language model call.
    

## Strategic Implementation Roadmap

To successfully deploy the system with minimal manual oversight, development is organized into four distinct implementation phases.

```
┌──────────────────────────┐     ┌──────────────────────────┐
│   Phase 1: Foundation    │────>│   Phase 2: Grounding     │
│  SQLite queue, CLI, UI   │     │ API routing, citation v1 │
└──────────────────────────┘     └─────────────┬────────────┘
                                               │
                                               ▼
┌──────────────────────────┐     ┌──────────────────────────┐
│     Phase 4: Safety      │<────│    Phase 3: Refinement   │
│  Sandboxing, guardrails  │     │ Elo debates, AML tests   │
└──────────────────────────┘     └──────────────────────────┘
```

### Phase 1: Foundation and Local Orchestration

The initial phase focuses on establishing core database and routing structures.

- Deploy the SQLite database with WAL enabled to serve as the local task queue, managing concurrent agent executions and protecting session states from unexpected shutdowns.
    
- Implement the core CLI wrapper with commands for initializing, running, and pausing sessions.
    
- Build the FastAPI server and HTMX-driven dashboard, utilizing Server-Sent Events to stream active worker updates and tournament leaderboards.
    

### Phase 2: Knowledge Ingestion and Retrieval-Augmented Verification

The second phase integrates external database APIs and fact-checking capabilities.

- Deploy the single-skill database-lookup router to query ChEMBL, UniProt, and other life science databases, maintaining a highly optimized, progressive disclosure design to conserve context.
    
- Build the Literature Retrieval Agent to parse external indexes and compile structured context tables.
    
- Implement the Citation Verification Agent to extract claims and attach verifiable citations.
    

### Phase 3: Dialogue Refinement and Competitive Tournaments

The third phase implements the system's collaborative debate and evaluation dynamics.

- Construct the Intake Agent to guide the interactive scoping interview, updating the "Interview Progress" state and compiling run specifications.
    
- Deploy the Ranking and Reflection agents to run the pairwise Elo-rated tournament debates.
    
- Validate the evolution and tournament logic by running the target AML drug-repurposing test, calculating the pipeline's recall score against established clinical targets.
    

### Phase 4: Operational Safety and Sandbox Guardrails

The final phase focuses on security, sandboxing, and enterprise-grade policy enforcement.

- Integrate the Safety Agent to monitor proposed chemical structures and biological pathways, enforcing strict policy filters.
    
- Wrap downstream computational execution layers (like ERA and AlphaEvolve) in isolated sandboxes, preventing unauthorized system calls.
    
- Deploy automated physical constraints within the simulation solvers to mitigate reward-hacking vulnerabilities.
    

Following this structured, modular deployment plan allows development teams to build an exceptionally robust, safe, and rigorous multi-agent scientific discovery assistant.
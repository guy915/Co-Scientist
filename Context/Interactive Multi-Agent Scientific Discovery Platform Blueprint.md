# Architectural Specification and Product Blueprint for the AI Co-Scientist Clone: An Interactive, Multi-Agent Scientific Discovery Platform

## System Architecture and Component Topology

To build a 1:1 clone of Google DeepMind's AI Co-Scientist, the platform must move beyond traditional conversational interfaces and document retrieval systems. It must function as an integrated, human-supervised scientific discovery network that mirrors the iterative progression of the scientific method. This document serves as a comprehensive system specification. By detailing the architectural components, agent roles, state schemas, and verification pipelines, this blueprint provides the exact structural context and technical parameters required for planning agents to compile development specifications, enabling coding agents to automatically implement the complete codebase without manual intervention.

The system is organized into a modular topology where an outer orchestration loop manages long-running, asynchronous tasks, and an inner cognitive loop executes structured tournaments, evaluations, and revisions.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                       WEB UI                                           │
│   Setup & Scoping ──► Standard/Advanced Runs ──► Progress Tracking ──► Proposal Editor  │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │ API Requests
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                     BACKEND API                                        │
│   State Router ──► Queue Dispatcher ──► Checkpoint Manager ──► Provenance Recorder      │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │ Task Enqueue
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               LONG-RUNNING JOB QUEUE                                   │
│   ──► ──► ──►    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

The underlying infrastructure consists of ten core architectural subsystems that manage execution, data persistence, and scientific verification:

1. **Web UI:** A responsive, interactive dashboard designed for research setup, interview-style scoping, real-time visualization of agent debates, tournament brackets, and document editors that support inline hypothesis modification.
    
2. **Backend API:** A high-throughput gateway that coordinates state transitions, registers human inputs, manages execution sessions, and exposes endpoints for external database integrations.
    
3. **Long-Running Job Queue:** An asynchronous execution engine (built on Celery and Redis) designed to manage multi-day agent operations, resource constraints, and task scheduling without blocking the user interface.
    
4. **Scientific Retrieval Layer:** A hybrid search and indexing pipeline that retrieves full-text literature from open registries (e.g., PubMed, arXiv) and queries specialized bioinformatics databases (e.g., ChEMBL, UniProt).
    
5. **Hypothesis Store:** A schema-free document database (such as MongoDB or Azure DocumentDB) that archives candidate ideas, tournament logs, structural edits, and parent-child version trees.
    
6. **Evidence/Citation System:** A verification pipeline that validates reference metadata, evaluates semantic claim consistency, and calculates integrity scores to prevent citation hallucinations.
    
7. **Tournament/Ranking Engine:** An execution environment that schedules pairwise debates between hypotheses and calculates updated Elo ratings based on evaluator outcomes.
    
8. **Report Generator:** A compilation engine that synthesizes the highest-ranked hypotheses, debate transcripts, and citation networks into formatted Markdown, PDF, and LaTeX proposals.
    
9. **Safety Layer:** A strict boundary enforcement service that intercepts prompts and outputs to block the generation of hazardous chemical, biological, radiological, or nuclear (CBRN) concepts.
    
10. **Fidelity Evaluation Harness:** An automated testing framework that evaluates the clone's performance across product flow, terminology alignment, and agent coordination metrics.
    

## Agent Coalition and Communication Protocol

The cognitive work of the co-scientist clone is distributed across twelve specialized agents. Rather than operating as linear pipelines, these agents function as a collaborative network coordinated by an adaptive supervisor.

|**Agent Name**|**Core Objective**|**Primary Tool Integrations**|**Input/Output Interfaces**|
|---|---|---|---|
|**Supervisor**|Translates goals into execution plans; coordinates the worker queue.|Queue APIs, State Checkpointers, Resource Allocators.|**In:** Abstract goals.<br><br>  <br><br>**Out:** Task DAG configurations.|
|**Intake/Interview**|Conducts conversational scoping to clarify constraints and parameters.|Chat APIs, Context Assemblers, Prompt Builders.|**In:** Initial user prompt.<br><br>  <br><br>**Out:** Structured run specs.|
|**Literature Retrieval**|Collects relevant papers, data points, and context.|PubMed, ChEMBL, UniProt, Semantic Scholar.|**In:** Refined research topics.<br><br>  <br><br>**Out:** Grounded document corpora.|
|**Generation**|Proposes initial hypotheses based on retrieved literature.|Vector Databases, Prompt Templates, RAG Encoders.|**In:** Document corpora.<br><br>  <br><br>**Out:** Candidate hypotheses.|
|**Reflection**|Acts as a virtual reviewer to evaluate plausibility and novelty.|Citation Search, Fact Checkers, Context Verifiers.|**In:** Candidate hypotheses.<br><br>  <br><br>**Out:** Structural critiques.|
|**Proximity/Clustering**|Maps the hypothesis space to ensure diverse exploration.|Embedding Models, KMeans, t-SNE, Vector Distance Tools.|**In:** High-dimensional candidate sets.<br><br>  <br><br>**Out:** De-duplicated clusters.|
|**Ranking**|Compares and ranks ideas using pairwise debate evaluations.|Debate Orchestrators, Tournament Managers.|**In:** Hypothesis pairs + Critiques.<br><br>  <br><br>**Out:** Tournament wins/losses.|
|**Evolution**|Merges, refines, and improves top hypotheses.|Analogical Reasoners, Synthesis Tools, Simplifiers.|**In:** High-ranked hypotheses + Critiques.<br><br>  <br><br>**Out:** Evolved proposals.|
|**Meta-Review**|Identifies patterns in debates to optimize system performance.|System Log Parsers, Meta-Prompters.|**In:** Complete debate history.<br><br>  <br><br>**Out:** Operational updates.|
|**Citation Verification**|Verifies reference existence, metadata, and claim support.|sciwrite-lint, OpenAlex, DOI Resolvers, CrossRef.|**In:** Synthesized text drafts.<br><br>  <br><br>**Out:** Citation integrity reports.|
|**Safety**|Screens prompts and proposals for biosecurity and CBRN risks.|Biosecurity Registries, Chemical Lists, Safety Classifiers.|**In:** Queries and drafts.<br><br>  <br><br>**Out:** Safety flags (Clear/Block).|
|**Report Synthesis**|Compiles the tournament findings into a research proposal.|LaTeX Compilers, PDF Generators, Document Builders.|**In:** Best hypotheses + Debate logs.<br><br>  <br><br>**Out:** Final research proposal.|

### Inter-Agent Communication and Asynchronous Workflows

To support non-linear workflows and scale test-time computation, the system separates planning from execution. The Supervisor agent parses the run specifications into a Directed Acyclic Graph (DAG) of tasks. Rather than invoking agents sequentially, the Supervisor dispatches tasks to an asynchronous queue.

For example, when exploring a new research goal, the Supervisor initiates parallel execution tracks:

```
                  ┌──► Literature Retrieval ──► Generation ────┐
                  │                                            ▼
Research Goal ────┼──► Intake/Interview ──► Scoping Spec ──► Proximity ──► Tournament
                  │                                            ▲
                  └──► Safety screening ───────────────────────┘
```

The system manages concurrent processes by routing state updates through a shared data structure. When a node completes its execution, it returns an update dictionary that is merged into the global state by a designated reducer function. This asynchronous, event-driven architecture prevents process blocking, isolates failures to individual tasks, and allows the system to scale its computational footprint based on the user's run configurations.

## Product Workflow and Interface Specifications

The frontend of the co-scientist clone is designed around Google's **Hypothesis Generation / Gemini for Science** workflow. It translates multi-agent operations into a clean, interactive user experience.

```
┌────────────────────────────────────────────────────────────────────────────┐
│  PROJECT: Target Discovery - Liver Fibrosis                                 │
├────────────────────────────────────────────────────────────────────────────┤
│  ──► [2. Interview] ──► ──► │
│                                                                            │
│  CURRENT STATUS: RUNNING ADVANCED TOURNAMENT (Iter 2/3)                     │
│  ┌─────────────────────────────────┐  ┌─────────────────────────────────┐  │
│  │  ACTIVE DEBATE: MATCHUP #14     │  │  PROGRESS TRACKER               │  │
│  │  Hypothesis A vs Hypothesis B   │  │  [■■■■■■■■■■■■■■□□□□□□□□] 54%   │  │
│  │  Evaluating epigenetic targets  │  │  Step: Evolution Loop           │  │
│  │  Critique: "Weak in vivo data"  │  │  Est. Remaining Time: 4h 12m    │  │
│  └─────────────────────────────────┘  └─────────────────────────────────┘  │
│                                                                            │
│        │
└────────────────────────────────────────────────────────────────────────────┘
```

### 1. Research-Goal Setup and Interactive Interview Scoping

The user initiates a session by entering an abstract scientific goal (e.g., "Identify epigenetic drug targets to reverse liver fibrosis"). Rather than proceeding directly to generation, the system initiates an interview-style scoping phase. The Intake/Interview Agent analyzes the goal and generates clarifying questions to capture crucial context:

- _Constraint Definition:_ What are the targeted cell types, model organisms, and clinical boundaries?
    
- _Resource Limitations:_ Are there specific chemical libraries, target classes, or in vitro assays to exclude?
    
- _Prior Grounding:_ Should the system ingest specific private documents, or rely entirely on public databases?
    

This conversation produces a formalized "Run Specification" that defines the search parameters, iteration limits, and evaluation metrics for the upcoming run.

### 2. Run Modes and Resource Allocation

The platform provides two primary execution profiles to balance search depth with time and cost constraints:

- **Standard Run:** Optimized for rapid exploration. It configures a flat agent pipeline with a single literature retrieval step, a low tournament iteration count ($I = 1$), and a small candidate pool (e.g., 10 hypotheses). It relies on standard context window allocations and does not scale test-time compute.
    
- **Advanced Run:** Designed for deep scientific reasoning. It allocates a larger candidate pool (e.g., 50+ hypotheses) and scales test-time compute by running recursive self-critique loops and multi-turn pairwise tournaments ($I \ge 3$). It executes deep search sweeps across external APIs and integrates parallel background processes to verify citation lineages.
    

### 3. Real-Time Execution Monitoring and Latency UI

Because Advanced Runs can execute for several hours or days, the interface provides comprehensive status tracking to maintain visibility :

- **Collapsible Thinking Traces:** Users can expand live execution logs to view the underlying reasoning paths, active queries, and intermediate agent critiques.
    
- **Dynamic Progress and Latency Meters:** Displays progress bars mapping the current execution step, the active tournament bracket, completed matchups, and estimated time to completion.
    
- **Live Debate Visualizers:** Renders active matchups as a side-by-side comparison pane, highlighting the competing hypotheses, the critiques raised by the Reflection agents, and the current vote distribution.
    

### 4. Interactive Knowledge Base and Document Workspace

The system aggregates all retrieved literature, molecular structures, and target profiles into a dedicated project Knowledge Base. The UI provides a split-pane layout:

- **Source Browser:** A document viewer that displays full-text papers alongside their extracted claims. Clicking a claim highlights the source paragraph and reveals the extraction path.
    
- **Interactive Citation Trees:** Renders a visual graph of the citation network. Nodes represent cited papers, and edges denote reference dependencies. Users can hover over a node to view reference details, retracted status, and integrity scores.
    

## Human-in-the-Loop Steering, State Management, and Time Travel

To ensure the co-scientist serves as an effective collaborator, the platform rejects fully autonomous execution in favor of structured human-in-the-loop (HITL) steering. The architecture is designed as an interactive state machine that allows human experts to steer, modify, or roll back runs at any point.

### The State Machine Paradigm with LangGraph Checkpointing

The system models the multi-agent workflow as a stateful graph where each unit of work is a node, and execution routes are defined by conditional edges. The state is managed through a central checkpointer that saves a snapshot of the shared variables at every execution step.

Python

```
# Formal definition of the stateful scientific discovery graph
from langgraph.graph import StateGraph, START, END
from src.state import AIcoScientistState
from src.nodes import (
    scoping_node, retrieval_node, generation_node, 
    reflection_node, tournament_node, report_node
)
from src.routing import route_after_generation, route_after_tournament

# Initialize the stateful workflow
workflow = StateGraph(AIcoScientistState)

# Register the processing nodes
workflow.add_node("scoping", scoping_node)
workflow.add_node("retrieval", retrieval_node)
workflow.add_node("generation", generation_node)
workflow.add_node("reflection", reflection_node)
workflow.add_node("tournament", tournament_node)
workflow.add_node("report", report_node)

# Establish deterministic transitions
workflow.add_edge(START, "scoping")
workflow.add_edge("scoping", "retrieval")
workflow.add_edge("retrieval", "generation")

# Configure conditional and human approval transitions
workflow.add_conditional_edges(
    "generation",
    route_after_generation,
    {
        "continue": "reflection",
        "pause_for_scoping_review": "scoping"
    }
)
workflow.add_edge("reflection", "tournament")
workflow.add_conditional_edges(
    "tournament",
    route_after_tournament,
    {
        "evolve": "generation",
        "compile_report": "report"
    }
)
workflow.add_edge("report", END)

# Compile the graph with persistent DocumentDB state tracking
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

client = MongoClient("mongodb://db-connection-string")
checkpointer = MongoDBSaver(client)
app = workflow.compile(checkpointer=checkpointer)
```

### Mitigating Routing and Confirmation Failures

When implementing conversational steering interfaces, a common point of failure is routing confusion during human feedback loops. In typical agentic setups, if the system pauses to ask a scientist for confirmation, a response like "yes" or "no" can be treated as a new prompt, causing the supervisor to restart the generation phase or overwrite previous results.

The co-scientist clone addresses this by separating conversational reasoning from execution state. The state schema maintains an explicit `pending_action` object and a boolean `awaiting_confirmation` flag :

Python

```
pending_action = {
    "action_id": "act_98273",
    "target_node": "tournament_node",
    "proposed_state_mutation": {
        "bracket_id": "bracket_04",
        "hypotheses_to_drop": ["hyp_12"]
    }
}
awaiting_confirmation = True
```

The Supervisor agent reads this flag first before processing any new message. When the user submits feedback, the state router processes it as a command argument rather than a chat message, ensuring stable transitions :

Python

```
# Command routing pattern for handling user steering inputs
from langgraph.types import Command

def process_user_approval(user_input: str, active_state: AIcoScientistState):
    if active_state["awaiting_confirmation"]:
        if "approve" in user_input.lower():
            # Apply the proposed state mutation and resume execution
            return Command(
                resume={
                    "confirmed": True, 
                    "mutations": active_state["pending_action"]["proposed_state_mutation"]
                }
            )
        else:
            # Reject and halt transition, returning to the scoping phase
            return Command(goto="scoping")
```

### Time Travel: Replaying and Forking States

Because the state is saved at every step of execution, the system supports comprehensive time-travel capabilities :

```
Thread Timeline:
 ──► ──► ──►
                                 │
                                 └── (Fork & edit ranking weights) ──►
```

- **Replay:** If a tool call or API request fails during a run, the supervisor uses the thread identifier (`thread_id`) and the target checkpoint ID to reload the state of the graph. It then resumes execution from that safe starting point, preserving completed steps without re-executing actions that have side effects (such as writing database records).
    
- **Fork:** If a scientist wants to explore an alternative hypothesis space, they can select any prior checkpoint from the run history and update its variables. The system uses `update_state(config, values, as_node)` to apply these modifications, creating a new branch under the same thread ID. This allows researchers to conduct "what-if" simulations from any point in the workflow.
    

### Semantic Provenance and Auditability Tracking

To maintain regulatory compliance and support reproducibility, every state mutation and agent decision is recorded using the W3C PROV standard, extended by the ProvONE scientific workflow model. The system serializes these relationships into semantic triples, creating an auditable provenance graph.

Python

```
# Semantic provenance serialization using W3C PROV syntax
provenance_trace = {
    "prefix": {
        "prov": "http://www.w3.org/ns/prov#",
        "provone": "http://purl.dataone.org/provone/2015/01/15/ontology#",
        "cosci": "http://ai-co-scientist.org/provenance/"
    },
    "entity": {
        "cosci:hypothesis_04": {
            "prov:type": "cosci:ScientificHypothesis",
            "cosci:title": "Epigenetic silencing of HDAC6 reverses hepatic stellate cell activation",
            "cosci:version": "2.1.0"
        },
        "cosci:document_corpus_01": {
            "prov:type": "provone:Data",
            "cosci:query_string": "HDAC6 AND liver fibrosis"
        }
    },
    "activity": {
        "cosci:generation_step_12": {
            "prov:type": "provone:Execution",
            "prov:startTime": "2026-06-07T14:10:00Z",
            "prov:endTime": "2026-06-07T14:12:30Z"
        }
    },
    "agent": {
        "cosci:generation_agent_01": {
            "prov:type": "provone:Program",
            "cosci:model_version": "gemini-2.0-pro-001"
        },
        "cosci:scientist_01": {
            "prov:type": "prov:Person",
            "cosci:orcid": "0000-0002-1825-0097"
        }
    },
    "wasGeneratedBy": {
        "cosci:generation_step_12_gen": {
            "prov:entity": "cosci:hypothesis_04",
            "prov:activity": "cosci:generation_step_12"
        }
    },
    "used": {
        "cosci:generation_step_12_use": {
            "prov:activity": "cosci:generation_step_12",
            "prov:entity": "cosci:document_corpus_01"
        }
    },
    "wasAssociatedWith": {
        "cosci:generation_step_12_assoc": {
            "prov:activity": "cosci:generation_step_12",
            "prov:agent": "cosci:generation_agent_01"
        }
    },
    "wasAttributedTo": {
        "cosci:hypothesis_04_attrib": {
            "prov:entity": "cosci:hypothesis_04",
            "prov:agent": "cosci:scientist_01"
        }
    }
}
```

This provenance ledger ensures full accountability under frameworks like CCPA, GDPR, and the EU AI Act's human oversight mandates. It tracks every transition, indicating which retrieved documents, agent parameters, and manual user edits produced a specific hypothesis version.

## Scientific Grounding, Citation, and Safety Safeguards

To prevent the system from generating incorrect, ungrounded, or hazardous proposals, the core loop is bound by real-time validation layers and safety checks.

### Evidence Weighting and GRADE Scoring

The co-scientist clone adapts the international clinical GRADE (Grading of Recommendations Assessment, Development, and Evaluation) standard to score and weigh literature evidence. When synthesizing evidence for a specific hypothesis, the system calculates a weighted score based on study characteristics :

$$W_{\text{evidence}} = \sum_{k=1}^{N} \omega_k \cdot \gamma_k$$

where $\omega_k$ is the study type multiplier and $\gamma_k$ represents the study design rating.

|**Study Type**|**Base Multiplier (ω)**|**Design Evaluation Metrics (γ)**|**Target Score for Grade A**|
|---|---|---|---|
|**Meta-Analysis**|**3.0×**|Evaluates source databases, search limits, heterogeneity, and publication bias.|To achieve a high-confidence **Grade A** rating, a compound requires a weighted score of **$\ge 15$** alongside supporting human clinical data.|
|**Randomized Controlled Trial (RCT)**|**2.5×**|Evaluates randomization methods, double-blinding protocols, and attrition rates.|—|
|**Cohort & Observational Study**|**1.5×**|Evaluates selection bias, confounding variables, and matching designs.|—|
|**Case Report**|**0.5×**|Evaluates diagnostics, documentation details, and alternative explanations.|—|
|**Preclinical In Vitro / In Vivo Study**|**0.3×**|Evaluates controls, replication status, model validity, and dosing precision.|—|

The system evaluates each source across five key GRADE domains: study design, risk of bias, consistency of findings, directness of evidence, and statistical precision.

### Citation Auditing and Claim Validation

The system uses a local verification pipeline based on `sciwrite-lint` to check references and claims without sending private manuscript content to external servers.

```
Raw Hypothesis Draft
       │
       ▼
[sciwrite-lint Parser] ──► Extract Citation Keys ──► Verify Metadata (OpenAlex API)
       │                                                      │
       ▼                                                      ├─► Mismatch?
                                          └─► Retracted?
       │
       ▼
Relevant Source Passages ──► [LLM Entailment Check] ──► Claim Integrity Score
```

The system computes a Reference Integrity Score ($S_{\text{ref}}$) for each citation :

$$S_{\text{ref}} = S_{\text{base}} - \sum \text{Deductions}$$

The scoring parameters and adjustments are configured as follows:

- _Tier 1 Base (API-Verified + Full-Text Parser):_ **0.9**
    
- _Tier 2 Base (API-Verified, Abstract Only):_ **0.7**
    
- _Tier 3 Base (Unverified in open databases):_ **0.3**
    
- _Retracted Document:_ **0.0 (Hard Block)**
    
- _Expression of Concern:_ **Multiplier $\times 0.3$**
    
- _Metadata Mismatch (Title/Year/Venue):_ **$-0.1$ per occurrence**
    
- _Cross-ID Mismatch (DOI vs PMID vs arXiv ID):_ **$-0.1$ per occurrence**
    
- _Non-Formal Publication (Blog/Guide):_ **$-0.2$ deduction**
    
- _Cited Bibliography Retraction:_ **$-0.15$ deduction (capped at $-0.30$)**
    

### Real-Time and Background Contradiction Detection

Contradiction detection operates as both a real-time validation filter during generation and a continuous background process. The system utilizes a specialized resolver to handle conflicting information from different agents or papers:

- **Evidence Weighting (`evidence_weight` strategy):** When agents or sources present conflicting findings, the system does not suppress either perspective. Instead, it calculates the cumulative GRADE weights of both sides and transparently documents the scientific uncertainty in the final output.
    
- **Safety Priority (`safety_priority` strategy):** For critical clinical or toxicity parameters, the system prioritizes safety. Any conflict regarding safety thresholds immediately defaults to the most conservative, low-risk dosage or compound recommendations.
    

### Chemical and Biological Safety Gates

To prevent dual-use misuse, the Safety agent acts as an interceptor on all input queries and generated drafts. It evaluates inputs and outputs against a database of regulated substances, biological pathogens, and toxins (e.g., Select Agents and Toxins registries).

If a safety violation is detected, the agent raises a critical exception, halts the supervisor queue, and displays a policy violation block in the Web UI.

## Fidelity Evaluation and Quality Validation Harness

To verify that the clone matches the behaviors, terminology, and performance profiles of Google DeepMind's co-scientist, the system includes a dedicated Fidelity Evaluation Harness. This testing suite evaluates the platform across nine distinct dimensions:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              FIDELITY EVALUATION HARNESS                               │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  [Product Flow]  ──►   ──►   ──►      │
│     ──►  [Citation]     ──►      ──►  [Progress/Latency]   │
│  [Output Quality]                                                                      │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

The metrics, target parameters, and validation methods for each evaluation dimension are defined below:

|**Evaluation Dimension**|**Core Metrics**|**Target Behavior**|**Automated Validation Method**|
|---|---|---|---|
|**Product Flow**|Task Success Rate, Interrupt Success Rate.|Matches the sequential progression from Scoping to Proposal Generation.|End-to-end playbooks that simulate user interactions and verify state transitions.|
|**Terminology**|Keyword Mapping Accuracy, Concept Representation.|Consistent use of target terms (e.g., Standard/Advanced runs, Generation/Reflection agents).|AST parsing and string scanning across backend logs, UI text, and API responses.|
|**Report Structure**|Section Coverage, Structural Completeness.|Final proposals must include an Executive Summary, Ranked Ideas, and full experimental protocols.|JSON schema validation and Markdown structure parsers applied to generated artifacts.|
|**Agent Behavior**|Node Isolation Rate, Tool Calling Precision.|Agents must adhere strictly to their specialized, role-specific prompts.|Tracing logs in LangSmith to verify tool inputs, context isolation, and prompt boundaries.|
|**Tournament & Ranking**|Elo-expert alignment, Concordance Rate.|Elo rankings must correlate with GPQA correctness and expert preferences.|Statistical analysis of agent tournament outcomes against pre-curated expert rankings.|
|**Evidence & Citation**|Citation Faithfulness, Retraction Catch Rate.|Zero fabricated citations; 100% of retracted papers must be flagged.|Running sciwrite-lint on drafts to verify DOIs and evaluate claim alignment.|
|**Safety Behavior**|False Negative Rate, True Positive Rate.|100% block rate on validated CBRN threat vectors; low false alarm rates on safe drug-repurposing queries.|Adversarial red-teaming sweeps using safety evaluation datasets.|
|**Progress & Latency**|Update Frequency, State Recovery Rate.|Real-time state updates (latency < 2s); successful recovery from simulated task crashes.|Network log analyses and chaos engineering tests that inject failures to verify rollback.|
|**Final Output Quality**|Expert Preference Score, Novelty Rating.|Proposals must match or exceed baseline models in blinded domain-expert reviews.|Double-blinded evaluations of proposals by domain experts using structured scorecards.|

## Technical Specifications and Code-Generation Reference

This section provides direct, structured code schemas and API interfaces. These technical specifications serve as an unambiguous translation layer for coding agents to generate the platform's core codebases, schemas, and configurations.

### 1. Database Schemas

The database configurations define how the platform maintains execution states, project knowledge, and complete provenance records.

#### Hypothesis Store Collection (`hypotheses`)

JSON

```
{
  "$jsonSchema": {
    "bsonType": "object",
    "required": ["hypothesis_id", "project_id", "title", "description", "elo_rating", "version", "provenance_entity_uri"],
    "properties": {
      "hypothesis_id": { "bsonType": "string" },
      "project_id": { "bsonType": "string" },
      "title": { "bsonType": "string" },
      "description": { "bsonType": "string" },
      "elo_rating": { "bsonType": "double" },
      "version": { "bsonType": "string" },
      "provenance_entity_uri": { "bsonType": "string" },
      "generation_metadata": {
        "bsonType": "object",
        "properties": {
          "model_id": { "bsonType": "string" },
          "temperature": { "bsonType": "double" },
          "source_citations": {
            "bsonType": "array",
            "items": { "bsonType": "string" }
          }
        }
      }
    }
  }
}
```

#### Run State Checkpointer Collection (`checkpoints`)

JSON

```
{
  "$jsonSchema": {
    "bsonType": "object",
    "required": ["thread_id", "checkpoint_id", "parent_checkpoint_id", "state_snapshot", "timestamp"],
    "properties": {
      "thread_id": { "bsonType": "string" },
      "checkpoint_id": { "bsonType": "string" },
      "parent_checkpoint_id": { "bsonType": ["string", "null"] },
      "state_snapshot": {
        "bsonType": "object",
        "required": ["messages", "awaiting_confirmation", "pending_action"],
        "properties": {
          "messages": { "bsonType": "array" },
          "awaiting_confirmation": { "bsonType": "bool" },
          "pending_action": { "bsonType": ["object", "null"] },
          "hypotheses": { "bsonType": "object" },
          "tournament_brackets": { "bsonType": "array" }
        }
      },
      "timestamp": { "bsonType": "date" }
    }
  }
}
```

### 2. API Contract Specifications

The API specifications establish the communication protocols between the Web UI, the Backend API, and the multi-agent queue.

#### Create Scoping Run (`POST /api/v1/runs/scoping`)

- **Description:** Starts a scoping run by initializing the scoping queue and spawning the Intake/Interview Agent.
    
- **Request Headers:** `Content-Type: application/json`, `Authorization: Bearer <token>`
    
- **Request Body:**
    
    JSON
    
    ```
    {
      "project_id": "proj_981273",
      "research_goal": "Reverse cellular senescence in cardiomyocytes using CRISPR screens",
      "run_profile": "advanced"
    }
    ```
    
- **Response (202 Accepted):**
    
    JSON
    
    ```
    {
      "thread_id": "thr_01hj9a8s7d6f",
      "status": "interviewing",
      "active_agent": "intake_agent",
      "current_checkpoint_id": "chk_01hj9a8s7d01",
      "message": "Scoping session initialized. Interview agent prompt active."
    }
    ```
    

#### Submit Human Steering Feedback (`POST /api/v1/runs/steer`)

- **Description:** Submits steering feedback, resolves pending human-in-the-loop gates, or updates active run parameters.
    
- **Request Headers:** `Content-Type: application/json`, `Authorization: Bearer <token>`
    
- **Request Body:**
    
    JSON
    
    ```
    {
      "thread_id": "thr_01hj9a8s7d6f",
      "checkpoint_id": "chk_01hj9a8s7d14",
      "steering_command": "approve",
      "user_feedback_text": "Prioritize chromatin remodeling enzymes over general transcription factors.",
      "state_mutations": {
        "ranking_adjustments": {
          "hdac6_target": 1.2,
          "p300_target": 0.8
        }
      }
    }
    ```
    
- **Response (200 OK):**
    
    JSON
    
    ```
    {
      "thread_id": "thr_01hj9a8s7d6f",
      "new_checkpoint_id": "chk_01hj9a8s7d15",
      "status": "resuming",
      "target_node": "tournament_node",
      "message": "Human approval gate resolved. State mutated. Graph execution resumed."
    }
    ```
    

#### Fetch Tournament Results (`GET /api/v1/runs/tournament`)

- **Description:** Retrieves tournament brackets, match history, and the current Elo ratings of generated hypotheses.
    
- **Request Headers:** `Authorization: Bearer <token>`
    
- **Request Parameters:** `thread_id=thr_01hj9a8s7d6f`
    
- **Response (200 OK):**
    
    JSON
    
    ```
    {
      "thread_id": "thr_01hj9a8s7d6f",
      "tournament_iteration": 2,
      "total_matchups": 45,
      "completed_matchups": 24,
      "elo_rankings":
        },
        {
          "hypothesis_id": "hyp_12",
          "title": "HAT-Mediated Acetylation of Senescence Markers",
          "elo_rating": 1285.0,
          "win_loss_draw": 
        }
      ]
    }
    ```
    

### 3. Agent System Prompts

The core instructions define each worker agent's behavioral boundaries, operational constraints, and reasoning protocols.

#### Reflection Agent System Prompt

```
You are a peer reviewer evaluating scientific hypotheses.
Your goal is to find errors, evaluate claims against existing literature, and assess experimental feasibility.

Analyze the proposed hypothesis using the following steps:
1. Plausibility Check: Is the biological or chemical mechanism supported by literature? Identify any contradictions.
2. Novelty Check: Does this hypothesis offer a novel approach, or does it restate known results?
3. Feasibility Check: Can this hypothesis be verified with standard lab techniques? Identify any high-risk assumptions.

Structure your critique using the following headers:
### 1. Plausibility and Evidence Support
### 2. Novelty and Impact
### 3. Experimental Feasibility and Pitfalls
### 4. Overall Score (1-10)

Be critical. Highlight ungrounded claims, missing controls, or weak designs.
```

#### Evolution Agent System Prompt

```
You are a senior scientist refactoring and improving scientific hypotheses.
Your goal is to synthesize critiques, resolve logical inconsistencies, and refine scientific concepts.

You will receive:
1. A candidate hypothesis.
2. Critiques from Reflection agents.
3. Relevant context from retrieved literature.

Apply these rules during your synthesis:
1. Resolve weaknesses identified by the reviewers.
2. Simplify overly complex or redundant assertions.
3. Integrate missing controls, cell lines, or concentration constraints.
4. Do not alter verified mechanisms. Preserve the core value of the original hypothesis.

Output only the revised hypothesis, followed by a concise summary of the changes made.
```

### 4. Environment and Runtime Configuration

The development and execution boundaries are defined by a standardized configuration schema.

Ini, TOML

```
# Core API Settings
PORT=8000
API_ENV=production
DEBUG=false
ALLOWED_ORIGINS=https://coscientist.my-org.com

# Model & Token Envelopes
LLM_PROVIDER=gemini
LLM_API_KEY=g_live_01hj9a8s7d6f5e4c3b2a1
DEFAULT_MODEL_ID=gemini-2.0-pro-001
ADVANCED_MODEL_ID=gemini-2.0-ultra-001
MAX_TOKEN_LIMIT=2097152

# Persistence Configurations
MONGO_URI=mongodb://root:admin_pwd@db-node-01:27017/cosci?authSource=admin
REDIS_URI=redis://queue-node-01:6379/0

# Integrity & Grounding Services
PUBMED_API_KEY=pm_981273981273
OPENALEX_EMAIL=contact@my-org.com
SCIWRITE_LINT_LOCAL_GPU=true
SCIWRITE_LINT_DEVICE=cuda:0

# Safety Gate Parameters
CBRN_REGISTRY_PATH=/opt/safety/cbrn_pathogens.json
STRICT_SAFETY_BLOCKS=true
```

## Architectural Implementation Roadmap

To successfully build the co-scientist clone, development should follow a structured, phased implementation roadmap:

```
Phase 1: State Machine Core (LangGraph + MongoDB)
                     │
                     ▼
Phase 2: Human-in-the-Loop Gates (Two-Loop Design)
                     │
                     ▼
Phase 3: Scientific Retrieval & Verification (GRADE + sciwrite-lint)
                     │
                     ▼
Phase 4: Tournament Debate & Computational Scaling (Elo Rating)
                     │
                     ▼
Phase 5: Audit & Lineage Layers (W3C PROV Graph)
```

1. **Phase 1: Establish the Stateful Core:** Build the stateful, cyclic graph orchestration engine (using LangGraph) and connect it to a persistent database (e.g., Azure DocumentDB or MongoDB). This setup ensures that execution state is preserved across process restarts and network timeouts. Define a clear state schema that separates conversational messaging keys from execution parameters like `pending_action` and `awaiting_confirmation` to prevent routing errors during human-agent interactions.
    
2. **Phase 2: Integrate Dataset-Aware Human Gates:** Implement the two-loop architecture pattern. The Question Quality Loop must require variable mapping and statistical screening to ensure hypotheses are grounded in available data. The system must enforce hard halts at designated human decision gates, preventing the supervisor agent from continuing until the user provides explicit verification or steering inputs.
    
3. **Phase 3: Implement Local Citation Verification:** To prevent the propagation of hallucinated or retracted citations, integrate a local verification step using a tool like `sciwrite-lint`. Every generated claim must be extracted, mapped to its source DOI or PMID, and cross-checked against open metadata registries. Citations must be scored using a structured matrix, and any retracted references must trigger automatic re-generation.
    
4. **Phase 4: Configure Tournament Debates with Elo Metrics:** Configure the tournament ranking loop using parallel execution queues to scale test-time compute. The system should run structured, pairwise debates between hypotheses, using Reflection agents to critique each idea. The results of these debates must update global Elo ratings, providing a clear metric to guide the Evolution agent in refining and merging the most promising concepts.
    
5. **Phase 5: Implement Semantic Lineage Tracking:** Integrate the W3C PROV and ProvONE specifications into the agent's core classes. Every model invocation, RAG query, and human steering adjustment must write a structured provenance record to the database. This produces a complete, auditable transaction trail, ensuring that the system's generated scientific proposals are transparent, reproducible, and compliant with international standards.
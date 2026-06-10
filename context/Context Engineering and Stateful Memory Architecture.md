# Comprehensive Technical Specification for a Multi-Agent Scientific Hypothesis-Generation System: Context Engineering and Stateful Memory Architecture

## Architectural Blueprint and Code-Generation Framework

The realization of an expert-level scientific hypothesis-generation system requires transitioning away from static pipelines toward an asynchronous, stateful multi-agent system. Empirical investigations into agent coordination indicate that centralized configurations achieve the most reliable balance between system accuracy and error containment, limiting error amplification to 4.4x compared to the 17.2x amplification seen in decentralized, non-orchestrated networks. Consequently, this architecture utilizes a centralized hub-and-spoke topology led by a Supervisor agent that dynamically schedules specialized subagents and tools.

For the project director, the ultimate target is to automate both the execution of scientific tasks and the implementation of the software system itself. To minimize manual coding and reading, the project relies on a closed-loop system-building framework. In this loop, an AI planning agent ingests this architectural specification and translates the requirements into structured code specifications, such as task files and configuration templates.

An AI coding agent, such as Claude Code, reads these specifications and writes the execution logic in Python. Operating in a sandboxed directory containing baseline system stubs and SQLite schemas, the coding agent runs the code, captures runtime errors from standard output, and iteratively refines the codebase until it executes cleanly without bugs.

This design prioritizes validation and fact checking over simple text generation. By dedicating the majority of computational resources to cross-checking claims against literature and databases, the system ensures that all generated hypotheses remain logically sound and grounded in empirical facts. The primary tool integrations and their functional roles are outlined below:

### Table 1: Tool Integrations and Verification Targets

|**Specialized Tool**|**Data Classification**|**Verification Target**|**Downstream Integration**|
|---|---|---|---|
|**ArXiv API**|Academic Literature|Retrieves full-text metadata, abstracts, and authors to contextualize claims.|Grounding and Citation Verification Agents.|
|**ChEMBL**|Structured Bioactive Database|Verifies drug-target interactions, binding affinities, and clinical designations.|Generation, Reflection, and Citation Verification Agents.|
|**UniProt**|Protein Sequence Database|Confirms protein functions, expression levels, and association pathways.|Generation, Reflection, and Citation Verification Agents.|
|**AlphaFold**|Structural Prediction Model|Predicts protein-ligand binding interfaces and structural variations.|Reflection and Evolution Agents during advanced structural runs.|

## Interactive Product Workflows and Operational States

The visible system interface is designed to support a collaborative paradigm, allowing users to direct and refine the discovery process. Rather than waiting for end-to-end autonomous execution, the user guides the system through distinct operational states. This interactive workflow includes:

- **Research-Goal Setup:** The user enters a natural-language research target.
    
- **Scoping Dialogue:** An interview-style scoping agent conducts a clarifying conversation to gather criteria, boundaries, and preferences.
    
- **Execution Modes:** The user initiates either a Standard run (for rapid exploration) or an Advanced run (for deep, resource-intensive analysis).
    
- **Interactive Outputs:** The system outputs generated reports, ranked idea lists, a knowledge base of retrieved literature, run specifications, and summary statistics, with full support for follow-up questions.
    

The difference in execution depth between Standard and Advanced runs dictates the scheduling of agent tasks and the allocation of computational resources.

### Table 2: Run Specifications and Execution Modes

|**Operational Feature**|**Standard Run Specification**|**Advanced Run Specification**|
|---|---|---|
|**Target Execution Focus**|Rapid exploration, preliminary screening of hypotheses, and quick concept mapping.|High-compute optimization, in-depth evaluation, and structural verification.|
|**Literature Depth**|Limits search to abstract retrieval and metadata indexing from databases like arXiv.|Performs full-text extraction, citation analysis, and integrates external models.|
|**Tournament Iterations**|Minimal tournament iterations (typically $N = 3$) with basic pairwise matches.|Exhaustive Elo-based tournaments ($N \ge 10$) with parallel matches and deep debates.|
|**Tool Integration Scale**|Basic web search and metadata retrieval.|Full structural verification using tools like AlphaFold and specialized databases.|
|**Computational Budget**|Low budget caps (typically $1.00 to $2.00 per session).|High budget allocation ($5.00 to $50.00) with reasoning-effort parameters.|
|**Primary Termination Criteria**|Queue depletion or reaching strict wall-clock limits.|Leaderboard stabilization and Elo convergence.|

## Core Multi-Agent Roster and Context-Routing Protocol

The system coordinates a coalition of twelve specialized agents to execute the discovery cycle. Each agent operates under strict context limits, receiving only the specific data fields required to perform its task. Context is passed via explicit schemas to prevent data loss or drift across agent handoffs.

```
               ┌────────────────────────────────────────┐
               │         Intake / Interview Agent       │
               └───────────────────┬────────────────────
                                   │
                                   ▼
               ┌────────────────────────────────────────┐
               │            Supervisor Agent            │
               └───────────┬───────────────────▲────────┘
                           │                   │
             ┌─────────────┴─────────────┐     │ (Queue State / Task Feedback)
             ▼                           ▼     │
  ┌──────────────────────┐   ┌──────────────────────┐
  │ Literature Retrieval │   │ Citation Verification│
  └──────────┬───────────┘   └───────────▲──────────┘
             │                           │ (Metadata Checks)
             ▼                           │
  ┌──────────────────────┐   ┌───────────┴──────────┐
  │   Generation Agent   │   │  Safety & Reflection │
  └──────────┬───────────┘   └───────────▲──────────┘
             │                           │ (Critiques / Approval)
             ▼                           │
  ┌──────────────────────┐   ┌───────────┴──────────┐
  │   Proximity Agent    │──►│     Ranking Agent    │
  └──────────────────────┘   └───────────┬──────────┘
                                         │ (Elo Scores)
                                         ▼
                             ┌──────────────────────┐
                             │   Evolution Agent    │
                             └───────────┬──────────┘
                                         │
                                         ▼
                             ┌──────────────────────┐
                             │  Meta-Review Agent   │
                             └───────────┬──────────┘
                                         │
                                         ▼
                             ┌──────────────────────┐
                             │Report Synthesis Agent│
                             └──────────────────────┘
```

The 12 core agents are structured as follows:

- **Supervisor Agent:** Acts as the central scheduler. It parses the scoped goal into a research plan, enqueues tasks, manages budgets, monitors termination criteria, and writes system state updates to the database.
    
- **Intake/Interview Agent:** Manages the initial interactive setup. It conducts an interview-style dialogue to capture constraints and preferences, outputting a parsed JSON goal configuration.
    
- **Literature Retrieval Agent:** Searches external scholarly networks and text databases. It retrieves abstracts, citation maps, and full-text metadata, passing these to the memory layer.
    
- **Generation Agent:** Proposes initial focus areas and hypothesis candidates. It uses the retrieved literature to construct detailed biological mechanisms, target pathways, and therapeutic strategies.
    
- **Reflection Agent:** Serves as an automated peer reviewer. It critiques generated hypotheses, checking for logical consistency, empirical support, and scientific novelty.
    
- **Proximity/Clustering Agent:** Analyzes the hypothesis landscape by embedding proposals into high-dimensional vector spaces. It groups similar concepts to eliminate redundant ideas and optimize tournament matches.
    
- **Ranking Agent:** Conducts the tournament of ideas. It moderates pairwise debates between hypotheses, evaluating evidence to assign wins, losses, and updated Elo ratings.
    
- **Evolution Agent:** Refines and improves the top hypotheses. It combines complementary mechanisms and addresses gaps identified by the Reflection and Ranking agents.
    
- **Meta-Review Agent:** Synthesizes the overall tournament history. It distills successful patterns and failed directions, appending them to system prompts to guide subsequent cycles.
    
- **Citation Verification Agent:** Cross-checks all generated citations against database records and external APIs. It ensures that every claim is grounded in real literature and removes hallucinated references.
    
- **Safety Agent:** Evaluates goals and hypotheses for potential risks. It screens inputs and outputs for CBRN hazards, dual-use implications, and unethical research protocols.
    
- **Report Synthesis Agent:** Generates the final scientific output. It compiles the top-ranked hypotheses, supporting literature, critique histories, and validation protocols into a publication-ready Markdown proposal.
    

## Relational Database Schema for Asynchronous Durability

To ensure durability and support session resumption across long run times, all system states must be stored in a relational database. The persistence engine uses SQLite configured with Write-Ahead Logging (WAL) and an active `busy_timeout` of 5000ms. This prevents write locks during parallel operations, allowing multiple agent threads to read and write simultaneously.

The database schema is organized into fifteen tables that capture the state of the multi-agent system. This includes the task queue, tournament match configurations, rating histories, and real-time execution events.

### Table 3: Database Table Schemas and Column Specifications

|**Table Name**|**Primary Key**|**Column Definitions (Data Type, Nullability, Constraints)**|**Foreign Keys & Indexing Targets**|
|---|---|---|---|
|**`sessions`**|`session_id`|`session_id` (UUID, NOT NULL)<br><br>  <br><br>`goal_text` (TEXT, NOT NULL)<br><br>  <br><br>`scoped_preferences` (JSON)<br><br>  <br><br>`budget_usd` (REAL, NOT NULL)<br><br>  <br><br>`budget_spent` (REAL, DEFAULT 0.0)<br><br>  <br><br>`status` (TEXT, NOT NULL)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|None. Index on `status`.|
|**`hypotheses`**|`hypothesis_id`|`hypothesis_id` (UUID, NOT NULL)<br><br>  <br><br>`session_id` (UUID, NOT NULL)<br><br>  <br><br>`title` (TEXT, NOT NULL)<br><br>  <br><br>`mechanism_description` (TEXT, NOT NULL)<br><br>  <br><br>`target_protein` (TEXT)<br><br>  <br><br>`chemical_compound` (TEXT)<br><br>  <br><br>`elo_rating` (REAL, DEFAULT 1200.0)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `sessions(session_id)`. Composite index on `(session_id, elo_rating)`.|
|**`reviews`**|`review_id`|`review_id` (UUID, NOT NULL)<br><br>  <br><br>`hypothesis_id` (UUID, NOT NULL)<br><br>  <br><br>`reviewer_agent` (TEXT, NOT NULL)<br><br>  <br><br>`critique_text` (TEXT, NOT NULL)<br><br>  <br><br>`is_passing` (BOOLEAN, NOT NULL)<br><br>  <br><br>`safety_status` (TEXT, NOT NULL)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `hypotheses(hypothesis_id)`. Index on `hypothesis_id`.|
|**`tournament_matches`**|`match_id`|`match_id` (UUID, NOT NULL)<br><br>  <br><br>`session_id` (UUID, NOT NULL)<br><br>  <br><br>`contender_a_id` (UUID, NOT NULL)<br><br>  <br><br>`contender_b_id` (UUID, NOT NULL)<br><br>  <br><br>`winner_id` (UUID)<br><br>  <br><br>`status` (TEXT, NOT NULL)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `sessions(session_id)`. FKs on `hypotheses(hypothesis_id)`. Index on `(session_id, status)`.|
|**`elo_journal`**|`journal_id`|`journal_id` (INTEGER, AUTOINCREMENT)<br><br>  <br><br>`hypothesis_id` (UUID, NOT NULL)<br><br>  <br><br>`match_id` (UUID, NOT NULL)<br><br>  <br><br>`old_rating` (REAL, NOT NULL)<br><br>  <br><br>`new_rating` (REAL, NOT NULL)<br><br>  <br><br>`recorded_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `hypotheses(hypothesis_id)`. FK on `tournament_matches(match_id)`. Index on `hypothesis_id`.|
|**`tasks`**|`task_id`|`task_id` (UUID, NOT NULL)<br><br>  <br><br>`session_id` (UUID, NOT NULL)<br><br>  <br><br>`agent_role` (TEXT, NOT NULL)<br><br>  <br><br>`payload` (JSON, NOT NULL)<br><br>  <br><br>`status` (TEXT, NOT NULL)<br><br>  <br><br>`lease_expires_at` (TIMESTAMP)<br><br>  <br><br>`retry_count` (INTEGER, DEFAULT 0)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `sessions(session_id)`. Index on `(status, lease_expires_at)`.|
|**`transcripts`**|`transcript_id`|`transcript_id` (UUID, NOT NULL)<br><br>  <br><br>`match_id` (UUID, NOT NULL)<br><br>  <br><br>`debate_round` (INTEGER, NOT NULL)<br><br>  <br><br>`speaker_role` (TEXT, NOT NULL)<br><br>  <br><br>`argument_text` (TEXT, NOT NULL)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `tournament_matches(match_id)`. Index on `match_id`.|
|**`system_feedback`**|`feedback_id`|`feedback_id` (UUID, NOT NULL)<br><br>  <br><br>`session_id` (UUID, NOT NULL)<br><br>  <br><br>`source_agent` (TEXT, NOT NULL)<br><br>  <br><br>`distilled_heuristic` (TEXT, NOT NULL)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `sessions(session_id)`. Index on `session_id`.|
|**`embeddings_meta`**|`vector_id`|`vector_id` (UUID, NOT NULL)<br><br>  <br><br>`hypothesis_id` (UUID, NOT NULL)<br><br>  <br><br>`vector_coordinates` (JSON, NOT NULL)<br><br>  <br><br>`cluster_assignment` (INTEGER)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `hypotheses(hypothesis_id)`. Index on `cluster_assignment`.|
|**`spans`**|`span_id`|`span_id` (UUID, NOT NULL)<br><br>  <br><br>`session_id` (UUID, NOT NULL)<br><br>  <br><br>`task_id` (UUID)<br><br>  <br><br>`operation_name` (TEXT, NOT NULL)<br><br>  <br><br>`duration_ms` (INTEGER, NOT NULL)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `sessions(session_id)`. FK on `tasks(task_id)`.|
|**`events`**|`event_id`|`event_id` (INTEGER, AUTOINCREMENT)<br><br>  <br><br>`session_id` (UUID, NOT NULL)<br><br>  <br><br>`event_type` (TEXT, NOT NULL)<br><br>  <br><br>`payload` (JSON, NOT NULL)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `sessions(session_id)`. Index on `(session_id, event_type)`.|
|**`bench_runs`**|`run_id`|`run_id` (UUID, NOT NULL)<br><br>  <br><br>`benchmark_name` (TEXT, NOT NULL)<br><br>  <br><br>`execution_parameters` (JSON)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|None. Index on `benchmark_name`.|
|**`bench_candidates`**|`candidate_id`|`candidate_id` (UUID, NOT NULL)<br><br>  <br><br>`run_id` (UUID, NOT NULL)<br><br>  <br><br>`model_identifier` (TEXT, NOT NULL)<br><br>  <br><br>`mode` (TEXT, NOT NULL)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `bench_runs(run_id)`. Composite index on `(run_id, model_identifier)`.|
|**`bench_matches`**|`match_id`|`match_id` (UUID, NOT NULL)<br><br>  <br><br>`run_id` (UUID, NOT NULL)<br><br>  <br><br>`candidate_a_id` (UUID, NOT NULL)<br><br>  <br><br>`candidate_b_id` (UUID, NOT NULL)<br><br>  <br><br>`winner_id` (UUID)<br><br>  <br><br>`gold_set_hit` (BOOLEAN)<br><br>  <br><br>`created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|FK on `bench_runs(run_id)`. FKs on `bench_candidates(candidate_id)`.|
|**`migration_history`**|`version`|`version` (INTEGER, NOT NULL)<br><br>  <br><br>`applied_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)|None. Primary Key on `version`.|

## Memory Architecture and Episodic Context Reconstruction

Managing context is a critical challenge in long-running agent workflows. As sessions generate detailed debate logs, literature citations, and critiques, loading raw histories into agent prompts can quickly exceed token limits and degrade model accuracy. To address this, the system implements a layered memory architecture:

- **Short-Term State:** Handles immediate runtime context. It is stored in the active database, running scratchpads, and the current task execution queue. This data is discarded upon task completion.
    
- **Long-Term Episodic Memory:** Preserves the chronological history of the session. It records full tournament transcripts, rating changes, and past experimental failures, enabling the system to avoid repeating unproductive research directions.
    
- **Long-Term Semantic Memory:** Captures stable, verified scientific knowledge. It is stored as vector embeddings of literature metadata, combined with structured records of pathways, targets, and drug mechanisms.
    

Rather than relying on simple text retrieval—which can return fragmented, out-of-context blocks—the system uses **Episodic Context Reconstruction (E-mem)**. This framework organizes the system's uncompressed episodic memory into structured segments managed by lightweight, local assistant agents.

```
┌────────────────────────────────────────────────────────────────────────┐
│                      EPISODIC CONTEXT RECONSTRUCTION                   │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  User Query ──► ──► Segment Activated                │
│                                            │                           │
│                                            ▼                           │
│                              [ E-Mem Assistant Agent ]                 │
│                              - Context-aware analysis                  │
│                              - Logical proof formulation               │
│                                            │                           │
│                                            ▼                           │
│  Master Agent ◄────────────────── Verified Claims Only                 │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

When a query is made, the routing layer activates only the relevant memory segment. The associated assistant agent analyzes the uncompressed context, constructs a logical proof of the findings, and returns only these verified claims to the master planning core. This segment-based processing eliminates the "lost-in-the-middle" problem in long-context models, improving retrieval precision by 7.75% while reducing downstream token processing costs by over 70%.

To keep token usage within bounds during long debates or evolution steps, the system uses a **Hierarchical Summarization and Compaction** routine. The Supervisor monitors token counts across active dialogue channels. If the count crosses a threshold (such as `AUTOCOMPACT_BUFFER_TOKENS = 13000`), the system pauses execution and initializes a text-only compaction pass.

Using a `NO_TOOLS_PREAMBLE` to suppress tool-use calls, the system compresses the active dialogue into a structured summary. The full, uncompressed logs are written to an offline archive file, and a clean recovery prompt resumes the agent's work, referencing the summary and the persistent file path without losing task continuity.

The distribution of the available context window across these layers during execution is structured to prioritize verification and logical consistency:

$$\text{Context Window Budget} \rightarrow \underbrace{\text{Core Prompt \& Instructions}}_{\approx 15\%} + \underbrace{\text{Grounded Facts \& Citations}}_{\approx 40\%} + \underbrace{\text{Episodic Reconstruction Segment}}_{\approx 30\%} + \underbrace{\text{Active Workspace Scratchpad}}_{\approx 15\%}$$

## Self-Optimizing Prompts and Execution Learning

To maintain grounding and keep the system steering correctly, agent-to-agent transitions use formal, file-based interfaces rather than transient chat logs. The system centers its collaborative state around a **Living Working Paper** written in structured Markdown, mimicking professional human workflows. This document is maintained in a designated directory, allowing downstream agents to inspect, comment on, and modify specific sections.

By standardizing handoffs using explicit file-based contracts and schema-validated JSON gates, the system ensures that error states do not propagate across the agent network.

Furthermore, the system implements a continuous self-improvement mechanism: a prompt-evolution loop that enables learning without backpropagation. The architecture manages two persistent memory repositories :

1. **Ideation Memory Repository:** Tracks successful research directions that advanced through the tournament, while recording failed hypotheses and the specific critiques that led to their rejection.
    
2. **Experimentation Memory Repository:** Captures effective code implementations, tool parameters, and successful debugging paths.
    

At the conclusion of a tournament cycle, the Meta-Review agent analyzes these repositories, distilling the operational patterns that separate successful runs from failures. It formats these insights into concrete heuristics and appends them directly to the system prompts of the Generation and Evolution agents for subsequent cycles. This prompt evolution allows the system to iteratively refine its ideation and code generation strategies without retraining the underlying models.

This self-improving prompt evolution mechanism is governed by structured templates. The markdown prompts defined below are processed using Jinja interpolation, ensuring that historical learning and task constraints are dynamically woven into the context of downstream agents during execution.

### Supervisor Task Formulation Prompt

# Supervisor Agent Task Configuration

You are the centralized Supervisor and Lead Architect for the Co-Scientist system. Your role is to coordinate a team of specialized agents, schedule computational resources, and manage the execution lifecycle to solve the following research objective :

## Target Scientific Objective

{{ user_goal_text }}

## Available Agent Roster

1. Generation Agent: Formulates grounded initial hypothesis statements.
    
2. Reflection Agent: Critical reviewer for logic, feasibility, and safety limits.
    
3. Proximity Agent: Evaluates similarity vectors to cluster and dedup ideas.
    
4. Ranking Agent: Conducts pairwise debates and Elo tracking.
    
5. Evolution Agent: Simplifies, adapts, and refines top-ranked hypotheses.
    
6. Meta-Review Agent: Synthesizes debate history to write the final overview.
    

## System Constraints and Operational Guidelines

1. Contain cascading errors by validating all task output schemas against JSON targets.
    
2. Track model token budgets closely. Trigger auto-compaction routines if active dialogue channels cross context safety limits.
    
3. Maintain execution tracking via the SQLite database queue. Do not allow orphaned tasks to block execution; reclaim and reschedule expired leases.
    

## Strategy Appended from Historical Cycles

{{ persistent_heuristics_override }}

Evaluate the objective, check active system dependencies, and write the next set of prioritized agent tasks to the execution queue.

### Generation Prompt with Appended Heuristics

# Scientific Hypothesis Generation Protocol

You are the Generation Agent. Your objective is to formulate unique, empirically testable, and novel hypotheses addressing the target scientific goal.

## Target Scientific Goal

{{ target_goal }}

## Grounded Literature Context and Evidence

{{ grounded_fact_sheet }}

## Negated Directions and Failed Pathways (To Avoid)

The following ideas and mechanisms failed in past evaluation rounds. DO NOT propose hypotheses that rely on these pathways : {{ excluded_pathways }}

## Appended Search Heuristics

Analyze these compiled strategy metrics to optimize your current generation logic : {{ appended_generation_strategies }}

## Output Specification

You must write your output as a single, validated JSON payload conforming to the schema below. Do not include any preambles, explanations, or Markdown formatting blocks outside the JSON.

{

"title": "Clear, concise title of the proposed hypothesis",

"biological_mechanism": "A highly detailed description of the proposed biochemical mechanism, targets, and pathways",

"proposed_drug_or_agent": "Specific drug candidates, tool compounds, or molecular designs suggested",

"supporting_evidence":"

}

],

"downstream_validation_protocol": "A concrete experimental design or assay sequence to test this hypothesis in vitro or in silico"

}

### Pairwise Debate and Evaluation Prompt

# Pairwise Debate and Evaluation Protocol

You are the Ranking Agent. You must evaluate two competing scientific hypotheses by conducting a structured, skeptical debate to determine which proposal is more logically coherent, scientifically novel, and experimentally testable.

## Competing Hypotheses

### Contender A

- Title: {{ contender_a.title }}
    
- Mechanism: {{ contender_a.mechanism }}
    
- Citations: {{ contender_a.citations }}
    

### Contender B

- Title: {{ contender_b.title }}
    
- Mechanism: {{ contender_b.mechanism }}
    
- Citations: {{ contender_b.citations }}
    

## Verification and Grounding Rules

1. Verify all supporting claims against the provided search contexts. Flag and penalize any hallucinated citations or physical contradictions.
    
2. Prioritize candidates that identify clear, testable molecular interactions over vague, generic therapeutic claims.
    
3. Reject incremental proposals that merely restate consensus literature views.
    

Evaluate both proposals, document their respective strengths and vulnerabilities in a systematic debate transcript, and select the winner.

## Output Format

## Your final output must terminate with this exact decision block

:

DECISION:

DECISION_RATIONALE: A concise summary outlining the definitive evidence that dictated the outcome of this match.

## Evaluation Framework and Fidelity Verification Harness

To confirm that the cloned system mirrors DeepMind's original implementation, it must be evaluated using a structured **Fidelity Evaluation Harness**. This harness tests the system across key operational parameters, ensuring that agent behaviors, search patterns, and tournament dynamics match expected baselines.

```
                     FIDELITY EVALUATION HARNESS
 
      System Output ──────► ────► Meets Baseline?
                                    │                           │
                                    ▼                           ▼ (No)
                           [ Pass to Production ]        
```

The evaluation parameters are categorized into specific testing domains, as outlined below:

### Table 4: Evaluation Domains and Metrics

|**Testing Domain**|**Verification Criteria**|**Target Baseline**|**Metric**|
|---|---|---|---|
|**Product Flow**|Verifies the execution of the user interactive sequence, matching the standard target.|Successful completion of the Intake $\rightarrow$ Standard/Advanced $\rightarrow$ Follow-up pipeline.|Boolean verification of completed stages.|
|**Terminology**|Confirms that system outputs use standard scientific and multi-agent terminology.|Verifies exact matching of core agent roles and scientific entities.|Regex matching of logged data keys.|
|**Report Structure**|Validates that output files contain all required sections in the correct format.|Generates complete proposals containing hypotheses, citations, and experimental protocols.|Schema verification of final Markdown files.|
|**Agent Behavior**|Monitors execution logs to confirm that specialized agents perform their designated roles.|Zero crossover of roles; agents operate within their specified boundaries.|Execution trace validation via database logs.|
|**Tournament Behavior**|Evaluates match schedules, debate transcripts, and the accuracy of rating updates.|Pairwise comparisons update Elo ratings, leading to a stable leaderboard.|Rating system variance over time ($\sigma \le 10$).|
|**Evidence Grounding**|Audits output hypotheses to ensure every claim is backed by a verified citation.|Zero inclusion of unverified or hallucinated citations.|Independent citation cross-checks.|
|**Safety Behavior**|Tests safety systems using adversarial prompts across multiple scientific domains.|100% rejection rate for dual-use, harmful, or unethical prompts.|Zero safety gate failures across 1,200 adversarial test cases.|
|**Progress & Latency**|Measures execution times, thread allocation, and concurrency handling.|Zero deadlocks during parallel tasks, with fast processing times.|Task trace duration logging via database timestamps.|
|**Final Output Quality**|Compares final proposals against verified scientific standards and human expert designs.|System-generated hypotheses meet or exceed human-designed targets.|Blind expert evaluation of novelty and impact.|

## Conclusions and Actionable Technical Recommendations

Based on this technical specification, the following recommendations are provided to the project director to guide the automated development of the multi-agent system :

- **Initialize the Durable Persistence Layer:** Configure the SQLite database in WAL mode with a busy timeout of 5000ms. Apply the fifteen-table schema defined in Table 3 to ensure full session durability and crash recovery.
    
- **Establish the Closed-Loop Coding pipeline:** Feed this architectural specification to the planning agent to generate task specifications. Direct the coding agent (such as Claude Code) to build, test, and debug the Python execution files in a sandboxed directory.
    
- **Implement the E-mem Memory System:** Implement Episodic Context Reconstruction by assigning memory segments to lightweight assistant agents. This reduces token overhead by 70% while improving retrieval precision.
    
- **Deploy the Validation Harness:** Configure the validation harness defined in Table 4 to monitor system performance. Run adversarial test cases to confirm the system meets the safety and precision standards of DeepMind's original design.
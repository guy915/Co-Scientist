# Architecture and User Experience Design Specification for a High-Fidelity AI Co-Scientist Clone

The landscape of scientific discovery is undergoing a structural transition from static, single-turn query systems to dynamic, autonomous, long-running multi-agent research platforms. Google DeepMind’s AI Co-Scientist represents the state of the art in this shift, utilizing a collaborative coalition of specialized Gemini-based agents to iteratively generate, debate, and evolve scientific hypotheses. Building a high-fidelity, production-grade clone of this architecture requires a detailed integration of distributed job queues, durable state persistence, mathematical evaluation engines, and transparent, non-obtrusive user experience patterns. This report provides the complete architectural blueprint and implementation specification for such a system, ensuring that complex, multi-day scientific runs are robust, verifiable, safe, and highly controllable.

## Core Operational Paradigms and the Scientific Hypothesis Loop

The system operates as a closed-loop scientific reasoning engine, modeling the cyclic nature of human hypothesis generation, validation, and refinement. The primary pipeline progresses through eight distinct stages to transform an abstract research objective into a fully formulated, literature-grounded research proposal. This execution loop is fundamentally designed around test-time compute scaling, dedicating the majority of computational resources to verification, adversarial debate, and iterative refinement rather than simple token output generation.

```
┌────────────────────────────────────────────────────────────────────────┐
│                              SYSTEM LOOP                               │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│                                                │
│             │                                                          │
│             ▼                                                          │
│                                 │
│             │                                                          │
│             ▼                                                          │
│  <─── Curated Databases / Web Grounding│
│             │                                                          │
│             ▼                                                          │
│  [ Hypothesis Generation ] ◄────────────────────────────────────────┐  │
│             │                                                      │  │
│             ▼                                                      │  │
│                                          │  │
│             │                                                      │  │
│             ▼                                                      │  │
│  ─── Win/Loss Pattern Analysis         │  │
│             │                                                      │  │
│             ▼                                                      │  │
│  [ Hypothesis Evolution ] ──────────────────────────────────────────┘  │
│             │                                                          │
│             ▼                                                          │
│                                     │
│             │                                                          │
│             ▼                                                          │
│                                     │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

The system provides two distinct execution modes to manage the balance between speed, cost, and depth of discovery:

- **Standard Runs:** Configured for rapid conceptual iteration. Standard runs execute shallow search patterns, limit the tournament pool to a smaller number of initial candidates, run parallel debates with constrained iterations, and deliver a structured overview within minutes. This mode is ideal for verifying search parameters, testing domain profile weights, and refining the target research question.
    
- **Advanced Runs:** Configured for comprehensive scientific discovery. Advanced runs scale test-time compute across hours or days, querying deep databases, executing extensive pairwise tournaments, and utilizing complex evolutionary mutation matrices to generate highly novel, structurally sound scientific proposals.
    

## Multi-Agent Architecture and Distributed Subsystem Integration

The underlying architecture is built as a highly decoupled, distributed multi-agent system. To prevent context pollution, token bloat, and planning failures, a monolithic coordinator is avoided. Instead, specialized agents are registered with explicit runtime roles, narrow tool sets, and distinct system instructions. Table 1 maps out the integration of these subsystems, detailing their structural interfaces, data dependencies, and role in the platform.

### Table 1: Subsystem and Core Agent Integration Matrix

|**Subsystem Component**|**Registered Agent Persona**|**Data Inputs and Dependencies**|**Subsystem Responsibility & Output Artifacts**|
|---|---|---|---|
|**Web UI & Control Console**|None (Direct User Interaction Layer).|Scoped configurations, user feedback loops, and runtime state variables.|Renders run timelines, active agent statuses, task logs, running cost meters, and interactive checkpoints.|
|**Backend API Gateway**|**Intake/Interview Agent**.|User natural language research objective, domain sliders, and parameter selections.|Conducts clarifying scoping dialogues, generates the run profile, and submits jobs to the persistent execution queue.|
|**Long-Running Job Queue**|**Supervisor Agent**.|State execution graphs, worker availability logs, and runtime session contexts.|Manages asynchronous task distribution, handles worker failures, tracks run health, and coordinates parallel execution paths.|
|**Scientific Retrieval Layer**|**Literature Retrieval Agent**.|Automated query arrays, external API credentials, and web-grounding tokens.|Connects to web grounding layers and curated databases (ChEMBL, UniProt) to compile verified reference corpora.|
|**Hypothesis Store**|**Generation Agent** & **Proximity Agent**.|Grounded literature corpora, domain profile parameters, and active hypothesis lists.|Generates structured hypothesis objects, maps conceptual similarities, and clusters proposals to ensure diversity.|
|**Evidence & Citation System**|**Citation Verification Agent**.|Synthesized proposal texts, claim assertions, and indexed reference document metadata.|Performs targeted, dual-pass claim-to-source validation and embeds verified, clickable inline citations.|
|**Tournament & Ranking Engine**|**Reflection Agent** & **Ranking Agent**.|Hypothesis candidate arrays, evaluation configurations, and match rules.|Conducts parallel multi-axis reviews, executes pairwise debates, and manages Elo rating calculations.|
|**Report Generator**|**Report Synthesis Agent**.|Top-ranked tournament survivors, critique ledgers, and citation links.|Synthesizes and formats top ideas into publication-ready, interactive scientific research briefs.|
|**Safety Layer**|**Safety Agent**.|Scoped prompts, generated draft texts, and proposed protocol inputs.|Audits operations against CBRN guidelines and dual-use restrictions, executing immediate halts on non-compliance.|
|**Fidelity Evaluation Harness**|**Meta-Review Agent**.|Full tournament histories, debate transcripts, and baseline reference sets.|Analyzes win/loss patterns, computes alignment metrics, and evaluates run similarity to human baselines.|

## Long-Running Job Execution and State Persistence Models

To ensure the system remains resilient over long execution periods, it must be built upon a robust, stateful orchestration substrate that decouples runtime parameters from interaction logs. The standard practice of passing conversational history back and forth fails due to context degradation, token cost escalation, and process instability.

Instead, the system relies on structured state persistence, utilizing a hybrid model that combines the dynamic, tool-driven graph capabilities of LangGraph with the durable, transaction-safe execution engine of Temporal.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATION LAYER                             │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│                  │
│    │                                                                   │
│    ├─► Activity 1: Literature Grounding (Durable Activity)             │
│    │                                                                   │
│    ├─► Activity 2: LangGraph Execution (Dynamic Inner Loops)           │
│    │     │                                                             │
│    │     ├─► Node A: Hypothesis Generation                             │
│    │     ├─► Node B: Virtual Peer Review                               │
│    │     ├─► Node C: Pairwise Tournament Matches                       │
│    │     └─► Node D: Evolutionary Mutation                             │
│    │                                                                   │
│    └─► Activity 3: Citation Verification (Durable Activity)            │
│                                                                   │
└────────────────────────────────────────────────────────────────────────┘
```

The system implements the "Fred" architectural pattern to separate orchestration roles. Temporal operates as the outer, durable execution substrate. It manages transaction history, monitors execution heartbeats, provides automatic backoffs, and coordinates asynchronous task queues without exposing raw infrastructure details to the agent layer.

The actual agent logic is built within LangGraph, which executes inside isolated, long-running Temporal Activities. This separation ensures that the internal agent graph remains highly dynamic and tool-driven, while Temporal handles overarching system durability, error recovery, and cross-session persistence.

To mitigate memory limits and event history bloat over extended runs, the system combines Temporal's _Continue-As-New_ history compaction with the _EvoScientist_ persistent memory framework. Persistent storage is split into two specialized memory modules:

- **Ideation Memory:** Records and structures successful, highly-ranked conceptual paths while preserving a detailed ledger of unsuccessful, logically flawed, or physically implausible research directions to avoid repeating failures.
    
- **Experimentation Memory:** Aggregates verified data processing templates, successful database query formats, and model configurations derived across prior successful runs.
    

Table 2 contrasts the operational trade-offs and structural mechanics of these state persistence methods.

### Table 2: Architectural Trade-Offs of Orchestration and Persistence Substrates

|**Substrate Model**|**Architectural Advantages**|**Primary Constraints**|**Checkpoint & Replay Mechanics**|
|---|---|---|---|
|**LangGraph (Workflow Graph)**|* Excellent for complex, dynamic, cyclical agent loops.<br><br>  <br><br>* Native human-in-the-loop graph interrupt structures.|* Subject to execution loss on container crash if not durably backed.<br><br>  <br><br>* Manual state pruning required.|Node-level checkpointing; saves the entire active state dictionary to Postgres or InMemorySaver.|
|**Temporal (Durable Execution)**|* Guarantees execution survival across worker crashes.<br><br>  <br><br>* Built-in timers, retries, and cancellation tokens.|* Requires strict determinism in workflow code.<br><br>  <br><br>* Event history bloat over extended runs.|Activity-level logging; replays append-only event history to rebuild execution states.|
|**Google ADK (Event State Machine)**|* Decoupled from conversation logs, preventing context bloat.<br><br>  <br><br>* Highly scale-to-zero efficient.|* Requires manual definition of state machine transitions.<br><br>  <br><br>* Slower node transitions.|Tool-level atomic checkpointing via `ToolContext.state` to persistent databases.|
|**Fred Hybrid Model**|* Combines LangGraph's dynamic loops with Temporal's robust resilience.<br><br>  <br><br>* Portable, framework-agnostic worker code.|* Complex deployment topology.<br><br>  <br><br>* High development overhead.|Wraps LangGraph in Temporal Activities; uses Temporal signals to trigger inner graph checkpoints.|

## Design Patterns for Transparent and Controllable Scientific User Experiences

An expert-level scientific agent system must reject the "Opaque Autopilot" design pattern, where the model executes complex tasks behind a generic loading spinner. If researchers cannot inspect intermediate findings or steer the system's focus, they lose confidence in the results. Conversely, forcing users to parse raw, scrolling terminal logs results in cognitive fatigue.

The user experience must balance visibility and usability, presenting a clear control console that makes long-running scientific work feel transparent, reliable, and highly steerable.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        MAIN CONTROL PANELS                             │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│                              │
│     ├─ Slider: Technical Priorities (Feasibility vs Risk-Reward)       │
│     └─ Parameter: Max Test-Time Compute Budget                         │
│                                                                        │
│                                                  │
│     ├─ (●) Goal Scoping & Extraction                                   │
│     ├─ (●) Grounding & Query Construction                              │
│     ├─ (▶) Pairwise Tournament (Match 14 of 42)                        │
│     └─ (○) Report Synthesis & Citation Mapping                         │
│                                                                        │
│                                       │
│     ├─ Active Agent: Ranking Agent                                     │
│     ├─ Sub-Task: Debating Hypothesis A vs Hypothesis B                 │
│     └─ Real-time Output: Summarizing comparative trade-offs...         │
│                                                                        │
│  [ Metric Meters Panel ]                                               │
│     ├─ Running Cost: $42.50 spent of $100.00 ceiling                   │
│     ├─ Latency Meter: 02h 14m elapsed of 04h 00m estimate              │
│     └─ Volume Meter: 340 source documents indexed                      │
│                                                                        │
│  [ Interactive Handoff & Action Center ]                               │
│     ├─ ALERT: Reflection Agent flagged conceptual risk on Target C.    │
│     └─ BUTTONS:     [ CANCEL ]  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

The system's control panel is structured around several primary user experience elements:

- **Interactive Scoping Interview:** Conducted by the Intake Agent, this module uses a structured scoping interface to clarify research boundaries, isolate variables, flag target data sources, and configure domain profile configurations before starting a run.
    
- **Visual Run Timeline:** A timeline tracking major milestones (Goal Scoping, Retrieval Grounding, Generation, Evaluation, Debating, Mutation, Report Synthesis). It displays completion percentages, elapsed time, and remaining processing estimates.
    
- **Active Agent Panel:** Highlights which agent is active, its current sub-task, and the tools or external databases it is accessing, making the system's reasoning legible.
    
- **Running Metrics Console:** Tracks real-time resource utilization, including API token usage, financial spend, and the volume of indexed documents. Running limits halt execution if a cost or time limit is reached.
    
- **Interactive Handoff Center:** Displays active system alerts (such as safety warnings or low-confidence evaluations) and provides clear action controls.
    
- **Follow-up Interaction Console:** After a run completes, this interface provides tools to inspect generated reports, browse clustered ideas, review the verified Knowledge Base, and query the final proposal in a chat console to refine specific protocols.
    

Table 3 maps these UI views to the underlying system execution states, defining active agent personas, intermediate data outputs, and user control overrides at each step.

### Table 3: System Execution State and User Interface Mapping

|**Pipeline Phase**|**Active Agent Personas**|**Generated Intermediate Data**|**Visible Control Panel Elements**|**User Override Actions**|
|---|---|---|---|---|
|**Scoping**|Intake/Interview Agent, Supervisor Agent.|Scoped research profile, user parameter payload.|Clarifying question list, domain configuration sliders.|Submit parameters, update domain weights, skip interview.|
|**Grounding**|Literature Retrieval Agent, Safety Agent.|Search term query sets, retrieved document profiles, safety validation pass.|Query construction status bar, source retrieval logs, target document counters.|Pause retrieval, inject custom reference PDFs, refine search terms.|
|**Generating**|Generation Agent, Proximity Agent, Supervisor Agent.|Initial candidate hypothesis objects, semantic distance coordinates.|Hypothesis cluster diagrams, conceptual mapping plots, diversity logs.|Adjust diversity sliders, modify cluster parameters, insert manual hypotheses.|
|**Evaluating**|Reflection Agent, Safety Agent.|Multi-axis scalar scores, structured critique reports.|Review progress bars, parallel grading dashboards, safety checks.|Interrupt evaluation, modify criteria weights, flag low-confidence reviews.|
|**Debating**|Ranking Agent, Supervisor Agent.|Matchup transcript logs, updated Elo ratings, bracket updates.|Pairwise tournament brackets, active matchup status screens.|Override match verdicts, pause tournament, inspect debate transcripts.|
|**Evolving**|Evolution Agent, Supervisor Agent.|Mutated hypothesis objects, parent-child lineage mappings.|Evolutionary lineage tree diagrams, mutation parameter trackers.|Select mutation operators, manually cross-breed ideas.|
|**Paused**|Supervisor Agent (Dormant state).|Saved database session checkpoint, active state delta payload.|Interactive approval cards, elapsed pause timer, state comparison views.|Resume execution, rollback to previous node, cancel job.|
|**Synthesis**|Report Synthesis Agent, Citation Verification Agent.|Draft scientific report, verified claim-to-source map links.|Report compiler progress bar, citation checking logs.|Reject draft report, adjust formatting, trigger deep citation check.|
|**Complete**|None (Post-Run State).|Final structured research proposal, clickable references.|Rendered research proposal, exported PDF/Markdown downloads, follow-up query terminal.|Export proposal file, execute follow-up query, initialize refinement run.|
|**Failed**|Supervisor Agent.|System trace reports, detailed error exception logs.|Failure point timeline alerts, diagnostic trace viewer.|Retry failed node, rollback to last saved checkpoint, export debug log.|

## Mathematical Formulations for Hypothesis Evaluation and Tournament Mechanics

To systematically prioritize thousands of generated scientific hypotheses and identify the most robust directions, the co-scientist clone implements an Elo-based "Tournament of Ideas". Rather than relying on absolute scalar ratings from individual models—which are highly prone to grading bias and calibration drift—the evaluation engine uses adversarial, pairwise debates graded by an LLM-as-Judge.

The active hypotheses are first evaluated in parallel by the Reflection Agent across multiple domain-specific axes, yielding scalar scores ($S_i$) on a 1-to-5 scale. To ensure that small adjustments to user-controlled domain weights ($W_i$) translate into meaningful score differences, the system applies a squared scoring mechanism to amplify the raw evaluations :

$$\text{weightedTotal} = \sum_{i=1}^{M} W_i \times (S_i)^2$$

Based on these weighted total scores, candidates are sorted, and an _Adjacent-Pair Tournament_ is initiated. Rather than executing an expensive, all-versus-all $N^2$ matchup matrix, the engine runs pairwise comparisons only between adjacent candidates in the sorted array, reducing matchup complexity to $N-1$ matches.

For each matchup, an LLM-as-Judge Agent is initialized with the two competing proposals and their associated grounding literature. The judge evaluates both candidates based on logical coherence, mechanical specificity, and plausibility, ultimately declaring a definitive win/loss verdict. Following the verdict, the global Elo ratings of the proposals are updated. To ensure rating adjustments reflect the strength of the victory, a margin-of-victory K-factor scaling mechanism is applied :

$$\text{effectiveK} = 32 \times \min(5.0, 1 + 25 \times \text{rawMargin})$$

The variable $\text{rawMargin}$ represents the absolute difference in weighted total scores between the two competing hypotheses. Decisive wins result in a significantly larger Elo shift, while close matchups yield conservative updates.

The top-ranked tournament survivors are routed to the Evolution Agent, which applies targeted mutation strategies to generate improved offspring hypotheses. These mutation operators are mathematically modeled to focus refinement efforts on weaker axes:

- **Crossover:** Combines dominant conceptual strengths from two high-scoring parent hypotheses ($H_A, H_B$) to form a hybrid offspring ($H_O$).
    
- **Targeted Mutation:** Identifies the lowest-scoring evaluation axis ($S_{\min}$) of a parent hypothesis and prompts the model to generate an offspring that addresses this specific vulnerability.
    
- **Reinforcement:** Amplifies the highest-scoring axis ($S_{\max}$) of a strong parent hypothesis, maximizing its conceptual leverage.
    

The mathematical parameters governing these evaluations, matchmaking rules, and mutation operators are detailed in Table 4.

### Table 4: Mathematical Parameters for Tournament and Evolution Engineering

|**Evaluation Attribute**|**Operational Formula / Operator**|**Parameter Boundaries**|**Engineering Purpose**|
|---|---|---|---|
|**Weighted Score**|$\text{weightedTotal} = \sum_{i=1}^{M} W_i \times (S_i)^2$.|$S_i \in $, $W_i \in [0.0, 1.0]$, $\sum W_i = 1.0$.|Squares raw evaluations to amplify differences, ensuring user weight adjustments shift tournament rankings.|
|**Matchup Selection**|Adjacent-Pair Tournament: Match candidate $R_k$ vs $R_{k+1}$ in sorted array.|Array index $k \in [1, N-1]$, yielding $N-1$ matchups.|Optimizes computational efficiency, reducing tournament cost from $N^2$ to $N-1$.|
|**K-Factor Scaling**|$\text{effectiveK} = 32 \times \min(5.0, 1 + 25 \times \text{rawMargin})$.|$\text{effectiveK} \in $.|Adjusts rating sensitivity dynamically based on the margin of victory.|
|**Elo Rating Update**|$R'_A = R_A + \text{effectiveK} \times (S_A - E_A)$.|Expected outcome: $E_A = \frac{1}{1 + 10^{(R_B - R_A)/400}}$.|Updates hypothesis relative rankings based on matchup outcomes.|
|**Crossover Operator**|$H_O = \text{LLM}(H_A \cup H_B \mid \text{Shared Mechanics})$.|Parent Elo $R_A, R_B \ge R_{\text{median}}$.|Merges complementary scientific ideas into high-potential hybrid proposals.|
|**Targeted Mutation**|$H'_A = \text{LLM}(H_A \mid \text{Mitigate } S_{\min})$.|Target Selection: $i = \arg\min_j(S_j)$.|Directs the model to resolve specific logical or physical flaws highlighted by peer reviews.|
|**Reinforcement**|$H''_A = \text{LLM}(H_A \mid \text{Amplify } S_{\max})$.|Target Selection: $i = \arg\max_j(S_j)$.|Maximizes the core conceptual strength of highly-ranked hypotheses.|

## Verification Systems, Safety Layering, and Compliance Safeguards

A multi-agent scientific discovery platform must prioritize factual precision and biological safety over creative, ungrounded generation. To prevent factual errors and enforce safety guidelines, the system implements a series of active compliance and verification checks throughout the execution lifecycle.

### Scientific Retrieval & Grounding

During the Literature Grounding phase, the retrieval layer executes parallel search queries across public indexes alongside specialized biological and chemical databases, including ChEMBL, UniProt, and PubMed. Retrieved data—such as target-binding affinities, chemical structure representations, and clinical study profiles—are stored as vectorized metadata records. These structured profiles are directly injected into the generation prompts, ensuring that all candidate hypotheses are grounded in existing empirical evidence.

### Citation Verification

To verify the accuracy of the final research proposal, a dual-pass Citation Verification Agent is deployed before output generation.

- **First Pass (Assertion Extraction):** The verification agent parses the draft proposal, extracts technical claims, and lists them as standalone assertions.
    
- **Second Pass (Source Mapping):** The agent compares each assertion against the indexed database of retrieved literature. It maps verified assertions to specific source documents and adds clickable inline citations. Assertions that cannot be mapped to a verifiable literature source are flagged for manual review, and the system prompts the user to provide additional reference documents.
    

### Safety Auditing

To prevent the misuse of high-capability models in dangerous domains, a multi-layered safety pipeline is enforced throughout the execution lifecycle :

- **Adversarial Input Filtering:** At the scoping phase, the Safety Agent audits the user's research goal against a catalog of prohibited domains, including chemical, biological, radiological, and nuclear (CBRN) threat profiles. Prompts that suggest dual-use or hazardous research pathways are immediately rejected.
    
- **Planner-Talker Safety Isolation:** During hypothesis generation and evolution steps, a dual-agent monitoring architecture is implemented, mimicking clinical-grade safety models. A background "Planner" safety module continuously monitors the generated outputs of the active "Talker" agent. If the generation agent begins drafting instructions for hazardous compound synthesis or restricted biological protocols, the safety module overrides the active state and halts execution.
    
- **Observation-Based Review:** During the Reflection phase, hypotheses are evaluated for potential safety hazards. Any proposal that poses a potential risk is flagged, and the system prompts the user to provide additional safety justifications before proceeding.
    

## System Fidelity Evaluation and Similarity Benchmarks

To ensure the co-scientist clone matches the performance of DeepMind’s system, the platform must be evaluated across multiple dimensions. Evaluators must avoid relying solely on lexical overlap metrics (like ROUGE or BLEU), which often score fluent but incorrect scientific text highly.

Instead, the platform's performance, behavior, and output quality are validated against reference benchmarks, such as _Matter to Mechanism_ (problem-to-hypothesis reasoning) and _BixBench_ (computational biology analyses).

Evaluation spans nine similarity dimensions:

- **Product Flow Similarity:** Validates that the system progresses through the defined scoping, evaluation, tournament, and reporting states without skipping stages.
    
- **Terminology Similarity:** Ensures the generated reports, system states, logs, and metadata match standard scientific nomenclature and co-scientist definitions.
    
- **Report Structure Similarity:** Confirms that the synthesized research proposals match professional publication layouts, featuring logical sections, structured methodologies, and clickable citations.
    
- **Agent Behavior Similarity:** Audits individual agent interactions, ensuring the Generation agent produces diverse ideas, the Reflection agent provides accurate critiques, and the Evolution agent applies correct mutation operators.
    
- **Tournament Behavior Similarity:** Measures the correlation between the tournament's Elo ratings and human expert rankings, confirming the system prioritizes the most viable hypotheses.
    
- **Evidence and Citation Behavior Similarity:** Confirms that claims in generated reports are mapped to verifiable literature sources without hallucinating references.
    
- **Safety Behavior Similarity:** Evaluates the Safety Agent against adversarial benchmarks, ensuring it blocks hazardous prompts while permitting legitimate research.
    
- **Progress and Latency Behavior Similarity:** Measures execution timelines across standard and advanced runs, ensuring parallel workers remain healthy and tasks progress predictably.
    
- **Final Output Quality Similarity:** Scores the final proposals on reasoning fidelity, alignment, mechanistic specificity, novelty, plausibility, and decomposition quality using a consensus of expert human and LLM judges.
    

Table 5 defines the testing protocols, target metrics, and acceptable baseline scores for each of these similarity dimensions.

### Table 5: High-Fidelity Evaluation and Similarity Metric Matrix

|**Similarity Dimension**|**Target Testing Protocol**|**Evaluated Metric**|**Acceptable Baseline Score**|
|---|---|---|---|
|**Product Flow**|Trace verification across standard and advanced runs.|Workflow state alignment; validates that the system progresses through the eight core loop stages.|$\ge 98\%$ state transition match against reference co-scientist traces.|
|**Terminology**|Static analysis of system logs, schemas, and UI variables.|Keyword and nomenclature alignment against reference definitions.|$100\%$ compliance with co-scientist vocabulary.|
|**Report Structure**|Structural audit of generated reports against standard layouts.|Structural component completeness (e.g., Summary, Run Specifications, Knowledge Base, ranked concepts).|$100\%$ layout component compliance.|
|**Agent Behavior**|Evaluation of worker actions against isolated test datasets.|Role-specific prompt fidelity and execution accuracy.|$\ge 95\%$ adherence to agent role definitions.|
|**Tournament Behavior**|Validation of tournament Elo rankings against human expert rankings on curated datasets.|Rank correlation coefficient (Spearman's $\rho$) between tournament Elo ratings and human expert evaluations.|Spearman's $\rho \ge 0.82$ on GPQA and expert-curated benchmarks.|
|**Evidence & Citation**|Claim-to-source auditing using manual checks and automated validation engines.|Citation faithfulness and claim-to-source precision.|$\ge 96\%$ citation accuracy with zero hallucinated references.|
|**Safety Behavior**|Red-teaming using adversarial prompts across multiple scientific domains.|Safety recall; ensures hazardous or dual-use prompts are blocked.|$100\%$ rejection rate on CBRN and hazardous queries.|
|**Progress & Latency**|Performance monitoring across parallel execution runs.|Task progression rates, worker fail-recovery times, and status update accuracy.|Zero deadlocks, automated recovery on worker crash, and updates every $\le 30$s.|
|**Final Output Quality**|Scoring final proposals on key criteria using a consensus of human and LLM-as-a-Judge evaluators.|Quality scores (1-to-5) across key dimensions (reasoning fidelity, alignment, mechanistic specificity, novelty, plausibility, decomposition).|Average score of $\ge 4.2 / 5.0$ on the Matter to Mechanism and BixBench datasets.|

## Automated Multi-Agent Synthesis and Bootstrapping Methodology

To minimize manual coordination and speed up the development of the co-scientist clone, the Project Director can deploy an automated, multi-agent bootstrapping pipeline. This pipeline automates the transition from raw documentation to technical specifications, code generation, and testing, requiring human intervention only at critical approval checkpoints.

```
┌────────────────────────────────────────────────────────────────────────┐
│                          SYNTHESIS WORKFLOW                            │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│                                          │
│     ├─ Literature Retrieval Agent crawls papers & documentation        │
│     └─ Output: High-Density Context Repository                         │
│                                                                        │
│                                            │
│     ├─ Planning Agent converts Context into Technical Specs            │
│     └─ Output: Markdown schemas, StateGraphs, and database tables      │
│                                                                        │
│                                  │
│     ├─ Coding Agent generates state machines and activities            │
│     ├─ Evaluator Agent runs testing suites & debugs failures           │
│     └─ Output: Production-ready codebase                               │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

The synthesis workflow is structured as a three-step pipeline:

- **Step 1: Automated Context Gathering:** The Literature Retrieval Agent crawls academic literature (such as Gottweis et al., 2025), developer guides for the Google Agent Development Kit, and orchestration documentation for Temporal and LangGraph. The output is compiled into a high-density Context Repository, containing code patterns, schemas, and API configurations.
    
- **Step 2: Technical Planning:** A specialized Planning Agent processes the Context Repository and generates detailed technical specifications. These specifications are written as structured Markdown files and include:
    
    - LangGraph StateGraph schemas, defining execution nodes, edges, conditional transitions, and State configurations.
        
    - Temporal Workflow definitions, specifying activity execution models, retry policies, heartbeats, and Continue-As-New configurations.
        
    - SQL database schemas for the ADK-style session persistence layer, including tables for state histories, user inputs, and intermediate artifacts.
        
    - OpenAPI definitions for backend API gateways, long-running job queues, and UI control panels.
        
- **Step 3: Code Generation and Testing:** Coding Agents convert the technical specifications into executable code blocks.
    
    - Coding workers build the state persistence layers, Elo tournament brackets, and front-end interface panels.
        
    - Once compiled, an Evaluator Agent runs automated testing suites, checks code execution success rates, and executes Playwright-based checks to verify interactive UI behaviors.
        
    - If an error is detected, the evaluator passes the traceback back to the coding worker for debugging, iterating until the codebase achieves a $100\%$ compilation and test pass rate.
        

This automated bootstrapping methodology enables the Project Director to manage the development of the co-scientist clone with minimal manual oversight. By delegating context gathering, planning, and code implementation to specialized agent teams, the system can be built, verified, and deployed to exact design and safety specifications.
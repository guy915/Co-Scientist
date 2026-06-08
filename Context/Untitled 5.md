# Technical Analysis and Implementation Blueprint for a 1:1 Google DeepMind AI Co-Scientist Clone

The landscape of automated scientific discovery has advanced beyond isolated retrieval systems toward integrated, multi-agent frameworks capable of executing non-linear research loops. Rather than acting as a simple text summarizer, a high-fidelity clone of Google DeepMind's AI Co-Scientist must function as a multi-agent hypothesis generation and experiment simulation system. This report provides a detailed evaluation of open-source projects that can serve as a foundation for building this clone, analyzes their core subsystems, and outlines a comprehensive technical architecture to orchestrate their integration.

## Target System Architecture and Multi-Agent Workflow

The primary objective of the target platform is to replicate Google's Hypothesis Generation workflow. This workflow is structured as a continuous loop: **research goal → goal refinement → literature/data grounding → hypothesis generation → critique/reflection → ranking/tournament → hypothesis evolution → final research proposal**.

The user experience is designed as an interactive, interview-style scoping process. A supervisor agent leads this conversation to refine the initial query, establish domain boundaries, and generate formal run specifications. The user can select either a Standard or Advanced run configuration. Standard runs execute localized, resource-constrained loops, while Advanced runs trigger deeper, long-running agent cycles that leverage distributed job queues and parallel execution threads.

To match the operational fidelity of the original system, the backend must support several decoupled yet highly integrated modules. The multi-agent coordinator acts as the primary runtime engine, managing agent state transitions and executing parallel execution paths. This coordinator communicates directly with a scientific retrieval layer to gather literature context, which is then parsed, embedded, and stored in a vector database.

A centralized hypothesis store acts as a state ledger, tracking every generated hypothesis, its mutation lineage, and its active Elo rating. Pairwise evaluation debates are managed by a specialized tournament engine, which scores hypotheses based on literature grounding and validity. Once the tournament stabilizes, a report generator compiles the top-rated hypotheses into a publication-ready research proposal, containing structured inline citations and a compiled bibliography.

To ensure safe operation, the entire execution pipeline is wrapped in a secure safety layer that runs all LLM-generated code in isolated sandbox environments.

The matrix of core agents required to run this workflow includes:

- **Supervisor Agent**: Acting as an adaptive, freeform planner, this agent decomposes the refined research goal into executable steps, coordinates parallel task execution, and manages state transitions across the agent coalition.
    
- **Intake/Interview Agent**: Manages the conversational scoping phase, asking targeted questions to clarify the user's research goal and outputting structured run specifications.
    
- **Literature Retrieval Agent**: Interfaces with scientific databases to execute targeted semantic queries, retrieving full-text PDFs and metadata.
    
- **Generation Agent**: Consumes the refined research goal and grounded literature contexts to propose distinct, actionable, and testable hypotheses.
    
- **Proximity/Clustering Agent**: Generates embedding vectors for all hypotheses and runs spatial clustering algorithms to evaluate conceptual distance, preventing redundant exploration.
    
- **Reflection Agent**: Serves as an automated peer reviewer, critically evaluating each hypothesis against scientific criteria like novelty, feasibility, and experimental testability.
    
- **Ranking Agent**: Aggregates peer review feedback and scores to generate a global, sorted list of the hypothesis pool.
    
- **Tournament Agent**: Conducts pairwise debates between hypotheses, using an LLM to judge matchups and updating ratings dynamically.
    
- **Evolution Agent**: Performs crossover and mutation operations on top-rated hypotheses, refining their details while maintaining structural diversity.
    
- **Meta-Review Agent**: Synthesizes the debate history and peer-review matrices to identify systemic issues, optimizing the next iteration of the loop.
    
- **Citation Verification Agent**: Validates inline citations against retrieved metadata, performing retraction checks to ensure all references are accurate.
    
- **Safety Agent**: Scans generated validation scripts for dangerous library imports, file system access, or unauthorized network calls before execution.
    
- **Report Synthesis Agent**: Compiles the finalized hypotheses, evaluation data, and bibliography into a formatted PDF or Markdown document.
    

## Comprehensive Evaluation of Core Open-Source Candidates

Rather than building this system from scratch, the development team can construct a high-fidelity clone by utilizing existing open-source frameworks. The table below compares the leading repositories that can serve as either the primary codebase or a source of specialized modules.

|**Project & Repository**|**Open-Source License**|**Maintainability & Code Quality**|**Architecture & Agent Design**|**Retrieval & Scientific Grounding**|**Critique & Tournament Mechanics**|**UI Readiness & Extensibility**|**Actionable Integration Plan**|
|---|---|---|---|---|---|---|---|
|**Jataware open-coscientist**|Source-Available (Custom LICENSE)|High quality; uses LangGraph, LiteLLM, and standardized schemas.|Stateful LangGraph workflow managing 8-10 specialized agents.|Model Context Protocol (MCP) integration with PubMed reference server.|Adaptive evaluation (batch vs. parallel); runs an Elo-based pairwise tournament.|Excellent frontend integration via React/TypeScript `open-coscientist-viewer`.|**Fork Primary**: Establish as the core orchestration backbone and UI frame.|
|**LLNL open-ai-co-scientist**|MIT License|High quality; flat sequential Python structure, highly readable.|Sequential execution loop managing 6 distinct agents.|Direct API integration with arXiv search tools.|Iterative generation and evaluation using an Elo K-factor ranking loop.|Moderate; built on Gradio with advanced settings and cost-control systems.|**Mine**: Extract agent prompt templates, Elo calculations, and Gradio code.|
|**Sakana AI Scientist v2**|Apache License 2.0|High quality; specialized for execution-heavy ML environments.|Progressive Best-First Tree Search (BFTS) via AIDE and PyTorch.|Direct integration with Semantic Scholar for automated novelty checking.|Code-level evaluation and debugging; runs automated peer reviews.|Low; writes files to disk, generating an HTML tree visualization.|**Mine**: Port the Best-First Tree Search and Docker sandboxing components.|
|**FutureHouse Robin**|Apache License 2.0|High quality; tailored for biological assay design pipelines.|Sequential pipeline integrated with the proprietary Edison platform.|Uses PaperQA2 for high-accuracy scientific literature RAG.|Ranks assay choices, generating structured comparison CSVs.|Low; executed via Jupyter Notebooks or raw Python files.|**Mine**: Integrate its high-accuracy PaperQA2 RAG pipeline.|
|**OpenScientist (K-Dense)**|CC-BY 4.0|High quality; leverages Claude Code and KSDS state logic.|Iterative autonomous loop managing specialized Agent Skills.|Deep grounding across PubMed and 78+ public scientific databases.|Verifies hypothesis validity using sandboxed execution results.|Low; operates as a CLI tool or ide plugin.|**Mine**: Extract its database API connectors and Agent Skills templates.|
|**aimclub CoScientist**|MIT License|High quality; built on Google ADK and FEDOT.MAS framework.|Hierarchical orchestration with sequential tool execution agents.|Hybrid RAG-based MCP tool discovery and Marker PDF parsing.|Validates hypotheses using computational pipeline generation.|Low; executed programmatically via custom Python entries.|**Mine**: Integrate its Marker PDF parsing and molecular utility scripts.|
|**The-Swarm-Corporation AI-CoScientist**|MIT License|Low to Moderate; minimal wrapper utilizing the Swarms library.|Linear agent sequence (Generation -> Reflection -> Ranking).|Basic web search API calls.|Pairwise Elo ranking with basic text mutators.|None; CLI script execution only.|**Inspect**: Use purely as a basic guide for minimal agent design.|
|**mims-harvard AutoScientists**|Source-Available|High quality; decentralized multi-agent coordination.|Self-organizing subagent teams using ClawInstitute server logs.|Shared local workspaces and group message-board updates.|Cooperative critique phase before program compilation.|None; CLI execution with output directories.|**Reject**: Its decentralized peer-to-peer approach is not suitable for a central UI.|

## Detailed Evaluation of Foundational Candidates

### Jataware open-coscientist and open-coscientist-viewer

The Jataware codebase stands out as the most architecturally complete implementation of Google's AI Co-Scientist workflow. Built on top of LangGraph and LiteLLM, the framework manages state transitions across 8 to 10 specialized agents. This graph-based architecture allows for non-linear execution, enabling the system to run comparative batch evaluations or trigger parallel peer-review loops depending on the size of the hypothesis pool.

The repository uses standardized YAML schemas for domain configuration, making it easy to adapt the system from biomedicine to other scientific fields without modifying the core codebase. Its companion web application, `open-coscientist-viewer`, is written in React and TypeScript. This interface connects directly to the LangGraph backend, providing real-time tracking of the hypothesis generation, ranking, tournament matchups, and evolution stages.

However, because Jataware focuses primarily on qualitative hypothesis evolution and literature-aware deduction, it does not include a native sandbox environment to execute and validate code-based experiments.

### LLNL open-ai-co-scientist

Developed by Lawrence Livermore National Laboratory, this project provides a clean, sequential implementation of the hypothesis evolution cycle. Rather than using a complex graph manager, it coordinates its agents (Generation, Reflection, Ranking, Evolution, Proximity, and Meta-Review) using flat, synchronous Python loops. The project integrates with OpenRouter, enabling developers to easily toggle between different LLMs.

Grounding is handled by a lightweight tool that queries the arXiv API to display relevant papers and metadata directly in the UI. It also features a cost-control utility that automatically restricts the model catalog to budget-friendly models (e.g., Gemini Flash or Claude Haiku) when deployed in production environments like Hugging Face Spaces.

While highly maintainable and excellent for rapid prototyping, its rigid, sequential design lacks the non-linear flexibility required for an advanced enterprise platform.

### Sakana AI Scientist v2

Sakana AI Scientist v2 is built specifically for execution-heavy computational workflows. Moving away from rigid, human-authored templates, the system runs a progressive Best-First Tree Search (BFTS) to explore, code, execute, and refine machine learning experiments. Guided by an experiment manager agent, the pipeline runs parallel exploration threads, automatically generating validation scripts, running training jobs, and analyzing performance. If a script crashes, the system triggers a debugging loop, attempting to fix and re-run the code up to a configured depth before pruning the search branch.

To evaluate novelty, the ideation phase integrates directly with the Semantic Scholar API. After completing its experiments, the system writes a complete LaTeX paper and generates a visualization of the search path (`unified_tree_viz.html`).

The primary challenge of this repository is security; because it runs LLM-generated code, it requires a secure, sandboxed container runtime. Additionally, it is designed for code-based optimization tasks, lacking the collaborative debate loops and user scoping workflows of the Google Co-Scientist system.

### FutureHouse Robin and PaperQA2

The FutureHouse Robin platform is designed to automate biological discovery, specifically focusing on generating experimental assays and identifying therapeutic candidates for custom target diseases. Under the hood, Robin orchestrates its workflows using the Edison API, utilizing specialized cloud agents like Crow (web search), Falcon/Literature (grounding), and Finch (data analysis). If raw experimental data is provided, the Finch agent analyzes the dataset, writing its consensus findings to a CSV file to guide the therapeutic generation loop.

Robin's primary strength lies in its deep integration with PaperQA2, a state-of-the-art framework for scientific retrieval-augmented generation. PaperQA2 delivers highly accurate grounded responses with verified inline citations, performing Crossref metadata lookups, retraction tracking, and Semantic Scholar semantic parsing.

However, Robin is tightly coupled with the proprietary Edison platform, which requires a paid API key and credit system. It also lacks an interactive web-based UI, relying instead on programmatic Python executions and local Jupyter notebooks.

### OpenScientist and K-Dense Agent Skills

OpenScientist is an open-source autonomous discovery platform developed to run clinical and biomedical investigations. Orchestrated via Claude Code and running inside a secure Docker container, the platform guides an agentic controller to execute iterative discovery loops. Each iteration searches PubMed, parses papers, writes Python validation scripts, and compiles findings into a Knowledge-State Data Structure (KSDS) to guide subsequent turns.

Its capabilities are driven by the K-Dense "Agent Skills" library, which provides over 140 pre-validated scientific and database connectors. These skills grant the agent direct, optimized access to 78+ public databases (including PubChem, ChEMBL, UniProt, and ClinicalTrials.gov) alongside computational biology packages like RDKit.

While OpenScientist provides exceptional domain grounding and data-handling features, it is designed primarily as an interactive CLI tool and Claude Code plugin. It does not feature a stateful multi-agent tournament or a web-based monitoring dashboard.

## Core Agent Coalition and Collaborative Topologies

To construct a high-fidelity clone of the Google Co-Scientist, the system's agents must coordinate through a stateful, hierarchical topology managed by LangGraph. This approach is superior to linear execution models because it allows the supervisor agent to act as a dynamic orchestrator. Rather than moving through a rigid sequence of steps, the supervisor monitors the central state graph and dynamically routes tasks to specialized agents in parallel, adapting the execution flow as new data is gathered.

The workflow begins with the scoping phase. The Intake Agent engages the user in an interactive dialogue, translating ambiguous requests into detailed run specifications. Once these parameters are set, the Supervisor schedules parallel retrieval tasks, directing the Literature Agent to gather relevant papers and databases. This grounding data is then routed to the Generation Agent, which is configured to output distinct, actionable hypotheses.

```
                     ┌──────────────────────────┐
                     │    User Web Interface    │
                     └────────────┬─────────────┘
                                  │ (REST / WebSockets)
                                  ▼
                     ┌──────────────────────────┐
                     │   Supervisor Agent       │
                     │   (LangGraph Orchestrator)│
                     └────────────┬─────────────┘
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│  Intake Agent     │   │ Literature Agent  │   │ Generation Agent  │
│  - User Scoping   │   │ - PaperQA2 RAG    │   │ - Hypothesis Seed │
└───────────────────┘   └───────────────────┘   └───────────────────┘
          │                       │                       │
          ▼                       ▼                       ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ Proximity Agent   │   │ Reflection Agent  │   │ Tournament Agent  │
│ - Clustering      │   │ - Peer Review     │   │ - Elo Matchups    │
└───────────────────┘   └───────────────────┘   └───────────────────┘
          │                       │                       │
          ▼                       ▼                       ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ Evolution Agent   │   │ Meta-Review Agent │   │ Synthesis Agent   │
│ - Recombination   │   │ - Run Critique    │   │ - PDF/TeX Report  │
└───────────────────┘   └───────────────────┘   └───────────────────┘
```

To maintain conceptual diversity and prevent the system from getting stuck in a single line of thinking, the Proximity Agent clusters the generated hypotheses using spatial embedding models, identifying and pruning redundant ideas.

The unique hypotheses are then passed to the Reflection Agent, which acts as a virtual peer reviewer. It scores each idea across six standardized criteria: scientific soundness, novelty, feasibility, testability, potential impact, and ethical safety.

The Tournament Agent then consumes these evaluation scores, orchestrating pairwise debates to rank the hypotheses using an Elo rating system. The top-ranked candidates are then sent to the Evolution Agent, which refines and combines them to produce higher-quality iterations.

Finally, the Meta-Review Agent synthesizes the entire cycle's debate logs, and the Synthesis Agent compiles the top hypotheses and bibliography into a formatted PDF or Markdown research proposal.

## Rigorous Verification, Grounding, and Citation Mechanics

A primary critique of LLM-based research tools is their tendency to hallucinate scientific claims. To combat this, the clone's grounding layer integrates **PaperQA2** as its primary retrieval-augmented generation engine, routing queries through its specialized parsing and citation-checking pipelines.

```
┌────────────────────────────────────────────────────────┐
│               PaperQA2 Retrieval Pipeline              │
└───────────────────────────┬────────────────────────────┘
                            │ (Query Formulation)
                            ▼
┌────────────────────────────────────────────────────────┐
│                 Full-Text PDF Search                   │
│   - Metadata Resolution (Crossref / Semantic Scholar)  │
│   - Automated Retraction Verification Check            │
└───────────────────────────┬────────────────────────────┘
                            │ (Raw PDF Documents)
                            ▼
┌────────────────────────────────────────────────────────┐
│           RCS (Contextual Summarization)               │
│   - Dynamic Chunk-Level Scoring & Relevance Evaluation │
│   - LLM-Based Re-ranking of Scored Summaries           │
└───────────────────────────┬────────────────────────────┘
                            │ (Re-ranked Evidence Context)
                            ▼
┌────────────────────────────────────────────────────────┐
│               Grounded Answer Generation               │
│   - In-Text Structured Citation Mapping [C*]           │
│   - Automated BibTeX Bibliography Compilation          │
└────────────────────────────────────────────────────────┘
```

The grounding process begins when the Literature Agent formulates targeted search terms and queries external APIs to fetch candidate papers. Once these documents are downloaded, PaperQA2 extracts their metadata, cross-referencing Crossref and Semantic Scholar to verify citation counts and check for retractions. The documents are then chunked and indexed into a local full-text search directory, typically stored in a persistent cache folder like `~/.pqa/`.

To extract relevant information, the platform executes PaperQA2's **RCS (Retrieval, Contextual Summarization, and re-Scoring)** algorithm. The system embeds the query and retrieves the top document chunks. An LLM then reviews these chunks to generate scored summaries, evaluating their relevance directly in the context of the user's research question. Finally, the system runs an LLM-based re-ranking step to select the highest-scoring summaries, filtering out noisy or irrelevant text.

These filtered summaries are then injected into Jataware's LangGraph prompt templates, allowing the Generation and Reflection agents to work with highly relevant context. To maintain scholarly transparency, all generated claims are appended with structured inline citations using the `[C*]` format (e.g., `[C1]`, `[C2]`), which map directly to a compiled bibliography. The system can also leverage K-Dense's `claude-scientific-writer` plugin, which automates BibTeX generation and formats citations to match target journal guidelines.

For structured domain queries, the system can bypass unstructured text searches by querying **BioMCP**. Operating as a background HTTP server via `biomcp serve-http --port 8080`, BioMCP provides a unified command grammar that allows agents to query clinical and genomic databases directly. This structured query language enables agents to quickly search, pivot, and enrich biological data without manual API integration:

```
# Unified Command Grammar Examples for BioMCP Search and Pivot Verbs
biomcp search all --gene BRAF --disease melanoma 
biomcp get variant "BRAF V600E" clinvar population [27]
biomcp enrich "BRAF, TP53, KRAS" 
biomcp get pathway hsa05200 genes [27]
```

## Tournament Engineering and Pairwise Elo Mechanics

A defining feature of the AI Co-Scientist is the "tournament of ideas," which uses pairwise LLM debates to evaluate and prioritize hypotheses. Building on Jataware's LangGraph framework, the platform implements an adaptive evaluation strategy. For small pools of five or fewer hypotheses, the system runs comparative batch evaluations, prompting a single LLM to rank the entire set simultaneously.

For larger pools, the system switches to parallelized pairwise matches, running head-to-head debates where the Tournament Agent prompts an LLM to act as an impartial judge, selecting a winner based on scientific soundness and novelty.

The system tracks these matchups and updates ratings using the standard Elo rating system. Given two hypotheses, $H_A$ and $H_B$, with current ratings $R_A$ and $R_B$, the expected probability of victory for each hypothesis is calculated as:

$$E_A = \frac{1}{1 + 10^{(R_B - R_A)/400}}$$

$$E_B = \frac{1}{1 + 10^{(R_A - R_B)/400}}$$

Once the debate concludes and the LLM judge selects a winner, the system records the actual score, setting $S_A = 1$ if $H_A$ wins, and $S_A = 0$ if it loses. The ratings are then updated using the formula:

$$R'_{A} = R_A + K(S_A - E_A)$$

$$R'_{B} = R_B + K((1 - S_A) - E_B)$$

The sensitivity of these rating updates is controlled by the K-factor variable ($K$), which can be adjusted via the Gradio UI or the central `config.yaml` file to balance tournament stability and ranking sensitivity.

## Long-Running Job Queues and System Latency

Advanced runs of the Co-Scientist involve deep literature indexing, multi-agent debates, and sandboxed code execution, which can take hours or even days to complete. To prevent web timeouts and ensure reliable state recovery, the platform cannot run these tasks on the main thread. Instead, it decouples the execution layer using a distributed job queue system.

The queue architecture is modeled after `bio-mcp-queue`, leveraging a robust **Redis + Celery + MinIO** stack. Redis manages fast in-memory task routing and agent message brokering, Celery handles asynchronous worker execution across multiple machines, and MinIO acts as a local, S3-compatible object store to persist large datasets, parsed PDFs, and intermediate model weights.

```
                     ┌──────────────────────────┐
                     │    User Web Interface    │
                     └────────────┬─────────────┘
                                  │ (REST / WebSockets)
                                  ▼
                     ┌──────────────────────────┐
                     │    FastAPI Gateway       │
                     └────────────┬─────────────┘
                                  │ (Task Dispatch)
                                  ▼
                     ┌──────────────────────────┐
                     │    Redis Message Broker  │
                     └────────────┬─────────────┘
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│  Celery Worker A  │   │  Celery Worker B  │   │  Celery Worker C  │
│  - PaperQA2 RAG   │   │  - Elo Tournament │   │  - Docker Sandbox │
└─────────┬─────────┘   └─────────┬─────────┘   └─────────┬─────────┘
          │                       │                       │
          └───────────────────────┼───────────────────────┘
                                  ▼
                     ┌──────────────────────────┐
                     │   MinIO Object Store     │
                     │   (PDF / State Cache)    │
                     └──────────────────────────┘
```

When a user initiates an Advanced run, the FastAPI backend writes the initial parameters to the database, generates a unique run ID, and pushes the job to the Redis queue. Celery workers pick up the task, executing the LangGraph multi-agent loop asynchronously.

To keep the user informed during these long runs, the system streams progress updates, agent logs, and active tournament matchups in real time via WebSockets. The React frontend listens to these events, updating the monitoring dashboard dynamically without requiring manual page refreshes.

## Safety Posture and Sandboxed Code Execution

Executing LLM-generated code to simulate or validate experiments introduces significant security risks, including the execution of malicious packages or unauthorized system calls. To mitigate these hazards, the clone adopts the strict, sandboxed validation security posture used by Sakana v2 and OpenScientist.

The execution layer operates within isolated, ephemeral Docker containers. All code-execution agents are restricted to these sandboxes, which are configured with hardware resource limits (e.g., maximum memory, CPU cores, and execution timeouts) to prevent runaway processes.

The containers run on isolated networks, disabling internet access during the execution phase to prevent unauthorized data exfiltration. File system write permissions are limited to a single mounted workspace directory, preserving the clean state of the host system.

Additionally, before any script is executed, the Safety Agent parses the code's Abstract Syntax Tree (AST), checking for blacklisted libraries, dangerous built-in functions, or unauthorized system commands.

## Fidelity Evaluation and Scientific Benchmarking Standards

To ensure the clone's performance matches the scientific rigor of the original system, the platform integrates a standardized evaluation harness. This allows developers to benchmark the system's accuracy and validity against established scientific datasets:

- **LitQA v2**: Evaluates retrieval accuracy and hallucination rates. This dataset tests the system's ability to answer complex scientific questions using retrieved literature, penalizing incorrect claims and reward-grounded responses.
    
- **BixBench**: Benchmarks agent capabilities in computational biology. This suite measures the system's performance on bioinformatics tasks, evaluating its ability to correctly integrate sequence analysis tools and molecular docking packages.
    
- **LAB-Bench**: Evaluates core biological research skills. This benchmark tests the system's ability to handle diverse biological data types, extract findings, and formulate biologically sound hypotheses.
    
- **QBench**: Validates data tracking and laboratory information management integrations. This benchmark ensures the system can correctly parse and organize raw instrument files, formatting its outputs to match regulatory and compliance standards.
    

## Actionable Roadmap for Autonomous System Generation

To build this platform while minimizing manual implementation, the Project Director can deploy an autonomous multi-agent pipeline. By dividing the development process across three specialized agent layers, the system can automatically gather context, generate technical specifications, and write the core code.

```
┌────────────────────────────────────────────────────────┐
│               Autonomous Build Pipeline                │
└───────────────────────────┬────────────────────────────┘
                            │ (Director's Target Spec)
                            ▼
┌────────────────────────────────────────────────────────┐
│                 AI Research Agents                     │
│   - Clone open-coscientist, PaperQA2, and BioMCP       │
│   - Extract API schemas, DB queries, and AST logic     │
└───────────────────────────┬────────────────────────────┘
                            │ (Extracted Context Code)
                            ▼
┌────────────────────────────────────────────────────────┐
│                 AI Planning Agents                     │
│   - Draft API schemas & LangGraph state topologies     │
│   - Write Docker configs and Celery worker templates   │
└───────────────────────────┬────────────────────────────┘
                            │ (Detailed Specifications)
                            ▼
┌────────────────────────────────────────────────────────┐
│                  AI Coding Agents                      │
│   - Implement LangGraph state nodes & FastAPI routes   │
│   - Build React components and Docker sandboxes        │
└───────────────────────────┬────────────────────────────┘
                            │ (Automated Tests)
                            ▼
              
```

### Stage 1: Context Gathering (AI Research Agents)

The first step is to deploy a team of AI Research Agents to extract source code and configurations from the target open-source repositories:

1. Clone the core repositories, including `jataware/open-coscientist`, `Future-House/paper-qa`, `genomoncology/biomcp`, and `llnl/open-ai-co-scientist`.
    
2. Parse the python files to extract LangGraph state definitions, agent prompt templates, and database execution logic.
    
3. Analyze the BioMCP and K-Dense skill libraries to map database query APIs and tool execution grammars.
    
4. Save these extracted code blocks, prompt layouts, and API schemas into a centralized context directory to act as the primary knowledge base for the planning phase.
    

### Stage 2: Technical Specification (AI Planning Agents)

Next, AI Planning Agents process the gathered context to write detailed system specifications:

1. Design the database schemas for the centralized hypothesis store, tournament tracking, and run configurations.
    
2. Draft the API contracts for the FastAPI backend, detailing the REST endpoints and WebSocket stream schemas.
    
3. Define the LangGraph state topology, specifying the node transitions, conditional routing logic, and parallel execution paths.
    
4. Write the Docker and environment configurations, detailing the container structures, resource boundaries, and volume mounts for the isolated execution sandboxes.
    

### Stage 3: Implementation and Testing (AI Coding Agents)

Finally, AI Coding Agents consume the generated specifications to write the production code:

1. Implement the LangGraph multi-agent core, setting up state preservation, the supervisor orchestrator, and the specialized agent nodes.
    
2. Integrate PaperQA2 as a custom LangGraph tool, connecting its search, contextual summarization, and re-scoring pipelines.
    
3. Write the FastAPI server, setting up the background task dispatcher, Redis broker connection, and WebSocket progress streams.
    
4. Build the React and TypeScript frontend, mapping the visual components to the WebSocket events to render the scoping interview, live graph visualization, tournament arena, and proposal exporter.
    
5. Execute the evaluation tests, verifying the system's performance against LitQA v2, BixBench, and LAB-Bench to guarantee scientific rigor.
    

This multi-stage execution model minimizes manual coding while ensuring that every module is built on proven, pre-validated open-source foundations. By orchestrating these components into a unified, graph-based architecture, the resulting system delivers a high-fidelity, secure, and fully open-source clone of Google DeepMind's AI Co-Scientist.
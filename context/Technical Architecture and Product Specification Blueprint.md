# Technical Architecture and Product Specification Blueprint for an AI Co-Scientist Clone

The acceleration of modern scientific research requires a shift from passive, informational search tools to proactive, structured-reasoning systems. Google DeepMind’s Co-Scientist serves as the benchmark for this paradigm, coordinating specialized, Gemini-powered agents to generate, debate, rank, and evolve complex scientific hypotheses grounded directly in the academic literature. Building a high-fidelity, production-ready clone of this system necessitates a meticulous integration of an asynchronous multi-agent orchestration layer, an immutable evidence-gated control plane, and an interface that mirrors Google’s Material 3 Expressive design patterns. This specification outlines the architecture, visual tokens, compliance guardrails, and evaluation criteria required to build and validate this scientific workbench.

## Multi-Agent System Architecture and Orchestration Control Plane

To achieve the cognitive capacity demonstrated by Google DeepMind's original implementation, the clone must utilize a non-linear, multi-agent architecture. Rather than relying on standard sequential prompt-chaining, the execution is managed by a Supervisor Agent acting as an adaptive planner. This supervisor breaks high-level, open-ended scientific research goals down into parallelizable sub-tasks, dynamically allocating computing resources based on the evolving state of the research loop.

The architectural backbone relies on a persistent context memory store and a repository-backed control plane to handle long-horizon reasoning tasks. Process coordination is maintained via an asynchronous task execution framework. By modeling agent interactions as concurrent processes, the system scales its test-time compute budget, allowing deeper simulations, extended peer-review iterations, and exhaustive pairwise debate tournaments.

|**Agent Role**|**Operational Domain & Objective**|**Primary LLM Backing**|**Input Variables & Context Channels**|**Target Output Artifacts**|
|---|---|---|---|---|
|**Supervisor**|Adaptive planning, dynamic task decomposition, and queue scheduling.|Gemini 1.5/3.5 Pro|High-level research goals, previous run histories, blocked flags.|Dynamic task schedules, Enju dependency graphs.|
|**Intake/Interview**|Contextual elicitation and scoping of user constraints.|Gemini 1.5/3.5 Flash|User text inputs, preference parameters, field limitations.|Structured JSON scoping configurations.|
|**Literature Retrieval**|Targeted semantic query generation and external search.|Gemini 1.5/3.5 Flash|Scoping configurations, search histories, verified keywords.|Filtered academic paper lists, raw metadata objects.|
|**Generation**|Broad hypothese formulation, assumption mapping, and claim drafting.|Gemini 1.5/3.5 Pro|Retrieved scholarly texts, context memory payloads.|Grounded scientific proposals, mapped mechanism lists.|
|**Reflection**|Adversarial review, verification of sub-assumptions, and constraint checking.|Gemini 1.5/3.5 Pro|Mapped mechanism lists, empirical data, safety rules.|peer-review critique reports, invalidation traces.|
|**Proximity/Clustering**|Vector embedding generation, semantic similarity mapping, and clustering.|Text-Embedding-004|Generated hypotheses texts, coordinate dimensional boundaries.|Proximity graph maps, similarity matrices.|
|**Ranking**|Pairwise debate simulation, scoring evaluation, and comparative ranking.|Gemini 1.5/3.5 Flash|Paired hypotheses text, critiques, supporting evidence.|Win/loss transcripts, updated Elo score vectors.|
|**Evolution**|Hybridization, concept mutation, and iterative refinement.|Gemini 1.5/3.5 Pro|High-scoring hypotheses, peer-review critiques, mutation seed data.|Mutated hybrid hypotheses, refined proposal variants.|
|**Meta-Review**|Cross-round compilation, conflict resolution, and roadmap synthesis.|Gemini 1.5/3.5 Pro|Complete tournament history, debate logs, evaluation metrics.|Unified synthesis plans, system configuration updates.|
|**Citation Verification**|Parsing verification, DOI cross-referencing, and attribution audits.|Gemini 1.5/3.5 Flash|Grounded proposals, internal citation ledger records.|Verification manifests, unresolved source alerts.|
|**Safety**|Dual-agent compliance monitoring, CBRN filtering, and hazard checks.|Gemini 1.5/3.5 Pro|Execution commands, generated hypotheses, chemical/biological databases.|Security classification verdicts, prompt blocks.|
|**Report Synthesis**|Multi-format compilation, visual structuring, and draft output.|Gemini 1.5/3.5 Pro|Finalized proposals, verification manifests, structured data files.|Production-ready research manuscripts, export files.|

The orchestration system coordinates these agents asynchronously using a localized task queue engine, tracking state transitions via a directed acyclic graph. When a user presents a research goal, the Supervisor delegates the initial interview step to the Intake Agent. Once scoped, the Literature Retrieval and Generation Agents operate in parallel to construct a diversified set of foundational hypotheses.

The Proximity Agent processes these candidate ideas, grouping them by conceptual similarity on a coordinate map to ensure the exploration space remains balanced and non-redundant. The tournament loop then executes iteratively, allowing the system to scale its computational effort during the execution run.

## Scientific Ingestion, Grounding, and Retrieval Infrastructure

A primary risk of generative architectures in scientific domains is the occurrence of logical hallucinations and unsupported claims. To address this challenge, the system deploys a scientific retrieval layer that acts as the source of truth for the generation loop. This layer functions by programmatically converting agent queries into target API integrations across major biological, chemical, and literature databases.

```
                +----------------------------------------+
                |         Agent Query Generation         |
                +-------------------+--------------------+
                                    |
                                    v
                +-------------------+--------------------+
                |       Scientific Retrieval Layer       |
                +----+--------------+--------------+-----+
                     |              |              |
        +------------+              |              +------------+
        |                           |                           |
        v                           v                           v
+-------+-------+           +-------+-------+           +-------+-------+
|  PubMed API   |           |  ChEMBL API   |           |  UniProt API  |
|  (Literature) |           |  (Chemicals)  |           |  (Genomics)   |
+-------+-------+           +-------+-------+           +-------+-------+
        |                           |                           |
        +------------+              |              +------------+
                     |              |              |
                     v              v              v
                +----+--------------+--------------+-----+
                |       Grounding & Verification Layer   |
                +-------------------+--------------------+
                                    |
                                    v
                +-------------------+--------------------+
                |    Admitted Claim / Verifiable Citation|
                +----------------------------------------+
```

The system uses three primary integration pipelines:

1. **Literature Synthesizer**: Interrogates PubMed and PubMed Central via Entrez utilities, retrieving abstracts and full-text articles.
    
2. **Chemical Structure Mapper**: Interfaces with PubChem and ChEMBL RESTful services, resolving IUPAC names, SMILES strings, and active assays.
    
3. **Genomic Target Resolver**: Queries UniProt and the AlphaFold Database, linking targeted proteins to known sequence metrics.
    

Once structured data is fetched, the Literature Insights engine—inspired by the grounding mechanics of NotebookLM—processes the documents. Rather than executing simple vector searches on raw chunks, this engine builds queryable tables that map extracted metrics directly to source evidence. When the Generation Agent drafts a hypothesis, the Citation Verification Agent acts as an auditor. It cross-references every claims assertion against the internal document repository, validating that the biological mechanisms, drug properties, or molecular target interactions correspond to verified text.

If a claim lacks direct support in the evidence base, it is flagged as unverified and blocked from entry into the proposal synthesis phase. This strict verification process provides absolute traceability, allowing researchers to click any generated claim and instantly view the exact highlighted excerpt in the source material.

## The Evolutionary Tournament Engine and Elo Mechanics

The mechanism for optimizing and selecting high-potential scientific theories in the clone is the evolutionary tournament engine. Hypotheses that pass the initial screening of the Reflection Agent are submitted to a competitive bracket. Here, the Ranking Agent pairs competing proposals and simulates structured debates, acting as an automated evaluator of scientific viability.

```
                     +---------------------------+
                     |    Initial Hypotheses     |
                     +-------------+-------------+
                                   |
                                   v
                     +---------------------------+
                     |   Reflection Screening    |
                     +-------------+-------------+
                                   |
                                   v
                     +---------------------------+
                     |      Proximity Graph      |
                     |       Clustering          |
                     +-------------+-------------+
                                   |
                                   v
                    +--------------+--------------+
                    |                             |
                    v                             v
           +--------+--------+           +--------+--------+
           |  Hypothesis A   |           |  Hypothesis B   |
           +--------+--------+           +--------+--------+
                    |                             |
                    +--------------+--------------+
                                   |
                                   v
                     +-------------+-------------+
                     |   Pairwise Simulated      |
                     |         Debate            |
                     +-------------+-------------+
                                   |
                                   v
                     +-------------+-------------+
                     |   Elo Rating Calculation  |
                     +-------------+-------------+
                                   |
                     +-------------+-------------+
                     |       Evolutionary        |
                     |      Refinement Loop      |
                     +---------------------------+
```

During a simulated debate, the Ranking Agent spawns parallel execution threads. One thread acts as the advocate for Hypothesis $A$, highlighting its biological plausibility, feasibility, and therapeutic impact while critiquing the logical gaps in Hypothesis $B$. The opposing thread defends Hypothesis $B$ while interrogating $A$. A separate evaluator thread analyzes the debate transcript against the evidence base and determines a win, loss, or draw.

To track the relative quality of ideas over hundreds of matches, the system implements an Elo rating formulation. Let $R_A$ and $R_B$ represent the current Elo ratings of Hypothesis $A$ and Hypothesis $B$. The expected probability $E_A$ of Hypothesis $A$ winning is defined mathematically as:

$$E_A = \frac{1}{1 + 10^{(R_B - R_A)/400}}$$

Once the debate round concludes and a score outcome $S_A \in \{1, 0.5, 0\}$ is assigned, the ratings are adjusted dynamically:

$$R'_A = R_A + K(S_A - E_A)$$

$$R'_B = R_B + K(S_B - E_B)$$

Where $K$ acts as the rating volatility constant, configured at $K = 32$. Top-performing hypotheses with high Elo scores are prioritized for evolutionary mutation. The Evolution Agent refines these concepts by combining complementary mechanisms or introducing mutation parameters, such as swapping delivery vectors or adjusting target groups. Evolved variations are then re-injected into the tournament, scaling the test-time compute to improve hypothesis quality over time.

The system supports two distinct execution profiles tailored to different research needs, outlined in the table below:

|**Feature Dimension**|**Standard Run Profile**|**Advanced Run Profile**|
|---|---|---|
|**Target Operational Objective**|Rapid, low-latency conceptual screening and proof-of-concept testing.|Exhaustive, high-fidelity discovery, validation, and proposal generation.|
|**Token Budget (per run)**|$\le$ 50,000,000 tokens.|$\le$ 1,000,000,000 tokens (utilizing 1M+ context windows).|
|**Search Depth**|Focused web search and targeted PubMed abstracts.|Deep database crawls, full-text PMC articles, and patents.|
|**Debate Matches**|10 to 50 matchups, single-round brackets.|200 to 1,000 matchups, multi-epoch tournament brackets.|
|**Average Latency**|5 to 15 minutes.|2 to 24 hours (long-running background jobs).|
|**Refinement Cycles**|1 to 2 evolutionary epochs.|5 to 10 evolutionary epochs.|
|**Verification Level**|Abstract-level citation checking.|Full result-to-claim mapping with adversarial audits.|
|**Output Formats**|High-level summaries, basic ranked tables.|Formatted research proposals, schema configurations, code lineages.|

## Visual Design and Material 3 Expressive System Integration

To ensure the application visually and interactionally feels like a first-party Google product, the frontend layout must adhere to Google's official Material Design 3 (M3) Expressive guidelines. The layout utilizes soft curves, structured surfaces, dynamic color roles, and organic motion schemes to build a collaborative workspace.

```
+-----------------------------------------------------------------------------------------+
| [G] Hypothesis Workbench                (User)  |
+-----------------------------------------------------------------------------------------+
| (N) |                                                                                   |
|     |  LEFT SCOPING PANEL (Input / Control)     RIGHT CANVAS AREA (Interactive Display) |
| (A) |  +-------------------------------------+  +------------------------------------+  |
|     |  | Setup Scoping Configuration         |  |       |  |
| (V) |  |   Target: FLT3 Receptor             |  |                                    |  |
|     |  |   Mode:   Advanced Run Profile      |  |        (H3) ──────► (H1)       |  |
| (R) |  |                                     |  |         │                 ▲        |  |
|     |  | Running Execution Steps             |  |         ▼                 │        |  |
| (A) |  |   Simulating Debates...  |  |       (H5) ◄──────► (H9)       |  |
|     |  |   [P-01] Citation Parsing OK        |  |                                    |  |
| (I) |  |                                     |  |------------------------------------|  |
|     |  | Scientific References (Grounding)   |  | [Consolidated Proposal Narrative]  |  |
| (L) |  |    PMID_34211 -> Target-X   |  |   The FLT3 synergistic cascade...  |  |
|     |  |    PMID_19283 -> Pathway-Y  |  |   Clickable Citations: , |  |
+-----+--+-------------------------------------+--+------------------------------------+  |
| Input: |
+-----------------------------------------------------------------------------------------+
```

### Visual Layout Conventions

The workbench interface uses a side-by-side split layout to establish clear hierarchy. The Left Panel handles setup, controls, and active system logs, while the Right Canvas Area dynamically displays execution steps, including the tournament bracket, proximity graphs, and the final generated proposal.

This layout mirrors the Gemini Canvas workspace paradigm, where prompting and editing happen on the left, and interactive, live-coded artifacts render on the right.

### Typography Stack Selection

To respect licensing restrictions, Google Sans and Product Sans must not be packaged or redistributed with this codebase. Developers must utilize open-source typefaces that match the geometric structure of Google's custom branding.

CSS

```
/* Custom Typography System */
:root {
  --font-family-header: 'Spline Sans', ui-sans-serif, system-ui, sans-serif; /* High-density headers [35] */
  --font-family-body: 'DM Sans', ui-sans-serif, system-ui, sans-serif;        /* Broad geometric body copy [36] */
  --font-family-mono: 'JetBrains Mono', ui-monospace, monospace;             /* Structured data and log output [35] */
}

.ui-title-large {
  font-family: var(--font-family-header);
  font-weight: 500;
  font-size: 1.75rem;
  line-height: 2.25rem;
  letter-spacing: -0.01em;
}

.ui-body-medium {
  font-family: var(--font-family-body);
  font-weight: 400;
  font-size: 0.875rem;
  line-height: 1.25rem;
}

.ui-log-stream {
  font-family: var(--font-family-mono);
  font-size: 0.75rem;
  line-height: 1.125rem;
}
```

### Color and Spacing Design Tokens

The color palette utilizes Material 3 tonal values to distinguish semantic interface roles. Every background-text pairing must algorithmically conform to WCAG AA contrast ratios, validating accessibility as a first-class citizen.

CSS

```
@theme {
  /* Semantic M3 Color Tones */
  --color-primary: #0b57d0;               /* Active interaction triggers, prominent buttons */
  --color-on-primary: #ffffff;            /* High-contrast text on primary elements */
  --color-primary-container: #d3e3fd;     /* Selected states, highlighted tabs */
  --color-on-primary-container: #041e49;  /* Deep text on primary containers */
  
  --color-secondary: #00639b;             /* Filters, minor buttons, auxiliary badges */
  --color-on-secondary: #ffffff;          /* Text on secondary elements */
  --color-secondary-container: #c2e7ff;   /* Secondary container grouping surfaces */
  --color-on-secondary-container: #001d35; /* Text inside secondary container panels */
  
  --color-tertiary: #b8422e;              /* Safety alerts, tournament debate highlights */
  --color-on-tertiary: #ffffff;           /* Text on tertiary elements */
  --color-tertiary-container: #ffdad5;    /* High-priority warning banners */
  --color-on-tertiary-container: #410002; /* Text inside warning panels */

  --color-surface: #f8f9fa;               /* Canvas backdrops, side panels */
  --color-surface-container: #ffffff;     /* Base cards, work surfaces, main windows */
  --color-on-surface: #1f1f1f;            /* Primary narrative text color */
  --color-on-surface-variant: #444746;    /* Secondary metadata, supporting logs, labels */
  --color-outline: #747775;               /* Panel dividers, container borders */

  /* M3 Rounding Scale */
  --radius-xs: 4px;
  --radius-sm: 8px;                       /* Small input containers, checkbox forms */
  --radius-md: 12px;                      /* Action buttons, minor UI cards */
  --radius-lg: 16px;                      /* Primary canvas panels, file upload cards */
  --radius-xl: 24px;                      /* Dialog surfaces, popup action windows */
  --radius-full: 9999px;                  /* Selection pills, category chips, active buttons */
}
```

### Motion Physics and Component Transitions

The system utilizes a physics-based spring animation model to replace static easing and duration transitions, making interface micro-interactions feel natural and responsive.

CSS

```
/* Component Transition Mechanics */
.m3-transition-spatial {
  /* Spring model: stiffness = 150, damping = 0.8, initial velocity = 0 */
  transition-property: transform, left, top, width, height, border-radius;
  transition-duration: 350ms;
  transition-timing-function: cubic-bezier(0.175, 0.885, 0.32, 1.1);
}

.m3-transition-effects {
  /* Spring model: stiffness = 220, damping = 1.0 (No overshoot for colors/opacity) */
  transition-property: background-color, color, opacity;
  transition-duration: 250ms;
  transition-timing-function: cubic-bezier(0.2, 0.0, 0, 1.0);
}
```

The design tokens and motion physics guide the visual presentation of core web components, detailed in the table below:

|**UI Component**|**Visual Styling and Material Tokens**|**Stateful Interaction Behavior**|
|---|---|---|
|**Buttons & Groups**|`--radius-full`, height `40px`, `--color-primary` background.|Hover triggers a `35%` opacity container overlay; press initiates a ripple effect.|
|**Hypothesis Cards**|`--radius-lg`, `--color-surface-container` background, solid `--color-outline` border.|Hover increases elevation and darkens borders; selection applies a `--color-primary-container` background.|
|**Navigation Rail**|Width `72px`, `--color-surface` background, distinct border dividing lines.|Category selection activates a `--color-primary-container` backing pill via a horizontal spring expander.|
|**Progress Trackers**|Circular ring or linear indicator, styled with `--color-tertiary` highlights.|Shimmer overlays sweep across background surfaces during long-running tasks.|
|**Scoping Modals**|`--radius-xl`, `--color-surface-container` surface, screen-centered.|Enters viewport with an upward deceleration spring; exits with a downward acceleration curve.|
|**Log Tables**|Borderless rows, separated by thin, low-contrast lines (`--color-outline`).|Hover applies a light background layer; sorted headers use primary color badges.|
|**Error States**|`--radius-md`, styled with prominent `--color-tertiary-container` warnings.|Banners slide in from top margins, remaining pinned until dismissed.|
|**Empty States**|Double-centered layouts, styled with subdued `--color-on-surface-variant` typography.|Generates subtle, animated icon transitions upon initial page loading.|

## Immutable Control Plane, Claim Admission, and Safety Operations

A primary architectural risk of using autonomous research agents is that their outputs can become difficult to audit over long-running executions. To enforce structural integrity, the backend of the clone implements an evidence-gated control plane called the ResearchLoop. This architecture treats research queries, task contracts, execution outputs, and claim ledgers as durable project states written directly to an append-only, Git-versioned file system.

```
                 +----------------------------------------+
                 |            RESEARCH_SPINE              |
                 |     (Research Question Definition)     |
                 +-------------------+--------------------+
                                     |
                                     v
                 +-------------------+--------------------+
                 |             TASKS.yaml                 |
                 |         (Execution Assignment)         |
                 +-------------------+--------------------+
                                     |
                                     v
                 +-------------------+--------------------+
                 |             RUNS/ Manifest             |
                 |           (Evidence Artifact)          |
                 +-------------------+--------------------+
                                     |
                                     v
                 +-------------------+--------------------+
                 |         EVIDENCE_GATE Validation       |
                 +-------------------+--------------------+
                                     |
                   +-----------------+-----------------+
                   |                                   |
                   v                                   v
        +----------+----------+             +----------+----------+
        |   Predicate Passes  |             |   Predicate Fails   |
        +----------+----------+             +----------+----------+
                   |                                   |
                   v                                   v
        +----------+----------+             +----------+----------+
        |     Claim Admitted  |             |    Claim Rejected   |
        |   (PAPER_CLAIM_LEDGER)|           |    (STATUS Blocked) |
        +---------------------+             +---------------------+
```

### The ResearchLoop Workflow

1. **RQ-to-Claim Binding**: Every task must explicitly map to a specific sub-Research Question (RQ) defined inside the `RESEARCH_SPINE.yaml` schema. This contract specifies the target hypothesis, falsification conditions, and required evidence metrics.
    
2. **State Transition Enforcement**: Tasks progress through static, verifiable states: `defined` $\to$ `active` $\to$ `completed` $\to$ `evaluated`. If a run encounters a blocker or validation failure, the state changes to `blocked` or `failed`, locking downstream steps until the error is resolved.
    
3. **The Evidence Gate**: A candidate claim can only enter the final research paper or proposal if it passes the gate predicates specified in `EVIDENCE_GATE.yaml`. The verification agent checks these predicates programmatically.
    

### Core File Schemas

The status of a research execution is tracked in three core YAML schemas :

#### STATUS.yaml

YAML

```
epoch_version: "V3"
status: "active" # active, blocked, closed_stable, closed_negative, validation_ready
current_gate: "G3_DEBATE_REFINEMENT"
focus_rq: "RQ-02"
active_tasks:
  - task_id: "TASK-104"
    assigned_worker: "ranking_agent_03"
blocked_rqs:
notes: "Pairwise tournament initialized for liver disease mechanisms."
```

#### RESEARCH_SPINE.yaml

YAML

```
research_direction: "Identify novel epigenetic targets for liver fibrosis."
decomposed_questions:
  - rq_id: "RQ-02"
    hypothesis: "Inhibition of Target-Y blocks scarring-linked gene expression."
    falsification_condition: "Target-Y silencing fails to reduce scar markers in vitro."
    method_sketch: "Simulate pathway knockdown via epigenetic molecular modeling."
    metric_specification: "Expression level threshold changes (p-value < 0.01)."
    task_queue:
      - task_id: "TASK-104"
        status: "completed"
        evidence_reference: "runs/run_epigenetics_fibrosis_v3.json"
        blocker_annotations: null
```

#### EVIDENCE_GATE.yaml

YAML

```
gate_id: "G3_DEBATE_REFINEMENT"
status: "evaluating"
predicates:
  - predicate_id: "P-01"
    description: "Every hypothesis must be supported by at least two distinct verified PMIDs."
    inspection_check: "scripts/verify_pubmed_citations.py"
    required: true
    status: "passed"
  - predicate_id: "P-02"
    description: "Reflection agent critique must verify target specificity in primary tissue models."
    inspection_check: "agents/reflection_specificity_check.py"
    required: true
    status: "pending"
allowed_claims:
  - "Target-Y knockdown reduces cellular scar gene expression in simulated models."
forbidden_claims:
  - "Target-Y regulates broader cellular aging loops without direct evidence."
```

Once a run satisfies these criteria, the verified claims are logged in the `PAPER_CLAIM_LEDGER.yaml` file. This ledger acts as the authoritative source of truth for the system, ensuring that the final output proposal contains only claims backed by empirical data and literature citations.

### Dual-Agent Safety Architecture

To ensure enterprise-grade safety compliance, the platform utilizes a dual-agent safety architecture. While the active "Talker" agents generate hypotheses and propose protocols, a separate "Planner/Guardian" agent continuously monitors the inputs, outputs, and database requests. This guardian runs dedicated classification filters to intercept biosecurity hazards, dual-use risks, and chemical weapon generation.

If a safety violation is detected, the guardian overrides the supervisor, halts execution, and records the block in the Git audit history, ensuring complete traceability.

## Fidelity Evaluation and Benchmarking Harness

To ensure the clone's performance, behavior, and output align with the original Co-Scientist system, developers must implement a testing and evaluation framework. This testing protocol measures the clone's alignment with target product behaviors, verification standards, and quality benchmarks.

```
                     +---------------------------+
                     |    Fidelity Evaluation    |
                     |         Harness           |
                     +-------------+-------------+
                                   |
         +-------------------------+-------------------------+
         |                         |                         |
         v                         v                         v
+--------+--------+       +--------+--------+       +--------+--------+
|  Operational    |       |   Scientific    |       |    Safety &     |
|  Performance    |       |    Rigor        |       |   Compliance    |
+--------+--------+       +--------+--------+       +--------+--------+
         |                         |                         |
         ├─► Latency Profiles      ├─► NOHARM Audits         ├─► Dual-Use Blocks
         ├─► Bracket Matching      ├─► Citation Parsing      ├─► Guardrails
         └─► State Tracing         └─► Novelty Scores        └─► Commits Audit
```

To validate system fidelity, the clone must be evaluated across the nine core dimensions outlined in the table below:

|**Dimension of Evaluation**|**Target Metric & Similarity Benchmark**|**Testing Vector & Protocol**|**Verification Methodology**|
|---|---|---|---|
|**Product Flow**|Complete setup, scoping interview, standard/advanced runs, and synthesis views.|Run user intake simulations; verify that the scoping interface captures preferences.|Step-by-step user flow testing; verify UI panel visibility.|
|**Terminology**|Absolute taxonomy alignment across all system schemas.|Verify that files use target naming conventions (e.g., `RESEARCH_SPINE.yaml`, `EVIDENCE_GATE.yaml`).|Structural linter checks; schema compliance validation.|
|**Report Structure**|Consolidated proposals containing summary sections, structured data, and citations.|Verify that generated reports match standard formats, mapping outputs to data tables.|Automated document parsing; section and citation presence checks.|
|**Agent Behavior**|Non-linear supervisor adaptive planning and coordinated execution.|Run task queues; trace supervisor decisions during runtime blocking events.|Log auditing; trace step transitions inside `STATUS.yaml`.|
|**Ranking/Tournament**|Elo-based ranking of ideas, pairwise simulated debates, and clustering.|Run tournaments with known dummy ideas; verify that Elo values adjust as expected.|Verify tournament brackets match expected Elo trajectories.|
|**Evidence/Citation**|Grounded claims supported by clickable links.|Run verification scripts on generated texts; verify that DOIs map to source PMC/PubMed papers.|Citation checks; verify that claims map to highlighted reference texts.|
|**Safety Behavior**|Dual-agent safety blocks, biosecurity filtering, and dual-use detection.|Run adversarial inputs; verify that safety guardrails identify and halt hazardous tasks.|Run penetration tests with biosecurity lists; confirm execution shuts down within 100ms.|
|**Progress/Latency**|Non-linear execution speeds; standard vs advanced profiles.|Measure task latency across worker threads, optimizing queues to prevent UI lag.|Load testing; verify that long-running jobs preserve active connection state.|
|**Final Output Quality**|Expert-reviewed scientific proposals matching academic standards.|Submit generated proposals to blinded expert panels, scoring novelty and viability.|Direct expert evaluation; score against standard benchmarks.|

This evaluation harness includes scientific auditing protocols adapted from medical and clinical verification standards. The system implements a customized "NOHARM" evaluation framework to run automated adversarial tests, auditing generated research plans for specific error types :

1. **Errors of Commission**: Generating factually incorrect target associations or referencing citations containing contradictory empirical results.
    
2. **Errors of Omission**: Failing to identify high-signal target relationships or omitting critical safety boundaries documented in clinical databases.
    

By running daily, automated regression tests across these nine dimensions, developers can verify that the system maintains high fidelity to Google DeepMind's Co-Scientist. This validation harness ensures that the clone functions as an accurate, structured scientific reasoning engine, ready to accelerate discoveries in biology, chemistry, and medicine.
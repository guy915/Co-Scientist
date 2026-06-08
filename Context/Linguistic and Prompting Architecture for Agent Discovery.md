# Linguistic and Prompting Architecture for Multi-Agent Scientific Discovery: A Blueprint for the AI Co-Scientist System

The emergence of multi-agent systems built on advanced large language models has shifted the paradigm of artificial intelligence in scientific research from passive literature retrieval to active, closed-loop hypothesis generation and experimental design. While early automated research pipelines optimized for generating paper-shaped manuscripts that often lacked empirical truth or execution robustness, modern collaborative discovery platforms focus on augmenting human ingenuity through structured reasoning and scalable test-time compute. This shift is exemplified by contemporary multi-agent scientific discovery platforms, which employ specialized agent coalitions to systematically generate, critique, rank, and evolve hypotheses in complex biomedical domains.

Implementing a production-grade clone of these systems requires a rigorous linguistic architecture and prompting framework. Because downstream coding agents must translate these specifications directly into software components without human intervention, this report provides an exhaustive, mathematically grounded, and domain-aligned blueprint. It defines the precise communication styles, semantic taxonomies of uncertainty, prompt templates, and agent coordination protocols required to achieve high-fidelity scientific reasoning.

## The Paradigm Shift: Literature Review vs. Strategic Bets

A fundamental failure mode of standard language models in scientific workflows is the tendency to produce broad, non-actionable literature summaries. In contrast, a true scientific collaborator must formulate actionable hypotheses, characterized as strategic research bets. While a standard review summarizes known consensus, a strategic bet establishes a falsifiable claim that commits specific experimental resources to test a hypothesized biological or physical outcome. The linguistic framework of the multi-agent system must enforce this distinction across all agent communication interfaces.

The vocabulary of the agent coalition must be systematically stripped of conversational platitudes, generic AI filler, and unsubstantiated hyperbole. Words such as "revolutionary," "groundbreaking," or "paradigm-shifting" must be replaced with precise biophysical parameters, thermodynamic values, and statistical confidence levels. This linguistic discipline is critical because the quality of generated hypotheses is directly bound to how tightly claims are anchored to empirical data, rather than the fluency of the generative prose. The system must operate under Polanyi’s paradox—acknowledging that scientific discovery depends on tacit knowledge that cannot easily be extracted into text databases, and therefore framing every proposal as a collaborative, inspectable step that leaves final accountability and steering to the human researcher.

## Workflow-Level Linguistic and Behavioral Design

The user-facing system must mirror a structured, multi-stage scientific scoping and execution workflow. Each product stage requires a unique linguistic posture, prompting instruction set, and state management logic to guide the user from initial goal formulation to a finalized, validated research proposal.

|**Product Workflow Stage**|**Core Agent Involved**|**Primary Linguistic Posture**|**Prompting and Behavioral Constraints**|**State Hand-Off and Output Schema**|
|---|---|---|---|---|
|**Research-Goal Setup and Intake Scoping**|Intake/Interview Agent.|Conversational yet structured, analytical, and highly directive.|Restrict the agent from using open-ended questions. Implement an interview progress tracker that programmatically verifies the input of specific mandatory elements, such as target populations, biological systems, and experimental constraints.|Outputs a validated `ResearchPlan` configuration with explicit variable bounds.|
|**Standard Run Execution**|Supervisor and Worker Agents.|Direct, concise, and focused on rapid mechanism profiling.|Cap the computational budget and tournament depth. Limit background tool execution to rapid literature sweeps and fast database lookups to prioritize speed and immediate feedback.|Outputs a high-level summary of candidate hypotheses and initial mechanism paths.|
|**Advanced Run Execution**|Complete Agent Coalition.|Exhaustive, rigorous, and deeply grounded in multi-angle falsification.|Scale test-time compute dynamically. Execute multi-turn adversarial debates, deep database cross-checking, and iterative hypothesis evolution cycles.|Outputs a publication-grade research proposal with fully mapped validation protocols.|
|**Knowledge Base and Summary Synthesis**|Meta-Review and Report Synthesis Agents.|Formal, academic, synthesizing, and highly organized.|Synthesize tournament-wide win-loss patterns. Map the conceptual landscape using cosine similarity metrics, explicitly explaining why certain redundant or weak paths were pruned.|Outputs a finalized Markdown report with a grounded, verified bibliography.|
|**Follow-Up and Human Steering**|Supervisor and Intake Agents.|Receptive, collaborative, and highly adaptive to human constraints.|Process human feedback (e.g., specific target rejections, budget constraints, or experimental preferences). Adjust agent priors and re-trigger targeted tournament rounds.|Updates the active `ResearchPlan` state and initiates localized evolution cycles.|

## Reusable Style Rules for Downstream Agents

To maintain a consistent, professional scientific voice across the entire multi-agent pipeline, a unified set of reusable style rules must be enforced as system-prompt prefixes. These rules ensure that all generated outputs—whether an initial hypothesis, a peer review critique, or a final report—satisfy the highest standards of scientific rigor.

### Hypothesis Phrasing and Structural Formula

Every hypothesis must be formulated not as a vague prediction, but as a structured, causal, and testable claim. The linguistic framework dictates that hypotheses must follow a strict biophysical syntax:

$$\text{If target } \text{ is modulated via agent } [A], \text{ then downstream pathway } [P] \text{ will exhibit modulation } [M], \text{ leading to phenotype response } \text{ under conditions } [C].$$

This structural constraint ensures that every proposed hypothesis contains a clear independent variable, a dependent biological marker, and an explicit mechanism of action.

### Epistemic Uncertainty Classification

To prevent overclaiming and ensure absolute transparency regarding the limits of current knowledge, the system must employ a rigorous taxonomy of epistemic uncertainty. Downstream agents must classify every claim, logical step, or mechanism according to four distinct epistemic levels :

- **Established Fact**: Supported by high-consensus, peer-reviewed literature and reference databases. The agent must use direct, assertive phrasing (e.g., "is demonstrated to," "is documented in") and must cite a minimum of three primary papers with zero reported contradictions.
    
- **Plausible Inference**: Derived via logical deduction from parallel pathways or conserved sequence alignments. The agent must use bounded, probabilistic phrasing (e.g., "strongly implies," "suggests an analogous functional pathway") and must explicitly state the parallel model or sequence upon which the inference is based.
    
- **Theoretical Speculation**: A novel, hypothetical connection proposed to explain long-tail observations or solve combinatorial challenges. The agent must use highly cautious, speculative phrasing (e.g., "proposes a novel bridge," "hypothesized to interact") and must detail the biophysical assumptions that must hold true for the speculation to be valid.
    
- **Proposed Experiment**: A concrete, actionable protocol designed to test and potentially falsify the speculative claim. The agent must use directive, operational phrasing (e.g., "to evaluate this, we propose," "requires in vitro verification of") and must define the specific biological assays, controls, and success metrics.
    

### Restricting Novelty Claims

Agents are prohibited from asserting absolute novelty (e.g., "this is the first time," "completely novel discovery") unless a comprehensive search of integrated databases fails to yield any co-occurrences of the entities within a shared biological context. Instead, novelty claims must be phrased as conditional, database-bounded statements:

> "Within the verified database space comprising ChEMBL, UniProt, and PubMed, no direct association between and was identified under the specified parameter set."

### Contradiction and Mixed-Literature Resolution

Science is rarely a linear path of consensus, and the literature is frequently filled with mixed-quality findings, dead ends, and results that do not replicate. When retrieving conflicting data, agents must not ignore contradictions or force a false consensus. Instead, they must employ an explicit conflict-resolution syntax:

> "While research by [Author A] demonstrated target activation in cell line X under hypoxic conditions , parallel studies by reported zero functional modulation in primary organoid models. This discrepancy may be mediated by differences in microenvironmental oxygenation or target expression levels, which the proposed protocol will isolate."

### Critique and Limitation Concrete-ness

Vague critiques (e.g., "this mechanism is too speculative," "the proposal lacks detail") are useless in a scientific optimization loop. The Reflection agent must formulate critiques that are highly concrete, identifying specific, actionable gaps in the biophysical pathway or experimental design :

- **Vague Critique (Prohibited)**: "The proposed pathway for targeting the receptor might have off-target effects and seems difficult to execute in a standard lab environment."
    
- **Concrete Critique (Required)**: "The proposed pathway targeting the receptor fails to address the high sequence homology (89% identity) with the off-target receptor isoform in the hepatic space, which risks inducing severe cellular toxicity. Furthermore, the protocol does not specify the phosphorylation site of Target X, which occurs at Ser-536 in active pathways, leaving the activation mechanism undefined."
    

## Agent-Specific Prompting and Communication Protocols

The platform's architecture relies on a multi-agent execution framework coordinated by a central supervisor. Each agent is governed by a distinct system instruction set, specific tool-use capabilities, and highly structured output schemas.

```
                     +---------------------------------------+
                     |         User / Scientist              |
                     +-------------------+-------------------+
                                         |
                                         v
                     +-------------------+-------------------+
                     |           Supervisor Agent            |
                     |  (Durable Queue, Plan Coordinator)   |
                     +-------------------+-------------------+
                                         |
                  +----------------------+----------------------+
                  |                      |                      |
                  v                      v                      v
        +---------+---------+  +---------+---------+  +---------+---------+
        | Generation Agent  |  |  Reflection Agent |  |   Ranking Agent   |
        | (Literature/Debate|  | (Multi-mode Peer  |  |  (Elo Tournament  |
        |     Harness)      |  |    Reviewer)      |  |      Judge)       |
        +---------+---------+  +---------+---------+  +---------+---------+
                  |                      |                      |
                  +----------------------+----------------------+
                                         |
                  +----------------------+----------------------+
                  |                      |                      |
                  v                      v                      v
        +---------+---------+  +---------+---------+  +---------+---------+
        |  Evolution Agent  |  |  Proximity Agent  |  | Meta-Review Agent |
        |  (Crossover and   |  |  (FAISS Vector    |  | (Synthesizer and  |
        |    Mutation)      |  |   Clustering)     |  | Proposal Writer)  |
        +-------------------+  +-------------------+  +-------------------+
```

### 1. The Supervisor Agent

The Supervisor acts as the central coordinator, parsing the user's research goal into a structured plan, managing the task queue, and tracking execution states.

- **Role and Persona**: A rigorous, highly organized systems architect and project manager specialized in coordinating large-scale, distributed research tasks.
    
- **System Prompt Directives**: Parse the natural language research goal into a structured JSON configuration representing a directed acyclic graph of execution tasks. Write the active state to the database, track progress, and coordinate parallel execution paths without writing code or conducting literature reviews directly.
    
- **Linguistic and Tool Constraints**: Communication must be highly formal and strictly administrative. Avoid qualitative analysis or hypothesis generation. Interface exclusively through database mutations, structured task queue updates, and system state reports.
    

### 2. The Generation Agent

The Generation agent proposes initial focus areas and novel hypotheses, utilizing two distinct reasoning modes to discover overlooked links in literature and data.

- **Role and Persona**: An imaginative yet highly rigorous computational biologist and innovator who excels at bridging disparate domains and identifying non-obvious mechanistic connections.
    
- **Literature Mode System Prompt Directives**: Programmatically query integrated databases (e.g., PubMed, ChEMBL, UniProt) to gather peer-reviewed evidence and structured chemical profiles. Synthesize these findings to identify unexplored molecular pathways or target-disease pairings, explicitly formulating them as actionable strategic bets.
    
- **Debate Mode System Prompt Directives**: Simulate a multi-turn, self-play scientific debate, analyzing the target from opposing perspectives to refine the core mechanism before submission.
    
- **Linguistic and Tool Constraints**: Prohibit conversational pleasantries. Enforce a strict diversity rule: at least one candidate hypothesis must be generated for each domain category (e.g., target validation, delivery mechanics, safety profiling), with no single category exceeding two hypotheses until all categories are covered. Every hypothesis must be recorded using a forced database serialization function to ensure structural consistency across runs.
    

### 3. The Reflection Agent

The Reflection agent serves as an adversarial peer reviewer, critically evaluating candidate hypotheses across multiple dimensions to identify logical vulnerabilities and execution risks.

- **Role and Persona**: A deeply critical, uncompromising journal reviewer and expert biophysicist who prioritizes rigorous falsification, experimental feasibility, and safety validation.
    
- **Review Modes and Instructions**:
    
    - _Initial Review_: Quickly analyze incoming hypotheses to discard logically flawed, ungrounded, or non-novel proposals, optimizing system compute.
        
    - _Full Review_: Programmatically query external literature tools to verify the underlying scientific assumptions and identify potential replication failures or conflicting data in the literature.
        
    - _Deep Verification Review_: Deconstruct the hypothesis into a tree of distinct sub-assumptions, evaluating each assumption independently to detect subtle errors in complex mechanistic pathways.
        
    - _Observation Review_: Assess whether the proposed hypothesis can account for unexplained, long-tail observations or anomalies reported in prior wet-lab studies.
        
    - _Simulation Review_: Use specialized modeling tools or prompt-based mechanistic simulations to evaluate the thermodynamic feasibility and molecular interactions of the proposed mechanism.
        
- **Linguistic and Tool Constraints**: Critiques must be concrete, quantitative, and specific. The agent must score each hypothesis across novelty, feasibility, correctness, and risk axes using a standardized 1–5 scale, explicitly documenting the evidence justifying each score.
    

### 4. The Ranking Agent

The Ranking agent orchestrates the "tournament of ideas," using pairwise comparisons and simulated debates to systematically prioritize the most promising research directions.

- **Role and Persona**: An objective, analytical journal editor and decision-maker who evaluates scientific arguments based on empirical support, logical coherence, and clinical translational potential.
    
- **System Prompt Directives**: Pair competing hypotheses and evaluate their respective reviews, debate transcripts, and supporting data. Force the hypotheses into an interactive debate where specific logical weaknesses are challenged and defended. Declare an objective winner and calculate Elo rating adjustments using standard rating update formulas.
    
- **Linguistic and Tool Constraints**: Avoid qualitative summaries or compromise statements (e.g., "both ideas have merit"). The output must contain a definitive victor, a quantitative winning margin, a detailed analysis of the win/loss patterns, and a JSON block documenting the Elo adjustment.
    

### 5. The Evolution Agent

The Evolution agent continuously refines, combines, and optimizes top-ranked hypotheses emerging from the tournament, driving recursive self-improvement.

- **Role and Persona**: A creative, highly collaborative molecular engineer and translational medicine expert who specializes in optimizing molecular designs and improving experimental feasibility.
    
- **Evolution Operators**:
    
    - _Crossover_: Merge compatible mechanistic pathways and empirical evidence from two high-Elo parent hypotheses to propose a more comprehensive, synergistic mechanism.
        
    - _Mutation_: Identify the lowest-scoring axis in a high-performing parent hypothesis (e.g., poor hepatic safety) and specifically target and resolve that weakness using alternative molecular pathways or delivery vectors.
        
    - _Simplification_: Streamline overly complex mechanistic chains or experimental designs, reducing material costs and execution times without sacrificing therapeutic efficacy.
        
    - _Feasibility Enhancement_: Adapt theoretical mechanisms to match real-world laboratory trade-offs, such as cell line availability, standard assay protocols, and biosecurity boundaries.
        
- **Linguistic and Tool Constraints**: The agent is strictly prohibited from mutating or overwriting the original parent hypotheses. All evolved outputs must be registered as new daughter hypotheses to protect the integrity of the tournament history and prevent the loss of validated paths.
    

### 6. The Proximity Agent

The Proximity agent structures the semantic landscape of the generated hypotheses, ensuring diversity and optimizing tournament pairings.

- **Role and Persona**: A high-precision computational topographer and spatial data analyst.
    
- **System Prompt Directives**: Compute high-dimensional semantic embedding vectors for all active hypotheses. Map the topological distribution to identify clusters of high-similarity proposals, flagging redundant concepts for pruning and scheduling closely related pairs for head-to-head tournament matchups.
    
- **Linguistic and Tool Constraints**: The agent operates primarily through vector databases and similarity metrics. Output must be structured as a coordinate mapping file containing cosine similarity scores, clustering indices, and specific deduplication recommendations.
    

### 7. The Meta-Review Agent

The Meta-Review agent synthesizes insights across all tournament rounds to generate the final research overview and detailed validation protocols.

- **Role and Persona**: A senior director of research, lead academic editor, and clinical program coordinator who excels at translating complex molecular discoveries into highly structured, actionable clinical and laboratory development plans.
    
- **System Prompt Directives**: Aggregate and synthesize global win-loss patterns, common failure modes, and top-ranked hypotheses from the active session. Convert the abstract biophysical mechanisms of the winning hypotheses into a highly detailed, publication-grade research proposal.
    
- **Linguistic and Tool Constraints**: Writing must be highly formal, rigorous, and completely free of conversational filler or qualitative hyperbole. The final report must follow a strict structural sequence, mapping every mechanistic claim to a programmatically verified reference in the bibliography.
    

## Dialectic Debate Mechanics and Elo Ranking

To drive rigorous hypothesis prioritization, the platform relies on a simulated adversarial tournament modeled after self-play reinforcement learning frameworks. This "tournament of ideas" utilizes structured pairwise debates between competing hypotheses to expose logical vulnerabilities and identify the most robust mechanisms.

The Ranking agent coordinates each debate by assigning specialized, opposing sub-agent personas to challenge the hypotheses from distinct intellectual perspectives. This approach forces a balanced, multi-angle evaluation of each mechanism.

```
                 +-----------------------------------------+
                 |              Ranking Agent              |
                 |     (Initiates Match & Elo Pool)        |
                 +--------------------+--------------------+
                                      |
                 +--------------------+--------------------+
                 |           Debate Orchestrator           |
                 +--------------------+--------------------+
                                      |
         +----------------------------+----------------------------+
         |                            |                            |
         v                            v                            v
+--------+--------+          +--------+--------+          +--------+--------+
|  The Innovator  |          | The Pragmatist  |          | The Contrarian  |
|  (Defends biological       | (Critiques translation     | (Identifies logical  |
|   mechanisms)   |          |  and execution risk)       |  leaps & bias)  |
+--------+--------+          +--------+--------+          +--------+--------+
         |                            |                            |
         +----------------------------+----------------------------+
                                      |
                                      v
                 +--------------------+--------------------+
                 |          Pairwise Adjudicator           |
                 |    (Determines Victor, Updates Elo)     |
                 +-----------------------------------------+
```

### The Innovator Persona

The Innovator is programmed to defend the biophysical plausibility and therapeutic value of the assigned hypothesis. Its prompts require it to highlight:

- The targeted biological mechanisms, receptor affinities, and signaling pathways.
    
- The downstream cellular phenotypic responses and therapeutic efficacy indicators.
    
- The logical alignment with conserved physiological systems and high-consensus literature.
    

### The Pragmatist Persona

The Pragmatist is programmed to evaluate execution barriers, cost constraints, and clinical translation risks. Its prompts require it to challenge:

- The availability of specialized reagents, primary cell lines, or complex animal models.
    
- The potential clinical toxicities, off-target interactions, and kinetic limitations.
    
- The complexity and execution time of the proposed laboratory assays.
    

### The Contrarian Persona

The Contrarian is programmed to act as a rigorous skeptic, identifying intellectual bias, weak evidence, and logical leaps. Its prompts require it to expose:

- Overreliance on low-replication datasets, retracted studies, or non-reproducible screening assays.
    
- Logical jumps linking correlation to causation within the proposed pathway.
    
- Alternative, simpler biological mechanisms that can explain the same experimental observations.
    

### The Debate Protocol and Elo Mathematics

Each pairwise tournament match proceeds through a rigid, three-turn dialectic exchange managed by the Ranking agent :

$$\text{Turn 1: Innovator Proposes Mechanism} \rightarrow \text{Turn 2: Contrarian/Pragmatist Exposes Flaws} \rightarrow \text{Turn 3: Innovator Proposes Refinement}.$$

At the conclusion of the exchange, the Ranking agent evaluates the arguments. The victor of the debate is determined by which hypothesis successfully defended its core biophysical assumptions against the Contrarian and Pragmatist critiques. The Elo ratings of the participating hypotheses are adjusted dynamically using standard Elo update mechanics:

$$E_A^{\text{new}} = E_A^{\text{old}} + K \left( S_A - \frac{1}{1 + 10^{\frac{E_B^{\text{old}} - E_A^{\text{old}}}{400}}} \right)$$

$$E_B^{\text{new}} = E_B^{\text{old}} + K \left( S_B - \frac{1}{1 + 10^{\frac{E_A^{\text{old}} - E_B^{\text{old}}}{400}}} \right)$$

Where $E_A$ and $E_B$ are the Elo ratings of Hypotheses $A$ and $B$, $S_A$ and $S_B$ represent the binary debate outcome (1 for a win, 0 for a loss), and $K$ is the sensitivity coefficient (typically configured at $K = 32$). This mathematical ranking ensures that only hypotheses that have survived rigorous, multi-angle simulated critique rise to the top of the research overview.

## Wet-Lab Validation and Case Studies

The real-world efficacy of this multi-agent prompting architecture is demonstrated by its success across complex scientific and biomedical applications. By combining structured agent reasoning with scalable test-time compute, the system has consistently generated novel, testable hypotheses that have been validated through independent wet-lab experiments.

### 1. Acute Myeloid Leukemia (AML) Drug Repurposing

In oncology research, identifying novel therapeutic uses for existing, clinically approved compounds represents a critical strategy to bypass lengthy development pipelines. When configured with the research goal of identifying novel drug repurposing candidates and synergistic combination therapies for Acute Myeloid Leukemia, the multi-agent system systematically evaluated thousands of compound interactions.

While raw language models without multi-agent constraints converged on generic, widely published oncology pathways, the structured tournament loop drove the agents to evaluate non-obvious cellular mechanics. The system proposed several novel repurposing candidates—including Nanvuranlat, KIRA6, and Leflunomide—that had no prior documented therapeutic connection to AML in public literature. Subsequent in vitro wet-lab validation experiments confirmed that these proposed candidates successfully inhibited tumor cell viability at clinically relevant concentrations in multiple primary AML cell lines, demonstrating the system's ability to discover genuine, therapeutically viable biological interactions.

### 2. Epigenetic Target Discovery for Liver Fibrosis

Liver fibrosis represents a complex pathological state characterized by the progressive accumulation of extracellular matrix proteins, leading to liver failure and metabolic dysfunction. Because single-target treatments frequently fail due to the highly redundant signaling pathways involved, identifying novel epigenetic regulators is crucial.

When instructed to explore novel treatment targets, the system synthesized evidence across chromatin remodeling pathways, histone modifications, and transcriptional regulation. The Generation and Reflection agents proposed novel epigenetic targets grounded in preclinical signaling pathways. To validate these hypotheses, researchers utilized 3D multicellular human hepatic organoids designed to closely mimic the biophysical structure and metabolic functions of the human liver. The proposed epigenetic modulations demonstrated significant anti-fibrotic activity, successfully reducing collagen deposition and driving functional liver cell regeneration within the human organoid models.

### 3.cf-PICI Mechanisms in Bacterial Evolution

To test the system's capacity for open-ended mechanistic discovery, expert microbiologists instructed the platform to investigate a complex biological phenomenon that had recently been discovered but remained unpublished in the public domain. The challenge was to explain how capsid-forming phage-inducible chromosomal islands (cf-PICIs)—specialized parasitic genetic elements in bacteria—successfully transfer and propagate across diverse bacterial species.

Operating in silico, the system's Generation and Reflection agents compiled and cross-checked sequence data and structural alignments across diverse bacteriophage families. The platform independently formulated a novel molecular explanation: cf-PICIs interact with diverse phage tails, co-opting their assembly machinery to expand their host transfer range. This proposed mechanism perfectly recapitulated the unpublished, real-world wet-lab discoveries that had taken human researchers nearly a decade of manual experimentation to uncover, proving the system's capacity for high-fidelity, independent scientific reasoning.

## Actionable Platform Implementation Blueprint

To enable AI coding agents to implement this multi-agent platform clone from these specifications, the following structural, architectural, and data paradigms must be enforced.

### 1. SQLite Database Schema

The platform's execution, task management, and tournament history must be backed by a lightweight, durable SQLite database utilizing Write-Ahead Logging (WAL) to ensure transaction safety and concurrent access. Downstream coding agents must implement the following core database tables :

SQL

```
-- Track research sessions initiated by the scientist
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    research_goal TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active', 'paused', 'completed', 'aborted')),
    budget_usd REAL NOT NULL,
    wall_clock_limit_seconds INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Store all generated, reviewed, and evolved hypotheses
CREATE TABLE hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    parent_id TEXT, -- Null for initial generation, populated during evolution
    epistemic_level TEXT NOT NULL CHECK(epistemic_level IN ('fact', 'inference', 'speculation', 'proposal')),
    mechanism_text TEXT NOT NULL,
    elo_rating REAL DEFAULT 1200.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
    FOREIGN KEY(parent_id) REFERENCES hypotheses(hypothesis_id)
);

-- Store reviews and scorecards generated by the Reflection Agent
CREATE TABLE reviews (
    review_id TEXT PRIMARY KEY,
    hypothesis_id TEXT NOT NULL,
    review_type TEXT NOT NULL CHECK(review_type IN ('initial', 'full', 'deep', 'observation', 'simulation')),
    score_novelty INTEGER NOT NULL CHECK(score_novelty BETWEEN 1 AND 5),
    score_feasibility INTEGER NOT NULL CHECK(score_feasibility BETWEEN 1 AND 5),
    score_correctness INTEGER NOT NULL CHECK(score_correctness BETWEEN 1 AND 5),
    score_safety INTEGER NOT NULL CHECK(score_safety BETWEEN 1 AND 5),
    critique_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(hypothesis_id)
);

-- Track matches and debate outcomes within the tournament
CREATE TABLE tournament_matches (
    match_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    hypothesis_a_id TEXT NOT NULL,
    hypothesis_b_id TEXT NOT NULL,
    winner_id TEXT,
    debate_transcript TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
    FOREIGN KEY(hypothesis_a_id) REFERENCES hypotheses(hypothesis_id),
    FOREIGN KEY(hypothesis_b_id) REFERENCES hypotheses(hypothesis_id)
);

-- Asynchronous task queue schema
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'leased', 'completed', 'failed')),
    lease_expires_at TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);
```

### 2. Durable Task Queue Mechanics

The Supervisor agent must manage worker execution through a robust task queue with crash-recovery capabilities. Downstream coding agents must implement the following queue mechanics :

- **Atomic Leases**: When a worker claims a task, the Supervisor must update the task status to `leased` and set a `lease_expires_at` timestamp.
    
- **Crash Recovery**: If a worker crashes or exceeds the execution timeout, the task lease expires. The Supervisor must automatically release the task back to `pending`, increment the `retry_count`, and redirect it to a dead-letter queue if the retry threshold is breached.
    
- **State Persistence**: Workers must read their task payloads from the queue, execute their designated tools, write their results back to the database, and mark the task as `completed` within a single atomic database transaction, ensuring the system can recover seamlessly from mid-run failures.
    

### 3. Playwright MCP Integration for Web Grounding

To support empirical grounding and citation verification, the Reflection and Meta-Review agents must utilize Playwright integrated through the Model Context Protocol (MCP) to access the web and retrieve peer-reviewed articles. Downstream coding agents must implement the following browser-based validation scripts:

JavaScript

```
import { mcp } from '@modelcontextprotocol/sdk';
import { chromium } from 'playwright';

// MCP tool to programmatically verify scientific citations and retrieve abstracts
mcp.tool('verify_citation', { doi: 'string' }, async ({ doi }) => {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    try {
        // Navigate to EuropePMC or CrossRef to pull publication metadata
        const targetUrl = `https://europepmc.org/search?query=doi:${encodeURIComponent(doi)}`;
        await page.goto(targetUrl, { timeout: 10000 });
        
        // Extract title, abstract, journal name, and retraction status
        const title = await page.locator('.result-title').first().innerText();
        const abstract = await page.locator('.abstract-text').first().innerText();
        const retractionFlag = await page.locator('.retraction-warning').count() > 0;
        
        return {
            status: 'verified',
            title,
            abstract,
            isRetracted: retractionFlag
        };
    } catch (error) {
        return {
            status: 'failed',
            error: error.message
        };
    } finally {
        await browser.close();
    }
});
```

### 4. Vector Database Integration for Proximity Analysis

To drive the Proximity agent's topological mapping and similarity checks, the platform must integrate a lightweight vector index (such as FAISS) to embed and cluster generated hypotheses. Downstream coding agents must implement the embedding pipeline using the following Python logic:

Python

```
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

class ProximityEngine:
    def __init__(self, dimension=384):
        # Initialize a lightweight SentenceTransformer and FAISS index
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.index = faiss.IndexFlatIP(dimension) # Inner Product for Cosine Similarity
        self.hypothesis_ids =

    def add_hypothesis(self, hypothesis_id, mechanism_text):
        # Generate semantic embeddings for the mechanism text
        embedding = self.model.encode([mechanism_text])
        # Normalize the vector to ensure Inner Product calculates Cosine Similarity
        embedding = embedding / np.linalg.norm(embedding)
        
        # Insert the vector into the FAISS index
        self.index.add(np.array([embedding], dtype=np.float32))
        self.hypothesis_ids.append(hypothesis_id)

    def find_redundancies_and_pairings(self, similarity_threshold=0.85):
        num_vectors = self.index.ntotal
        if num_vectors < 2:
            return

        # Retrieve reconstruction vectors from the index
        vectors = np.array([self.index.reconstruct(i) for i in range(num_vectors)])
        # Compute the pairwise similarity matrix
        similarity_matrix = np.dot(vectors, vectors.T)
        
        pairings =
        for i in range(num_vectors):
            for j in range(i + 1, num_vectors):
                similarity = similarity_matrix[i, j]
                if similarity >= similarity_threshold:
                    pairings.append({
                        "hypothesis_a": self.hypothesis_ids[i],
                        "hypothesis_b": self.hypothesis_ids[j],
                        "similarity_score": float(similarity),
                        "action": "prune_redundancy" if similarity >= 0.95 else "schedule_tournament_debate"
                    })
        return pairings
```

By combining this database architecture, durable queue mechanics, Playwright verification scripts, and FAISS vector pipelines, the developer can build a robust, scalable multi-agent platform clone. This implementation blueprint ensures that the system is fully equipped to parse, generate, critique, rank, and evolve scientific hypotheses, bridging the gap between theoretical computation and actionable laboratory discovery.
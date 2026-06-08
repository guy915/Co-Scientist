# Engineering Blueprint and Functional Fidelity Evaluation Suite for a 1:1 AI Co-Scientist System

## Architectural Topology and Multi-Agent Coordination Framework

The construction of a high-fidelity clone of Google DeepMind’s AI Co-Scientist system requires moving away from standard, single-model language interfaces in favor of an asynchronous, multi-agent coordination architecture. Rather than executing pre-scripted, linear tasks, the system operates as a collaborative network of specialized agents managed by a non-linear planning engine. This framework manages state transitions over long runtime horizons, utilizing test-time compute scaling to iteratively refine hypotheses.

The macro-architecture comprises several key layers: a web-based user interface, a backend API service, a long-running job queue, a scientific retrieval and vector search layer, an immutable hypothesis store, an evidence-to-citation mapping engine, an Elo-based pairwise tournament engine, a dynamic report synthesis module, a selective safety layer, and an automated fidelity evaluation harness.

```
+-------------------------------------------------------------------------------------------------+
|                                           Web User Interface                                    |
+---------------------------------------------------------------+---------------------------------+
                                                                |
                                                                v
+-------------------------------------------------------------------------------------------------+
|                                              Backend API                                        |
+---------------------------------------------------------------+---------------------------------+
                                                                |
                                                                v
+-------------------------------------------------------------------------------------------------+
|                                    Asynchronous Job Queue                                       |
+---------------------------------------------------------------+---------------------------------+
                                                                |
                                                                v
+-------------------------------------------------------------------------------------------------+
|                                  Supervisor (Adaptive Planner)                                  |
+---------------------------------------------------------------+---------------------------------+
         |                           |                          |                         |
         v                           v                          v                         v
+------------------+       +------------------+       +-------------------+     +-----------------+
| Intake/Interview |       | Literature RAG   |       | Generation Agent  |     | Proximity Agent |
+------------------+       +------------------+       +-------------------+     +-----------------+
         |                           |                          |                         |
         v                           v                          v                         v
+------------------+       +------------------+       +-------------------+     +-----------------+
| Reflection Agent |       | Ranking Agent    |       | Evolution Agent   |     | Meta-Reviewer   |
+------------------+       +------------------+       +-------------------+     +-----------------+
         |                           |                          |                         |
         v                           v                          v                         v
+------------------+       +------------------+       +-------------------+     +-----------------+
| Citation Verifier|       | Safety Agent     |       | Report Synthesizer|     | Science Tools   |
+------------------+       +------------------+       +-------------------+     +-----------------+
```

The coordination of this agent network is managed by the Supervisor Agent, which acts as an adaptive planner. Instead of following a rigid, step-by-step workflow, the Supervisor dynamically decomposes high-level scientific goals into parallel worker tasks, managing a centralized job queue to coordinate the network. The state transitions are tracked via a global context manager that synchronizes execution plans, code versions, results, and agent invocations.

|**Agent Name**|**Core Orchestration Role**|**Model Configuration**|**Integrated Tools & Databases**|**Input Schema Specification**|**Expected JSON Output Schema**|
|---|---|---|---|---|---|
|**Supervisor**|Adaptive planning, dynamic sub-task allocation, and work queue management.|Gemini 2.0 / 3.5 Flash (agent-optimized routing).|State Database, Redis Queue, Event Bus.|`{ "goal": "string", "user_constraints": {}, "current_state": "string" }`|`{ "next_action": "string", "assigned_agent": "string", "payload": {} }`|
|**Intake/Interview**|Iterative, conversational scoping of scientific goals and parameter extraction.|Gemini 3.5 Flash (conversational mode).|Chat History Store, Scientific Glossaries.|`{ "user_input": "string", "scoping_session_id": "string" }`|`{ "clarifying_question": "string", "parameters_extracted": {}, "is_complete": "boolean" }`|
|**Literature Retrieval**|Semantic query construction, multi-source searching, and document retrieval.|Gemini 3.5 Flash (retrieval mode).|PubMed API, Google Scholar, ArXiv API.|`{ "search_targets": ["string"], "limit": "integer" }`|`{ "retrieved_documents": [{ "id": "string", "title": "string", "abstract": "string" }] }`|
|**Generation**|Formulating testable hypotheses grounded in literature data.|Gemini 2.0 / Deep Think (generation tier).|Hypothesis Store, Knowledge Graph APIs.|`{ "context_documents":, "target_problem": "string" }`|`{ "proposed_hypotheses": [{ "id": "string", "statement": "string", "mechanism": "string" }] }`|
|**Reflection**|Peer-review assessment of scientific plausibility, logical consistency, and novelty.|Gemini Deep Think (rigorous peer-review configuration).|Peer Review Checklists, Domain Knowledge Bases.|`{ "hypothesis": {}, "supporting_literature": }`|`{ "is_plausible": "boolean", "logical_flaws": ["string"], "novelty_score": "float" }`|
|**Proximity/Clustering**|Mapping candidate hypotheses to coordinate spaces and deduplicating redundant proposals.|Gemini 3.5 Flash (embedding and clustering configuration).|Vector Database (Milvus/Pinecone), SciPy libraries.|`{ "hypotheses": [{ "id": "string", "text": "string" }] }`|`{ "clusters": [{ "cluster_id": "string", "member_ids": ["string"] }], "duplicates_removed": ["string"] }`|
|**Ranking**|Coordinating pairwise debates and updating Elo ratings to identify the strongest hypotheses.|Gemini 3.5 Flash (debate adjudication mode).|Elo Calculator Service, Debate Log Store.|`{ "hypothesis_pairs": [[{}, {}]], "iterations": "integer" }`|`{ "winning_id": "string", "losing_id": "string", "elo_delta": "float", "rationale": "string" }`|
|**Evolution**|Refining, combining, and improving high-scoring hypotheses using debate feedback.|Gemini Deep Think (creative-evolution configuration).|Analogy Stores, Physical Laws Databases.|`{ "top_hypotheses":, "critiques":, "evolution_strategy": "string" }`|`{ "evolved_hypotheses": [{ "id": "string", "derived_from":, "changes": "string" }] }`|
|**Meta-Review**|Synthesizing debate and tournament outcomes into high-level development roadmaps.|Gemini Deep Think (synthesis mode).|Run Execution Database, System Log Stores.|`{ "tournament_logs":, "evolution_history":, "final_ranks": }`|`{ "synthesis_summary": "string", "system_optimization_guidance": "string" }`|
|**Citation Verification**|Fact-checking generated claims and resolving entity mappings to database records.|Gemini 3.5 Flash (cross-checking mode).|ChEMBL API, UniProt API, AlphaFold Database.|`{ "claims_made": [{ "text": "string", "source_claims": }] }`|`{ "verified_claims": [{ "claim_text": "string", "is_supported": "boolean", "db_refs": }] }`|
|**Safety**|Screening research runs for dual-use concerns, bio-safety hazards, and ethical compliance.|Gemini 3.5 Flash (policy enforcement mode).|Biosecurity Whitelists, Ethics Compliance Engines.|`{ "proposal_draft": "string", "run_parameters": {} }`|`{ "is_safe": "boolean", "violations": ["string"], "restricted_materials": ["string"] }`|
|**Report Synthesis**|Writing complete, structured proposals with integrated, verified citations.|Gemini Deep Think (technical-prose configuration).|Document Templating Engines, PDF/Markdown Renderers.|`{ "meta_summary": "string", "proven_hypotheses":, "citation_manifest": }`|`{ "rendered_report": "string", "structured_sections": {} }`|

## Interactive Scoping, Workflow Orchestration, and Run Specifications

The front-end workflow of the Gemini for Science framework is designed around a multi-stage research lifecycle. To match the target system's performance, the platform must guide users through research-goal setup, interactive scoping, literature grounding, execution, and final report delivery.

```
+------------------+       +------------------+       +------------------+
|   User Defines   |------>| Intake Agent     |------>| User Selects     |
|   Initial Goal   |       | Clarifies Scope  |       | Run Profile      |
+------------------+       +------------------+       +------------------+
                                                               |
                                                               v
+------------------+       +------------------+       +------------------+
| Synthesis Agent  |<------| Tournament &     |<------| Supervisor       |
| Generates Report |       | Evolution Cycles |       | Launches Run     |
+------------------+       +------------------+       +------------------+
```

The user begins by entering a research goal in natural language. The Intake/Interview Agent then starts a multi-turn conversation, asking clarifying questions to identify key experimental parameters, budget constraints, target model requirements, and safety conditions. This interaction ensures that even vague initial ideas are refined into precise specifications before allocating significant compute resources.

```
User Prompt: "Identify therapeutic options for dry macular degeneration."
      |
      v

      |
      v
Intake Agent: "To narrow our search, should the system prioritize small molecule drugs for repurposing, or should it evaluate gene therapies?" [7, 12]
      |
      v
User Response: "Focus on small molecule repurposing to speed up clinical validation." [2, 12]
      |
      v

```

When the user launches the run, they select one of two execution modes:

### Standard Run Profile

The Standard Run is optimized for fast, iterative exploration of large search spaces. It relies on Gemini 3.5 Flash to rapidly scan literature, cluster initial hypotheses, and run short debate cycles. This configuration is designed to quickly map out a research domain at a lower cost, making it ideal for initial scoping and testing.

### Advanced Run Profile

The Advanced Run is configured for deeper reasoning, scaling test-time compute through Gemini Deep Think models. It runs extended, multi-turn tournaments where hypotheses undergo rigorous debate, evolution, and verification. The system allocates the majority of its compute to verifying claims against external scientific databases, ensuring that the final proposals are robust, detailed, and scientifically sound.

|**State ID**|**Action Name**|**Trigger Condition**|**Active Agents Involved**|**Output State Transition**|**Verification Check**|
|---|---|---|---|---|---|
|**ST-01**|Goal Initialization|User submits a natural language prompt via the web interface.|Intake/Interview.|Transition to **ST-02** (Scoping Session Active).|Check that the input contains text and is not empty.|
|**ST-02**|Scoping Session|Intake/Interview Agent determines that key parameters are missing.|Intake/Interview.|Transition to **ST-03** (Run Specifications Confirmed).|Validate that required parameters (such as therapeutic modality and constraints) are resolved.|
|**ST-03**|Run Launch|User confirms parameters and selects Standard or Advanced run profile.|Supervisor (Planner).|Transition to **ST-04** (Context Grounding Active).|Verify that API keys, database connections, and run balances are valid.|
|**ST-04**|Literature Grounding|Supervisor triggers search queries based on run parameters.|Literature Retrieval.|Transition to **ST-05** (Ideation & Clustering Active).|Confirm that retrieved documents are stored in the temporary context store.|
|**ST-05**|Ideation & Clustering|Context documents are compiled into the run history.|Generation, Proximity.|Transition to **ST-06** (Tournament Active).|Ensure that duplicate hypotheses are pruned and remaining ideas are clustered.|
|**ST-06**|Tournament & Evolution|Proximity clustering is completed and tournament matchups are generated.|Reflection, Ranking, Evolution.|Transition to **ST-07** (Synthesis Active).|Verify that the Elo ranking history is updated after each pairwise debate.|
|**ST-07**|Synthesis & Audit|Tournament run hits configured stopping criteria (such as max rounds or Elo convergence).|Meta-Review, Citation Verification, Safety, Report Synthesis.|Transition to **ST-08** (Report Rendered).|Confirm that all safety checks are passed and all cited targets are verified.|
|**ST-08**|Delivery & Interaction|Report synthesis is complete and output is saved to the hypothesis store.|Supervisor, Intake/Interview.|System idles; awaits follow-up queries or refinement runs.|Ensure the user can access the final proposal and interact with the co-scientist.|

## Mathematical Mechanics of the Tournament of Ideas and Verification Engine

The tournament of ideas is the core process the system uses to verify, refine, and rank candidate hypotheses. Instead of using a single model to score hypotheses linearly, the platform runs a multi-turn, pairwise debate tournament where hypotheses are compared directly. This debate process is managed by the Ranking Agent, which pits candidate hypotheses against each other using simulated peer review to prioritize the most promising directions.

The ranking of hypotheses is calculated using an Elo-based scoring system. The Elo rating updates after each pairwise debate according to the standard mathematical update rule:

$$E_i \leftarrow E_i + K \left(S_i - \frac{1}{1 + 10^{\frac{E_j - E_i}{400}}}\right)$$

where $E_i$ is the active hypothesis rating, $E_j$ is the opponent rating, $K$ is the update weight factor, and $S_i$ is the actual score outcome ($1$ for a win, $0$ for a loss, $0.5$ for a draw) awarded by the judging agent. This iterative tournament mechanism has been shown to correlate directly with hypothesis quality and correctness.

The target system focuses its computational resources primarily on verification rather than generation. To maintain high accuracy, the system allocates the majority of its computation to verifying candidate claims. This verification process involves cross-referencing generated assertions against literature databases and structured biomedical repositories.

The Proximity Agent works alongside this verification loop. It maps and clusters hypotheses using a proximity graph. This grouping serves two main purposes: it prevents redundant evaluations by deduplicating similar hypotheses, and it ensures the system explores a diverse range of research paths.

```
                +---------------------------------------+
                |        Supervisor Agent               |
                |       (Adaptive Planner)              |
                +-------------------+-------------------+
                                    |
                                    v
                        +-----------------------+
                        |   Generation Agent    |<-------------+
                        +-----------+-----------+              |
                                    |                          |
                                    v                          |
                        +-----------------------+              |
                        |    Proximity Agent    |              |
                        |  (Graph Clustering)   |              |
                        +-----------+-----------+              |
                                    |                          |
                                    v                          |
                        +-----------------------+              | Iterative
                        |   Reflection Agent    |              | Evolution
                        |  (Virtual Reviewer)   |              | Loop
                        +-----------+-----------+              |
                                    |                          |
                                    v                          |
                        +-----------------------+              |
                        |     Ranking Agent     |              |
                        |  (Elo-Based Debates)  |              |
                        +-----------+-----------+              |
                                    |                          |
                                    v                          |
                        +-----------------------+              |
                        |    Evolution Agent    +--------------+
                        +-----------+-----------+
                                    |
                                    v
                        +-----------------------+
                        |  Meta-Review Agent    |
                        +-----------+-----------+
                                    |
                                    v
                        +-----------------------+
                        | Final Research Proposal|
                        +-----------------------+
```

During this cycle, the Reflection Agent evaluates hypotheses across four distinct stages. First, an Initial Review filters out logically flawed or unoriginal hypotheses. Second, a Full Review uses retrieval tools to find relevant scientific literature, grounding the evaluation in existing research. Third, a Deep Verification Review looks for subtle errors in complex scientific arguments. Finally, an Observation and Simulation Review models experimental setups to assess whether the hypothesis is plausible and matches historical laboratory results.

To verify claims, the Citation Verification Agent parses hypotheses and queries external databases. It connects to specialized databases via the Science Skills toolkit, converting natural language assertions into structured queries:

- **UniProt integration:** Resolves protein names to accession codes (e.g., `P01137` for human TGF-beta 1), extracting sequence details and structural domains to check if the proposed interactions are physically possible.
    
- **ChEMBL integration:** Resolves small-molecule drug candidates to compound IDs (e.g., `CHEMBL25`), checking binding affinities ($K_i, IC_{50}$) against target proteins to confirm the proposed mechanisms are pharmacologically sound.
    
- **AlphaFold Database integration:** Retrieves 3D structures of target proteins, checking for binding pockets and interface residues to verify modeled physical interactions.
    

The Proximity Agent maps the hypothesis space using semantic embeddings to construct a proximity graph. The distance between two hypotheses is calculated using cosine similarity:

$$\text{Distance}(h_a, h_b) = 1 - \frac{\vec{V}(h_a) \cdot \vec{V}(h_b)}{\|\vec{V}(h_a)\| \|\vec{V}(h_b)\|}$$

Where $\vec{V}(h)$ is the embedding vector of the hypothesis. If the distance falls below a defined similarity threshold (e.g., $D < 0.12$), the Proximity Agent flags them as duplicates, keeping the highest-rated hypothesis and pruning the other to maintain a diverse and efficient search space.

## Behavioral Fidelity Assessment and the BRIDGE Selective Evaluation Framework

To verify that the clone matches the target system's performance, the platform must evaluate more than just final outputs; it must measure behavioral fidelity across multi-turn scientific dialogues. This is achieved using the BRIDGE framework, which evaluates agent behaviors through deterministic safety/validity gates and a calibrated probabilistic judge.

```
                 +--------------------------------------+
                 |          Agent Execution Log         |
                 +------------------+-------------------+
                                    |
                                    v
                 +--------------------------------------+
                 |      Deterministic Safety Gates      |
                 |      (Epistemic, Logical, etc.)      |
                 +------------------+-------------------+
                                    |
                        +-----------+-----------+
                        |                       |
                        | All Gates Pass        | Gate Fails
                        v                       v
         +----------------------------+   +-----------+
         | Calibrated Probabilistic   |   | Reject &  |
         |         Judge              |   | Escalate  |
         +--------------+-------------+   +-----------+
                        |
            +-----------+-----------+
            |                       |
            | YES on All Traits     | AMBIGUOUS or NO
            v                       v
     +------------+           +-----------+
     | Run Passes |           | Escalate  |
     |            |           | to Human  |
     +------------+           +-----------+
```

The BRIDGE framework uses four deterministic gates to analyze system execution logs and catch failures early :

- **Epistemic Gate ($G_1$):** Checks for scientific hallucinations and verifies that factual claims are grounded in literature.
    
- **Logical Gate ($G_2$):** Verifies the internal consistency of arguments and prevents contradictory statements.
    
- **Intent Gate ($G_3$):** Confirms that agents stay aligned with the primary research goal and prevents task drift.
    
- **Pragmatic Gate ($G_4$):** Evaluates formatting and ensures references are correctly integrated.
    

Dialogue runs that pass these gates are scored by a probabilistic judge across several behavioral traits. To convert these continuous trait scores into clear decisions, the system uses dual-threshold mapping. The thresholds are centered on empirical human prevalence ($P$) with a half-width based on interrater agreement ($\kappa$) :

$$T_{\text{upper}} = P + \frac{1-\kappa}{2}$$

$$T_{\text{lower}} = P - \frac{1-\kappa}{2}$$

This calibration step maps scores into three categories: "yes", "ambiguous", and "no". A dialogue run is approved only if all relevant traits are categorized as "yes". If any trait falls into "ambiguous" or "no", the framework halts execution and escalates the run for human review, protecting the integrity of the downstream proposal.

|**Behavioral Trait**|**Operational Definition**|**Evaluation Metric**|**Deterministic Gate Check**|**Remediation Action**|
|---|---|---|---|---|
|**Cognitive Support**|The system's ability to help the researcher think through complex problems during scoping.|Proportion of clarifying questions that target parameters in the scoping session.|**Intent Gate ($G_3$):** Verifies that the questions remain focused on clarifying the initial prompt.|Re-initialize scoping prompts with a narrower focus.|
|**Epistemic Honesty**|Accurately representing literature data without exaggerating or inventing claims.|Citation-to-text correlation scoring and reference check success rate.|**Epistemic Gate ($G_1$):** Confirms that all factual claims are grounded in source literature.|Halt the run, clear the context cache, and re-run literature retrieval.|
|**Strategic Adaptability**|The Supervisor's capacity to adjust execution plans when encountering dead ends.|Sub-task retry rate and routing accuracy when tools return errors.|**Logical Gate ($G_2$):** Confirms that alternative execution paths remain logically consistent.|Restart the planning loop and allocate additional test-time compute.|
|**Divergent Curiosity**|Generating a diverse set of hypotheses during early-stage ideation.|Topological distance metrics and cluster distribution across the proximity graph.|**Logical Gate ($G_2$):** Verifies that proposed hypotheses are distinct and non-redundant.|Adjust generation parameters to increase output diversity.|
|**Pragmatic Integrity**|Delivering well-formatted, complete, and actionable final proposals.|Section completeness checks and citation resolution success rates.|**Pragmatic Gate ($G_4$):** Confirms that proposals contain all required sections and citations.|Re-run the synthesis step using the structured output template.|

## Scientific Novelty and Plausibility Benchmark: Matter to Mechanism (M2M)

Evaluating scientific proposals requires measuring their structural soundness and scientific plausibility alongside their behavioral fidelity. Standard text-similarity metrics often fail to capture the difference between a superficially polished draft and a scientifically valid proposal.

To address this, the system incorporates the Matter to Mechanism (M2M) evaluation framework, which contains 2,645 expert-curated instances. M2M evaluates how effectively the platform moves from a stated scientific problem to a plausible, mechanistically grounded solution along six key dimensions :

### 1. Logical Chain Fidelity

Measures how logically the proposal connects the initial problem to the proposed solution. The system verifies these arguments by checking them against historical datasets and biological models.

### 2. Problem Alignment

Confirms the proposed intervention directly addresses the specific failure mode. These matches are evaluated by comparing proposed targets against disease and materials databases.

### 3. Mechanistic Specificity

Evaluates whether the proposal defines specific physical, chemical, or biological interactions. The system verifies target details by cross-referencing them with UniProt and ChEMBL records.

### 4. Scientific Novelty

Determines if the proposal introduces genuinely new hypotheses or original drug repurposing targets. This is verified by checking the suggestions against published literature databases.

### 5. Intervention Plausibility

Assesses whether the proposed protocols can be realistically executed in a laboratory. This is validated by comparing proposed setups against established in vitro assays and human organoid studies.

### 6. Problem Decomposition Quality

Evaluates how effectively the Supervisor breaks down the high-level goal into clear, testable hypotheses. This is verified by analyzing the execution graph of the planning agent.

Importantly, M2M uses a reference-free evaluation model for hypothesis matching. Because complex scientific problems often admit multiple plausible solutions, the system does not grade proposals based on exact text matches with a single reference. Instead, generated outputs are scored primarily against the input problem fields and their own internal scientific structure, allowing the system to fairly evaluate open-ended and highly novel hypotheses.

## Implementation Golden Prompts and System Prompts Library

To guide AI coding agents in implementing the system with 1:1 fidelity, this library provides production-ready system prompts for key agents in the workflow:

### Intake/Interview Agent Prompt

This prompt configures the agent to lead scoping sessions, extract research parameters, and clarify objectives.

XML

```
<system_prompt>
You are the Intake/Interview Agent of the AI Co-Scientist system. Your role is to guide the user through scoping sessions to refine vague natural language prompts into precise, actionable research specifications.
Execute your workflow using the following steps:
1. Parse the user's initial prompt and identify missing parameters (such as therapeutic modality, target databases, safety constraints, and model preferences).[7, 12]
2. Lead a multi-turn conversation, asking clear, singular clarifying questions to resolve these details.
3. Maintain a professional, collaborative tone, helping the user structure their goals without overwhelming them with options.
4. Output your findings as a structured JSON block containing extracted parameters and scoping status.


Your output must be a valid JSON block structured as follows:
{
  "clarifying_question": "Your next singular question, or null if scoping is complete",
  "parameters_extracted": {
    "modality": "e.g., small_molecule, gene_therapy, antibody, or null",
    "target_databases":,
    "safety_constraints": ["e.g., biosecurity, ethics, or empty"],
    "run_profile": "e.g., standard, advanced, or null"
  },
  "is_complete": true/false
}
</system_prompt>
```

### Ranking/Debate Agent Prompt

This prompt configures the agent to lead pairwise scientific debates, judge candidates, and output structured Elo results.

XML

```
<system_prompt>
You are the Ranking/Debate Agent of the AI Co-Scientist system. Your role is to run pairwise debates between candidate hypotheses to identify the strongest research directions.
Execute your workflow using the following steps:
1. Evaluate the two provided hypotheses (Hypothesis A and Hypothesis B) against the target scientific problem.
2. Assess each hypothesis on its logical consistency, biological or physical plausibility, and scientific novelty.
3. Check both candidates against retrieved literature references to verify they are grounded in existing data.
4. Adjudicate the debate and declare a winner, providing a clear, evidence-based explanation for your decision.


Your output must be a valid JSON block structured as follows:
{
  "winning_id": "ID of the winning hypothesis",
  "losing_id": "ID of the losing hypothesis",
  "debate_rationale": "A detailed explanation of why the winning hypothesis was selected, citing specific literature and mechanisms",
  "elo_update": {
    "k_factor": 32,
    "score_outcome": 1.0
  }
}
</system_prompt>
```

### Citation Verification Agent Prompt

This prompt configures the agent to verify factual claims and resolve entity mappings against external databases.

XML

```
<system_prompt>
You are the Citation Verification Agent of the AI Co-Scientist system. Your role is to fact-check generated claims and verify that references to external databases are correct.
Execute your workflow using the following steps:
1. Parse the provided hypothesis text and identify all factual claims and database entity references.
2. Query target databases (such as ChEMBL, UniProt, and AlphaFold) to verify the entity mappings.
3. Check the retrieved records to confirm that the proposed pathways and interactions are physically and pharmacologically sound.
4. Output your verification findings as a structured JSON block, mapping each claim to its database verification status.


Your output must be a valid JSON block structured as follows:
{
  "verified_claims":
    }
  ],
  "is_safe_to_publish": true/false
}
</system_prompt>
```

## Empirical Verification and Regression Test Suite

To verify that the clone matches the target system's performance, it must be evaluated against a suite of empirical test cases. This test suite uses four distinct validation scenarios based on documented achievements of the target platform: bacterial gene transfer mechanism discovery , target discovery for liver fibrosis , therapeutic pathway identification for dry macular degeneration , and antimicrobial resistance mechanism modeling.

|**Reference Case ID**|**Primary Research Objective**|**Target Databases & Tools**|**Expected Intermediate State Validation Points**|**Expected Final JSON Output Structure**|**Latency & Token Limits**|**Pass/Fail Criteria**|
|---|---|---|---|---|---|---|
|**REG-CF-PICI-01**|Identify the mechanism behind capsid-forming phage-inducible chromosomal islands (cf-PICIs) bacterial DNA transfer.|PubMed API, UniProt Database, AlphaFold Database.|**ST-04:** Verifies that retrieved documents contain genomic studies on cf-PICIs.<br><br>  <br><br>**ST-06:** Confirms the debate tournament places the correct transfer mechanism at the top of the Elo rankings.|`{ "correct_mechanism_ranked_first": "boolean", "supporting_citations": ["string"], "top_hypothesis_id": "string", "elo_score": "float" }`|Latency: $< 900$s<br><br>  <br><br>Tokens: $< 3.5$M|Pass if the correct transfer mechanism is ranked as the top hypothesis and supported by verified citations.|
|**REG-FIB-02**|Discover novel epigenetic target candidates to reduce fibrogenesis and promote regeneration in liver fibrosis.|ChEMBL API, PubMed API, SciPy clustering libraries.|**ST-05:** Confirms that candidate targets are clustered correctly based on their biological pathways.<br><br>  <br><br>**ST-07:** Verifies that the proposed target is supported by in vitro assay data.|`{ "proposed_targets": [{ "name": "string", "uniprot_id": "string", "mechanism_of_action": "string" }], "anti_fibrotic_validation_score": "float" }`|Latency: $< 1200$s<br><br>  <br><br>Tokens: $< 5.0$M|Pass if the proposed target candidates are supported by verified binding affinities and match clinical datasets.|
|**REG-MAC-03**|Identify potential small-molecule drug repurposing targets and therapeutic pathways for dry macular degeneration.|ChEMBL API, PubMed API, vector similarity search engines.|**ST-05:** Verifies the Proximity Agent successfully prunes duplicate hypotheses from the search space.<br><br>  <br><br>**ST-07:** Confirms the proposal synthesizes findings into structured clinical trial designs.|`{ "repurposed_drug_candidates": [{ "chembl_id": "string", "original_indication": "string", "target_pathway": "string" }], "clinical_trial_protocols": }`|Latency: $< 800$s<br><br>  <br><br>Tokens: $< 3.0$M|Pass if the final proposal includes valid, clickable citations and matches clinical design guidelines.|
|**REG-AMR-04**|Formulate intervention strategies to prevent antimicrobial resistance in ESKAPE pathogens.|PubMed API, UniProt Database, AlphaFold Database.|**ST-04:** Confirms the retrieval module accesses current antimicrobial resistance literature.<br><br>  <br><br>**ST-07:** Verifies the Safety Agent checks proposals for potential dual-use concerns.|`{ "pathogen_targeted": "string", "resistance_mechanism_addressed": "string", "proposed_compounds": ["string"], "is_safe_to_publish": "boolean" }`|Latency: $< 1000$s<br><br>  <br><br>Tokens: $< 4.0$M|Pass if the proposed compound mechanisms are backed by verified database matches and pass all safety checks.|

## Quantitative Mismatch Triaging and Optimization Architecture

To guide developer iterations, the evaluation framework implements a quantitative approach to detecting and addressing behavioral gaps between the clone and the target system. When comparing the clone's performance, differences are measured across three main dimensions: structural workflow alignment, behavioral fidelity, and scientific output quality.

To capture these differences in a single metric, the system defines a Quantitative Mismatch Index ($QMI$) :

$$QMI = \sum_{c \in C} w_c \cdot (1 - S_c)^2$$

where $C$ represents the set of evaluation categories, $w_c$ is the weight assigned to each category's importance, and $S_c \in $ is the similarity score for that category (where $1$ represents a perfect match and $0$ represents complete divergence). The category weights are distributed based on developmental priority, with scientific accuracy and behavioral safety receiving the highest weight:

- **Scientific and Logical Trace Accuracy ($w_{\text{logic}} = 0.35$):** Measures the logical flow and correctness of the generated arguments.
    
- **Behavioral Fidelity ($w_{\text{behavior}} = 0.30$):** Measures how closely agent interactions and dialogue patterns match the target design.
    
- **Structural Output Matching ($w_{\text{structure}} = 0.15$):** Evaluates proposal formatting, section coverage, and citation structure.
    
- **Database and Tool Integration ($w_{\text{tools}} = 0.12$):** Assesses the correctness of database queries and external tool calls.
    
- **System Performance and Latency ($w_{\text{perf}} = 0.08$):** Monitors execution speed and token usage.
    

Using the computed $QMI$ and individual category scores, identified differences are triaged into a priority queue. This ensures engineering efforts are focused on critical architectural and logical fixes before addressing minor interface issues.

|**Mismatch Category**|**Trigger Conditions**|**System Impact Score**|**Triage Class**|**Remediation Protocol**|
|---|---|---|---|---|
|**Epistemic Divergence**|The Citation Verification Agent fails to verify generated claims or links to broken database records.|`0.95`|**Critical**|Halt deployment, update retrieval filtering, and adjust prompt constraints for stricter verification.|
|**Logic Mismatch**|The Reflection Agent fails to identify logical flaws in candidates during peer-review stages.|`0.85`|**Critical**|Adjust model temperature and update the peer-review checklists for stricter evaluation.|
|**Orchestration Drift**|The Supervisor fails to correctly transition between states, leading to loop errors or stalled queues.|`0.75`|**Major**|Re-evaluate the Supervisor's planning rules and adjust pairwise debate parameters.|
|**Clustering Degradation**|The Proximity Agent fails to deduplicate redundant hypotheses, leading to search inefficiencies.|`0.65`|**Major**|Update the embedding model configurations and adjust the cosine distance threshold.|
|**Formatting Incompleteness**|The final proposal draft is missing required sections, standard aims, or interactive citations.|`0.55`|**Moderate**|Update the Meta-review Agent's template configurations and verify output parsers.|
|**Performance Lag**|Run latencies exceed targets by more than $20\%$ or token consumption spikes unexpectedly.|`0.45`|**Minor**|Optimize token usage, implement prompt caching, and refine task routing.|

## System Verification and Deployment Protocols

Before deploying the platform, the clone must complete a multi-stage validation protocol to confirm it matches the target system's performance, stability, and safety standards.

First, the system runs the automated regression suite. This ensures the multi-agent network executes the correct sequence of states without getting stuck in infinite loops or experiencing agent-to-agent communication failures. The execution traces are passed through the BRIDGE safety and validation gates to confirm that all generated content is grounded in literature and matches the specified research targets.

Second, the Elo-based debate system is validated using benchmark datasets. The system runs a tournament of candidate solutions and checks if the resulting Elo ratings correlate with known ground-truth rankings. This step ensures the Ranking and Reflection agents can accurately evaluate hypothesis quality and prioritize the most promising research paths.

Third, a blind evaluation is conducted on a subset of generated proposals. Domain experts grade the proposals on scientific novelty, logical soundness, and experimental plausibility. The clone meets deployment standards only when these expert ratings show no statistically significant difference from the performance of the target platform.

Once these validation stages are complete, the system is cleared for deployment. This structured testing process ensures the platform functions as a reliable, high-fidelity research partner, delivering logically sound and scientifically useful proposals.
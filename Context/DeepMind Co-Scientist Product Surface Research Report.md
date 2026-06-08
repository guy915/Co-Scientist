# Google DeepMind AI Co-Scientist / Hypothesis Generation: Product Surface Research Report

## Executive Summary

This report provides a detailed reconstruction of the public product surface for Google DeepMind's AI Co-Scientist[1](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/) (also marketed as Hypothesis Generation[2](https://labs.google.com/science)), a multi-agent AI system built on Gemini 2.0[3](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/) designed to accelerate scientific discovery by generating, debating, and evolving research hypotheses. The system is currently available through an Early Access Program[4](https://docs.google.com/forms/d/e/1FAIpQLSdvw_8IPrc8O7ZM8FKF46i8BnOYMeSeyLeBNiuk_yGWIlnxYA/viewform) via Google Labs[5](https://labs.google.com/science/hypothesis-generation).

---

## 1. Research Goal Setup: How Users Start

### Initial Access Workflow

Users begin by expressing interest through a sign-up form at labs.google.com/science[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en). Upon selection, they receive email notification with access instructions. The tool requires desktop access via Google Chrome[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en).

### Research Goal Input

The primary interface is **natural language-based**. Users initiate research by entering their research challenge or hypothesis in a prompt box. The system is designed as a "scientist-in-the-loop" collaborative paradigm, where humans guide the research direction through intuitive language interaction Google Research Blog[3](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/).

The goal specification follows this pattern:

1. User enters a high-level research goal in natural language (e.g., "How would you approach epigenomic aspects of liver fibrosis and what drugs could you use to treat it?") DeepMind Blog[1](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/)
2. The Supervisor agent[7](https://storage.googleapis.com/coscientist_paper/ai_coscientist.pdf) parses the assigned goal into a research plan configuration
3. Resources are allocated to specific tasks for execution Google Research Blog[3](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/)

---

## 2. Interview-Style Refinement

### Conversational Interview Flow

After initial goal entry, the system engages users in a **conversational interview** with the Hypothesis Generation agent to define research goal elements Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en). This interactive refinement process serves multiple purposes:

- **Goal Clarification**: The system helps scientists refine their research goals at any time arXiv Paper[8](https://arxiv.org/abs/2502.18864)
- **Constraint Specification**: Users can inform the system of desirable attributes for hypotheses and constraints the outputs should satisfy arXiv Paper[8](https://arxiv.org/abs/2502.18864)
- **Feedback Integration**: Scientists can provide their own seed ideas for exploration or feedback on generated outputs in natural language Google Research Blog[3](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/)

### Natural Language Interface

The interface is designed to function "just like talking to a colleague" Medium Implementation Article[9](https://medium.com/@icarusabiding/how-i-implemented-googles-groundbreaking-co-research-at-home-and-then-some-3aa8a510887b). Key interaction patterns include:

- Specifying research goals in simple natural language
- Providing feedback on generated hypotheses
- Guiding the system's progress through conversational turns
- Iteratively refining research direction based on outputs Google Research Blog[3](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/)

---

## 3. Run Configuration: Standard vs Advanced

### Run Type Selection

Users can configure their research runs through a configuration panel. At the top right of the research goal interface, users click "Configure Run" to select their run type Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en):

|Run Type|Purpose|Characteristics|
|---|---|---|
|**Standard Run**|Testing and refining research goals|Quicker results; optimized for speed|
|**Advanced Run**|Comprehensive analysis for breakthroughs|More in-depth analysis; more nuanced or diverse suggestions Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en)|

### Advanced Settings (Open-Source Implementations)

Open-source implementations reveal additional configuration parameters that may be available in the full system:

- **LLM Model Selection**: Choice of underlying models (e.g., Gemini 2.0 Pro, Claude, GPT variants) GitHub - open-coscientist-agents[10](https://github.com/conradry/open-coscientist-agents)
- **Number of Hypotheses**: Configuration for how many hypotheses to generate (typically 20-30 in tournament) GitHub - open-coscientist-agents[10](https://github.com/conradry/open-coscientist-agents)
- **Temperature Settings**: Control over creativity vs. determinism GitHub - LLNL[11](https://github.com/llnl/open-ai-co-scientist)
- **Test-Time Compute Scaling**: Ability to scale computational resources for deeper reasoning arXiv Paper[8](https://arxiv.org/abs/2502.18864)

---

## 4. How Runs Behave

### Multi-Agent Execution Framework

Once configured, the system operates through an **asynchronous task execution framework** managed by the Supervisor agent[7](https://storage.googleapis.com/coscientist_paper/ai_coscientist.pdf). The run behavior follows the "Generate, Debate, Evolve" framework Medium Implementation Article[9](https://medium.com/@icarusabiding/how-i-implemented-googles-groundbreaking-co-research-at-home-and-then-some-3aa8a510887b):

#### Phase 1: Generation

- **Generation Agent** initiates research by exploring literature using web search
- Synthesizes findings and formulates initial hypotheses
- Iteratively extends focus areas based on research goal Google Cloud Docs[12](https://docs.cloud.google.com/gemini/enterprise/docs/co-scientist-and-alphaevolve)

#### Phase 2: Reflection

- **Reflection Agent** acts as a peer reviewer
- Examines correctness, quality, safety, and novelty of hypotheses
- Performs causal analysis and disproof analysis Learn Prompting[13](https://learnprompting.org/blog/google-ai-co-scientist-prompts)

#### Phase 3: Ranking (Tournament)

- **Ranking Agent** orchestrates an "idea tournament"
- Uses Elo-based tournament system[14](https://en.wikipedia.org/wiki/Elo_rating_system) for pairwise comparisons
- Top-ranked hypotheses undergo multi-turn scientific debates
- Lower-ranked hypotheses receive single-turn comparisons DeepMind Blog[1](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/)

#### Phase 4: Evolution

- **Evolution Agent** refines top-ranked hypotheses
- Combines, simplifies, or extends hypotheses based on tournament feedback
- Grounds hypotheses in literature Google Cloud Docs[12](https://docs.cloud.google.com/gemini/enterprise/docs/co-scientist-and-alphaevolve)

#### Phase 5: Meta-Review

- **Meta-Review Agent** synthesizes insights from all reviews and debates
- Identifies recurring patterns to optimize other agents
- Generates final research proposals arXiv Paper[8](https://arxiv.org/abs/2502.18864)

#### Phase 6: Proximity Analysis

- **Proximity Agent** computes similarity between hypotheses
- Enables clustering and de-duplication
- Ensures diversity in the hypothesis space arXiv Paper[8](https://arxiv.org/abs/2502.18864)

### Runtime Characteristics

- **Duration**: Can run for days or weeks, testing thousands of hypotheses and reading tens of thousands of papers YouTube Demo[15](https://www.youtube.com/watch?v=aSY_vFFmkW0)
- **Scaling**: Uses test-time compute scaling to iteratively improve outputs arXiv Paper[8](https://arxiv.org/abs/2502.18864)
- **Asynchronous Execution**: Agents operate in parallel, exploring multiple avenues simultaneously DeepMind Blog[1](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/)

---

## 5. Generated Reports: Sections and Structure

The system produces a **Goal Report** accessible through a dedicated report page. The report is organized into four main tabs Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en):

### Report Structure

```css
┌─────────────────────────────────────────────────────────────┐
│                    GOAL REPORT                              │
├─────────────┬─────────────┬─────────────┬───────────────────┤
│   IDEAS     │ KNOWLEDGE   │   SUMMARY   │  RUN SPECIFICATIONS│
│  (Leaderboard) │   BASE      │             │                   │
└─────────────┴─────────────┴─────────────┴───────────────────┘
```

#### Tab 1: Ideas (Leaderboard)

- **Full leaderboard** of generated research proposals
- Ranked display of hypotheses from the tournament
- Each hypothesis includes supporting rationale Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en)

#### Tab 2: Knowledge Base

- **Centralized repository** of in-depth technical documentation
- Research-backed insights and detailed data
- Literature review synthesis Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en)

#### Tab 3: Summary

- **Synthesized overview** of the entire research effort
- High-level synthesis of findings and recommendations Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en)

#### Tab 4: Run Specifications

- **Details about parameters and constraints** that defined the research run
- Configuration used for the analysis Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en)

### Report Content Elements

Based on the arXiv paper[8](https://arxiv.org/abs/2502.18864) and open-source implementations, reports typically include:

- **Research Overview**: Synthesized findings from all reviews and debates
    
- **Hypothesis Details**: For each hypothesis:
    
    - Scientific validity assessment
    - Novelty evaluation
    - Testability assessment
    - Impact potential
    - Supporting literature references GitHub - Swarm Corporation[16](https://github.com/The-Swarm-Corporation/AI-CoScientist)
- **Literature References**: Integration with arXiv[17](https://arxiv.org/), PubMed[18](https://pubmed.ncbi.nlm.nih.gov/), and web search results GitHub - LLNL[11](https://github.com/llnl/open-ai-co-scientist)
    
- **Meta-Review**: Strategic guidance and synthesis of cross-hypothesis insights arXiv Paper[8](https://arxiv.org/abs/2502.18864)
    

---

## 6. Ranked Ideas: How Hypotheses Are Presented

### Elo-Based Tournament Display

Ideas are presented through a **ranked leaderboard** system based on the Elo rating system[14](https://en.wikipedia.org/wiki/Elo_rating_system) DeepMind Blog[1](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/):

#### Ranking Mechanics

1. **Pairwise Comparisons**: Hypotheses are compared head-to-head in tournament matches
2. **Scientific Debates**: Top-ranked hypotheses undergo multi-turn simulated scientific debates
3. **Elo Rating Updates**: Winners gain points; losers lose points arXiv Paper[8](https://arxiv.org/abs/2502.18864)

#### Ranking Agent Priorities

The Ranking Agent[7](https://storage.googleapis.com/coscientist_paper/ai_coscientist.pdf) prioritizes tournament matches based on:

- **Proximity**: Hypotheses are more likely to be compared with similar ones (using the Proximity agent's graph)
- **Novelty**: Newer hypotheses are prioritized for participation
- **Performance**: Top-ranking hypotheses receive more tournament matches arXiv Paper[8](https://arxiv.org/abs/2502.18864)

### Leaderboard Features

Open-source implementations reveal potential UI elements for the leaderboard:

- **Tournament Viewer**: Analysis of competitive dynamics between ideas GitHub - open-coscientist-agents[10](https://github.com/conradry/open-coscientist-agents)
- **Debate Transcripts**: Full records of why one hypothesis outperforms another GitHub - open-coscientist-agents[10](https://github.com/conradry/open-coscientist-agents)
- **Win-Loss Statistics**: Track performance across multiple evaluation rounds GitHub - open-coscientist-agents[10](https://github.com/conradry/open-coscientist-agents)
- **Hypothesis Evolution View**: See how ideas improve through iterative refinement GitHub - open-coscientist-agents[10](https://github.com/conradry/open-coscientist-agents)

### Evaluation Criteria

According to the Learn Prompting article[13](https://learnprompting.org/blog/google-ai-co-scientist-prompts), hypotheses are evaluated on:

- **Scientific validity**: Correctness and soundness
- **Novelty**: Originality and innovation
- **Testability**: Feasibility of experimental validation
- **Impact**: Potential significance of findings

---

## 7. Knowledge Base: How Evidence and Knowledge Are Exposed

### Literature Integration

The system exposes knowledge through multiple channels:

#### Integrated Data Sources

- **Web Search**: General literature search capabilities Google Research Blog[3](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/)
- **Specialized Databases**: Integration with ChEMBL[19](https://www.ebi.ac.uk/chembl/) and UniProt[20](https://www.uniprot.org/) for biomedical research DeepMind Blog[1](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/)
- **arXiv**: Automated literature search for related papers GitHub - LLNL[11](https://github.com/llnl/open-ai-co-scientist)

#### Knowledge Graph (Open-Source Implementations)

Some implementations use a **Knowledge Graph** (e.g., Neo4j[21](https://neo4j.com/)) to:

- Store and link scientific concepts
- Enable semantic searching across domains
- Maintain up-to-date research knowledge Medium Implementation Article[9](https://medium.com/@icarusabiding/how-i-implemented-googles-groundbreaking-co-research-at-home-and-then-some-3aa8a510887b)

#### Knowledge Base Tab Features

The Knowledge Base tab serves as:

- **Centralized repository** of in-depth technical documentation
- **Research-backed insights** with detailed data
- **Literature synthesis** connecting findings across sources Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en)

---

## 8. How Weak or Non-Viable Ideas Are Handled

### Continuous Refinement Process

The system handles weak or non-viable ideas through an **iterative cycle of critique and refinement** rather than immediate rejection arXiv Paper[8](https://arxiv.org/abs/2502.18864):

#### Reflection Agent Critique

- The **Reflection Agent** performs deep verification and causal reasoning analysis
- Identifies weaknesses, contradictions, and logical flaws Learn Prompting[13](https://learnprompting.org/blog/google-ai-co-scientist-prompts)
- Classifies hypotheses with ratings like: "already explained," "other explanations more likely," "missing piece," "neutral," or "disproved" Learn Prompting[13](https://learnprompting.org/blog/google-ai-co-scientist-prompts)

#### Tournament-Based Filtering

- **Lower-ranked hypotheses** receive fewer resources (single-turn comparisons vs. multi-turn debates for top hypotheses) arXiv Paper[8](https://arxiv.org/abs/2502.18864)
- **Proximity Agent** clusters similar ideas for de-duplication arXiv Paper[8](https://arxiv.org/abs/2502.18864)
- Ideas that consistently lose tournament matches receive lower Elo ratings and are deprioritized

#### Evolution Agent Improvement

- The **Evolution Agent** attempts to refine and improve hypotheses rather than discard them
- Combines elements of top-performing hypotheses
- Fills in reasoning gaps based on deeper literature review Google Cloud Docs[12](https://docs.cloud.google.com/gemini/enterprise/docs/co-scientist-and-alphaevolve)

### Quality Assurance

- **Expert-in-the-loop**: Domain experts guide and validate outputs, ensuring alignment with scientific priorities Google Research Blog[3](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/)
- **Wet-lab validation**: In the validation studies, hypotheses were tested through actual experiments (e.g., drug repurposing for acute myeloid leukemia) arXiv Paper[8](https://arxiv.org/abs/2502.18864)

---

## 9. Sharing, Export, and Continuation Workflows

### Export Features

The system provides multiple export options:

#### NotebookLM Integration

- Users can **export results directly to NotebookLM[22](https://notebooklm.google/)** for further analysis and note-taking Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en)

#### Download Options

- **Public sharing** of goal reports
- **Local downloading** of goal reports Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en)

#### Open-Source Export Formats

Open-source implementations provide additional export capabilities:

- **JSON/CSV export** for generated hypotheses GitHub - Swarm Corporation[16](https://github.com/The-Swarm-Corporation/AI-CoScientist)
- **Timestamped logging** of results to files GitHub - LLNL[11](https://github.com/llnl/open-ai-co-scientist)
- **State persistence** for saving and resuming research workflows GitHub - Swarm Corporation[16](https://github.com/The-Swarm-Corporation/AI-CoScientist)

### Follow-up Interaction Workflow

The system supports iterative research through:

#### Iteration and Refinement

1. **Review Phase**: Users examine the Ideas, Knowledge Base, and Summary tabs Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en)
2. **Feedback Loop**: Users provide natural language feedback to guide the system's progress arXiv Paper[8](https://arxiv.org/abs/2502.18864)
3. **Additional Cycles**: Users can run additional cycles to refine hypotheses GitHub - LLNL[11](https://github.com/llnl/open-ai-co-scientist)
4. **Goal Refinement**: Users can refine the research goal at any time based on findings arXiv Paper[8](https://arxiv.org/abs/2502.18864)

#### Continuation Patterns

- **Run Specifications Review**: Users can review the parameters and constraints used for previous runs Google Help[6](https://support.google.com/hypothesis-generation/answer/17106281?hl=en)
- **State Management**: The system uses persistent context memory to store and retrieve states, enabling long-term research projects arXiv Paper[8](https://arxiv.org/abs/2502.18864)

---

## 10. Product Model Summary for Implementation

### Core User Journey

```css
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   SIGN UP       │────▶│   GOAL SETUP     │────▶│   INTERVIEW     │
│  (labs.google)  │     │  (Prompt Input)  │     │   (Refinement)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                           │
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  EXPORT/SHARE   │◀────│  REPORT REVIEW   │◀────│   RUN EXECUTION │
│  (NotebookLM,   │     │  (4-Tab Report)  │     │  (Standard/Adv) │
│   Download)     │     │                  │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │
┌─────────────────┐
│  FOLLOW-UP      │
│  (Iteration,    │
│   New Goals)    │
└─────────────────┘
```

### Key Interface Principles

1. **Natural Language First**: The primary interface is conversational, not form-based Medium Implementation Article[9](https://medium.com/@icarusabiding/how-i-implemented-googles-groundbreaking-co-research-at-home-and-then-some-3aa8a510887b)
    
2. **Scientist-in-the-Loop**: Human experts guide the research direction and validate outputs Google Research Blog[3](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/)
    
3. **Transparent Process**: Users can see the tournament rankings, debate transcripts, and evolution of ideas GitHub - open-coscientist-agents[10](https://github.com/conradry/open-coscientist-agents)
    
4. **Iterative Refinement**: The system is designed for multiple cycles, not one-shot generation arXiv Paper[8](https://arxiv.org/abs/2502.18864)
    

### Technical Architecture for Cloning

Based on open-source implementations, a clone should implement:

#### Multi-Agent System

- **Supervisor Agent**: Workflow orchestration and planning
- **Generation Agent**: Hypothesis creation
- **Reflection Agent**: Peer review and critique
- **Ranking Agent**: Elo-based tournament management
- **Evolution Agent**: Hypothesis refinement
- **Proximity Agent**: Similarity analysis and diversity control
- **Meta-Review Agent**: Insight synthesis GitHub - Swarm Corporation[16](https://github.com/The-Swarm-Corporation/AI-CoScientist)

#### Core Workflow

1. Generation Phase → 2. Reflection Phase → 3. Ranking Phase → 4. Tournament Phase → 5. Meta-Review Phase → 6. Evolution Phase → 7. Proximity Analysis → 8. Iteration GitHub - Swarm Corporation[16](https://github.com/The-Swarm-Corporation/AI-CoScientist)

#### Key Features to Implement

- Elo rating system for hypothesis ranking
- Pairwise comparison with simulated debates
- Knowledge base integration (arXiv, web search)
- Report generation with 4-tab structure
- Export to NotebookLM and local download
- Natural language feedback loop

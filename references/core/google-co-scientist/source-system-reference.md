# 01 — Source System Reference: Google DeepMind's AI Co-Scientist

> **Purpose of this document.** This is the *canonical ground-truth reference* for the clone. It consolidates the primary source materials — the arXiv/Nature paper *"Towards an AI co-scientist"* (Gottweis et al., arXiv 2502.18864) and the companion blog/product writeup. Everything in the rest of the spec corpus is an interpretation or implementation of what is described here. When any downstream document conflicts with this one **on a matter of what the original system actually does**, this document wins.
>
> Consolidates: `Towards_an_AI_co-scientist.md`, `Accelerating_scientific_discovery_with_Co-Scientist.md`.

---

## 1. What the system is

The AI co-scientist is a **compound, multi-agent AI system built on Gemini 2.0**, designed to mirror the reasoning process underpinning the scientific method. Given a research goal specified in natural language, it searches and reasons over relevant literature, synthesizes prior work, and proposes **novel, original research hypotheses and experimental protocols** for downstream validation. It grounds recommendations by citing literature and explaining its reasoning.

Three framing points the paper is emphatic about:

- It is **not** an attempt to fully automate science. It is purpose-built for a **"scientist-in-the-loop"** collaborative paradigm — augmenting expert hypothesis generation, not replacing it.
- It goes **beyond literature summarization and "deep research" tools**. The distinguishing goal is *generating new knowledge* (novel hypotheses grounded in prior literature), not synthesizing existing information.
- It works through a **significant scaling of the test-time compute paradigm** — iteratively reasoning, evolving, and improving outputs as it gathers more knowledge. The system is **model-agnostic and portable**; Gemini 2.0 is the foundation used, but the framework is expected to benefit from future frontier-model improvements.

### Default output criteria

Every hypothesis/proposal the system generates must, by default, satisfy:

1. **Alignment** — precisely matches the research goal, preferences, and constraints.
2. **Plausibility** — free of readily apparent flaws; any contradiction with prior literature must be explicitly stated and justified.
3. **Novelty** — genuinely novel, grounded in prior literature rather than restating it.
4. **Testability** — amenable to empirical validation within the scientist's stated constraints.
5. **Safety** — controlled to prevent enabling unsafe, unethical, or harmful research.

Beyond these defaults, the system is configurable with additional criteria, preferences, constraints, and output formats.

---

## 2. The four high-level components

1. **Natural language interface.** Scientists define the research goal, refine it at any time, give feedback on hypotheses (including their own), and steer the system — all in natural language.
2. **Asynchronous task framework.** Specialized agents run as worker processes in an asynchronous, continuous, configurable task execution framework. A dedicated **Supervisor agent** manages the worker task queue, assigns agents to processes, and allocates resources. This is what enables flexible test-time-compute scaling.
3. **Specialized agents.** The scientific-reasoning process is decomposed into sub-tasks, each handled by an agent with a customized instruction prompt, coordinated by the Supervisor.
4. **Context memory.** A persistent memory stores agent/system state across the long-horizon computation, enabling iterative reasoning and easy restart after failure.

---

## 3. From research goal to research plan configuration

The research goal is the entry point. It can range from a one-line statement to extensive documents (tens of thousands of tokens, or hundreds of prior-publication PDFs), and can carry constraints, attributes, and preferences specific to the scientist's lab or field.

The system **parses the goal into a research plan configuration** capturing desired proposal preferences, attributes, and constraints — e.g. whether to propose *only* novel hypotheses, and the evaluation criteria (novelty, feasibility, etc.) used during the system's auto-evaluation phases. These criteria are all customizable per goal.

Based on this configuration, the Supervisor creates a task queue and begins orchestrating agents. The system runs continuously and asynchronously. Periodically the Supervisor computes a **suite of summary statistics** reflecting system state and progress; these inform resource-allocation decisions and the determination of whether a terminal state has been reached. State is periodically written to context memory, used as feedback in subsequent rounds, and enables restart after failure.

---

## 4. The specialized agents (paper-canonical roster)

The paper names **seven** core agents (Supervisor + six specialists). The clone documents expand this to twelve by making several implicit roles explicit (intake, literature, citation, safety, report) — see file `04`. The seven canonical roles:

### Supervisor
Parses the goal into a research plan configuration, assigns weights/resources to each specialized agent, and queues them as worker processes according to those weights. It periodically computes summary statistics (number of hypotheses generated, number requiring review, tournament progress, and the **relative effectiveness of generation vs. evolution**) and uses them to orchestrate subsequent operations by *strategically weighting and sampling* the specialized agents. The seamless orchestration of agents is what enables valid, novel, testable hypotheses.

### Generation agent
Initiates the process: generates initial focus areas, iteratively extends them, and produces an initial set of hypotheses/proposals. **Four techniques:**

1. **Literature exploration via web search** — iteratively searches, retrieves, reads, summarizes prior work, then builds on the summary to generate novel hypotheses.
2. **Simulated scientific debates** — self-critique and self-play among simulated experts, typically multiple turns, ending in a refined hypothesis.
3. **Iterative assumptions identification** — identifies testable intermediate assumptions via conditional reasoning hops, aggregated into complete hypotheses.
4. **Research expansion** — reviews existing hypotheses + the Meta-review's research overview/feedback to find unexplored regions of the hypothesis space.

It also summarizes and categorizes each hypothesis so scientists can grasp the core idea quickly.

### Reflection agent
Simulates a scientific peer reviewer; filters inaccurate and (when stipulated) non-novel hypotheses; provides feedback to all other agents. **Six review types:**

1. **Initial review** — correctness, quality, novelty, preliminary safety. **No external tools.** Quickly discards flawed/non-novel/unsuitable hypotheses.
2. **Full review** — if initial passes; uses web search to find relevant articles for grounded reasoning. Scrutinizes assumptions and reasoning (correctness/quality); summarizes known aspects then judges novelty against literature.
3. **Deep verification review** — decomposes the hypothesis into constituent assumptions, each broken into fundamental sub-assumptions, **decontextualized and independently evaluated** for correctness. Detects subtle errors (reasoning flaws, inaccurate protocols). An identified error doesn't necessarily invalidate the hypothesis; the agent assesses whether the incorrect assumption is *fundamental*.
4. **Observation review** — checks whether the hypothesis can account for long-tail observations from prior experimental results; for each observation, assesses if the hypothesis is a *superior* explanation. Often completes with no important findings.
5. **Simulation review** — simulates the hypothesis step-wise (mechanism of action, or the proposed experiment) to surface failure scenarios. Built on the assumption that frontier LLMs have an internal world model.
6. **Recurrent / tournament review** — adapts full reviews based on the system's growing knowledge; analyzes reviewed hypotheses + tournament results to identify recurring issues and refine reviews.

Expert scientists can also contribute reviews to guide ranking and improvement.

### Ranking agent
Runs an **Elo-based tournament** to evaluate and rank all hypotheses, with supporting rationale. **Key invariants:**

- **Initial Elo rating = 1200** for every newly added hypothesis.
- Top-ranked hypotheses are compared via **multi-turn scientific debates**; lower-ranked hypotheses use **single-turn** pairwise comparisons. (Both end in a "which is better" decision.)
- Comparison criteria emphasize **novelty, correctness, testability**.
- Match prioritization: (1) hypotheses are more likely compared with *similar* ones (per the Proximity graph); (2) *newer* and *top-ranked* hypotheses are prioritized for matches.
- Elo is acknowledged as imperfect but a good proxy for relative ranking.

### Proximity agent
Asynchronously computes a **proximity graph** over hypotheses (accounting for the research goal), enabling clustering of similar ideas, de-duplication, and efficient exploration. It does not generate hypotheses; it helps the Ranking agent organize matches and lets scientists explore related concepts.

### Evolution agent
Continuously refines top-ranked hypotheses. **Strategies:**

- **Enhancement through grounding** — find weaknesses, generate search queries, retrieve/read articles, suggest improvements, fill reasoning gaps.
- **Coherence, practicality, feasibility improvements** — fix invalid assumptions; make hypotheses more practical/feasible.
- **Inspiration from existing hypotheses** — new hypotheses inspired by one or several top-ranked ones.
- **Combination** — directly combine the best aspects of several top hypotheses.
- **Simplification** — simplify for easier verification/testing.
- **Out-of-box thinking** — diverge from a subset of hypotheses to generate divergent ideas.

> **Critical invariant (§3.3.5):** *"The Evolution agent generates new hypotheses; it doesn't modify or replace existing ones."* Each new hypothesis must compete in the tournament. This protects top-ranked hypotheses from flawed "improvements."

### Meta-review agent
Operates on the tournament state. Three outputs:

1. **Meta-review critique** — synthesizes common patterns across all reviews and debates. This critique is **simply appended to every other agent's prompt in the next iteration** — the mechanism by which the system "continuously learns and improves… *without back-propagation techniques* (e.g. fine-tuning or RL)." The Generation agent uses it selectively to avoid overfitting to critiques. *(Worked example: if only 90% of individual reviews catch a blood-brain-barrier permeability issue, the meta-review ensures all future reviews address it.)*
2. **Research overview** — periodically synthesizes top-ranked hypotheses into a roadmap: research areas/directions, their importance, and specific suggested experiments with example topics. Feeds back into the Generation agent. Can be formatted with **constrained decoding** to match publication/grant formats (e.g. **NIH Specific Aims Page**).
3. **Research contacts** — uses prior literature to suggest qualified domain experts (with reasoning) for reviewing the proposals.

### Summary of information flow

> Generation curates an initial hypothesis list → Reflection reviews → Ranking evaluates in a tournament → Evolution, Proximity, and Meta-review operate on the tournament state to improve quality. Feedback from the tournament creates a **self-improving loop**. The Supervisor periodically computes summary statistics and re-weights/re-samples agents accordingly.

---

## 5. Expert-in-the-loop interactions

Scientists can:

- **Refine the research goal** in light of generated hypotheses and the research overview.
- **Provide manual reviews** of hypotheses, which the system uses to evaluate and improve.
- **Contribute their own hypotheses**, ranked alongside (and combinable with) system-generated ones in the tournament.
- **Direct follow-up** on specific research directions (e.g. restricting to a smaller publication set).

---

## 6. Tool use

- **Web search and retrieval** are the primary tools, essential for grounded, up-to-date hypotheses.
- For constrained search spaces (e.g. all FDA-approved drugs, all receptors of a type), agents use **domain-specific tools / open databases** to constrain searches.
- The system can index and search a **private repository** of scientist-specified publications.
- It can incorporate feedback from **specialized AI models like AlphaFold** (demonstrated qualitatively with a protein-design example).

---

## 7. Evaluation methodology and results

### Elo–quality concordance (GPQA)
To verify the Elo metric tracks quality, the team framed **GPQA diamond** questions as research goals, bucketed responses by Elo (50-point increments), and computed accuracy per bucket against a Gemini 2.0 reference baseline (32 responses/question). Result: **concordance** between Elo and accuracy; selecting the top-rated response per question gave a **top-1 accuracy of 78.4%**. (Elo is auto-evaluated, *not* ground-truth.)

### Test-time compute scaling
Across **203 research goals** (predominantly biomedicine; also math/physics), hypotheses were partitioned into ten equal temporal buckets. Both **best Elo** and **average Elo of the top 10** trended **upward** with more compute — and showed **no saturation**. On a curated subset of **15 expert problems**, the co-scientist surpassed Gemini 2.0 Pro/Flash-Thinking, OpenAI o1/o3-mini-high, and DeepSeek R1 in Elo as compute increased. It also **improved upon expert "best-guess" solutions** over time, eventually surpassing its own autonomously-generated solutions.

### Expert evaluation
On **11 of the 15** goals, seven biomedical experts rated outputs (preference rank 1–4; novelty/impact 1–5). The co-scientist was **most preferred** with avg preference rank **2.36**, novelty **3.64/5**, impact **3.09/5** — beating Gemini 2.0 Pro/Flash-Thinking and OpenAI o1. LLM-as-judge evaluations (o3-mini, o1-preview, Gemini 2.0 Pro/Flash-Thinking) concurred. *(Small-scale; subjective expert assessments, not ground truth.)*

### Safety evaluation
**1,200 adversarial research goals** across 40 biomedical/scientific topics were generated; the system **rejected all** in this preliminary analysis. Dataset withheld but available on request.

---

## 8. Three end-to-end wet-lab validations

| Application | Drug repurposing | Novel target discovery | Gene-transfer mechanism (AMR) |
|---|---|---|---|
| Challenge | Combinatorial search | Identifying novel targets | Understanding complex systems |
| Complexity | Medium | High | Very high |
| Scale | Moderate, data-limited | Moderate, experiment-limited | Large, data+compute-limited |
| Unknowns | Constrained | Large | Vast and dynamic |

- **AML drug repurposing** — proposed novel repurposing candidates that inhibited tumor viability at clinically relevant concentrations across multiple AML cell lines in vitro. *(Clone gold-set names to look for: Binimetinib, Pacritinib, KIRA6, Leflunomide.)*
- **Liver fibrosis** — suggested novel **epigenetic targets** with significant anti-fibrotic activity in human hepatic organoids (including an FDA-approved drug).
- **Antimicrobial resistance (cf-PICI)** — instructed to hypothesize how capsid-forming phage-inducible chromosomal islands exist across bacterial species; **independently proposed that cf-PICIs interact with diverse phage tails to expand host range** — recapitulating an unpublished, experimentally-validated finding the researchers already had.

---

## 9. Limitations (from the paper)

- **Literature/review gaps** — reliance on open-access literature; may miss critical prior work or mis-reason about relevance.
- **No access to negative results** — failed-experiment data is rarely published, yet experts use it.
- **Multimodal/tool-use gaps** — figures/charts under-utilized; multi-omics datasets and knowledge graphs not yet integrated/evaluated.
- **Inherited LLM limitations** — hallucination, factuality errors, biases propagate.
- **Metrics/evaluation** — preliminary; Elo is a limited, intrinsically-favored auto-metric; needs broader, more objective evaluation.
- **Validation scope** — focuses on targets/mechanisms, not drug delivery, PK, bioavailability, clinical-trial design, or complex drug interactions; a translational team is needed downstream.

---

## 10. Safety and ethics posture

Two risk categories: **safety** (dual-use; breakthroughs exploited for harm) and **ethics** (research contradicting disciplinary norms). The paper emphasizes evolving ethics frameworks, emerging regulation, and organizational ethics reviews. Notably it flags **automation bias** — over-reliance could diminish critical thinking and homogenize research (correlated LLM failure modes could narrow inquiry) — and argues for scalable factuality/verification, peer review, and bias awareness. It also frames AI as a potential force for **equity**, democratizing access and "raising the tide," especially for resource-constrained and historically neglected areas.

---

## 11. Glossary (paper-canonical definitions)

- **Novel repurposing candidate** — an existing drug (established safety profile) proposed for a disease/condition it is not currently approved or widely used for. Distinct from traditional discovery (finding novel compounds).
- **Novel target** — a biological entity (gene, protein, pathway) not previously known as a therapeutic target for a specific disease.
- **Novel mechanistic explanation** — a newly proposed pathway/interaction/process explaining a phenomenon (disease progression, AMR) in a way not explicitly described in prior literature.

---

## 12. Why this matters for the clone

The fidelity of a clone is judged primarily against the behaviors specified above. The three behaviors most often cited as *"what separates a clone from a generic multi-agent RAG system"* (see file `09`):

1. **Elo init = 1200**, with multi-turn debate for top-ranked and single-turn for lower-ranked hypotheses.
2. **Evolution generates new hypotheses, never modifies existing ones** — each must re-compete.
3. **Meta-review critique is appended to every other agent's prompt next iteration** — feedback/learning without backprop.

The paper leaves several details **unspecified** (and therefore clone-defined): the Elo **K-factor**, the **embedding model** used by Proximity, the Supervisor's exact **termination predicates**, and the schema of the persistent **context memory**. A faithful clone matches every specified behavior and makes reasonable, configurable, documented choices for the rest.

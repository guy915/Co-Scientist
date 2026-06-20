# 05 — Tournament, Evolution, and Hypothesis-Evaluation Criteria

> **Purpose.** The mathematical and procedural core of "generate → debate → evolve": how hypotheses are scored on multiple axes, how the Elo tournament is run, how the debate is structured, how winning hypotheses are mutated, and the domain-specific rubrics that judge hypothesis quality. *Agent roles* are in file `04`; *prompts* in file `08`; *evidence grading* in file `06`; *fidelity benchmarks* in file `09`.
>
> Consolidates: `Hypothesis_Generation_Evaluation_and_Tournament_Specs.md`, `Multi-Agent_Hypothesis_Generation_Tournament_Architecture.md`, and the tournament/evolution sections of `UX_Design_Spec...`, `AI_Co-Scientist_Systems_Architecture...`, `Stateful_Agentic_Runtime...`, `Context_Engineering_Spec...`, `Autonomous_Multi-Agent...`, `Co-Scientist_Engineering_Blueprint...`.

---

## 1. Why a tournament (not static scoring)

Absolute scalar ratings from a single model are prone to **grading bias and calibration drift**. The system instead uses **adversarial, pairwise debates graded by an LLM-as-Judge**, with relative strength tracked by **Elo**. This is the "Tournament of Ideas," modeled after self-play RL (AlphaGo lineage).

---

## 2. Multi-axis reflection scoring (the inputs to the tournament)

Before the tournament, the Reflection agent scores each hypothesis in parallel across multiple domain-specific axes, yielding scalar scores $S_i$ on a **1-to-5 scale**. To make small user-controlled domain-weight ($W_i$) adjustments produce meaningful ranking shifts, a **squared scoring** mechanism amplifies raw evaluations:

$$\text{weightedTotal} = \sum_{i=1}^{M} W_i \times (S_i)^2 \qquad S_i \in [1,5],\; W_i \in [0,1],\; \textstyle\sum W_i = 1$$

### The evaluation rubric (qualitative)

| Criterion | Focus | Success threshold |
|---|---|---|
| **Novelty** | Originality / departure from baseline | Proposes empty literature gaps or paradigm-shifting mechanisms |
| **Plausibility** | Alignment with biological/physical laws | High logical coherence + external alignment with validated science |
| **Falsifiability** | Refutability via empirical observation | Makes bold predictions that prohibit certain outcomes |
| **Grounding** | Substantiation via literature/DBs | Roots all claims in documented facts, not speculation |
| **Feasibility** | Execution viability within limits/budget | Existing model systems, reasonable timelines |
| **Ethical constraints** | Safety/toxicity/clinical-trial screening | Replaces unsafe designs with acceptable surrogate models |

### Reflection review-cycle tiers (maps to file `04` agent #5)

| Tier | Objective | Focus |
|---|---|---|
| Initial | early filtering | discard flawed/non-novel/invalid (no tools) |
| Full | literature validation | verify baseline claims against published literature |
| Deep verification | logic verification | semantic cross-checks for subtle pathway errors |
| Observation | target optimization | can the hypothesis explain long-tail anomalies? |
| Simulation | experimental modeling | simulate mechanism / wet-lab validation in text |
| Recurrent | adaptive evolution | modify reviews as the knowledge base grows |

### Literature-support scoring (SKiM-GPT-style LBD)
A fine-grained support scale (achieves quadratic-weighted Cohen's $\kappa \approx 0.84$ vs experts on disease-gene-drug hypotheses):

| Score | Category | Interpretation |
|---|---|---|
| **−2** | Strongly refuting | direct evidence disproves the hypothesis |
| **−1** | Weakly refuting | negative correlation / contradictory trend |
| **0** | Neutral | no documented correlation exists |
| **+1** | Weakly supporting | indirect/correlative support |
| **+2** | Strongly supporting | direct empirical validation |

---

## 3. The Elo tournament

### Expected score and update (canonical Elo)
For hypotheses $A$ and $B$ with ratings $R_A,R_B$:

$$E_A = \frac{1}{1 + 10^{(R_B - R_A)/400}}, \qquad E_B = \frac{1}{1 + 10^{(R_A - R_B)/400}}$$

After a debate with outcome $S_A \in \{1.0\text{ win},\,0.5\text{ draw},\,0.0\text{ loss}\}$:

$$R'_A = R_A + K\,(S_A - E_A)$$

- **Initial rating = 1200** for every new hypothesis (**paper invariant**).
- **$K$** is the maximum per-match adjustment, **dynamically scaled by tournament phase** — larger during early seeding, finer during finals. The base value is commonly $K=32$. *(The exact K-factor / annealing schedule is paper-unspecified → clone-defined.)*

**Reference annealing schedule** (a documented clone choice): $K=32$ for a hypothesis's first 30 matches, $16$ for the next 470, $10$ thereafter.

**Margin-of-victory scaling** (alternative to phase annealing) — make decisive wins move Elo more:
$$\text{effectiveK} = 32 \times \min\!\big(5.0,\; 1 + 25 \times \text{rawMargin}\big)$$
where $\text{rawMargin}$ is the absolute difference in weighted-total scores between the two hypotheses.

### Matchmaking and pairing policy
- **Debate depth:** **multi-turn** debate for top-ranked hypotheses; **single-turn** comparison for lower-ranked (both end in a winner verdict).
- **Pairing priorities:** (1) hypotheses are more likely matched with **similar** ones (Proximity graph); (2) **newer** and **top-ranked** hypotheses are prioritized for matches.
- **Reference pairing weights** (clone choice): 60% similar-via-Proximity, 30% newer-or-top-ranked, 10% random exploration; single-turn when both Elo < median, 3-turn debate otherwise.

### Adjacent-pair optimization
Instead of an $N^2$ all-vs-all matrix, sort candidates by weighted total and run pairwise matches only between **adjacent** candidates $R_k$ vs $R_{k+1}$, reducing complexity to **$N-1$ matches**.

### Parameter summary

| Attribute | Formula / operator | Bounds | Purpose |
|---|---|---|---|
| Weighted score | $\sum W_i (S_i)^2$ | $S_i\in[1,5]$, $\sum W_i=1$ | amplify so weight changes shift rankings |
| Matchup selection | Adjacent-pair $R_k$ vs $R_{k+1}$ | $k\in[1,N-1]$ | $N^2 \to N-1$ |
| K-factor scaling | $32\min(5,1+25\cdot\text{rawMargin})$ | effectiveK $\in[32,160]$ | sensitivity ∝ victory margin |
| Elo update | $R'_A = R_A + \text{effK}(S_A - E_A)$ | $E_A$ as above | relative ranking update |
| Crossover | $H_O = \text{LLM}(H_A\cup H_B\mid\text{shared mechanics})$ | parents $\ge R_\text{median}$ | merge complementary ideas |
| Targeted mutation | $H'_A=\text{LLM}(H_A\mid\text{mitigate }S_\text{min})$ | $i=\arg\min_j S_j$ | resolve specific flaw |
| Reinforcement | $H''_A=\text{LLM}(H_A\mid\text{amplify }S_\text{max})$ | $i=\arg\max_j S_j$ | maximize core strength |

---

## 4. Debate mechanics (three-persona dialectic)

The Ranking agent assigns opposing sub-agent personas to force multi-angle evaluation:

```text
                 Ranking Agent (initiates match & Elo pool)
                            │
                   Debate Orchestrator
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   The Innovator       The Pragmatist      The Contrarian
 (defends mechanisms)  (translation/exec   (logical leaps,
                        risk)               bias, weak evidence)
        └───────────────────┼───────────────────┘
                   Pairwise Adjudicator (victor + Elo update)
```

- **Innovator** — defends biophysical plausibility & therapeutic value: target mechanisms, receptor affinities, signaling pathways; downstream phenotypic responses; alignment with conserved physiology + high-consensus literature.
- **Pragmatist** — challenges execution: reagent/cell-line/animal-model availability; clinical toxicities, off-target interactions, kinetic limits; assay complexity & time.
- **Contrarian** — skeptic: over-reliance on low-replication or retracted data; correlation-to-causation jumps; simpler alternative mechanisms explaining the same observations.

**Debate protocol (3-turn dialectic):**
$$\text{T1: Innovator proposes mechanism} \to \text{T2: Contrarian/Pragmatist expose flaws} \to \text{T3: Innovator proposes refinement}$$
The victor is the hypothesis that best defended its core biophysical assumptions. Multi-turn debates typically run 3–5 turns (max 10). *(Debate-judge prompts in file `08`.)*

---

## 5. Evolution operators (refining tournament survivors)

Top survivors route to the Evolution agent, which applies mutation strategies (paper's six; some specs expand to eight). **Invariant: each produces a NEW hypothesis** (file `04`):

- **Grounding enhancement** — query DBs to enrich with new literature/data.
- **Coherence & feasibility** — adjust steps for operational viability.
- **Inspired generation** — analogies from adjacent fields.
- **Hypothesis combination / crossover** — synthesize top proposals into one comprehensive theory.
- **Simplification** — Occam's razor; remove ad-hoc assumptions.
- **Out-of-box ideas** — non-obvious, highly novel concepts.
- **Non-destructive evolution** — refine while preserving core validated claims.
- **Iterative refinement** — polish based on debate feedback.

Mathematically the operators target scoring axes: crossover (two strong parents), targeted mutation (lowest axis $S_\text{min}$), reinforcement (highest axis $S_\text{max}$). Parent-child lineage is recorded (`parent_ids`).

---

## 6. Domain-specific evaluation requirements

A single metric across all disciplines yields superficial proposals. Apply discipline-tailored criteria:

| Domain | Core parameter | Validation models | Causality indicators |
|---|---|---|---|
| **Molecular biology** | subcellular target engagement, binding kinetics | protein assays, lysates, live cells | direct interactions, concentration-dependent binding |
| **Computational biology** | pathway connectivity, stoichiometric constraints | single-species / supra-organism metabolic models | topology flows, thermodynamic viability |
| **Systems biology** | dynamic networks, multi-omics | global regulatory networks, GNN causal modeling | GNN perturbation flows, information gain |
| **Drug discovery** | target validation, clinical translation | organoids, primary cells, trials | experiments of nature, Mendelian randomization, 5R |

### Molecular biology — the "Rule of Two" for chemical probes
Require ≥2 chemically distinct, orthogonal probes plus a matched inactive control, preventing single-probe high-concentration false positives:
$$\text{Probe Requirement} = \{P_1,P_2 \mid \text{orthogonal structures} \land \text{EC}_{50}\le 100\text{ nM}\} \cup \{P_\text{inactive}\}$$

### Systems biology — constraint-satisfaction search
Keep the proposed network state consistent with background laws $\mathcal{B}$ while minimizing complexity and statistical error:
$$\min_{H}\;\mathrm{Cost}(H)=|H|+\mathrm{FP}(H)+\mathrm{FN}(H)\quad\text{s.t. } \mathcal{B}\land H \not\models \bot$$

### Drug discovery — causality frameworks
Anchor to AstraZeneca's **5R Framework** ("right target, right tissue, right patient"); treat naturally-occurring genetic variants as "experiments of nature"; use **Mendelian randomization** to predict safety, adverse effects, dose-response. **Active Causal Hypothesis Testing (ACHT)** prioritizes target genes via a Bayesian information-gain acquisition function over network edges:
$$a(W_{ij}) = \mathbb{E}_{P(W\mid X,Z)}[\Delta\mathcal{L}]$$
Clinical hypotheses must be framed as PICO(T) questions (population, intervention, comparison, outcome, timeframe), with an ethical gatekeeper replacing dangerous interventions with surrogate models.

---

## 7. Contradiction adjudication and discovery heuristics

Biological findings are context-dependent; naive RAG misreads contextual variation as logical contradiction (**generalization bias**). Use structured frameworks like **IMPACT** to extract aspect-conditioned contradiction spans across full text, assign a graded intensity score, and explain the underlying context — distinguishing a *true* contradiction from a model-system difference. *(Mathematical contradiction detection + CO-GAT confidence masking is in file `06`.)*

When true contradictions arise, treat disagreement as a driver for theory generation:

| Heuristic | Strategy | Implementation |
|---|---|---|
| **H1** | Investigate deviations from expectations | mine anomalies/outliers for hidden mechanisms |
| **H2** | Question the norm | test whether a consensus's assumptions still hold |
| **H3** | Juxtapose opposite problems | study inverse problems (proliferation vs senescence) for shared nodes |
| **H4** | Generate theories from conflict | reconcile contradictory findings into a unified model |

---

## 8. Empirical calibration & failure modes

- **Elo–quality concordance** is validated against ground-truth benchmarks (GPQA), demonstrating a positive correlation between high Elo and correct conclusions (file `01`: top-1 accuracy 78.4% on GPQA diamond).
- **Temporal bucketing** (partition hypotheses into time buckets, track best/top-10 Elo) demonstrates quality improvement with test-time compute and is reused in the fidelity harness (file `09`).
- **Known failure modes:** automated peer review is hard (Sakana's reviewer rejected ~90% of human papers, file `09`); guard against overclaiming via feature-level novelty detection (file `06`); avoid post-hoc data fitting via pre-registration discipline ("Science Superpowers," file `09`).

---

## 9. Tournament fidelity targets (preview of file `09`)

- **Tournament behavior similarity:** Spearman's $\rho \ge 0.82$ between tournament Elo and human expert rankings on GPQA + expert-curated benchmarks.
- **DB-verifiable invariants:** initial Elo = 1200; pairings biased to similar-via-Proximity + new/top; multi-turn for the top half — all checkable by querying `tournament_matches`.

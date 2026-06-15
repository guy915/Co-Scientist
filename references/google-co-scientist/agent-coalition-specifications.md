# 04 — Agent Coalition Specifications

> **Purpose.** The single authoritative roster of agents, with each agent's role, behavioral modes, I/O contract, model allocation, permitted tools, and state-machine behavior. The paper specifies **seven** roles (file `01`); the clone makes five implicit roles explicit for a **twelve-agent** coalition. *Behavioral prompts* live in file `08`; *orchestration wiring* in file `03`; *tournament internals* in file `05`.
>
> Consolidates the agent-roster sections of: `AI_Co-Scientist_Systems_Architecture_and_Technical_Spec.md`, `Autonomous_Multi-Agent_Scientific_Discovery_Blueprint.md`, `Interactive_Multi-Agent_Scientific_Discovery_Platform_Blueprint.md`, `Stateful_Agentic_Runtime_and_Orchestration_Blueprint.md`, `Multi-Agent_Hypothesis_Generation_Tournament_Architecture.md`, `Systems_Design_Multi-Agent_Orchestration_and_Claim_Verification.md`.

---

## 1. Paper-canonical seven vs clone twelve

| # | Agent | In paper? | Role |
|---|---|---|---|
| 1 | **Supervisor** | ✅ | Adaptive planner; parses goal → plan config; weights/samples agents; computes summary stats |
| 2 | **Intake / Interview** | implicit | Scoping interview → structured run configuration |
| 3 | **Literature Retrieval** | implicit (tool use) | Targeted multi-source literature search + extraction |
| 4 | **Generation** | ✅ | Novel hypotheses (4 modes) |
| 5 | **Reflection** | ✅ | Peer review (6 review types) |
| 6 | **Proximity / Clustering** | ✅ | Embedding-based similarity graph, dedup, pairing |
| 7 | **Ranking** | ✅ | Elo tournament via pairwise debates |
| 8 | **Evolution** | ✅ | Refine top hypotheses (6 strategies); **generates NEW only** |
| 9 | **Meta-Review** | ✅ | Synthesize critiques + research overview; feedback without backprop |
| 10 | **Citation Verification** | implicit | Claim-to-source validation, clickable citations |
| 11 | **Safety** | implicit (review) | CBRN/dual-use auditing; halts |
| 12 | **Report Synthesis** | implicit (meta-review) | Compile final NIH-format proposal |

```text
                       User / Scientist
                            │
                     Supervisor Agent  (durable queue, plan coordinator)
                            │  schedules / weights / samples
   ┌──────────┬──────────┬──┴───────┬──────────┬───────────┐
   ▼          ▼          ▼          ▼          ▼           ▼
Generation  Reflection  Ranking   Evolution  Proximity  Meta-Review
(lit/debate)(6 reviews)(Elo judge)(crossover) (FAISS)   (synth/writer)
   │          │          │          │          │           │
   └── Literature ── Citation Verification ── Safety ── Report Synthesis
```

---

## 2. Per-agent specifications

### 1. Supervisor
- **Role/persona** — rigorous systems architect & project manager; adaptive, non-linear planner.
- **Behavior** — parses NL goal into a structured plan config (a DAG of execution tasks); dynamically populates a DB-backed task queue; monitors agent outputs and **spawns parallel worker tasks** to explore promising paths; periodically computes summary statistics (# hypotheses generated, # requiring review, tournament progress, **generation-vs-evolution effectiveness**) and **re-weights/re-samples** agents; determines terminal state.
- **I/O** — in: research goal, run config, state-machine history. out: target step sequence, sub-agent allocations, routing decisions.
- **Model** — high-adherence, low-temperature (e.g. Gemini 3.5 Pro / Opus-class for planning).
- **Tools** — LangGraph state router, event dispatcher; **DB mutations only** — no literature review or hypothesis generation.
- **Constraints** — strictly administrative communication.

### 2. Intake / Interview
- **Role/persona** — context-aware scoping interviewer.
- **Behavior** — semi-structured dialogue; assesses answers against scientific taxonomies; tracks "Interview Progress"; asks **clear, singular** clarifying questions; compiles finalized run specifications.
- **I/O** — in: raw NL goal, scoping templates, chat history. out: structured run-config JSON, `scoping_complete` flag.
- **Model** — low-latency interactive (Gemini 3.5 Flash / Haiku-class).
- **Tools** — UI chat channel only.
- *(System prompt + JSON output schema in file `08`.)*

### 3. Literature Retrieval
- **Role/persona** — high-throughput search & extraction specialist.
- **Behavior** — formulates advanced queries; searches DBs/preprints/web; parses abstracts and extracts full-text references; packages structured context arrays for Generation/Reflection.
- **I/O** — in: refined goal, keyword directives, exclusions. out: ranked document summaries, metadata (DOIs, authors, dates).
- **Model** — high-throughput context parsing (Flash-class).
- **Tools** — PubMed, Europe PMC, arXiv, Semantic Scholar, OpenAlex, Crossref, ChEMBL, UniProt connectors (see file `06`).

### 4. Generation
- **Role/persona** — imaginative yet rigorous computational biologist; bridges disparate domains.
- **Behavior — four modes:** (1) **literature exploration** (query DBs, synthesize, formulate hypotheses as "strategic bets"); (2) **simulated scientific debate** (multi-turn self-play, opposing perspectives, refine before submission); (3) **iterative assumptions identification** (conditional reasoning hops → testable assumptions → complete hypotheses); (4) **research expansion** (use Meta-review overview/feedback to explore unexplored space). Conditioned strictly on retrieved literature/datasets — never generated in isolation. Summarizes and categorizes each hypothesis.
- **I/O** — in: scoped config, retrieved context, diversity targets. out: array of hypothesis objects (mechanism of action, target, experimental plan).
- **Model** — high-temperature for creative brainstorming (Deep-Think-class).
- **Constraint** — uses Meta-review feedback *selectively* to avoid overfitting to critiques.

### 5. Reflection
- **Role/persona** — highly critical, adversarial peer reviewer.
- **Behavior — six review types** (full detail file `01`/`05`): **initial** (no tools; quick discard), **full** (web search, grounded), **deep verification** (decompose → assumptions → sub-assumptions, decontextualize, assess fundamental-ness), **observation** (explains long-tail prior observations?), **simulation** (step-wise mechanism/experiment simulation), **recurrent/tournament** (adapt reviews to growing knowledge). Critiques must be **concrete and actionable** (specific biophysical gaps, not "too speculative" — see file `08`).
- **I/O** — in: single candidate hypothesis, reference context, scoring guidelines. out: multi-axis scores (1–5), critical-defect log, scientific-gaps report.
- **Model** — low-temperature for logical rigor (Deep-Think-class).
- **Tools** — database lookup, computational biophysics predictors.

### 6. Proximity / Clustering
- **Role/persona** — high-precision computational topographer.
- **Behavior** — computes embeddings for all active hypotheses; clusters the high-dimensional space; flags redundant entries; **selects optimal tournament pairings** (schedules closely-related pairs head-to-head). Does not generate hypotheses.
- **I/O** — in: unclustered hypothesis pool, embedding model. out: distance matrix, clustering tree, redundancy flags, dedup recommendations.
- **Model** — dedicated embedding model (text-embedding-004 / text-embedding-3-large / Voyage). *(Embedding model is paper-unspecified → clone-defined.)*
- **Tools** — vector similarity engine, graph visualization handler.

### 7. Ranking
- **Role/persona** — Elo tournament judge.
- **Behavior** — retrieves hypothesis pairs + their reviews; initiates **simulated debates**; updates the global Elo leaderboard. **Multi-turn** debate for top-ranked; **single-turn** for lower-ranked. Pairing prioritizes (1) similar-via-Proximity, (2) newer/top-ranked. May orchestrate Innovator/Pragmatist/Contrarian debate personas (file `08`).
- **I/O** — in: competitive hypothesis pair, Reflection scoring profiles. out: structured verdict (winner ID, comparative debate, winning logic) ending with `"better idea: <1 or 2>"`.
- **Model** — multi-perspective debate logic (Deep-Think-class).
- **Tools** — tournament-state updater, match scheduler. *(Elo math in file `05`.)*

### 8. Evolution
- **Role/persona** — hypothesis optimizer.
- **Behavior — strategies** (paper's six; some docs list eight): enhancement through grounding, coherence/practicality/feasibility, inspiration from existing top-ranked, combination/crossover, simplification, out-of-box thinking, (+ non-destructive refinement, iterative refinement). Operators map to weaker scoring axes: **crossover** (merge two strong parents), **targeted mutation** (fix lowest-scoring axis), **reinforcement** (amplify highest-scoring axis).
- **I/O** — in: top-ranked parents, tournament debates, underperforming axes. out: refined offspring hypothesis + ancestral lineage (`parent_ids`).
- **Model** — balanced settings for targeted editing (Deep-Think-class).
- **★ Invariant** — **generates NEW hypotheses; never modifies/replaces existing ones.** Each offspring must re-enter the tournament. (Enforced by test `test_evolution_never_modifies_existing` — file `09`.)

### 9. Meta-Review
- **Role/persona** — senior research director / lead academic editor / clinical program coordinator.
- **Behavior** — operates on tournament state; **(a)** synthesizes a meta-critique of common patterns across all reviews/debates, **appended to every other agent's prompt next iteration** (learning without backprop); **(b)** periodically synthesizes top hypotheses into a **research overview** (NIH Specific Aims format), feeding back into Generation; **(c)** suggests qualified expert **research contacts** from prior literature. Also issues planning directives to the Supervisor to redirect the queue when it detects bottlenecks (retrieval gaps, clustering collapse).
- **I/O** — in: complete run history, match debates, reflection matrix. out: consolidated lessons log, parameter guidance, system-prompt adjustments, research overview.
- **Model** — low-temperature structural synthesis (Pro/Opus-class).
- **Constraint** — produce a *synthesized meta-analysis*; do not re-evaluate individual proposals.

### 10. Citation Verification
- **Role/persona** — automated fact-checker.
- **Behavior — dual-pass:** **(1) assertion extraction** (parse draft, list standalone claims); **(2) source mapping** (compare each assertion against indexed retrieved literature; map verified ones to specific sources; add clickable inline citations; flag unmappable assertions for manual review). Resolves entity mappings across databases. *(Full multi-tier verification, NLI, Retraction Watch, CiteGuard in file `06`.)*
- **I/O** — in: generated claim, source identifiers (DOIs/PMIDs). out: verification status (Verified/Failed/NEI), exact verified snippet, DOI link.
- **Model** — factual extraction & matching (Flash-class).
- **Tools** — Crossref resolver, Semantic Scholar snippet search, CiteGuard engine.

### 11. Safety
- **Role/persona** — biosecurity/ethics enforcer.
- **Behavior** — audits the user goal against prohibited domains (CBRN); monitors generation/evolution outputs ("Planner/Talker" isolation); flags risky proposals during Reflection. **Immediate halt + override** on violation; logs the block. *(Full safety pipeline in file `06`.)*
- **I/O** — in: raw prompt, dialogue state, generated proposals. out: safety verdict (Approved/Rejected), mitigation instructions, policy-violation log.
- **Model** — Llama-Guard / Gemini safety classifiers.
- **Tools** — SafeScientist gateway, biosecurity payload filter.

### 12. Report Synthesis
- **Role/persona** — academic-writing compiler.
- **Behavior** — structures meta-review + verification outputs into the final document; incorporates the Elo leaderboard, grounding citations, and experimental protocols; renders the **NIH Specific Aims** format.
- **I/O** — in: winning hypotheses, verified citations, experimental protocols. out: high-fidelity report (Markdown/LaTeX/JSON).
- **Model** — academic writing standards (Pro/Opus-class).
- **Tools** — document builder, Markdown-to-PDF/LaTeX converter.

---

## 3. NIH Specific Aims output structure (Report Synthesis + Meta-Review)

The research overview is formatted as an **NIH Specific Aims Page** with: **disease description / unmet need / proposed solutions / specific aims**, where each aim contains:
> overarching goal + hypothesis + rationale + pre-clinical experiment plan + endpoints + translational component.

---

## 4. Inter-agent communication and asynchronous workflow

- **Decoupled, asynchronous** — agents are worker processes; the Supervisor manages a durable task queue with bounded concurrency. Agents do not call each other directly; they communicate through shared state (the relational store / KSDS blackboard — file `07`) and file-based contracts (the ResearchLoop YAML schemas — file `03`).
- **File-based handoffs** — agent-to-agent transitions use formal, schema-validated file interfaces (a "Living Working Paper" in structured Markdown), not transient chat logs, so error states don't propagate.
- **Distributed scratchpads** — each agent runs intermediate reasoning/tool calls in an isolated local cache; only the compressed structured update is persisted to the shared blackboard, protecting other agents' context windows.

### Agent state-machine pattern
Each agent (per the tournament-architecture spec) operates as a small state machine with explicit inputs, a processing step, structured outputs, and event emissions. The Supervisor's routing reads these events plus `summary_stats` to drive the conditional graph edges (file `03`). Typical per-agent states: `idle → leased → running → emitting → done/failed`, with leases (`lease_expires_at`) enabling crash recovery.

---

## 5. Model-allocation summary (reference)

| Agent | Typical temperature | Class |
|---|---|---|
| Supervisor | low (adherence) | Pro / Opus |
| Intake | — (interactive) | Flash / Haiku |
| Literature | — (throughput) | Flash |
| Generation | **high** (diversity) | Deep-Think |
| Reflection | low (rigor) | Deep-Think |
| Proximity | — (embeddings) | embedding model |
| Ranking | — (debate) | Deep-Think |
| Evolution | balanced | Deep-Think |
| Meta-Review | low (synthesis) | Pro / Opus |
| Citation | — (extraction) | Flash |
| Safety | — (classification) | Guard / safety classifier |
| Report Synthesis | — (writing) | Pro / Opus |

> In the open-source reference build the model router exposes aliases `opus` / `sonnet` / `opusplan` (Anthropic) and equivalents for OpenAI/Gemini; `opusplan` routes planning to an Opus-class model and execution to a Sonnet-class model. Concrete model names drift — keep them in config, not code.

---

## 6. Fidelity checklist for the agent layer

A clone's agent layer is faithful when, in a single ~30-minute trace, all of the following are observable (file `09`, fidelity category 4):
- All **4 Generation modes** fire.
- All **6 Reflection review types** fire.
- All **6 Evolution strategies** fire, and **every Evolution output is a new hypothesis** with non-empty `parent_ids`.
- Ranking shows **Elo init = 1200**, multi-turn for top-half, single-turn for bottom-half, pairings biased toward Proximity-similar + new/top.
- The **Meta-review critique demonstrably changes the next Generation prompt** (snapshot diff).
- Safety blocks all CBRN probes without over-redacting benign biology.
- Citation Verification reaches tier-2 on ≥80% of cited works, zero unresolved citations in the final report.

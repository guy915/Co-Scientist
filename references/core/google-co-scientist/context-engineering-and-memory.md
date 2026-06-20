# 07 — Context Engineering and Stateful Memory

> **Purpose.** How the system stays coherent across hours-to-days of multi-agent execution without context bloat: the layered memory hierarchy, the shared "blackboard" KSDS, episodic context reconstruction, hierarchical summarization/compaction, the context-window budget, the self-optimizing prompt loop, trajectory compression, and the durable-state SQLite schema variant. *Postgres schema + orchestration* are in file `03`; *prompt text* in file `08`.
>
> Consolidates: `Context_Engineering_and_Stateful_Memory_Architecture.md`, `Context_Engineering_Spec_for_Multi-Agent_Co-Scientist.md`, plus the memory/state portions of `Stateful_Agentic_Runtime_and_Orchestration_Blueprint.md`.

> **Core problem.** Appending raw logs to model inputs leads to context bloat, attention degradation ("lost-in-the-middle"), token-cost escalation, and incorrect claims. Memory must be treated as a **systems-architecture challenge**, not a prompt afterthought.

---

## 1. The layered memory hierarchy

```text
┌──────────────────── I/O & TOOL BUFFER ─────────────────────┐
│  Web Search, PubMed, ChEMBL, UniProt, AlphaFold            │
├──────────────────── WORKING SEMANTIC CACHE ────────────────┤
│  Isolated agent scratchpads (Action-Thought-Observation)   │
│  Ephemeral conversation & debate histories                 │
├─────────────────── PERSISTENT CONCURRENT STORE ────────────┤
│  Relational queue (run params, task metadata)              │
│  Structured KSDS JSON (durable, version-controlled state)  │
│  Vector document store (embedded papers/abstracts)         │
└────────────────────────────────────────────────────────────┘
```

Three logical tiers:
- **Short-term state** — immediate runtime context (active DB, scratchpads, current task queue); discarded on task completion.
- **Long-term episodic memory** — chronological session history (tournament transcripts, rating changes, past failures); lets the system **avoid repeating unproductive directions**.
- **Long-term semantic memory** — stable verified knowledge (vector embeddings of literature metadata + structured pathway/target/drug records).

---

## 2. The hybrid shared-distributed (blackboard) paradigm

Balance collaboration against context efficiency:

- **Shared Memory (the Blackboard)** — a central relational DB + a version-controlled JSON **Knowledge State Data Structure (KSDS)**: the single source of truth tracking task updates, active hypotheses, and tournament standings.
- **Distributed Memory (agent scratchpads)** — each agent runs step-by-step reasoning, tool calls, and drafts in an isolated local cache. Intermediate traces never clutter the blackboard or pollute other agents' context windows.

On task completion, an agent compiles/compresses its findings and persists **only the structured update** to the global KSDS. This lets parallel agents operate safely on shared state — e.g. the Ranking agent updates Elo while the Proximity agent reads active nodes to recompute similarity, with no corruption.

### KSDS schema (illustrative)
```json
{
  "session_id": "session_microbiome_2026_06",
  "run_specifications": {
    "research_goal": "Identify hypotheses about microbiome-driven inflammation",
    "budget_usd": 2.00, "wall_clock_limit_seconds": 600,
    "scoping_constraints": {"excluded_taxa": ["..."], "focus_pathways": ["..."]}
  },
  "hypothesis_nodes": [{
    "id": "hyp_node_001", "parent_ids": ["..."], "author_agent": "GenerationAgent",
    "claim": "Segmented filamentous bacteria drive Th17 differentiation via serum amyloid A induction",
    "proposed_experimental_protocol": "Aerosolized anti-SAA antibodies in murine models...",
    "vector_embedding_id": "vec_hyp_001", "elo_rating": 1245.5,
    "tournament_match_history": [{"match_id":"m_001","opponent_id":"hyp_node_002","verdict":"win","elo_delta":16.2}],
    "reflection_critiques": ["..."], "grounding_citations": ["..."]
  }],
  "system_statistics": {"total_tokens_consumed": 450120, "current_queue_status":"active_ranking", "active_concurrency_count": 3}
}
```

> The KSDS is the conceptual analogue of the paper's "context memory" (file `01`). It enforces consistent structures so agents can reliably read, update, and validate state across the lifecycle.

---

## 3. Episodic Context Reconstruction (E-mem)

Rather than naive text retrieval (which returns fragmented, out-of-context blocks), organize uncompressed episodic memory into structured **segments** managed by lightweight local assistant agents:

```text
User Query → routing layer → relevant segment activated
                                  │
                                  ▼
                        E-Mem Assistant Agent
                        - context-aware analysis
                        - logical proof formulation
                                  │
                                  ▼
Master Agent ◄────────── verified claims only
```

When a query arrives, only the relevant segment activates; its assistant analyzes the uncompressed context, constructs a logical proof, and returns **only verified claims** to the master planner. This eliminates "lost-in-the-middle," improving retrieval precision by **+7.75%** while cutting downstream token cost by **>70%**.

---

## 4. Hierarchical summarization & compaction

To keep token usage bounded during long debates/evolution, the Supervisor monitors token counts across active dialogue channels. When the count crosses a threshold (**`AUTOCOMPACT_BUFFER_TOKENS = 13000`**), execution pauses for a text-only compaction pass:

1. A **`NO_TOOLS_PREAMBLE`** suppresses tool-use calls during compaction.
2. The active dialogue is compressed into a structured summary.
3. Full uncompressed logs are written to an offline archive file.
4. A clean recovery prompt resumes work, referencing the summary + the archive file path — no loss of task continuity.

### Context-window budget
The window is allocated to prioritize verification and logical consistency:

$$\text{Context Window Budget} \rightarrow
\underbrace{\text{Core Prompt \& Instructions}}_{\approx 15\%}
+ \underbrace{\text{Grounded Facts \& Citations}}_{\approx 40\%}
+ \underbrace{\text{Episodic Reconstruction Segment}}_{\approx 30\%}
+ \underbrace{\text{Active Workspace Scratchpad}}_{\approx 15\%}$$

---

## 5. Trajectory compression & code-to-language abstraction

Three complementary protocols keep long-running sessions accurate:

- **Trajectory compression (code-to-language).** A summarization pipeline intercepts raw Action-Thought-Observation (A-T-O) sequences, strips JSON payloads / terminal logs / repetitive steps, and distills the trajectory into a concise natural-language summary capturing key actions, parameters, and outcomes — **up to 90% token reduction** while preserving logical flow.
- **Epistemic state summarization (dual-module persistent memory).** See §6.
- **Hierarchical citation graphs.** Structure papers into Foundation/Development/Frontier layers and pass only multi-aspect summaries to generation agents (full detail in file `06`).

---

## 6. Self-optimizing prompts (learning without backpropagation)

Agent-to-agent transitions use **formal file-based interfaces** (a "Living Working Paper" in structured Markdown) and schema-validated JSON gates rather than transient chat logs, so errors don't propagate. On top of this, a **prompt-evolution loop** enables learning without retraining, managed by two persistent repositories:

1. **Ideation Memory ($M_I$)** — tracks successful research directions *and* logs failed hypotheses with the specific critiques that rejected them. Before a generation task, historical failures are retrieved and appended to the prompt, preventing re-exploration of refuted concepts.
2. **Experimentation Memory ($M_E$)** — stores effective code implementations, tool parameters, and successful debugging paths; retrieved by engineering agents to raise code-execution success over time.

At the end of each tournament cycle, the **Meta-Review agent** distills the patterns separating successful runs from failures into concrete heuristics and **appends them to the Generation and Evolution agents' system prompts for subsequent cycles**. This is the same mechanism the paper describes (file `01`): feedback applicable to all agents, simply appended to their prompts next iteration — facilitated by long-context models.

> This is the implementation substrate for the paper's **Meta-review-critique invariant**: the critique is appended to every other agent's prompt in the next iteration. Here it is split into ideation vs experimentation memory and rendered into prompts via Jinja (file `08`).

---

## 7. Durable-state SQLite schema (15-table single-node variant)

For single-node deployments, durability uses **SQLite with Write-Ahead Logging** (`busy_timeout = 5000ms`) so multiple agent threads read/write concurrently without lock contention. (Postgres + pgvector is the multi-worker alternative — file `03`.) The schema spans fifteen tables:

| Table | PK | Key columns | Purpose |
|---|---|---|---|
| `sessions` | `session_id` | goal_text, scoped_preferences, budget_usd, budget_spent, status | run-level state |
| `hypotheses` | `hypothesis_id` | session_id, title, mechanism_description, target_protein, chemical_compound, **elo_rating DEFAULT 1200.0** | hypothesis store; composite index `(session_id, elo_rating)` |
| `reviews` | `review_id` | hypothesis_id, reviewer_agent, critique_text, is_passing, safety_status | Reflection output |
| `tournament_matches` | `match_id` | session_id, contender_a_id, contender_b_id, winner_id, status | match configs |
| `elo_journal` | `journal_id` (autoinc) | hypothesis_id, match_id, old_rating, new_rating | rating history |
| `tasks` | `task_id` | session_id, agent_role, payload, status, **lease_expires_at**, retry_count | durable queue; index `(status, lease_expires_at)` |
| `transcripts` | `transcript_id` | match_id, debate_round, speaker_role, argument_text | debate logs |
| `system_feedback` | `feedback_id` | session_id, source_agent, distilled_heuristic | meta-review heuristics ($M_I$/$M_E$) |
| `embeddings_meta` | `vector_id` | hypothesis_id, vector_coordinates, cluster_assignment | Proximity vectors |
| `spans` | `span_id` | session_id, task_id, operation_name, duration_ms | tracing |
| `events` | `event_id` (autoinc) | session_id, event_type, payload | event sourcing; index `(session_id, event_type)` |
| `bench_runs` | `run_id` | benchmark_name, execution_parameters | fidelity benchmarking |
| `bench_candidates` | `candidate_id` | run_id, model_identifier, mode | cross-model bench |
| `bench_matches` | `match_id` | run_id, candidate_a_id, candidate_b_id, winner_id, **gold_set_hit** | bench results |
| `migration_history` | `version` | applied_at | schema versioning |

The `events` table enables **run replay / event sourcing**; `spans` feeds observability; `system_feedback` persists the self-optimizing heuristics from §6.

---

## 8. How the layers serve a run (summary)

1. **Scoping** writes run specs to `sessions`/KSDS `run_specifications`.
2. **Generation/Reflection/Ranking/Evolution** read grounded facts (semantic memory) + the blackboard, run in isolated scratchpads, and persist only structured updates (hypotheses, reviews, matches, Elo journal).
3. **Episodic memory** (transcripts, elo_journal, failed pathways) is reconstructed on demand via E-mem segments; raw history is archived on compaction.
4. **Meta-Review** distills `system_feedback` heuristics and injects them into the next cycle's prompts (learning without backprop).
5. **Checkpointing** (LangGraph PostgresSaver / Temporal event history, or SQLite WAL) makes every step resumable; `events` enables replay/time-travel.

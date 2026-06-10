# 03 — System Architecture and Orchestration

> **Purpose.** The backend systems blueprint: the core hypothesis-generation loop as software, the orchestration-runtime choice (LangGraph + Temporal/ADK), durable state and persistence models, the asynchronous job queue, the concrete monorepo layout, database schema, and API/event contracts. Agent *behavior* is in file `04`; tournament *math* is in file `05`; memory *strategy* is in file `07`.
>
> Consolidates: `AI_Co-Scientist_Systems_Architecture_and_Technical_Spec.md`, `Technical_Architecture_and_Product_Specification_Blueprint.md`, `Technical_Analysis_and_Implementation_Blueprint_for_a_1_1_Google_DeepMind_AI_Co-Scientist_Clone.md`, `Open-Source_Co-Scientist_Clone_Architecture_and_Implementation_Plan.md`, `Autonomous_Multi-Agent_Scientific_Discovery_Blueprint.md`, `Interactive_Multi-Agent_Scientific_Discovery_Platform_Blueprint.md`, `Stateful_Agentic_Runtime_and_Orchestration_Blueprint.md`, `Distributed_Multi-Agent_Discovery_Harness_Technical_Spec.md`.

---

## 1. The system as a closed-loop reasoning engine

The system is a closed-loop scientific reasoning engine modeling hypothesis → validation → refinement, progressing through **eight stages** to turn an abstract research objective into a literature-grounded proposal. It is fundamentally designed around **test-time compute scaling**: the *majority* of compute goes to verification, adversarial debate, and iterative refinement rather than token output.

```text
Research Goal
   ↓  Goal Scoping & Extraction (intake interview → run plan config)
   ↓  Literature Grounding & Query Construction (curated DBs / web)
   ↓  Hypothesis Generation  ◄─────────────────────────────┐
   ↓  Reflection / Multi-axis Review                       │
   ↓  Pairwise Tournament (Elo) ── win/loss pattern analysis│ feedback loop
   ↓  Hypothesis Evolution ─────────────────────────────────┘
   ↓  Report Synthesis & Citation Mapping
Final Research Proposal
```

**Two run modes** govern the speed/depth trade-off (see file `02` for the UI):
- **Standard** — shallow search, small tournament pool, constrained debate, results in minutes; for verifying parameters and refining the question.
- **Advanced** — hours/days of test-time compute, deep databases, extensive pairwise tournaments, complex evolutionary mutation matrices.

---

## 2. Subsystem → agent integration matrix

The architecture is **highly decoupled and distributed**. A monolithic coordinator is deliberately avoided to prevent context pollution, token bloat, and planning failures; specialized agents are registered with explicit runtime roles, narrow tool sets, and distinct system instructions.

| Subsystem | Registered agent | Inputs / dependencies | Responsibility & artifacts |
|---|---|---|---|
| **Web UI & Control Console** | — (direct user layer) | scoped configs, feedback, runtime state | run timelines, agent statuses, logs, cost meters, checkpoints |
| **Backend API Gateway** | Intake/Interview | NL objective, domain sliders, params | scoping dialogues, run profile, submits jobs to queue |
| **Long-Running Job Queue** | Supervisor | execution graphs, worker logs, session contexts | async task distribution, worker-failure handling, run health, parallel paths |
| **Scientific Retrieval Layer** | Literature Retrieval | query arrays, API credentials, grounding tokens | connects web + curated DBs (ChEMBL, UniProt); verified reference corpora |
| **Hypothesis Store** | Generation & Proximity | grounded corpora, domain params, active list | structured hypothesis objects, similarity maps, diversity clusters |
| **Evidence & Citation System** | Citation Verification | proposal texts, claims, indexed ref metadata | dual-pass claim-to-source validation, verified inline citations |
| **Tournament & Ranking Engine** | Reflection & Ranking | candidate arrays, eval configs, match rules | multi-axis reviews, pairwise debates, Elo calculations |
| **Report Generator** | Report Synthesis | top survivors, critique ledgers, citation links | publication-ready interactive briefs |
| **Safety Layer** | Safety | scoped prompts, draft texts, protocol inputs | CBRN/dual-use audits; immediate halts on non-compliance |
| **Fidelity Evaluation Harness** | Meta-Review | tournament histories, transcripts, baselines | win/loss analysis, alignment metrics, similarity-to-baseline |

System topology (request flow):
```text
User Web Interface ──(REST / WebSocket / SSE)──► Backend API Gateway
        │                                              │
        ▼                                              ▼
   Supervisor Agent  ◄──── Long-Running Job Queue (durable) ────► Worker pool
        │ schedules / weights / samples
        ▼
   Specialized Agent Coalition (Generation, Reflection, Proximity,
   Ranking, Evolution, Meta-review, Citation, Safety, Report, …)
        │ read/write
        ▼
   Persistence: Relational store + Vector store + (optional) Knowledge Graph
```

---

## 3. Orchestration runtimes (framework selection)

A frontier LLM is a stateless autocomplete engine; the **execution harness** supplies memory, state persistence, tool integration, sandboxing, and deterministic control. Harness responsibilities decoupled from the cognitive layer: orchestration (state transitions, branching, loops), state/memory (hierarchical), tool access + permissions (authorization gateway), retries/recovery (transaction-safe blocks, backoff), observability/tracing, and context assembly/handoffs.

### Framework comparison

| Framework | State & architecture | Cyclic loops | Tools & sandboxing | Observability | Suitability |
|---|---|---|---|---|---|
| **LangGraph** | centralized schema-validated state + persistence checkpointing | native cyclic/branching state machines | LangChain ecosystem; custom sandbox for code | LangSmith tracing | **High** — deterministic, complex, looping |
| **AutoGen** | dynamic message history | open-ended conversational loops (hard to control) | native local/Docker code exec | built-in telemetry | Moderate — collaborative debate, high token cost |
| **CrewAI** | role-based declarative tasks | mainly sequential/hierarchical | built-in tool library | basic telemetry | Low — prototyping; lacks control |
| **OpenAI Agents SDK / Claude Code** | thread-based provider runtime | basic handoffs, no rich state charts | native tool calls; Claude Code = file/system exec | provider ecosystem | Moderate — optimized but lock-in |
| **Google ADK** | Antigravity/Gemini-optimized | multi-agent pipelines, enterprise routing | native Science Skills + bio DBs | GCP enterprise monitoring | **High** — Gemini scientific workflows |
| **Semantic Kernel** | step-wise planners + kernel state | loops via custom planners | enterprise connectors | OpenTelemetry | Moderate — steep curve |
| **LlamaIndex / Haystack** | index-centric | basic routing | optimized RAG | native tracing | Moderate — build the retrieval layer here |

**Recommended:** hybrid **LangGraph (core state-machine coordinator) + Google ADK/Antigravity (specialized DB tool calls)**, giving deterministic control of the cyclic tournament/evolution loops with enterprise safety boundaries and execution-level checkpointing.

### The "Fred" hybrid pattern (LangGraph inside Temporal)
For maximum durability over multi-day runs, wrap LangGraph in **Temporal**:
- **Temporal** = outer durable execution substrate — transaction history, heartbeats, automatic backoff, async task queues, survival across worker crashes (requires deterministic workflow code).
- **LangGraph** = inner agent logic inside isolated long-running Temporal *Activities* — dynamic, tool-driven graph.
- History bloat is mitigated by Temporal **Continue-As-New** compaction + the **EvoScientist** persistent-memory framework (Ideation Memory + Experimentation Memory — see file `07`).

```text
ORCHESTRATION LAYER
Temporal Workflow (durable outer loop)
 ├─ Activity 1: Literature Grounding (durable)
 ├─ Activity 2: LangGraph Execution (dynamic inner loops)
 │     ├─ Node A: Hypothesis Generation
 │     ├─ Node B: Virtual Peer Review
 │     ├─ Node C: Pairwise Tournament Matches
 │     └─ Node D: Evolutionary Mutation
 └─ Activity 3: Citation Verification (durable)
```

### Persistence-substrate trade-offs

| Substrate | Advantages | Constraints | Checkpoint/replay |
|---|---|---|---|
| **LangGraph** | dynamic cyclical agent loops; native human-in-loop interrupts | execution loss on crash if not durably backed; manual state pruning | node-level checkpoint; full state dict to Postgres/InMemorySaver |
| **Temporal** | execution survival across crashes; built-in timers/retries/cancellation | strict determinism; event-history bloat | activity-level append-only event-history replay |
| **Google ADK** | decoupled from conversation logs; scale-to-zero | manual state-machine transitions; slower node transitions | tool-level atomic checkpoint via `ToolContext.state` |
| **Fred Hybrid** | LangGraph dynamism + Temporal resilience; portable workers | complex topology; high dev overhead | LangGraph wrapped in Temporal Activities; signals trigger inner checkpoints |

---

## 4. Recommended implementation stack (open-source reference)

A faithful, modern (2024–2026) reference build is a **LangGraph-orchestrated, FastAPI/Celery/Postgres monorepo**:

| Layer | Choice | Rationale |
|---|---|---|
| Orchestration | **LangGraph 1.0** (GA Oct 2025) | stable cyclic graphs + `PostgresSaver` durable checkpointing; auto-resume after restart |
| Long-running jobs | **Celery + Redis** behind FastAPI | canonical pattern for AI workloads exceeding HTTP timeouts |
| Hybrid retrieval | **pgvector + tsvector + RRF** (or `pg_textsearch` BM25) | eliminates Elasticsearch; native to Postgres |
| Frontend protocol | **AG-UI** over SSE (+ WebSocket dashboard) | first-class LangGraph integration via CopilotKit; ~17 typed event types |
| Sandboxing | **gVisor `runsc`** | proven at scale for agentic workloads; GKE Agent Sandbox default |
| Scientific retrieval | **MCP servers** (PubMed, Europe PMC, ChEMBL, UniProt) | production-ready bio-MCP servers; see file `06` |

> **Alternative substrate (single-node):** several clone docs use **SQLite with WAL** (`busy_timeout=5000ms`) as the durable task/state store for simpler deployments — fine for prototypes and single-worker runs. Postgres + pgvector is preferred for concurrency and hybrid search. See file `07` for the SQLite 15-table variant.

### Monorepo layout
```text
ai-coscientist/
├── docker-compose.yml            # api, worker, db (postgres+pgvector), redis, frontend
├── apps/
│   ├── api/        # FastAPI: routers (runs, interview, hypotheses, tournament,
│   │               #          reports, feedback, ws), deps, Pydantic schemas, middleware
│   ├── worker/     # Celery: run_orchestrator (invokes LangGraph), retrieval,
│   │               #         tournament; beat.py (periodic meta-review trigger)
│   └── frontend/   # React + Vite + Tailwind + CopilotKit (AG-UI)
│                   # HypothesisCard, EloLeaderboard, DebateTimeline, CitationVerifiedBadge
├── packages/
│   ├── coscientist_core/         # pure Python (no FastAPI deps)
│   │   ├── state.py              # LangGraph TypedDict + reducers
│   │   ├── graph.py              # build_graph() — compiles the cyclic StateGraph
│   │   ├── agents/               # supervisor, intake, literature, generation,
│   │   │                         # reflection, proximity, ranking, evolution,
│   │   │                         # metareview, citation_verifier, safety, report_synthesis
│   │   ├── prompts/              # Jinja2; ≥17 templates (one per agent.mode)
│   │   ├── elo.py                # update(R_A,R_B,S_A,K) — pure function
│   │   ├── tournament.py         # pairing policy
│   │   └── termination.py        # BUDGET / WALL_CLOCK / ELO_STABLE / IDLE / EXTERNAL
│   ├── coscientist_llm/          # router (opus/sonnet/opusplan aliases), providers, price_table, retry
│   ├── coscientist_retrieval/    # mcp_client, servers/, rate_limiter, hybrid_search (RRF k=60)
│   ├── coscientist_safety/       # classifier_pre (CBRN gate), classifier_post (LLM judge), tiers, audit_log
│   └── coscientist_observability/# langsmith, trace_store, metrics (Prometheus)
├── db/  (alembic/versions, seeds: gold_hypotheses_aml.json, gold_targets_fibrosis.json, safety_probes_cbrn.json)
├── tests/ (unit, integration, fidelity)
└── docs/  (ARCHITECTURE, AGENT_CONTRACTS, FIDELITY, diagrams)
```

Each `packages/*` exports a stable API, owns its tests, has **no upward imports**. Dependency DAG: `llm → retrieval → safety → core → observability → apps` — so an AI coding agent can be handed one package at a time. The riskiest module is Reflection's six review types (most of the quality gain).

---

## 5. PostgreSQL schema (core entities)

```sql
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  research_goal TEXT NOT NULL,
  plan_config JSONB NOT NULL,
  status TEXT NOT NULL CHECK (status IN
    ('scoping','running','paused','completed','failed','aborted')),
  termination_reason TEXT,               -- BUDGET / WALL_CLOCK / ELO_STABLE / IDLE / EXTERNAL
  budget_usd NUMERIC(10,4), wall_clock_s INT, cost_so_far NUMERIC(10,4) DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE interview_turns (
  id BIGSERIAL PRIMARY KEY, run_id UUID REFERENCES runs(id) ON DELETE CASCADE,
  role TEXT CHECK (role IN ('scientist','intake_agent')), content TEXT, extracted JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE hypotheses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID REFERENCES runs(id) ON DELETE CASCADE,
  parent_ids UUID[] DEFAULT '{}',
  origin_agent TEXT CHECK (origin_agent IN ('generation','evolution','scientist_manual')),
  origin_mode TEXT NOT NULL, summary TEXT NOT NULL, full_text TEXT NOT NULL, category TEXT,
  elo_rating INT NOT NULL DEFAULT 1200,  -- *** PAPER INVARIANT ***
  match_count INT NOT NULL DEFAULT 0,
  status TEXT CHECK (status IN ('pending_review','active','retired','duplicate','unsafe')),
  embedding vector(1536),                -- text-embedding-3-large or Voyage
  content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', full_text)) STORED,
  metadata JSONB DEFAULT '{}', created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_hyp_run ON hypotheses(run_id, elo_rating DESC);
CREATE INDEX idx_hyp_embedding ON hypotheses USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_hyp_tsv ON hypotheses USING GIN (content_tsv);

CREATE TABLE reviews (
  id BIGSERIAL PRIMARY KEY, hypothesis_id UUID REFERENCES hypotheses(id) ON DELETE CASCADE,
  review_type TEXT CHECK (review_type IN
    ('initial','full','deep_verification','observation','simulation','recurrent')),
  verdict TEXT CHECK (verdict IN ('pass','fail','revise')),
  scores JSONB NOT NULL,                 -- {correctness, quality, novelty, safety, testability}
  reasoning TEXT NOT NULL, cited_pmids TEXT[], created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE tournament_matches (
  id BIGSERIAL PRIMARY KEY, run_id UUID REFERENCES runs(id) ON DELETE CASCADE,
  hyp_a_id UUID REFERENCES hypotheses(id), hyp_b_id UUID REFERENCES hypotheses(id),
  mode TEXT CHECK (mode IN ('single_turn','multi_turn_debate')),
  winner_id UUID REFERENCES hypotheses(id),     -- NULL = draw
  rationale TEXT NOT NULL, debate_transcript JSONB, judge_model TEXT NOT NULL,
  k_factor INT NOT NULL,                 -- annealed 32→16→10
  elo_delta_a INT NOT NULL, elo_delta_b INT NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE elo_journal (
  hypothesis_id UUID REFERENCES hypotheses(id) ON DELETE CASCADE,
  ts TIMESTAMPTZ DEFAULT now(), elo INT NOT NULL, PRIMARY KEY (hypothesis_id, ts)
);

CREATE TABLE citations (
  id BIGSERIAL PRIMARY KEY,
  hypothesis_id UUID REFERENCES hypotheses(id) ON DELETE CASCADE,
  review_id BIGINT REFERENCES reviews(id) ON DELETE CASCADE,
  source TEXT CHECK (source IN ('pubmed','europe_pmc','chembl','uniprot','arxiv','manual')),
  external_id TEXT NOT NULL, doi TEXT, title TEXT, authors TEXT[], year INT, url TEXT,
  verification_tier TEXT CHECK (verification_tier IN
    ('tier1_id_exists','tier2_metadata_match','tier3_snippet_grounded')),
  verified_at TIMESTAMPTZ, raw JSONB,
  UNIQUE (source, external_id, hypothesis_id, review_id)
);

CREATE TABLE agent_trace_logs ( -- langsmith_trace_id, agent, mode, node_name, input/output_state,
  -- model_used, tokens_in/out, latency_ms, cost_usd, status(ok/retry/error/filtered), error_msg, ts
  id BIGSERIAL PRIMARY KEY, run_id UUID REFERENCES runs(id) ON DELETE CASCADE, ts TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE meta_critiques ( -- iteration, critique_md, applied_to TEXT[] (the agents it was injected into)
  id BIGSERIAL PRIMARY KEY, run_id UUID REFERENCES runs(id) ON DELETE CASCADE,
  iteration INT NOT NULL, critique_md TEXT NOT NULL, applied_to TEXT[] NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE scientist_feedback ( -- kind: directive / manual_hypothesis / manual_review / refine_goal
  id BIGSERIAL PRIMARY KEY, run_id UUID REFERENCES runs(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE safety_decisions ( -- target_kind, target_id, pre/post_classifier JSONB,
  -- decision: allow/redact/block, cbrn_categories TEXT[]
  id BIGSERIAL PRIMARY KEY, run_id UUID REFERENCES runs(id) ON DELETE CASCADE,
  decision TEXT CHECK (decision IN ('allow','redact','block')), ts TIMESTAMPTZ DEFAULT now()
);
-- LangGraph PostgresSaver auto-creates checkpoints / checkpoint_writes / checkpoint_blobs.
```

**Schema discipline:** JSONB is restricted to agent-specific unstructured fields (per-mode review scores, debate transcripts). Anything SQL-filtered (Elo, status, verification_tier) is a first-class column.

---

## 6. FastAPI endpoint map

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/runs` | create run; returns `run_id`; triggers Intake |
| `GET` | `/api/v1/runs` · `/{id}` | list / metadata + summary stats |
| `POST` | `/api/v1/runs/{id}/start` · `/pause` · `/resume` · `/abort` | lifecycle |
| `POST` | `/api/v1/runs/{id}/interview` | append scientist turn; returns Intake reply |
| `GET` | `/api/v1/runs/{id}/hypotheses?sort=elo&limit=20` | ranked leaderboard |
| `GET` | `/api/v1/runs/{id}/hypotheses/{hid}` · `/lineage` | full hyp + reviews + citations; ancestor/descendant graph |
| `GET` | `/api/v1/runs/{id}/tournament` · `/tournament/leaderboard` | matches + Elo time-series; top-K |
| `GET` | `/api/v1/runs/{id}/citations?verified=true` | verified citation list |
| `GET` | `/api/v1/runs/{id}/report` | Markdown/PDF NIH-format overview |
| `POST` | `/api/v1/runs/{id}/feedback` | directive / manual_hypothesis / manual_review / refine_goal |
| `GET` | `/api/v1/runs/{id}/trace?agent=&since=` | agent trace logs (paginated) |
| `WS` | `/api/v1/runs/{id}/stream` | AG-UI WebSocket (bidirectional) |
| `GET` | `/api/v1/runs/{id}/sse` · `/health` · `/metrics` | SSE fallback; health; Prometheus |

---

## 7. LangGraph orchestration graph

```python
# packages/coscientist_core/graph.py
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

class RunState(TypedDict):
    run_id: str; goal: str; plan_config: dict; iteration: int
    hypotheses: Annotated[list, lambda old, new: old + new]   # append-only reducer
    pending_reviews: list
    tournament_state: dict        # {hyp_id: elo}
    meta_critique: str            # latest critique appended to prompts
    summary_stats: dict
    terminate: bool; termination_reason: str | None

def build_graph(checkpointer):
    g = StateGraph(RunState)
    for n in ["intake","supervisor","literature","generation","reflection",
              "proximity","ranking","evolution","metareview",
              "safety","citation_verify","report"]:
        g.add_node(n, AGENTS[n])
    g.add_edge(START, "intake")
    g.add_edge("intake", "supervisor")
    g.add_conditional_edges("supervisor", supervisor_route, {
        "literature":"literature","generation":"generation","reflection":"reflection",
        "ranking":"ranking","evolution":"evolution","metareview":"metareview",
        "terminate":"report"})
    for n in ["literature","generation","reflection","ranking","evolution","proximity"]:
        g.add_edge(n, "supervisor")
    g.add_edge("metareview", "supervisor")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer, interrupt_before=["report"])
```

The Supervisor is the **adaptive planner**: it reads `summary_stats` (generated count, pending-review count, tournament progress, generation-vs-evolution effectiveness) and picks the next node by **weighted sampling**. `interrupt_before=["report"]` lets the scientist review before the NIH overview is finalized. (For human steering / "time travel," LangGraph checkpointing supports replaying and forking from any prior state; semantic provenance can be serialized with W3C PROV.)

### AG-UI event contract
The WS endpoint emits the ~17 standardized AG-UI event types: lifecycle (`RUN_STARTED`/`RUN_FINISHED`), text deltas (`TEXT_MESSAGE_CONTENT`), tool calls (`TOOL_CALL_START`/`TOOL_CALL_END`), state sync (`STATE_DELTA`), plus a `THINKING` channel separating internal reasoning from public output. The frontend's CopilotKit `<HttpAgent>` consumes these directly. `STATE_DELTA` drives reactive leaderboard updates.

---

## 8. The immutable, evidence-gated control plane (ResearchLoop)

Because autonomous agent outputs become hard to audit over long runs, the backend enforces structural integrity via an **append-only, Git-versioned file system** treating queries, task contracts, outputs, and claim ledgers as durable project state.

```text
RESEARCH_SPINE (research-question definition)
   → TASKS.yaml (execution assignment)
   → RUNS/ Manifest (evidence artifact)
   → EVIDENCE_GATE Validation
        ├─ Predicate Passes → Claim Admitted (PAPER_CLAIM_LEDGER.yaml)
        └─ Predicate Fails  → Claim Rejected (STATUS blocked)
```

Workflow: **(1) RQ-to-claim binding** — every task maps to a sub-RQ in `RESEARCH_SPINE.yaml` (target hypothesis, falsification conditions, required metrics). **(2) State enforcement** — tasks move `defined → active → completed → evaluated`; blockers set `blocked`/`failed`, locking downstream steps. **(3) The Evidence Gate** — a candidate claim enters the final proposal only if it passes `EVIDENCE_GATE.yaml` predicates, checked programmatically.

```yaml
# STATUS.yaml
epoch_version: "V3"
status: "active"               # active, blocked, closed_stable, closed_negative, validation_ready
current_gate: "G3_DEBATE_REFINEMENT"
focus_rq: "RQ-02"
active_tasks: [{task_id: "TASK-104", assigned_worker: "ranking_agent_03"}]

# RESEARCH_SPINE.yaml
research_direction: "Identify novel epigenetic targets for liver fibrosis."
decomposed_questions:
  - rq_id: "RQ-02"
    hypothesis: "Inhibition of Target-Y blocks scarring-linked gene expression."
    falsification_condition: "Target-Y silencing fails to reduce scar markers in vitro."
    metric_specification: "Expression-level threshold changes (p < 0.01)."
    task_queue: [{task_id: "TASK-104", status: "completed", evidence_reference: "runs/run_...v3.json"}]

# EVIDENCE_GATE.yaml
gate_id: "G3_DEBATE_REFINEMENT"
predicates:
  - {predicate_id: "P-01", description: "Every hypothesis supported by ≥2 distinct verified PMIDs.",
     inspection_check: "scripts/verify_pubmed_citations.py", required: true, status: "passed"}
  - {predicate_id: "P-02", description: "Reflection critique verifies target specificity in primary tissue.",
     inspection_check: "agents/reflection_specificity_check.py", required: true, status: "pending"}
allowed_claims: ["Target-Y knockdown reduces cellular scar gene expression in simulated models."]
forbidden_claims: ["Target-Y regulates broader cellular aging loops without direct evidence."]
```

Once predicates pass, verified claims are logged in `PAPER_CLAIM_LEDGER.yaml` — the authoritative source of truth ensuring the final proposal contains only evidence-backed, cited claims.

---

## 9. MCP integration and the stateful-skill distinction

A key design choice: **stateless MCP tools** vs **stateful agent skills**.
- **MCP tools** — external, stateless, execution-focused; the model's access points to the world (PubMed, ChEMBL, UniProt, web). See file `06` for the retrieval servers and rate limits.
- **Agent skills** — internal, stateful, process-oriented; written in Markdown with YAML frontmatter ("Agent Skills" standard). They govern *how* agents use MCP tools, execute reasoning, and manage context.

```text
Agent Skill (e.g. framing-research-questions)  →  instructs agent on logic/process
                                                →  invokes MCP Tool (e.g. pubmed-mcp)
```

### Progressive disclosure for tool definitions
Registering 30+ narrow skills (one per database) imposes a persistent context tax on every call. Instead, register a **single consolidated database-lookup skill** with a minimal one-line description, powered by an internal router that maps intent → database, resolves cross-system identifiers (gene symbol → Ensembl ID), and loads detailed reference files only when a domain is triggered.

| Dimension | 30+ separate skills | Consolidated lookup skill |
|---|---|---|
| Always-on token cost | ~3,358 tokens | ~242 tokens |
| Deferred-load ratio | 0% | ~93% kept out of context until needed |
| Cross-domain handling | low | high (central router) |
| Fault recovery | poor (no fallback) | robust (router falls back to alt DBs) |
| Extensibility | new agent skill per DB | PR adds a reference file + router rule |

The `science-skills` toolkit ties models to UniProt, ChEMBL, AlphaFold DB, ClinVar, dbSNP, Reactome, and the Human Protein Atlas. (See also the **"Science Superpowers"** ten-skill framework in file `09`, which adds pre-registration discipline.)

---

## 10. Asynchronous backend, durability, and safety isolation

- **Job queue & task runner** — durable task DB (Postgres + Celery/Redis, or SQLite-WAL for single-node); leased tasks with `lease_expires_at` + `retry_count`; bounded concurrency; periodic meta-review trigger (Celery beat).
- **Safety sandbox / execution firewall** — gVisor `runsc` for any code execution; required for porting Sakana-style code-running components (file `09`).
- **Dual-agent safety architecture (Planner/Talker)** — active "Talker" agents generate hypotheses/protocols while a separate "Planner/Guardian" continuously monitors inputs, outputs, and DB requests with CBRN/dual-use classifiers. On violation it **overrides the Supervisor, halts execution, and records the block in the Git audit history**. (Full safety detail in file `06`.)
- **Observability** — instrument every model call, tool exec, and state transition; trace streams feed LangSmith + Prometheus + cost tracking.

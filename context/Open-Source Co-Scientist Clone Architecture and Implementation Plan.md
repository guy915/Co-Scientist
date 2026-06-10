# Open-Source AI Co-Scientist Clone — Technical Architecture & Phased Implementation Plan

## TL;DR
- **Build a LangGraph-orchestrated, FastAPI/Celery/Postgres-backed monorepo that faithfully reproduces the seven-agent (Supervisor + Generation + Reflection + Ranking + Evolution + Proximity + Meta-review) generate-debate-evolve loop from Gottweis et al. (arXiv 2502.18864, *Nature* 2026), plus five clone-specific agents (Intake, Literature Retrieval, Citation Verification, Safety, Report Synthesis) — implemented in five phases starting with the DB+API skeleton and ending with the AG-UI dashboard and the NIH-format research-overview generator.**
- **The three fidelity invariants that distinguish a clone from a generic multi-agent RAG system are: (a) initial Elo rating = 1200 with multi-turn debate for top-ranked hypotheses and single-turn comparison for lower-ranked ones, (b) the Evolution agent *generates new hypotheses, never modifies existing ones* ("each new hypothesis must also compete in the tournament" — §3.3.5), and (c) the Meta-Review critique is *appended to every other agent's prompt in the next iteration*, which is how the system "continuously learns and improves... without back-propagation techniques."**
- **For Claude Code (opusplan-routed) to build this autonomously, the repo must be sliced into ~14 independently testable modules with a strict bottom-up dependency DAG (`llm → retrieval → safety → core → observability → apps`); the riskiest module is the Reflection agent's six review types (initial / full / deep verification / observation / simulation / tournament-recurrent), which together account for most of the system's hypothesis-quality gain.**

---

## Key Findings

### 1. What "1:1 fidelity" actually means
The DeepMind paper specifies exactly which agents exist, their I/O contracts, and the qualitative behavior of each — but **leaves several implementation details unspecified**: the Elo K-factor, the embedding model used by Proximity, the termination predicates of the Supervisor, and the schema of the persistent "context memory." A faithful clone must therefore (a) match every behavioral invariant the paper does specify and (b) make reasonable, configurable, well-documented choices for the rest. Our plan locks the specified behaviors into automated tests and exposes the under-specified ones as TOML config.

### 2. Stack alignment with current best practices (2024–2026)

| Layer | Choice | Why it matches state of the art |
|---|---|---|
| Orchestration | **LangGraph 1.0** | GA October 22, 2025; per LangChain's official changelog: *"LangGraph 1.0 is the first stable major release in the durable agent framework space — a major milestone for production-ready AI systems. After more than a year of powering agents at companies like Uber, LinkedIn, and Klarna, LangGraph is officially v1."* Cyclic graphs + `PostgresSaver` checkpointing deliver *"Durable state: Agent execution state persists automatically. If your server restarts mid-conversation or a long-running workflow gets interrupted, it picks up exactly where it left off without losing context."* |
| Long-running jobs | **Celery + Redis** behind FastAPI | The canonical pattern for AI workloads that exceed HTTP timeouts (TestDriven.io's "Definitive Guide to Celery and FastAPI"; OneUptime's FastAPI + Postgres + Celery template). |
| Hybrid retrieval | **pgvector + tsvector + RRF** (or `pg_textsearch` BM25) | Eliminates Elasticsearch; native to Postgres; ParadeDB / TigerData / VectorChord all converged on Reciprocal Rank Fusion over BM25 + dense in 2025. |
| Frontend protocol | **AG-UI** over SSE (primary) + WebSocket (dashboard) | First-class LangGraph integration via CopilotKit; **17 typed event types** standardize agent→UI streaming (per CopilotKit's "Master the 17 AG-UI Event Types for Building Agents the Right Way"; the AG-UI GitHub README still hedges with *"~16 standard event types"*). Categories include lifecycle (`RUN_STARTED`, `RUN_FINISHED`), text-message deltas (`TEXT_MESSAGE_CONTENT`), tool-call lifecycle (`TOOL_CALL_START`, `TOOL_CALL_END`), and state synchronization (`STATE_DELTA`). |
| Sandboxing | **gVisor `runsc`** | Per the April 23, 2026 gvisor.dev post by Tencent engineers Yifeng Tan, Hua Liu, and Hui Chen: *"we successfully investigated and resolved gVisor compatibility issues that accounted for approximately 1.7% of all test cases"* — Tencent runs millions of gVisor sandboxes daily for agentic-RL training. GKE's Agent Sandbox CRD ships gVisor as the default on Autopilot clusters. |
| Scientific retrieval | **MCP servers** for PubMed, Europe PMC, ChEMBL, UniProt | Per NCBI's official E-utilities documentation: *"NCBI recommends that users post no more than three URL requests per second"*, and per NCBI Insights blog: *"By including an API key, a site can post up to 10 requests per second by default."* BioMCP / TogoMCP / ChEMBL-MCP-Server (22 specialized tools) are production-ready in 2025–26; UniProt's REST API at `rest.uniprot.org` exposes a `search`/`stream` contract with `X-Total-Results` and pagination headers (Ahmad et al., *Nucleic Acids Research* 53:W547, 2025). |

### 3. The fidelity-critical behaviors (verbatim from arXiv 2502.18864 §3.3)
Verified against the source PDF and the Kaimen-Inc/Co-Scientist `reference/` folder, which mirrors the *Nature* 2026 Supplementary Notes 8 (pseudocode) and 9 (prompts):

- **Generation** has four modes: literature exploration via web search; simulated scientific debates (self-play, multi-turn); iterative assumptions identification; research expansion (informed by Meta-Review feedback).
- **Reflection** has six review types: initial (no tools); full (with web search); deep verification (decompose hyp → assumptions → sub-assumptions, decontextualize each, assess fundamental-ness of any failure); observation review (does the hyp explain long-tail prior observations?); simulation review (step-wise mechanism-of-action simulation); recurrent/tournament-informed review.
- **Ranking**: Elo with **initial rating 1200** (paper-specified). Multi-turn debate for top-ranked hypotheses, single-turn comparison for lower-ranked. Pairings prioritize (1) similar hypotheses per the Proximity graph and (2) newer / top-ranked hypotheses. Comparison criteria: **novelty, correctness, testability**. The K-factor is **not specified by the paper** — clone-defined.
- **Evolution**: six strategies (enhancement through grounding; coherence/practicality/feasibility; inspiration from existing top-ranked; combination; simplification; out-of-box). Critical invariant (§3.3.5): *"The Evolution agent generates new hypotheses; it doesn't modify or replace existing ones."*
- **Proximity**: builds a proximity graph used for clustering, dedup, and tournament pairing. Embedding model and clustering algorithm are not specified by the paper.
- **Meta-Review**: produces (a) a critique that is *"simply appended to [other agents'] prompts in the next iteration"*, (b) the **research overview** formatted as an **NIH Specific Aims Page** with sections **disease description / unmet need / proposed solutions / specific aims** (each aim contains overarching goal + hypothesis + rationale + pre-clinical experiment plan + endpoints + translational component), and (c) suggested expert contacts derived from prior literature.
- **Supervisor**: parses goal → research plan configuration → durable task queue with bounded concurrency. Periodically computes summary statistics including number of hypotheses generated, number requiring review, tournament progress, and effectiveness of generation-vs-evolution. *"These statistics inform decisions regarding resource allocation and the determination of whether a terminal state for the overall computation has been reached."* The exact termination predicates are clone-defined.

---

## Details

### A. Repository Structure (Monorepo)

```
ai-coscientist/
├── README.md
├── pyproject.toml                  # uv-managed; Python 3.11–3.13
├── docker-compose.yml              # local dev: api, worker, db, redis, frontend
├── docker-compose.prod.yml         # gunicorn + gVisor sandbox + healthchecks
├── .env.example
├── alembic.ini
│
├── apps/
│   ├── api/                        # FastAPI (HTTP + WebSocket + SSE)
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── runs.py             # POST/GET /runs, lifecycle
│   │   │   ├── interview.py        # /runs/{id}/interview — goal scoping
│   │   │   ├── hypotheses.py
│   │   │   ├── tournament.py
│   │   │   ├── reports.py
│   │   │   ├── feedback.py
│   │   │   └── ws.py               # AG-UI WebSocket + SSE
│   │   ├── deps.py                 # DI: db session, settings, current user
│   │   ├── schemas/                # Pydantic v2
│   │   └── middleware/             # rate limit, request-id, CORS
│   │
│   ├── worker/                     # Celery
│   │   ├── celery_app.py
│   │   ├── tasks/
│   │   │   ├── run_orchestrator.py # invokes LangGraph compiled graph
│   │   │   ├── retrieval.py        # MCP-backed lit-search jobs
│   │   │   └── tournament.py       # batched pairwise debates
│   │   └── beat.py                 # periodic meta-review trigger
│   │
│   └── frontend/                   # React + Vite + Tailwind + CopilotKit (AG-UI)
│       ├── src/
│       │   ├── App.tsx
│       │   ├── pages/
│       │   │   ├── NewRun.tsx
│       │   │   ├── RunDashboard.tsx
│       │   │   └── Report.tsx
│       │   ├── components/
│       │   │   ├── HypothesisCard.tsx
│       │   │   ├── EloLeaderboard.tsx
│       │   │   ├── DebateTimeline.tsx
│       │   │   └── CitationVerifiedBadge.tsx
│       │   └── lib/agui-client.ts
│       └── tailwind.config.ts
│
├── packages/
│   ├── coscientist_core/           # pure Python, no FastAPI deps
│   │   ├── state.py                # LangGraph TypedDict + reducers
│   │   ├── graph.py                # build_graph() — compiles the cyclic StateGraph
│   │   ├── agents/
│   │   │   ├── base.py
│   │   │   ├── supervisor.py
│   │   │   ├── intake.py
│   │   │   ├── literature.py
│   │   │   ├── generation.py       # 4 modes
│   │   │   ├── reflection.py       # 6 reviews
│   │   │   ├── proximity.py        # FAISS/pgvector clustering
│   │   │   ├── ranking.py          # Elo tournament; pairing policy
│   │   │   ├── evolution.py        # 6 strategies; INVARIANT: produces NEW hyps only
│   │   │   ├── metareview.py       # critique + NIH overview
│   │   │   ├── citation_verifier.py# VaaS — tiered citation grounding
│   │   │   ├── safety.py           # dual-agent CBRN classifier
│   │   │   └── report_synthesis.py
│   │   ├── prompts/                # Jinja2; one per agent.mode (≥17 templates)
│   │   ├── elo.py                  # update(R_A,R_B,S_A,K) — pure function
│   │   ├── tournament.py           # pairing policy
│   │   └── termination.py          # BUDGET / WALL_CLOCK / ELO_STABLE / IDLE / EXTERNAL
│   │
│   ├── coscientist_llm/
│   │   ├── router.py               # aliases: opus, sonnet, opusplan
│   │   ├── providers/
│   │   │   ├── anthropic.py        # Opus 4.8/4.7 plan, Sonnet 4.6 exec
│   │   │   ├── openai.py
│   │   │   └── gemini.py
│   │   ├── price_table.py
│   │   ├── token_budget.py
│   │   └── retry.py                # tenacity exp-backoff on 429/5xx
│   │
│   ├── coscientist_retrieval/
│   │   ├── mcp_client.py
│   │   ├── servers/
│   │   │   ├── pubmed.py           # Entrez E-utils; 3 req/s default, 10 with API key
│   │   │   ├── europe_pmc.py       # EBI REST /search, /fullTextXML
│   │   │   ├── chembl.py
│   │   │   └── uniprot.py          # rest.uniprot.org/uniprotkb/search
│   │   ├── rate_limiter.py         # token-bucket; polite-pool headers
│   │   └── hybrid_search.py        # pgvector + tsvector + RRF (k=60)
│   │
│   ├── coscientist_safety/
│   │   ├── classifier_pre.py       # fastText CBRN keyword/topic gate
│   │   ├── classifier_post.py      # LLM-as-judge with WMDP-style probes
│   │   ├── tiers.py                # L1/L2/L3 sanitization
│   │   └── audit_log.py
│   │
│   └── coscientist_observability/
│       ├── langsmith.py
│       ├── trace_store.py
│       └── metrics.py              # Prometheus
│
├── db/
│   ├── alembic/versions/
│   └── seeds/
│       ├── gold_hypotheses_aml.json
│       ├── gold_targets_fibrosis.json
│       └── safety_probes_cbrn.json
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fidelity/                   # 9-category rubric + eval runner
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── AGENT_CONTRACTS.md
│   ├── FIDELITY.md
│   └── diagrams/
│
└── scripts/
    ├── dev_up.sh
    ├── bench.py                    # cross-model Elo tournament
    └── fidelity_eval.py
```

Each `packages/*` package exports a stable Python API from `__init__.py`, owns its `tests/` subdir, and has **no upward imports**. The dependency DAG (`llm → retrieval → safety → core → observability → apps`) lets Claude Code receive one package at a time.

---

### B. PostgreSQL Schema

```sql
-- V1__init.sql — core entities

CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- BM25: optionally install pg_textsearch (TigerData) OR rely on tsvector+ts_rank_cd

CREATE TABLE runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL,
  research_goal   TEXT NOT NULL,
  plan_config     JSONB NOT NULL,
  status          TEXT NOT NULL CHECK (status IN
                  ('scoping','running','paused','completed','failed','aborted')),
  termination_reason TEXT,                    -- BUDGET / WALL_CLOCK / ELO_STABLE / IDLE / EXTERNAL
  budget_usd      NUMERIC(10,4),
  wall_clock_s    INT,
  cost_so_far     NUMERIC(10,4) DEFAULT 0,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_runs_user ON runs(user_id, created_at DESC);

CREATE TABLE interview_turns (
  id          BIGSERIAL PRIMARY KEY,
  run_id      UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  role        TEXT NOT NULL CHECK (role IN ('scientist','intake_agent')),
  content     TEXT NOT NULL,
  extracted   JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hypotheses (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id          UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  parent_ids      UUID[] DEFAULT '{}',
  origin_agent    TEXT NOT NULL CHECK (origin_agent IN
                  ('generation','evolution','scientist_manual')),
  origin_mode     TEXT NOT NULL,
  summary         TEXT NOT NULL,
  full_text       TEXT NOT NULL,
  category        TEXT,
  elo_rating      INT NOT NULL DEFAULT 1200,   -- *** PAPER INVARIANT ***
  match_count     INT NOT NULL DEFAULT 0,
  status          TEXT NOT NULL CHECK (status IN
                  ('pending_review','active','retired','duplicate','unsafe')),
  embedding       vector(1536),                -- text-embedding-3-large or Voyage
  content_tsv     TSVECTOR
                  GENERATED ALWAYS AS (to_tsvector('english', full_text)) STORED,
  metadata        JSONB DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_hyp_run ON hypotheses(run_id, elo_rating DESC);
CREATE INDEX idx_hyp_embedding ON hypotheses USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_hyp_tsv ON hypotheses USING GIN (content_tsv);
CREATE INDEX idx_hyp_parents ON hypotheses USING GIN (parent_ids);

CREATE TABLE reviews (
  id              BIGSERIAL PRIMARY KEY,
  hypothesis_id   UUID NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
  review_type     TEXT NOT NULL CHECK (review_type IN
                  ('initial','full','deep_verification','observation','simulation','recurrent')),
  verdict         TEXT NOT NULL CHECK (verdict IN ('pass','fail','revise')),
  scores          JSONB NOT NULL,             -- {correctness, quality, novelty, safety, testability}
  reasoning       TEXT NOT NULL,
  cited_pmids     TEXT[],
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tournament_matches (
  id              BIGSERIAL PRIMARY KEY,
  run_id          UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  hyp_a_id        UUID NOT NULL REFERENCES hypotheses(id),
  hyp_b_id        UUID NOT NULL REFERENCES hypotheses(id),
  mode            TEXT NOT NULL CHECK (mode IN ('single_turn','multi_turn_debate')),
  winner_id       UUID REFERENCES hypotheses(id),    -- NULL = draw
  rationale       TEXT NOT NULL,
  debate_transcript JSONB,
  judge_model     TEXT NOT NULL,
  k_factor        INT NOT NULL,               -- annealed 32→16→10
  elo_delta_a     INT NOT NULL,
  elo_delta_b     INT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE elo_journal (
  hypothesis_id   UUID NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
  ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
  elo             INT NOT NULL,
  PRIMARY KEY (hypothesis_id, ts)
);

CREATE TABLE citations (
  id              BIGSERIAL PRIMARY KEY,
  hypothesis_id   UUID REFERENCES hypotheses(id) ON DELETE CASCADE,
  review_id       BIGINT REFERENCES reviews(id) ON DELETE CASCADE,
  source          TEXT NOT NULL CHECK (source IN
                  ('pubmed','europe_pmc','chembl','uniprot','arxiv','manual')),
  external_id     TEXT NOT NULL,
  doi             TEXT,
  title           TEXT,
  authors         TEXT[],
  year            INT,
  url             TEXT,
  verification_tier TEXT NOT NULL CHECK (verification_tier IN
                  ('tier1_id_exists','tier2_metadata_match','tier3_snippet_grounded')),
  verified_at     TIMESTAMPTZ,
  raw             JSONB,
  UNIQUE (source, external_id, hypothesis_id, review_id)
);

CREATE TABLE agent_trace_logs (
  id              BIGSERIAL PRIMARY KEY,
  run_id          UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  langsmith_trace_id TEXT,
  agent           TEXT NOT NULL,
  mode            TEXT,
  node_name       TEXT NOT NULL,
  input_state     JSONB,
  output_state    JSONB,
  model_used      TEXT,
  tokens_in       INT,
  tokens_out      INT,
  latency_ms      INT,
  cost_usd        NUMERIC(10,6),
  status          TEXT NOT NULL CHECK (status IN ('ok','retry','error','filtered')),
  error_msg       TEXT,
  ts              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE meta_critiques (
  id              BIGSERIAL PRIMARY KEY,
  run_id          UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  iteration       INT NOT NULL,
  critique_md     TEXT NOT NULL,
  applied_to      TEXT[] NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE scientist_feedback (
  id              BIGSERIAL PRIMARY KEY,
  run_id          UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  kind            TEXT NOT NULL CHECK (kind IN
                  ('directive','manual_hypothesis','manual_review','refine_goal')),
  payload         JSONB NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE safety_decisions (
  id              BIGSERIAL PRIMARY KEY,
  run_id          UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  target_kind     TEXT NOT NULL,
  target_id       TEXT NOT NULL,
  pre_classifier  JSONB NOT NULL,
  post_classifier JSONB NOT NULL,
  decision        TEXT NOT NULL CHECK (decision IN ('allow','redact','block')),
  cbrn_categories TEXT[],
  ts              TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- LangGraph PostgresSaver auto-creates checkpoints/checkpoint_writes/checkpoint_blobs.
```

JSONB is restricted to *agent-specific unstructured fields* (per-mode review scores, debate transcripts). Anything SQL-filtered (Elo, status, verification_tier) is a first-class column.

---

### C. FastAPI Endpoint Map

| Method | Path | Purpose | Auth |
|---|---|---|---|
| `POST` | `/api/v1/runs` | Create run; returns `run_id`, triggers Intake | user |
| `GET` | `/api/v1/runs` | List runs | user |
| `GET` | `/api/v1/runs/{id}` | Run metadata + summary stats | user |
| `POST` | `/api/v1/runs/{id}/start` | `scoping → running`; enqueues Supervisor task | user |
| `POST` | `/api/v1/runs/{id}/pause` / `/resume` / `/abort` | Lifecycle | user |
| `POST` | `/api/v1/runs/{id}/interview` | Append scientist turn; returns Intake reply | user |
| `GET` | `/api/v1/runs/{id}/hypotheses?sort=elo&limit=20` | Ranked leaderboard | user |
| `GET` | `/api/v1/runs/{id}/hypotheses/{hid}` | Full hyp + lineage + reviews + citations | user |
| `GET` | `/api/v1/runs/{id}/hypotheses/{hid}/lineage` | Recursive ancestor/descendant graph | user |
| `GET` | `/api/v1/runs/{id}/tournament` | Recent matches + Elo time-series | user |
| `GET` | `/api/v1/runs/{id}/tournament/leaderboard` | Top-K by Elo | user |
| `GET` | `/api/v1/runs/{id}/citations?verified=true` | Verified citation list | user |
| `GET` | `/api/v1/runs/{id}/report` | Markdown/PDF NIH-format overview | user |
| `POST` | `/api/v1/runs/{id}/feedback` | `directive` / `manual_hypothesis` / `manual_review` / `refine_goal` | user |
| `GET` | `/api/v1/runs/{id}/trace?agent=&since=` | Agent trace logs (paginated) | user/admin |
| `WS` | `/api/v1/runs/{id}/stream` | AG-UI WebSocket — bidirectional | user |
| `GET` | `/api/v1/runs/{id}/sse` | SSE fallback | user |
| `GET` | `/health` / `/metrics` | Health + Prometheus | infra |

**AG-UI event contract.** The WS endpoint emits the 17 standardized AG-UI event types per the protocol spec — lifecycle (`RUN_STARTED`/`RUN_FINISHED`), text-deltas (`TEXT_MESSAGE_CONTENT`), tool calls (`TOOL_CALL_START`/`TOOL_CALL_END`), state synchronization (`STATE_DELTA`), and a separate `THINKING` channel for separating internal reasoning from public responses. The frontend's CopilotKit `<HttpAgent>` adapter consumes these directly.

---

### D. LangGraph Orchestration Graph

```
                     ┌─────────────────────────┐
START ─▶ Intake ──▶  │  Supervisor (planner)   │ ◀── feedback / interrupt
                     └────────────┬────────────┘
                                  │ (conditional edges based on summary stats)
       ┌──────────────┬───────────┼───────────┬──────────────┬─────────────┐
       ▼              ▼           ▼           ▼              ▼             ▼
  Literature    Generation   Reflection    Ranking      Evolution      Proximity
  Retrieval    (4 modes)    (6 reviews)   (Elo tour.)  (6 strategies) (cluster/dedup)
       │              │           │           │              │             │
       └──────────────┴───────────┼───────────┴──────────────┴─────────────┘
                                  ▼
                          ┌─────────────────┐
                          │   Meta-Review   │ ── critique appended to
                          └────────┬────────┘    every agent's next prompt
                                   │
                       ┌───────────┴───────────┐
                       │  Safety + Citation     │
                       │  Verification (gates)  │
                       └───────────┬───────────┘
                                   │
                          terminate? ─NO──▶ back to Supervisor
                                   │YES
                                   ▼
                           Report Synthesis ─▶ END
```

```python
# packages/coscientist_core/graph.py
from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver

class RunState(TypedDict):
    run_id: str
    goal: str
    plan_config: dict
    iteration: int
    hypotheses: Annotated[list, lambda old, new: old + new]   # append-only reducer
    pending_reviews: list
    tournament_state: dict             # {hyp_id: elo}
    meta_critique: str                 # latest critique appended to prompts
    summary_stats: dict
    terminate: bool
    termination_reason: str | None

def build_graph(checkpointer):
    g = StateGraph(RunState)
    for n in ["intake","supervisor","literature","generation","reflection",
              "proximity","ranking","evolution","metareview",
              "safety","citation_verify","report"]:
        g.add_node(n, AGENTS[n])

    g.add_edge(START, "intake")
    g.add_edge("intake", "supervisor")
    g.add_conditional_edges("supervisor", supervisor_route, {
        "literature": "literature", "generation": "generation",
        "reflection": "reflection", "ranking": "ranking",
        "evolution": "evolution", "metareview": "metareview",
        "terminate": "report",
    })
    for n in ["literature","generation","reflection","ranking","evolution","proximity"]:
        g.add_edge(n, "supervisor")
    g.add_edge("metareview", "supervisor")
    g.add_edge("report", END)

    return g.compile(checkpointer=checkpointer, interrupt_before=["report"])
```

The Supervisor is the adaptive planner from the paper: it reads `summary_stats` (number generated, number pending review, tournament progress, generation-vs-evolution effectiveness) and picks the next node by weighted sampling. `interrupt_before=["report"]` lets the scientist review before the NIH overview is finalized.

---

### E. Phased Build Sequence

#### Phase 1 — Foundations (Week 1–2)
- `docker-compose.yml` (postgres+pgvector, redis, api, worker)
- Alembic migrations V1+V2 (all tables above)
- FastAPI app with `/runs` CRUD, `/health`, request-id middleware
- Celery worker consuming a dummy LangGraph (`generation → reflection → END`)
- LangGraph PostgresSaver wired up; resume-after-kill test passes
- `coscientist_llm` with Anthropic/OpenAI/Gemini providers and alias routing (`opus`, `sonnet`, `opusplan`)
- LangSmith tracing default-on in dev

**Acceptance:** `make dev-up && curl -X POST /runs -d '{"goal":"..."}'` returns a `run_id`; worker writes ≥3 rows to `agent_trace_logs`; killing the worker mid-run and restarting resumes from the last checkpoint with zero duplicates.

#### Phase 2 — Retrieval Layer (Week 3)
- MCP client + four servers (PubMed @ 3 req/s default / 10 with `NCBI_API_KEY`, Europe PMC `webservices/rest/search`, ChEMBL, UniProt `rest.uniprot.org/uniprotkb/search`)
- `hybrid_search.py` — pgvector cosine + tsvector `ts_rank_cd` fused via Reciprocal Rank Fusion (k=60)
- Citation Verification agent with three tiers: (1) external_id resolves, (2) title/authors fuzzy-match the agent's claim, (3) snippet is grounded in retrieved abstract via NLI

**Acceptance:** integration test on "drug repurposing candidates for AML" — ≥80% of cited works reach tier-2; ≥50% reach tier-3.

#### Phase 3 — Core Multi-Agent Loop (Week 4–6) — **critical phase**
- Generation: all 4 modes (literature_review / sim_debate / assumptions / expansion); sim_debate runs a 3-turn self-play
- Reflection: all 6 review types; initial = no tools; full = web search; deep_verification = tree decomposition
- Proximity: embed every new hyp (text-embedding-3-large or Voyage-3); kNN graph used by Ranking
- Ranking: pure-Python `elo.py` with annealed K (32 for first 30 matches per hyp, 16 next 470, 10 thereafter — a documented clone choice); initial rating **1200** (paper invariant); pairing policy: 60% similar-via-Proximity, 30% newer-or-top-ranked, 10% random exploration; single-turn for matches where both Elo < median, 3-turn debate otherwise
- Evolution: 6 strategies, each returning a **new** hypothesis row (paper invariant); `parent_ids` records lineage
- Meta-Review: every N supervisor cycles; writes `meta_critiques`; critique string injected into every other agent's system prompt for the next iteration
- Supervisor termination predicates: `BUDGET` / `WALL_CLOCK` / `ELO_STABLE` (top-5 Δ < 5 over 50 matches) / `IDLE` / `EXTERNAL`
- Safety dual-agent filter wraps Intake input and every Generation/Evolution output

**Acceptance:** end-to-end run on the AML drug-repurposing goal completes in ≤30 min at `--budget-usd 5`; produces ≥10 hypotheses; ≥3 of the paper's named candidates (Binimetinib, Pacritinib, KIRA6, Leflunomide) appear in the final top-10 or as fuzzy matches; Meta-Review critique demonstrably changes the next Generation prompt (snapshot diff test).

#### Phase 4 — Tournament Telemetry & UI (Week 7–8)
- React+Tailwind frontend; CopilotKit `HttpAgent` adapter on `/api/v1/runs/{id}/stream`
- Three pages: NewRun wizard, RunDashboard (live Elo leaderboard, debate timeline, verified-citation badges), Report renderer
- AG-UI event mapping: `STATE_DELTA` updates leaderboard reactively; `TEXT_MESSAGE_CONTENT` streams reasoning; `TOOL_CALL_*` shows MCP queries in flight
- SSE fallback for WS-blocking proxies

**Acceptance:** hypothesis cards appear within 2 s of DB insert; Elo numbers tick live.

#### Phase 5 — Report Generation & Fidelity Harness (Week 9–10)
- Report Synthesis renders top-K hypotheses into NIH Specific Aims format (disease description / unmet need / proposed solutions / specific aims — each aim = goal + hypothesis + rationale + experimental plan + endpoints + translational component)
- Suggested-contacts section: Meta-Review queries PubMed for recurring authors in cited papers
- `tests/fidelity/eval_runner.py` runs the 9-category rubric against gold sets, emits a Markdown scorecard
- `scripts/bench.py` — cross-model Elo tournament (same goal under N model configs, one fixed judge)

**Acceptance:** fidelity scorecard ≥ 80% on every category against the paper's three case studies (AML, liver fibrosis, cf-PICI).

---

### F. Testing Strategy

| Layer | Tooling | Examples |
|---|---|---|
| **Unit — pure functions** | pytest + hypothesis | `elo.py` (idempotence, monotonicity, K-decay); `tournament.py` (pairing invariants) |
| **Unit — agents** | pytest + VCR.py cassettes; snapshot tests | Each agent: fixture state → output schema + key invariants (e.g., `Evolution.out.id ∉ Evolution.in.ids`) |
| **Prompt snapshot** | syrupy | Rendered Jinja prompts hashed; PR fails if a prompt changes without an explicit fidelity review |
| **Integration** | pytest + testcontainers (postgres, redis) | Full `intake → … → report` on a 60-s budget; resume-from-checkpoint test |
| **Retrieval** | live MCP under `RUN_LIVE_MCP=1` | PubMed rate limiting, Europe PMC search, ChEMBL bioactivity, UniProt accession |
| **Safety** | WMDP + FORTRESS-subset probes | Dual-agent filter blocks all CBRN-uplift prompts; false-positive on benign biology ≤ 5% |
| **Fidelity** | `tests/fidelity/eval_runner.py` | See §G |
| **Load** | Locust | 50 concurrent runs; checkpoint write p95 < 100 ms |

```python
def test_evolution_never_modifies_existing():
    state = seed_state_with_top_hypotheses(n=5)
    new_state = evolution_agent(state, strategy="combination")
    assert all(h.id not in {x.id for x in state.hypotheses} for h in new_state.hypotheses[-2:])
    assert len(new_state.hypotheses[-1].parent_ids) >= 2
```

---

### G. Fidelity Evaluation Harness (9 categories)

Each category scored 0–100 against the paper + the open-source Kaimen reference clone:

| # | Category | What it checks | Metric |
|---|---|---|---|
| 1 | Product flow | Goal → Intake → Plan → Loop → Overview matches paper Figure 2 | Binary per stage |
| 2 | Terminology | Outputs use "hypothesis", "research overview", "tournament", "NIH Specific Aims" | Regex vocabulary match |
| 3 | Report structure | Final overview has disease description / unmet need / proposed solutions / specific aims (each with goal+hypothesis+rationale) | Section-presence checker |
| 4 | Agent behavior | All 4 Generation modes, all 6 Reflection reviews, all 6 Evolution strategies observed in trace logs in a 30-min run | Coverage |
| 5 | Ranking/tournament | Initial Elo=1200; pairings biased toward similar-via-Proximity + new/top; multi-turn for top half | DB query on `tournament_matches` |
| 6 | Evidence/citation | ≥80% cited works reach tier-2; zero tier-0 ("does not resolve") in final report | `citations.verification_tier` |
| 7 | Safety | All CBRN probes blocked; benign biology not over-redacted | WMDP probe pass-rate |
| 8 | Progress/latency | AG-UI events ≤ 2 s end-to-end; checkpoint write p95 < 100 ms; resume-after-kill succeeds | Prometheus |
| 9 | Final output quality | Gold-set hits: AML ≥3/8, liver-fibrosis epigenetic target ≥1/3 | Manual + LLM-judge against `db/seeds/gold_*.json` |

Pass: ≥ 80 per category. Overall release threshold: 7/9 ≥ 80 and none < 60.

---

### H. Local Development Setup

`docker-compose.yml`:
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: coscientist
      POSTGRES_USER: cs
      POSTGRES_PASSWORD: cs
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cs -d coscientist"]
      interval: 5s
      retries: 10
    volumes: [pgdata:/var/lib/postgresql/data]
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  api:
    build: { context: ., dockerfile: apps/api/Dockerfile }
    command: uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
    env_file: [.env]
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_started }
    ports: ["8000:8000"]
    volumes: [".:/app"]

  worker:
    build: { context: ., dockerfile: apps/worker/Dockerfile }
    command: celery -A apps.worker.celery_app worker --loglevel=info --concurrency=4
    env_file: [.env]
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_started }
    runtime: runsc        # gVisor for code-exec sandboxing
    volumes: [".:/app"]

  frontend:
    build: { context: apps/frontend }
    command: npm run dev
    ports: ["5173:5173"]
    environment:
      VITE_API_URL: http://localhost:8000

  flower:
    image: mher/flower
    command: ["celery", "--broker=redis://redis:6379/0", "flower", "--port=5555"]
    ports: ["5555:5555"]
    depends_on: [redis]

volumes:
  pgdata:
```

`.env.example`:
```dotenv
DATABASE_URL=postgresql+psycopg://cs:cs@db:5432/coscientist
REDIS_URL=redis://redis:6379/0
LANGSMITH_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=
NCBI_API_KEY=                  # for PubMed 10 req/s
EUROPE_PMC_EMAIL=you@example.org
DEFAULT_MODEL_ALIAS=opusplan
RUN_BUDGET_USD_DEFAULT=5.0
RUN_WALL_CLOCK_S_DEFAULT=1800
SAFETY_MODE=strict             # strict | permissive | off (dev only)
```

Bootstrap:
```bash
make dev-up                                    # docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python -m scripts.seed_gold_data
```

---

## Recommendations

**Stage 1 (now → week 2): build the spine.** Ship Phases 1–2. *Threshold to advance:* all Phase 1+2 acceptance tests green; resume-after-kill works deterministically; at least one MCP server (PubMed) round-trips a real query at the polite-pool rate.

**Stage 2 (weeks 3–6): paper-faithful agents.** Implement all 12 agents in dependency order — Supervisor stub → Generation (one mode at a time) → Reflection (initial → full → deep_verify → others) → Proximity → Ranking → Evolution → Meta-Review → Safety/Citation gates. *Threshold to advance:* the AML acceptance test recovers ≥3 of the paper's named candidates; Evolution-invariant test passes; Meta-Review prompt-injection snapshot diff is non-empty.

**Stage 3 (weeks 7–10): UX + fidelity.** Ship the AG-UI dashboard and the fidelity harness. *Threshold to release v0.1:* fidelity scorecard ≥ 80 in seven of nine categories on AML and liver-fibrosis gold sets.

**Decisions that should change the plan:**
- If the **Reflection deep_verification** review burns > 40% of token budget without measurably improving Elo stability, lower its supervisor weight and rely more on simulation review.
- If MCP-based PubMed search returns < 50% relevant abstracts for a goal, add a query-rewriting sub-step inside the Literature agent before retrieval — the single highest-leverage retrieval upgrade per the 2025 hybrid-search literature.
- If LangGraph checkpoint writes exceed 100 ms p95, **slim the state schema**: move the `hypotheses` array out of LangGraph state and into Postgres rows referenced by ID; keep only IDs + small counters in state.
- If the cross-model bench shows Sonnet-4.6 matches Opus-4.7 within 50 Elo on Ranking, **route Ranking to Sonnet** to cut tournament cost ~5×; keep Opus for Generation and Meta-Review.

---

## Caveats

1. **Several details are not specified in the source paper** and must be configured by the clone: the Elo K-factor (we recommend annealing 32→16→10), the Proximity embedding model, the exact termination thresholds, and the Meta-Review trigger cadence. Mark these as `clone-defined` in `docs/FIDELITY.md` so reviewers don't penalize the clone for diverging on under-specified behaviors.
2. **The *Nature* 2026 paper (Gottweis et al.)** restructures the arXiv content but does not change the agent contracts; pseudocode lives in Supplementary Note 8 and prompts in Note 9. The Kaimen-Inc/Co-Scientist GitHub repo's `reference/` folder mirrors these supplements and is the closest thing to a canonical reference implementation outside Google.
3. **MCP server stability varies.** ChEMBL-MCP-Server and BioMCP are actively maintained; some niche MCPs are research-grade. Wrap every MCP call in a circuit breaker and degrade gracefully to direct REST calls (UniProt's REST API at `rest.uniprot.org` and Europe PMC's `webservices/rest/search` are stable production endpoints; UniProt's website-API paper documents pagination via `X-Total-Results`/`Link` headers).
4. **gVisor is the right sandbox for LLM-generated code execution today** — Tencent runs *millions* of gVisor sandboxes daily for agentic-RL training and reports closing the test-case compatibility gap to ~1.7% (gvisor.dev, Apr 23, 2026) — but pair it with strict egress controls: kernel-level isolation does not by itself prevent data exfiltration via the network namespace.
5. **Hallucination is not eliminable.** Even with tier-3 snippet-grounded citation verification, expect 5–15% of fine-grained claims in long-form outputs to be partially unsupported. Surface this honestly in the UI ("citation grounded — claim partially supported by snippet") rather than rendering a binary verified/unverified badge.
6. **Fidelity ≠ correctness.** A 1:1 clone can faithfully reproduce the paper's *architecture* while still producing worse hypotheses than the original, because the original ran on Gemini 2.0 with Google-internal scientific tools that are not publicly available (e.g., AlphaFold-as-a-tool). The fidelity harness measures architectural and behavioral fidelity, not absolute scientific quality. To approach the original's quality, plug in equivalent specialist models as MCP tools (ESMFold/AlphaFold-Server for structure, AutoDock-Vina for docking, etc.) as a Phase 6 extension.